"""M3 Stage 2 真实大模型分析编排层。

职责：把 M2 扫描出来的 ``cut_index.assets`` 交给 :class:`Provider`，写回分析
结果；管理样本抽样、并发线程池、增量落盘、阶段头尾状态、失败记录三处
（``Asset.failures`` / ``CutIndex.failures`` / ``AnalysisInfo.error_summary``）。
本模块**不**调用模型 API（那是 :mod:`tripclipper.provider` 的事），也**不**
抽帧（那是 :mod:`tripclipper.scan` 的事）。

设计要点（参见 ``docs/specs/M3-real-llm-analysis/spec.md``）：

- Q6：``_stratified_sample`` 两层分层随机抽样（``AssetType`` × 顶层目录），
  固定 seed 可复现。
- Q8：``ThreadPoolExecutor``，每线程独立 :class:`Provider`（``httpx.Client``
  非线程安全）。
- Q10：``full_analyze`` 默认跳过 ``analyzed`` 素材；``--force`` 重跑全部。
- Q12：阶段头写 ``status="running"`` + ``started_at``；过程中每 5 个全量
  落盘一次；阶段尾写 ``status`` 终态 + ``finished_at`` + ``error_summary``；
  ``AnalysisStatus.analyzing`` **从不**写入磁盘——崩溃后只剩 ``scanned`` /
  ``analyzed`` / ``analysis_failed``。
- Q13：重试由 provider 自身负责，编排层不再叠加。
- Q18：失败三处都写（素材级、项目级、阶段摘要）。
- Q24：每次执行写一份 ``projects/<slug>/logs/analyze-<ISO8601>.jsonl``。

关于 ``call_start``/``call_end`` attempt 编号的工程取舍：``provider.analyze``
内部已包含 ``_RETRY_BACKOFFS`` 重试循环，但 provider 不向外暴露内部尝试
事件——本编排层只在 ``provider.analyze`` 一次调用前后各写一次 ``call_start``
/ ``call_end``，单素材始终 ``attempt=1``。这是受限于 provider 接口边界的
合理近似（spec Q24 期望"重试每次一行"，将来若需要精确事件可在 provider
层接入回调钩子）。
"""

from __future__ import annotations

import concurrent.futures
import random
import re
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal, Optional, Union

from .audio_analysis import (
    AudioAnalysisParser,
    AudioExtractor,
    ParsedAudioChunk,
    aggregate_audio_chunks,
    is_near_digital_silence,
)
from .audio_provider import AudioAnalysisProvider, AudioProviderError
from .config import EditingIntent, ModelConfig, load_config, load_software_config
from .cut_index import read_cut_index, write_cut_index
from .logs import AnalyzeLogger
from .models import (
    AnalysisInfo,
    AnalysisStatus,
    Asset,
    CutIndex,
    Failure,
    SpeechQuality,
    TranscriptDocument,
    WarningItem,
)
from .paths import audio_cache_dir, cut_index_path, project_dir
from .progress import PeriodicProgressReporter
from .provider import Provider, ProviderError, apply_analysis
from .transcript_store import TranscriptStore

_PathLike = Union[str, Path]

# 处理这些状态的素材：scanned（待分析）、analyzing（异常状态，按 scanned 处理）、
# analyzed（force 时重跑）、analysis_failed（重试）。
_ELIGIBLE_STATUSES = {
    AnalysisStatus.scanned,
    AnalysisStatus.analyzing,
    AnalysisStatus.analyzed,
    AnalysisStatus.analysis_failed,
}

# 增量落盘的批大小（Q12）：每完成 N 个素材全量写一次 cut_index.json。
_PERSIST_EVERY = 5

_ANALYZE_STAGE = "analyze"


# ---------------------------------------------------------------------------
# 公共结果与异常
# ---------------------------------------------------------------------------


@dataclass
class AnalyzeResult:
    """一次 analyze 的运行摘要，供 CLI / runner / API 直接展示。"""

    stage: Literal["sample", "full"]
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)  # (asset_id, reason)
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    cut_index_path: Optional[str] = None
    log_path: Optional[str] = None


class AnalyzerError(Exception):
    """编排无法启动时抛出的面向用户的清晰错误（如项目未扫描、Provider 不可用）。"""


# ---------------------------------------------------------------------------
# 纯函数（模块级 _ 开头，便于 Task 7 unit 测试）
# ---------------------------------------------------------------------------


def _top_directory(relative_path: Optional[str]) -> str:
    """返回相对路径的顶层目录名；空路径 / 仅文件名归 ``"_root"``。"""
    if not relative_path:
        return "_root"
    head = relative_path.replace("\\", "/").split("/", 1)
    if len(head) < 2 or not head[0]:
        return "_root"
    return head[0]


def _clear_previous_project_failures(cut: CutIndex) -> None:
    """清除上一次 analyze 写入的项目级失败，保留其他阶段记录。"""
    cut.failures = [failure for failure in cut.failures if failure.stage != _ANALYZE_STAGE]


def _largest_remainder_allocate(
    sizes: dict[str, int],
    quota: int,
) -> dict[str, int]:
    """Hare/largest-remainder 配额：按 ``sizes`` 比例分配 ``quota`` 个名额。

    ``sizes`` 是 ``{key: 桶大小}``。返回 ``{key: 名额}``：

    - 向下取整后剩余按"小数部分降序、key 字典序升序"补齐。
    - 单桶名额不超过其大小。
    - 总名额始终等于 ``min(quota, sum(sizes.values()))``。
    - 给定 ``sizes`` / ``quota``，输出 deterministic 可复现。
    """
    total = sum(sizes.values())
    if quota <= 0 or total <= 0:
        return {key: 0 for key in sizes}
    keys = sorted(sizes.keys())
    capped_quota = min(quota, total)

    allocations: dict[str, int] = {}
    fractional: list[tuple[float, str]] = []
    for key in keys:
        size = sizes[key]
        share = capped_quota * size / total
        floor = int(share)
        allocations[key] = min(floor, size)
        fractional.append((share - floor, key))

    remainder = capped_quota - sum(allocations.values())
    fractional.sort(key=lambda x: (-x[0], x[1]))

    # 至多扫两轮：第一轮按小数降序补，第二轮把仍有空位的桶按字典序补满。
    for _round in range(2):
        if remainder <= 0:
            break
        for _, key in fractional:
            if remainder <= 0:
                break
            if allocations[key] < sizes[key]:
                allocations[key] += 1
                remainder -= 1
    return allocations


def _stratified_sample(
    assets: list[Asset],
    sample_size: int,
    *,
    seed: int = 42,
) -> list[Asset]:
    """两层分层随机抽样（Q6）。

    第一层按 :class:`AssetType`（``video`` / ``image`` / ``audio``）分配配额，
    第二层在每个类型配额内部按 ``relative_path`` 顶层目录（无目录归
    ``"_root"``）再次分配。两层都用 :func:`_largest_remainder_allocate`，
    优先按比例向下取整，余额按"小数部分降序、key 字典序"补齐 ——
    既保证小比例的类型（如 ``video`` 10%）在大样本下能拿到至少几个名额，
    又在 ``sample_size`` 极小、整体配额不足 1 时让小类自然落空（这是必然
    取舍：算法不会平均奖励每一类）。

    特殊情形：

    - ``sample_size <= 0``：返回空列表。
    - ``sample_size >= len(assets)``：返回按 ``relative_path`` 排序的全量
      列表（可复现，不再抽样）。
    - 固定 ``seed`` 下两次调用结果完全一致。
    """
    if sample_size <= 0 or not assets:
        return []
    if sample_size >= len(assets):
        return sorted(assets, key=lambda a: a.relative_path or "")

    # ----- 分桶：type -> top_dir -> [Asset, ...] -----
    by_type: dict[str, dict[str, list[Asset]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for asset in assets:
        type_key = asset.type.value if asset.type else "_unknown"
        dir_key = _top_directory(asset.relative_path)
        by_type[type_key][dir_key].append(asset)

    # ----- 桶内固定 seed shuffle（先 sort 再 shuffle，保证可复现） -----
    rng = random.Random(seed)
    for type_key in sorted(by_type.keys()):
        for dir_key in sorted(by_type[type_key].keys()):
            items = by_type[type_key][dir_key]
            items.sort(key=lambda a: a.relative_path or "")
            rng.shuffle(items)

    # ----- 第一层：按类型分配配额 -----
    type_sizes = {tk: sum(len(v) for v in by_type[tk].values()) for tk in by_type}
    type_quotas = _largest_remainder_allocate(type_sizes, sample_size)

    # ----- 第二层：在每个类型内部按顶层目录分配 -----
    selected: list[Asset] = []
    for type_key in sorted(by_type.keys()):
        type_quota = type_quotas.get(type_key, 0)
        if type_quota <= 0:
            continue
        dir_sizes = {dk: len(items) for dk, items in by_type[type_key].items()}
        dir_quotas = _largest_remainder_allocate(dir_sizes, type_quota)
        for dir_key in sorted(by_type[type_key].keys()):
            n = dir_quotas.get(dir_key, 0)
            if n > 0:
                selected.extend(by_type[type_key][dir_key][:n])

    # 返回时按 relative_path 排序，便于阅读 / 调试（不影响抽样语义）。
    selected.sort(key=lambda a: a.relative_path or "")
    return selected


def _should_process(asset: Asset, *, force: bool) -> bool:
    """Q10 跳过判定。

    - ``force=True``：处理所有素材（含 ``analyzed``）。
    - ``force=False``：跳过 ``analysis_status == analyzed``，处理其余
      （``scanned`` / ``analyzing`` / ``analysis_failed``）。
    """
    if force:
        return True
    audio_pending = (
        asset.type is not None
        and asset.type.value == "video"
        and "has_audio" in (asset.metadata or {})
        and asset.speech_quality is None
    )
    return asset.analysis_status != AnalysisStatus.analyzed or audio_pending


def _analyze_asset_audio(
    asset: Asset,
    *,
    source_path: Path,
    extractor,
    provider,
    store,
    force: bool = False,
    silence_detector=is_near_digital_silence,
) -> Optional[str]:
    """Run the independent audio substep and return a safe error summary."""
    if asset.type is None or asset.type.value != "video":
        return None
    if not bool((asset.metadata or {}).get("has_audio")):
        asset.speech_quality = SpeechQuality.none
        asset.transcript_path = None
        return None

    asset_id = asset.asset_id or "<unknown>"
    try:
        chunks = extractor.extract(source_path, asset_id, force=force)
    except Exception as exc:
        reason = f"音频提取失败：{type(exc).__name__}: {exc}"
        asset.failures.append(
            Failure(
                stage="audio_analysis",
                target=asset_id,
                reason=reason,
                suggestion="检查 ffmpeg、源文件音轨与缓存目录后重试",
                blocking=False,
                occurred_at=datetime.now(timezone.utc).isoformat(),
            ).model_dump()
        )
        return reason

    parser = AudioAnalysisParser()
    parsed_chunks = []
    chunk_errors: list[str] = []
    for index, chunk in enumerate(chunks):
        try:
            if silence_detector(chunk.path):
                parsed = ParsedAudioChunk(SpeechQuality.none)
            else:
                parsed = parser.parse(provider.analyze(chunk), chunk)
            parsed_chunks.append(parsed)
            for warning in parsed.warnings:
                asset.warnings.append(
                    WarningItem(
                        stage="audio_analysis",
                        target=asset_id,
                        reason=warning,
                        blocking=False,
                    ).model_dump()
                )
        except Exception as exc:
            parsed_chunks.append(None)
            chunk_errors.append(f"分块 {index} 失败：{type(exc).__name__}: {exc}")

    aggregate = aggregate_audio_chunks(parsed_chunks)
    if aggregate.incomplete:
        asset.warnings.append(
            WarningItem(
                stage="audio_analysis",
                target=asset_id,
                reason="音频分析不完整，部分分块失败",
                blocking=False,
            ).model_dump()
        )
    if aggregate.speech_quality is not None:
        document = TranscriptDocument(
            speech_quality=aggregate.speech_quality,
            speech_segments=aggregate.speech_segments,
        )
        try:
            store.save(asset, document, complete=aggregate.all_succeeded)
        except Exception as exc:
            chunk_errors.append(f"转写保存失败：{type(exc).__name__}: {exc}")

    if chunk_errors:
        reason = "；".join(chunk_errors)
        asset.failures.append(
            Failure(
                stage="audio_analysis",
                target=asset_id,
                reason=reason,
                suggestion="稍后重跑音频分析；已有画面和完整转写不会被覆盖",
                blocking=False,
                occurred_at=datetime.now(timezone.utc).isoformat(),
            ).model_dump()
        )
        return reason
    return None


def _classify_reason(reason: str) -> str:
    """把单条失败 ``reason`` 归类为预定义类目之一。"""
    text = reason or ""
    lower = text.lower()
    if "429" in text:
        return "HTTP 429"
    if re.search(r"http\s*5\d{2}", lower):
        return "HTTP 5xx"
    if "timeout" in lower or "超时" in text:
        return "timeout"
    if "network" in lower or "网络" in text:
        return "network"
    if "非法 json" in text.lower() or "invalid json" in lower or "json" in lower:
        return "非法 JSON"
    return "其他"


def _summarize_errors(errors: list[tuple[str, str]]) -> str:
    """把素材级失败列表归纳为一句中文摘要（Q18）。

    形如 ``"3 个素材分析失败（2 次 HTTP 429、1 次非法 JSON）"``。无错误返回
    空字符串。错误类目从 ``reason`` 字符串中抽关键词归类，覆盖
    ``HTTP 429`` / ``HTTP 5xx`` / ``timeout`` / ``network`` / ``非法 JSON``
    / ``其他``。
    """
    if not errors:
        return ""
    counts: dict[str, int] = defaultdict(int)
    for _asset_id, reason in errors:
        counts[_classify_reason(reason)] += 1

    # 固定输出顺序（与 _classify_reason 中分支顺序保持一致）。
    order = ("HTTP 429", "HTTP 5xx", "timeout", "network", "非法 JSON", "其他")
    parts = [f"{counts[name]} 次 {name}" for name in order if counts.get(name)]
    return f"{len(errors)} 个素材分析失败（{'、'.join(parts)}）"


# ---------------------------------------------------------------------------
# 公共编排入口
# ---------------------------------------------------------------------------


def sample_analyze(
    slug: str,
    *,
    base_dir: Optional[_PathLike] = None,
    concurrency: int = 5,
    progress: Optional[PeriodicProgressReporter] = None,
) -> AnalyzeResult:
    """FR-3 样本分析：分层随机抽样 ``min(sample_size, len(eligible))`` 个素材。

    流程见 :func:`_run` 的 docstring；本函数只是把 ``stage="sample"`` /
    ``force=False`` 固定下来。
    """
    return _run(
        stage="sample",
        slug=slug,
        base_dir=base_dir,
        force=False,
        concurrency=concurrency,
        progress=progress,
    )


def full_analyze(
    slug: str,
    *,
    base_dir: Optional[_PathLike] = None,
    force: bool = False,
    concurrency: int = 5,
    progress: Optional[PeriodicProgressReporter] = None,
) -> AnalyzeResult:
    """FR-4 全量分析：默认跳过 ``analyzed`` 素材；``force=True`` 全量重分析。"""
    return _run(
        stage="full",
        slug=slug,
        base_dir=base_dir,
        force=force,
        concurrency=concurrency,
        progress=progress,
    )


# ---------------------------------------------------------------------------
# 内部主流程
# ---------------------------------------------------------------------------


def _run(
    *,
    stage: Literal["sample", "full"],
    slug: str,
    base_dir: Optional[_PathLike] = None,
    force: bool = False,
    concurrency: int = 5,
    progress: Optional[PeriodicProgressReporter] = None,
    _persist_callback: Optional[Callable[[int], None]] = None,
) -> AnalyzeResult:
    """sample / full 共用的编排主流程。

    ``_persist_callback`` 是为 Task 7 单元测试预留的钩子：默认 ``None`` 时
    每次落盘真正调用 :func:`write_cut_index`；测试时可注入一个计数回调来
    验证"12 个素材触发 3 次落盘（5+5+2）"的边界（公共 API
    :func:`sample_analyze` / :func:`full_analyze` 不暴露此参数）。
    """
    index_path = cut_index_path(slug, base_dir)

    # ---------- 前置硬卡 ----------
    if not index_path.exists():
        raise AnalyzerError(
            f"项目尚未初始化或扫描（未找到 {index_path}）。请先运行 "
            f"`tripclipper init --config <project.yaml>` 与 "
            f"`tripclipper analyze --stage scan --config <project.yaml>`。"
        )

    cut: CutIndex = read_cut_index(index_path)
    eligible_assets = [
        a for a in cut.assets if a.analysis_status in _ELIGIBLE_STATUSES
    ]
    if not eligible_assets:
        raise AnalyzerError(
            "cut_index.json 中没有可分析的 asset。请先运行 "
            "`tripclipper analyze --stage scan ...`。"
        )

    # ---------- 加载软件级配置 + 项目 editing_intent ----------
    config_path = cut.project.config_path
    if not config_path:
        raise AnalyzerError(
            "cut_index.json 缺少 project.config_path，无法定位 project.yaml；"
            "请重新运行 init。"
        )
    project_config = load_config(config_path)
    software_config = load_software_config(legacy_project_path=config_path)
    llm_config: ModelConfig = software_config.llm
    analysis_config = software_config.analysis
    editing_intent: EditingIntent = project_config.editing_intent

    _clear_previous_project_failures(cut)

    # ---------- 项目级 Provider 探测 ----------
    try:
        Provider(llm_config, editing_intent)
        AudioAnalysisProvider(llm_config)
    except (ProviderError, AudioProviderError) as exc:
        # 项目级失败：直接写到 CutIndex.failures（list[Failure]，无需 model_dump）。
        cut.failures.append(
            Failure(
                stage=_ANALYZE_STAGE,
                target=slug,
                reason=str(exc),
                suggestion=(
                    "请检查 .env 中 TRIPCLIPPER_MODEL_API_KEY 是否设置，"
                    "并确认软件配置中的 model_config.provider / base_url / "
                    "vision_model / audio_analysis_model 完整"
                ),
                blocking=True,
                occurred_at=datetime.now(timezone.utc).isoformat(),
            )
        )
        write_cut_index(index_path, cut)
        raise AnalyzerError(f"Provider 初始化失败：{exc}") from exc

    # ---------- 样本选择 ----------
    sample_size_value: Optional[int] = None
    if stage == "sample":
        configured_size = analysis_config.sample_size or 25
        sample_size_value = configured_size
        selected = _stratified_sample(eligible_assets, configured_size)
        skipped = 0  # sample 模式下未抽中的不算"跳过"
    else:
        selected = [a for a in eligible_assets if _should_process(a, force=force)]
        skipped = len(eligible_assets) - len(selected)

    total_selected = len(selected)
    if progress is not None:
        progress.start(
            total=total_selected,
            skipped=skipped,
            extra=f"并发={concurrency}",
        )

    # ---------- 阶段头落盘 ----------
    started_at = datetime.now(timezone.utc).isoformat()
    cut.analysis = AnalysisInfo(
        provider=llm_config.provider,
        vision_model=llm_config.vision_model,
        text_model=llm_config.text_model,
        audio_analysis_model=llm_config.audio_analysis_model,
        stage=stage,
        sample_size=sample_size_value,
        started_at=started_at,
        finished_at=None,
        status="running",
        error_summary=None,
    )
    _persist(cut, index_path, done=0, callback=_persist_callback)

    logger = AnalyzeLogger(slug, base_dir if base_dir is None else Path(base_dir))
    logger.stage_start(stage=stage, total=total_selected, concurrency=concurrency)

    # ---------- 线程池执行 ----------
    run_start = time.monotonic()
    succeeded = 0
    failed = 0
    errors: list[tuple[str, str]] = []
    write_lock = threading.Lock()
    counter = {"done": 0}
    # 每线程一个独立 Provider 实例（Q8：httpx.Client 非线程安全）。
    thread_local = threading.local()
    extractor = AudioExtractor(audio_cache_dir(slug, base_dir))
    transcript_store = TranscriptStore(project_dir(slug, base_dir))

    def _get_provider() -> Provider:
        existing = getattr(thread_local, "provider", None)
        if existing is None:
            existing = Provider(llm_config, editing_intent)
            thread_local.provider = existing
        return existing

    def _get_audio_provider() -> AudioAnalysisProvider:
        existing = getattr(thread_local, "audio_provider", None)
        if existing is None:
            existing = AudioAnalysisProvider(llm_config)
            thread_local.audio_provider = existing
        return existing

    def _analyze_one(asset: Asset) -> tuple[str, Optional[tuple[str, str]]]:
        # 注意：AnalysisStatus.analyzing 仅是字面值的"内存协调标志"——本实现
        # 直接跳过这一步，永不写入 asset.analysis_status，崩溃后磁盘上不会出
        # 现 analyzing 僵尸态（Q12）。
        attempt = 1
        asset_id = asset.asset_id or "<unknown>"
        asset_type_value = asset.type.value if asset.type else "unknown"
        frame_count = len(asset.frame_paths or [])

        logger.call_start(
            asset_id=asset_id,
            attempt=attempt,
            asset_type=asset_type_value,
            frame_count=frame_count,
        )
        t0 = time.monotonic()
        errors_for_asset: list[str] = []
        visual_needed = force or asset.analysis_status != AnalysisStatus.analyzed
        if visual_needed:
            try:
                result = _get_provider().analyze(asset)
                apply_analysis(asset, result)
            except ProviderError as exc:
                asset.analysis_status = AnalysisStatus.analysis_failed
                reason = str(exc)
                suggestion = (
                    "瞬时错误：建议稍后重跑 `tripclipper analyze --stage full --force`"
                    if exc.transient
                    else "模型输出格式异常或鉴权失败：检查 prompt、vision_model 或 API key"
                )
                asset.failures.append(
                    Failure(
                        stage=_ANALYZE_STAGE,
                        target=asset_id,
                        reason=reason,
                        suggestion=suggestion,
                        blocking=True,
                        occurred_at=datetime.now(timezone.utc).isoformat(),
                    ).model_dump()
                )
                errors_for_asset.append(reason)
            except Exception as exc:
                asset.analysis_status = AnalysisStatus.analysis_failed
                reason = f"意外异常: {type(exc).__name__}: {exc}"
                asset.failures.append(
                    Failure(
                        stage=_ANALYZE_STAGE,
                        target=asset_id,
                        reason=reason,
                        suggestion="请检查日志与 cut_index.json 后重跑",
                        blocking=True,
                        occurred_at=datetime.now(timezone.utc).isoformat(),
                    ).model_dump()
                )
                errors_for_asset.append(reason)

        source_value = asset.path or asset.file or asset.relative_path
        source_path = (
            Path(source_value)
            if source_value and Path(source_value).is_absolute()
            else Path(project_config.source_folder)
            / (asset.relative_path or source_value or "")
        )
        audio_error = _analyze_asset_audio(
            asset,
            source_path=source_path,
            extractor=extractor,
            provider=_get_audio_provider(),
            store=transcript_store,
            force=force,
        )
        if audio_error:
            errors_for_asset.append(audio_error)

        latency_ms = int((time.monotonic() - t0) * 1000)
        if errors_for_asset:
            reason = "；".join(errors_for_asset)
            logger.call_end(
                asset_id=asset_id,
                attempt=attempt,
                status="failure",
                latency_ms=latency_ms,
                error=reason,
            )
            return ("failed", (asset_id, reason))
        logger.call_end(
            asset_id=asset_id,
            attempt=attempt,
            status="success",
            http_code=200,
            latency_ms=latency_ms,
        )
        return ("ok", None)

    # 即使 selected 为空也走完整阶段头尾，保证 cut_index.json 状态一致。
    if total_selected > 0:
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = {pool.submit(_analyze_one, asset): asset for asset in selected}
            for future in concurrent.futures.as_completed(futures):
                asset = futures[future]
                status_tag, err = future.result()
                with write_lock:
                    counter["done"] += 1
                    done = counter["done"]
                    if status_tag == "ok":
                        succeeded += 1
                        if progress is not None:
                            progress.advance_success()
                    else:
                        failed += 1
                        if progress is not None:
                            progress.advance_failure()
                        if err is not None:
                            errors.append(err)
                            cut.failures.append(
                                Failure(
                                    stage=_ANALYZE_STAGE,
                                    target=asset.asset_id,
                                    reason=err[1],
                                    suggestion="检查素材级 failures 与结构化日志后重跑",
                                    blocking=(
                                        asset.analysis_status
                                        == AnalysisStatus.analysis_failed
                                    ),
                                    occurred_at=datetime.now(timezone.utc).isoformat(),
                                )
                            )
                    # Q12：每完成 _PERSIST_EVERY 个素材增量落盘一次。
                    if done % _PERSIST_EVERY == 0:
                        _persist(cut, index_path, done=done, callback=_persist_callback)

    # ---------- 阶段尾落盘 ----------
    finished_at = datetime.now(timezone.utc).isoformat()
    if total_selected == 0:
        # 无可处理素材：视作完成（不算失败）。skipped 已表示了"未处理"的语义。
        status = "completed"
    elif failed == 0:
        status = "completed"
    elif succeeded == 0:
        status = "failed"
    else:
        status = "partial"

    cut.analysis.finished_at = finished_at
    cut.analysis.status = status
    cut.analysis.error_summary = _summarize_errors(errors) or None
    _persist(cut, index_path, done=counter["done"], callback=_persist_callback)

    duration_ms = int((time.monotonic() - run_start) * 1000)
    logger.stage_end(
        stage=stage,
        succeeded=succeeded,
        failed=failed,
        skipped=skipped,
        duration_ms=duration_ms,
    )
    logger.close()

    return AnalyzeResult(
        stage=stage,
        total=total_selected,
        succeeded=succeeded,
        failed=failed,
        skipped=skipped,
        errors=list(errors),
        started_at=started_at,
        finished_at=finished_at,
        cut_index_path=str(index_path),
        log_path=str(logger.log_path),
    )


def _persist(
    cut: CutIndex,
    index_path: Path,
    *,
    done: int,
    callback: Optional[Callable[[int], None]],
) -> None:
    """落盘 ``cut_index.json``；测试时可用 ``callback`` 拦截真实写盘。

    ``callback`` 是 :func:`_run` 暴露给单元测试的钩子，签名
    ``(done_count) -> None``。注入后**不**再调用 :func:`write_cut_index`，
    便于在不触碰磁盘的情况下验证落盘次数（如 SubTask 7.5 的 5+5+2 边界）。
    """
    if callback is not None:
        callback(done)
        return
    write_cut_index(index_path, cut)


__all__ = [
    "AnalyzeResult",
    "AnalyzerError",
    "sample_analyze",
    "full_analyze",
]
