from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any

from .config import ProjectConfig, load_project_config, materialize_project_config
from .constants import AUDIO_EXTENSIONS, IMAGE_EXTENSIONS, MEDIA_EXTENSIONS, VIDEO_EXTENSIONS
from .index import (
    append_task_log,
    empty_index,
    load_index,
    record_failure,
    record_warning,
    save_index,
)
from .utils import ensure_dir, normalize_path_for_id, stable_hash, utc_now_iso


def media_type_for_extension(extension: str) -> str | None:
    ext = extension.lower()
    if ext in VIDEO_EXTENSIONS:
        return "video"
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext in AUDIO_EXTENSIONS:
        return "audio"
    return None


def scan_project(config_path: str | Path) -> dict[str, Any]:
    config = load_project_config(config_path)
    materialize_project_config(config)
    data = load_index(config.project_dir, config)
    data = _refresh_project_block(data, config)
    data["failures"] = [failure for failure in data.get("failures", []) if failure.get("stage") != "scan"]
    data["warnings"] = [warning for warning in data.get("warnings", []) if warning.get("stage") != "scan"]
    data["capabilities"] = detect_media_capabilities()
    data["assets"] = []
    data["similar_groups"] = []
    data["default_candidates"] = []

    if not config.source_folder.exists() or not config.source_folder.is_dir():
        record_failure(
            data,
            stage="scan",
            reason=f"素材目录不存在或不可访问：{config.source_folder}",
            suggestion="请检查 source_folder 是否填写正确，并确认当前用户有读取权限。",
            blocking=True,
        )
        append_task_log(data, "scan", "素材目录不可访问，扫描停止。", "error")
        save_index(config.project_dir, data)
        return data

    if not data["capabilities"]["ffprobe"]:
        record_warning(
            data,
            "scan",
            "未找到 ffprobe，Stage 1 将只保存基础文件信息。",
            "如需时长、编码、分辨率等媒体信息，请安装 ffmpeg/ffprobe 并重新扫描。",
        )
    if not data["capabilities"]["ffmpeg"]:
        record_warning(
            data,
            "scan",
            "未找到 ffmpeg，Stage 1 将跳过缩略图和关键帧生成。",
            "如需本地报告缩略图和更强模型视觉上下文，请安装 ffmpeg 并重新扫描。",
        )

    existing = _existing_assets_by_id(load_index(config.project_dir, config).get("assets", []))
    media_files = list(_iter_media_files(config.source_folder))
    if not media_files:
        record_warning(
            data,
            "scan",
            "素材目录中未发现可处理媒体文件。",
            "请确认目录中包含支持的视频、图片或音频文件。",
        )

    for path in media_files:
        try:
            asset = build_asset_record(path, config, data["capabilities"], existing)
            data["assets"].append(asset)
        except Exception as exc:  # pragma: no cover - defensive, per-file resilience matters here.
            record_failure(
                data,
                "scan",
                reason=f"扫描文件失败：{path.name}；{exc}",
                suggestion="请检查文件是否损坏，或确认当前用户有读取权限。",
                blocking=False,
            )

    data["assets"].sort(key=lambda item: item["relative_path"])
    append_task_log(data, "scan", f"扫描完成：发现 {len(data['assets'])} 个媒体文件。")
    save_index(config.project_dir, data)
    return data


def detect_media_capabilities() -> dict[str, Any]:
    return {
        "ffprobe": bool(shutil.which("ffprobe")),
        "ffprobe_path": shutil.which("ffprobe"),
        "ffmpeg": bool(shutil.which("ffmpeg")),
        "ffmpeg_path": shutil.which("ffmpeg"),
        "detected_at": utc_now_iso(),
    }


def build_asset_record(
    path: Path,
    config: ProjectConfig,
    capabilities: dict[str, Any],
    existing: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    relative_path = path.relative_to(config.source_folder)
    stat = path.stat()
    asset_id = _asset_id(relative_path, stat.st_size)
    media_type = media_type_for_extension(path.suffix)
    modified_time = datetime.fromtimestamp(stat.st_mtime, timezone.utc).replace(microsecond=0).isoformat()
    old = (existing or {}).get(asset_id)

    asset = {
        "asset_id": asset_id,
        "file": path.name,
        "filename": path.name,
        "path": str(path.resolve()),
        "relative_path": normalize_path_for_id(relative_path),
        "type": media_type,
        "extension": path.suffix.lower(),
        "size": stat.st_size,
        "modified_time": modified_time,
        "metadata": {},
        "thumbnail_path": None,
        "frame_paths": [],
        "transcript_path": None,
        "analysis_status": "scanned",
        "scene": None,
        "summary": None,
        "tags": [],
        "rating": None,
        "subject_type": None,
        "primary_subject": None,
        "people_presence": None,
        "shot_scale": None,
        "shot_function": None,
        "segments": [],
        "audio_suggestion": None,
        "audio_strategy": None,
        "similar_group_id": None,
        "similar_selection": "none",
        "similar_rank": None,
        "similar_reason": None,
        "edit_candidate_status": None,
        "edit_candidate_priority": None,
        "edit_candidate_reason": None,
        "eagle_item_id": None,
        "eagle_sync_status": "not_synced",
        "warnings": [],
        "failures": [],
    }

    if old and _same_file_identity(old, asset):
        preserved = dict(old)
        preserved.update({key: asset[key] for key in _scan_owned_fields()})
        asset = preserved

    if capabilities.get("ffprobe"):
        metadata, warning = ffprobe_metadata(path)
        if warning:
            asset.setdefault("warnings", []).append(warning)
        asset["metadata"] = metadata

    if capabilities.get("ffmpeg") and media_type == "video":
        thumb = generate_video_thumbnail(path, config.project_dir, asset_id)
        if thumb:
            asset["thumbnail_path"] = str(thumb)
            asset["frame_paths"] = [str(thumb)]

    if media_type == "image":
        asset["frame_paths"] = [str(path.resolve())]
        asset["thumbnail_path"] = str(path.resolve())

    return asset


def ffprobe_metadata(path: Path) -> tuple[dict[str, Any], dict[str, Any] | None]:
    command = [
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
        completed = subprocess.run(command, capture_output=True, text=True, check=True, timeout=30)
        raw = json.loads(completed.stdout or "{}")
    except Exception as exc:
        return {}, {
            "stage": "scan",
            "reason": f"ffprobe 无法读取媒体信息：{exc}",
            "suggestion": "文件仍会保留基础信息；如需完整媒体信息，请检查文件或 ffprobe。",
        }

    streams = raw.get("streams") or []
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
    fmt = raw.get("format") or {}
    metadata = {
        "duration": _duration_to_timecode(fmt.get("duration") or (video or {}).get("duration")),
        "duration_seconds": _float_or_none(fmt.get("duration") or (video or {}).get("duration")),
        "width": (video or {}).get("width"),
        "height": (video or {}).get("height"),
        "codec": (video or audio or {}).get("codec_name"),
        "fps": _fps((video or {}).get("avg_frame_rate") or (video or {}).get("r_frame_rate")),
        "has_audio": audio is not None,
    }
    return metadata, None


def generate_video_thumbnail(path: Path, project_dir: Path, asset_id: str) -> Path | None:
    thumb_dir = ensure_dir(project_dir / "cache" / "thumbnails")
    thumb_path = thumb_dir / f"{asset_id}.jpg"
    command = [
        "ffmpeg",
        "-y",
        "-ss",
        "00:00:01",
        "-i",
        str(path),
        "-frames:v",
        "1",
        "-vf",
        "scale=480:-1",
        str(thumb_path),
    ]
    try:
        subprocess.run(command, capture_output=True, text=True, check=True, timeout=60)
        return thumb_path if thumb_path.exists() else None
    except Exception:
        return None


def _iter_media_files(source_folder: Path) -> list[Path]:
    media: list[Path] = []
    for path in sorted(source_folder.rglob("*")):
        if path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS:
            media.append(path)
    return media


def _asset_id(relative_path: Path, size: int) -> str:
    source = f"{normalize_path_for_id(relative_path)}:{size}"
    return f"asset_{stable_hash(source, 12)}"


def _duration_to_timecode(value: Any) -> str | None:
    seconds = _float_or_none(value)
    if seconds is None:
        return None
    seconds_int = max(0, int(round(seconds)))
    hours, remainder = divmod(seconds_int, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fps(value: Any) -> float | None:
    if not value:
        return None
    try:
        fraction = Fraction(str(value))
        if fraction.denominator == 0:
            return None
        return round(float(fraction), 3)
    except (ValueError, ZeroDivisionError):
        return None


def _refresh_project_block(data: dict[str, Any], config: ProjectConfig) -> dict[str, Any]:
    if not data:
        data = empty_index(config)
    project = data.setdefault("project", {})
    project.update(
        {
            "project_name": config.project_name,
            "project_slug": config.project_slug,
            "source_folder": str(config.source_folder),
            "config_path": str(config.project_dir / "project.yaml"),
            "editing_intent": config.editing_intent,
            "model_config_summary": config.model_config_summary,
            "eagle_sync": config.eagle_sync or {},
        }
    )
    return data


def _existing_assets_by_id(assets: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {asset.get("asset_id"): asset for asset in assets if asset.get("asset_id")}


def _same_file_identity(old: dict[str, Any], new: dict[str, Any]) -> bool:
    return old.get("size") == new.get("size") and old.get("modified_time") == new.get("modified_time")


def _scan_owned_fields() -> list[str]:
    return [
        "asset_id",
        "file",
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
        "transcript_path",
    ]
