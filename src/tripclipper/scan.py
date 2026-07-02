"""本地素材扫描核心（M2 / Stage 1 / FR-2）。

把 ``source_folder`` 下的原始素材递归发现、按扩展名分类、生成稳定
``asset_id``、提取基础文件信息，并在 ``ffprobe``/``ffmpeg`` 可用时补充媒体
信息与缩略图/关键帧，最终合并进项目 ``cut_index.json``。

本模块严格复用 M0 的数据契约与工具（``generate_asset_id``、``paths``、
``read_cut_index``/``write_cut_index``、``Capabilities``、``Asset``、
``WarningItem``、``Failure``、``assert_read_only_source``），不重新定义任何
字段或枚举。扫描与模型配置无关。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

from pydantic import BaseModel

from .cut_index import generate_asset_id, read_cut_index, write_cut_index
from .models import (
    AnalysisStatus,
    Asset,
    AssetType,
    Capabilities,
    CutIndex,
    Failure,
    WarningItem,
)
from .paths import cut_index_path, frames_dir, thumbnails_dir
from .security import assert_read_only_source
from .session_splitter import SESSION_GAP_HOURS, apply_sessions, split_sessions

_PathLike = Union[str, Path]

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 扩展名 → AssetType 的单一映射（严格依 TD 5 支持类型清单，键统一小写）。
SUPPORTED_EXTENSIONS: dict[str, AssetType] = {
    # 视频
    ".mp4": AssetType.video,
    ".mov": AssetType.video,
    ".m4v": AssetType.video,
    ".avi": AssetType.video,
    ".mkv": AssetType.video,
    ".webm": AssetType.video,
    ".mts": AssetType.video,
    ".m2ts": AssetType.video,
    # 图片
    ".jpg": AssetType.image,
    ".jpeg": AssetType.image,
    ".png": AssetType.image,
    ".heic": AssetType.image,
    ".heif": AssetType.image,
    ".webp": AssetType.image,
    ".tif": AssetType.image,
    ".tiff": AssetType.image,
    # 音频
    ".mp3": AssetType.audio,
    ".wav": AssetType.audio,
    ".m4a": AssetType.audio,
    ".aac": AssetType.audio,
    ".flac": AssetType.audio,
    ".ogg": AssetType.audio,
    ".opus": AssetType.audio,
}

# 关键帧抽取数量的下/上限：按 duration 自适应（见 _compute_frame_count）。
_MIN_FRAMES = 3
_MAX_FRAMES = 12
# 外部工具调用超时（秒）。大文件抽帧/探测可能偏慢，留足余量。
_FFPROBE_TIMEOUT = 120
_FFMPEG_TIMEOUT = 180

_SCAN_STAGE = "scan"
_CAPABILITY_WARNING_REASON = (
    "ffmpeg/ffprobe 不可用，已跳过媒体信息探测与缩略图/关键帧抽取"
)
_CAPABILITY_WARNING_SUGGESTION = (
    "安装 ffmpeg（含 ffprobe）后重新扫描即可补全媒体信息与浏览辅助图；"
    "macOS 可用 `brew install ffmpeg`"
)
_EMPTY_WARNING_REASON = "未发现可处理媒体"
_EMPTY_WARNING_SUGGESTION = (
    "确认 source_folder 指向正确的素材目录，或放入受支持的视频/图片/音频文件"
)
_MISSING_WARNING_REASON_PREFIX = "源目录中已不存在该素材文件"


# ---------------------------------------------------------------------------
# 结果摘要
# ---------------------------------------------------------------------------


class ScanResult(BaseModel):
    """一次扫描的结果摘要，供 CLI/API 展示。"""

    total: int = 0
    by_type: dict[str, int] = {}
    skipped: int = 0
    failures: int = 0
    is_empty: bool = False
    capabilities: Capabilities = Capabilities()
    cut_index_path: str = ""
    session_count: int = 0


class ScanError(Exception):
    """扫描无法启动时抛出的面向用户的清晰错误（如项目未初始化）。"""


# ---------------------------------------------------------------------------
# 分类与能力探测
# ---------------------------------------------------------------------------


def classify_file(path: _PathLike) -> Optional[AssetType]:
    """按扩展名判定媒体类型（大小写不敏感）；非媒体返回 ``None``。"""
    suffix = Path(path).suffix.lower()
    return SUPPORTED_EXTENSIONS.get(suffix)


def detect_capabilities() -> Capabilities:
    """用 ``shutil.which`` 探测 ffmpeg/ffprobe 是否可用，返回 M0 ``Capabilities``。"""
    has_ffmpeg = shutil.which("ffmpeg") is not None
    has_ffprobe = shutil.which("ffprobe") is not None

    if has_ffmpeg and has_ffprobe:
        notes = "ffmpeg 与 ffprobe 均可用"
    elif not has_ffmpeg and not has_ffprobe:
        notes = "ffmpeg 与 ffprobe 均不可用，将跳过媒体信息与缩略图/关键帧"
    else:
        missing = "ffmpeg" if not has_ffmpeg else "ffprobe"
        notes = f"{missing} 不可用，相关媒体处理步骤将被跳过"

    return Capabilities(ffmpeg=has_ffmpeg, ffprobe=has_ffprobe, notes=notes)


# ---------------------------------------------------------------------------
# 外部工具薄封装（统一超时与异常）
# ---------------------------------------------------------------------------


class _ToolError(Exception):
    """ffprobe/ffmpeg 调用失败（非零退出、超时或工具缺失）。"""


def _compute_frame_count(duration: Optional[float]) -> int:
    """按视频时长决定关键帧抽取数量。

    公式：``max(_MIN_FRAMES, min(_MAX_FRAMES, round(duration / 5)))``；
    ``duration`` 缺失（None/0/负）时退化为下限 3。该函数是纯函数，与外部工具
    无关，单测可独立覆盖。
    """
    if duration is None or duration <= 0:
        return _MIN_FRAMES
    return max(_MIN_FRAMES, min(_MAX_FRAMES, round(duration / 5)))


def _eval_frame_rate(raw: Optional[str]) -> Optional[float]:
    """把 ``avg_frame_rate`` 的 ``num/den`` 分数求值为浮点。

    ``den`` 为 0（如 ``0/0``）或无法解析时返回 ``None``。
    """
    if not raw or "/" not in raw:
        try:
            value = float(raw)  # type: ignore[arg-type]
            return value if value > 0 else None
        except (TypeError, ValueError):
            return None
    num_str, den_str = raw.split("/", 1)
    try:
        num = float(num_str)
        den = float(den_str)
    except ValueError:
        return None
    if den == 0:
        return None
    return round(num / den, 3)


def _select_primary_video_stream(streams: list[dict]) -> Optional[dict]:
    """从 ffprobe 的流列表里选主视频流：``codec_type=video`` 中像素面积最大者。

    自动忽略 ``data`` 流与 mjpeg 封面/缩略流（其面积通常更小或无宽高）。
    """
    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    if not video_streams:
        return None

    def area(stream: dict) -> int:
        try:
            return int(stream.get("width") or 0) * int(stream.get("height") or 0)
        except (TypeError, ValueError):
            return 0

    return max(video_streams, key=area)


def _run_ffprobe(path: _PathLike) -> dict:
    """调用 ffprobe 解析媒体信息，返回统一 dict。

    解析规则（由真实素材验证）：
    - 分辨率/编码取**主视频流**（像素面积最大的 video 流），忽略 data 与 mjpeg
      封面流；
    - ``fps`` 把 ``avg_frame_rate`` 的分数求值为浮点（den=0 记为缺省）；
    - ``has_audio`` 以是否存在 audio 流判定；
    - ``duration`` 取 ``format.duration``（秒，浮点）。

    失败（工具缺失、非零退出、超时、JSON 解析失败、无视频流）抛 :class:`_ToolError`。
    """
    if shutil.which("ffprobe") is None:
        raise _ToolError("ffprobe 不可用")

    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    try:
        completed = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=_FFPROBE_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise _ToolError(f"ffprobe 超时：{path}") from exc
    except OSError as exc:
        raise _ToolError(f"ffprobe 调用失败：{exc}") from exc

    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", "replace").strip()
        raise _ToolError(f"ffprobe 返回非零（{completed.returncode}）：{detail}")

    try:
        probe = json.loads(completed.stdout.decode("utf-8", "replace"))
    except json.JSONDecodeError as exc:
        raise _ToolError(f"ffprobe 输出无法解析为 JSON：{exc}") from exc

    streams = probe.get("streams") or []
    primary = _select_primary_video_stream(streams)
    if primary is None:
        raise _ToolError("未找到视频流（可能不是有效视频文件）")

    fmt = probe.get("format") or {}
    try:
        duration = float(fmt.get("duration")) if fmt.get("duration") is not None else None
    except (TypeError, ValueError):
        duration = None

    has_audio = any(s.get("codec_type") == "audio" for s in streams)

    metadata: dict = {
        "duration": duration,
        "width": int(primary["width"]) if primary.get("width") else None,
        "height": int(primary["height"]) if primary.get("height") else None,
        "codec": primary.get("codec_name"),
        "fps": _eval_frame_rate(primary.get("avg_frame_rate")),
        "has_audio": has_audio,
    }
    return metadata


def _run_ffmpeg_thumbnail(path: _PathLike, out_path: _PathLike) -> Path:
    """用 ffmpeg 在视频约 1s 处截一张缩略图到 ``out_path``，返回该路径。

    失败抛 :class:`_ToolError`。
    """
    if shutil.which("ffmpeg") is None:
        raise _ToolError("ffmpeg 不可用")

    target = Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-v",
        "error",
        "-y",
        "-ss",
        "1",
        "-i",
        str(path),
        "-frames:v",
        "1",
        "-vf",
        "scale=480:-2",
        str(target),
    ]
    _invoke_ffmpeg(cmd, label=f"缩略图 {path}")
    if not target.is_file():
        raise _ToolError(f"ffmpeg 未生成缩略图：{target}")
    return target


def _run_ffmpeg_frames(
    path: _PathLike,
    duration: Optional[float],
    out_dir: _PathLike,
    *,
    stem: str,
) -> list[tuple[Path, float]]:
    """为视频均匀抽取自适应数量的关键帧到 ``out_dir``。

    返回 ``(frame_path, timestamp_seconds)`` 元组列表，索引与抽帧顺序对齐；
    抽帧数由 :func:`_compute_frame_count` 按时长自适应（3 ≤ N ≤ 12）。无法
    得到时长时退化为下限 3 帧，时间戳取均匀分布（无 duration 时统一以 1.0s
    一个点回填）。失败抛 :class:`_ToolError`。
    """
    if shutil.which("ffmpeg") is None:
        raise _ToolError("ffmpeg 不可用")

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    count = _compute_frame_count(duration)
    # 计算均匀分布的时间点：避开 0 与末尾，取 (i+1)/(count+1) * duration。
    if duration and duration > 0:
        timestamps = [duration * (i + 1) / (count + 1) for i in range(count)]
    else:
        # 无 duration：从 1.0s 起每 1.0s 取一个，至少 count 个点。
        timestamps = [1.0 * (i + 1) for i in range(count)]

    produced: list[tuple[Path, float]] = []
    for idx, ts in enumerate(timestamps):
        frame_path = out / f"{stem}_frame{idx + 1:02d}.jpg"
        cmd = [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-ss",
            f"{ts:.3f}",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-vf",
            "scale=480:-2",
            str(frame_path),
        ]
        _invoke_ffmpeg(cmd, label=f"关键帧 {path}@{ts:.3f}")
        if frame_path.is_file():
            produced.append((frame_path, float(ts)))

    if not produced:
        raise _ToolError(f"ffmpeg 未生成任何关键帧：{path}")
    return produced


def _invoke_ffmpeg(cmd: list[str], *, label: str) -> None:
    """运行一个 ffmpeg 命令，统一超时与异常处理。"""
    try:
        completed = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=_FFMPEG_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise _ToolError(f"ffmpeg 超时：{label}") from exc
    except OSError as exc:
        raise _ToolError(f"ffmpeg 调用失败：{exc}") from exc

    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", "replace").strip()
        raise _ToolError(f"ffmpeg 返回非零（{completed.returncode}）：{detail}")


# ---------------------------------------------------------------------------
# 单文件处理
# ---------------------------------------------------------------------------


def _iso_mtime(path: Path) -> str:
    """文件修改时间的 ISO 8601（UTC）字符串。"""
    ts = path.stat().st_mtime
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def build_asset(path: _PathLike, source_folder: _PathLike) -> Asset:
    """从文件构造一个仅含基础信息的 :class:`Asset`（``analysis_status=scanned``）。"""
    file_path = Path(path)
    src = Path(source_folder)
    relative_path = file_path.relative_to(src).as_posix()
    asset_type = classify_file(file_path)
    stat = file_path.stat()

    return Asset(
        asset_id=generate_asset_id(relative_path),
        filename=file_path.name,
        path=str(file_path.resolve()),
        relative_path=relative_path,
        type=asset_type,
        extension=file_path.suffix.lower(),
        size=stat.st_size,
        modified_time=_iso_mtime(file_path),
        analysis_status=AnalysisStatus.scanned,
    )


def probe_media(path: _PathLike, capabilities: Capabilities) -> dict:
    """在 ffprobe 可用时返回媒体信息 dict；不可用/失败返回空 dict。

    失败不抛到顶层——由调用方决定如何记录（这里只负责返回数据）。
    """
    if not capabilities.ffprobe:
        return {}
    return _run_ffprobe(path)


# ---------------------------------------------------------------------------
# 端到端扫描
# ---------------------------------------------------------------------------

# 再次扫描时以本次结果刷新的文件级字段；其余（Stage 2 分析字段）一律保活。
_FILE_LEVEL_FIELDS = (
    "filename",
    "path",
    "relative_path",
    "type",
    "extension",
    "size",
    "modified_time",
    "metadata",
    "thumbnail_path",
    "frame_paths",
    "frame_timestamps",
)


def _collect_candidate_files(source_folder: Path) -> list[Path]:
    """递归收集 ``source_folder`` 下的所有文件，按相对路径排序（确定性）。"""
    files: list[Path] = []
    for root, _dirs, names in os.walk(source_folder):
        for name in names:
            files.append(Path(root) / name)
    files.sort(key=lambda p: p.relative_to(source_folder).as_posix())
    return files


def _extract_browse_aids(
    asset: Asset,
    file_path: Path,
    capabilities: Capabilities,
    slug: str,
    base_dir: Optional[_PathLike],
) -> None:
    """为单个 asset 回填缩略图/关键帧（视频用 ffmpeg；图片引用原图；音频跳过）。

    失败由调用方隔离；这里失败会抛 :class:`_ToolError`。
    """
    if asset.type == AssetType.image:
        # 图片不复制原图，仅把原图路径作为缩略图来源引用。
        asset.thumbnail_path = str(file_path.resolve())
        return
    if asset.type != AssetType.video:
        return
    if not capabilities.ffmpeg:
        return

    stem = asset.asset_id or file_path.stem
    thumb_target = thumbnails_dir(slug, base_dir) / f"{stem}.jpg"
    asset.thumbnail_path = str(_run_ffmpeg_thumbnail(file_path, thumb_target))

    duration = asset.metadata.get("duration") if asset.metadata else None
    frames = _run_ffmpeg_frames(
        file_path,
        duration,
        frames_dir(slug, base_dir),
        stem=stem,
    )
    asset.frame_paths = [str(p) for p, _ts in frames]
    asset.frame_timestamps = [float(ts) for _p, ts in frames]


def _merge_preserving_analysis(existing: Asset, fresh: Asset) -> Asset:
    """把 ``fresh`` 的文件级信息合并进 ``existing``，保留 Stage 2 分析字段。"""
    # 文件级字段以 fresh 为准刷新。
    for field in _FILE_LEVEL_FIELDS:
        setattr(existing, field, getattr(fresh, field))

    # analysis_status：已 analyzed 的不回退到 scanned。
    if existing.analysis_status not in (
        AnalysisStatus.analyzed,
        AnalysisStatus.analyzing,
        AnalysisStatus.analysis_failed,
    ):
        existing.analysis_status = fresh.analysis_status

    # 文件级失败/警告以本次为准刷新（分析字段保留不动）。
    existing.warnings = fresh.warnings
    existing.failures = fresh.failures
    return existing


def scan_project(
    slug: str,
    *,
    base_dir: Optional[_PathLike] = None,
    extract_media: bool = True,
) -> ScanResult:
    """端到端扫描项目 ``slug`` 的 ``source_folder``，更新 ``cut_index.json``。

    流程：读回 cut_index（不存在则抛 :class:`ScanError`）→ 只读引用
    source_folder → 递归收集并排序 → 分类、构造 asset、补媒体信息与缩略图/关键帧
    →（按 asset_id）合并保活 → 写能力/空目录警告 → 落盘 → 返回 :class:`ScanResult`。
    """
    index_path = cut_index_path(slug, base_dir)
    if not index_path.exists():
        raise ScanError(
            f"项目尚未初始化（未找到 {index_path}）。请先运行 "
            f"`tripclipper init --config <project.yaml>` 创建项目。"
        )

    cut: CutIndex = read_cut_index(index_path)

    source_raw = cut.project.source_folder
    if not source_raw:
        raise ScanError("cut_index.json 缺少 project.source_folder，无法扫描。")
    source_folder = assert_read_only_source(source_raw)
    if not source_folder.is_dir():
        raise ScanError(
            f"素材目录不存在或不是目录：{source_folder}。请检查 project.yaml 的 "
            f"source_folder。"
        )

    capabilities = detect_capabilities()

    existing_by_id: dict[str, Asset] = {
        a.asset_id: a for a in cut.assets if a.asset_id
    }
    seen_ids: set[str] = set()

    new_assets: list[Asset] = []
    by_type: dict[str, int] = {t.value: 0 for t in AssetType}
    skipped = 0
    failure_count = 0

    for file_path in _collect_candidate_files(source_folder):
        asset_type = classify_file(file_path)
        if asset_type is None:
            skipped += 1
            continue

        fresh = build_asset(file_path, source_folder)
        by_type[asset_type.value] += 1

        # 媒体信息探测（失败隔离到该 asset）。
        if extract_media and capabilities.ffprobe and asset_type == AssetType.video:
            try:
                fresh.metadata = probe_media(file_path, capabilities)
            except _ToolError as exc:
                failure_count += 1
                fresh.failures.append(
                    Failure(
                        stage=_SCAN_STAGE,
                        target=fresh.asset_id,
                        reason=f"媒体信息探测失败：{exc}",
                        suggestion="确认该文件为完整有效的媒体文件后重试",
                        blocking=False,
                    ).model_dump()
                )

        # 缩略图/关键帧抽取（失败隔离到该 asset）。
        if extract_media:
            try:
                _extract_browse_aids(
                    fresh, file_path, capabilities, slug, base_dir
                )
            except _ToolError as exc:
                failure_count += 1
                fresh.failures.append(
                    Failure(
                        stage=_SCAN_STAGE,
                        target=fresh.asset_id,
                        reason=f"缩略图/关键帧抽取失败：{exc}",
                        suggestion="确认该文件为完整有效的视频文件后重试",
                        blocking=False,
                    ).model_dump()
                )

        asset_id = fresh.asset_id or ""
        seen_ids.add(asset_id)
        if asset_id in existing_by_id:
            merged = _merge_preserving_analysis(existing_by_id[asset_id], fresh)
            new_assets.append(merged)
        else:
            new_assets.append(fresh)

    # 源中已消失的旧 asset：保留但记录非阻塞警告（不删除）。
    for old in cut.assets:
        if old.asset_id and old.asset_id not in seen_ids:
            new_assets.append(old)
            _append_warning_once(
                cut,
                WarningItem(
                    stage=_SCAN_STAGE,
                    target=old.asset_id,
                    reason=(
                        f"{_MISSING_WARNING_REASON_PREFIX}："
                        f"{old.relative_path or old.filename}"
                    ),
                    suggestion="如该素材已删除，可在后续清理；分析结果暂予保留",
                    blocking=False,
                ),
            )

    # assets 按相对路径排序（确定性）。
    new_assets.sort(key=lambda a: a.relative_path or "")
    cut.assets = new_assets

    # 能力状态落盘。
    cut.capabilities = capabilities
    if not (capabilities.ffmpeg and capabilities.ffprobe):
        _append_warning_once(
            cut,
            WarningItem(
                stage=_SCAN_STAGE,
                reason=_CAPABILITY_WARNING_REASON,
                suggestion=_CAPABILITY_WARNING_SUGGESTION,
                blocking=False,
            ),
        )

    total = len(seen_ids)
    is_empty = total == 0
    if is_empty:
        _append_warning_once(
            cut,
            WarningItem(
                stage=_SCAN_STAGE,
                reason=_EMPTY_WARNING_REASON,
                suggestion=_EMPTY_WARNING_SUGGESTION,
                blocking=False,
            ),
        )

    cut.project.updated_at = datetime.now(timezone.utc).isoformat()

    # session 切分（分析阶段的一等公民；纯确定性，无 IO/LLM）。
    sessions = split_sessions(cut.assets)
    apply_sessions(cut.assets, sessions)
    cut.sessions = sessions

    write_cut_index(index_path, cut)

    return ScanResult(
        total=total,
        by_type=by_type,
        skipped=skipped,
        failures=failure_count,
        is_empty=is_empty,
        capabilities=capabilities,
        cut_index_path=str(index_path),
        session_count=len(sessions),
    )


def _append_warning_once(cut: CutIndex, warning: WarningItem) -> None:
    """按 (stage, reason, target) 去重后追加一条警告。"""
    for existing in cut.warnings:
        if (
            existing.stage == warning.stage
            and existing.reason == warning.reason
            and existing.target == warning.target
        ):
            return
    cut.warnings.append(warning)


__all__ = [
    "SUPPORTED_EXTENSIONS",
    "ScanResult",
    "ScanError",
    "classify_file",
    "detect_capabilities",
    "build_asset",
    "probe_media",
    "scan_project",
]
