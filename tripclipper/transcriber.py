from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .config import ProjectConfig, load_project_config, materialize_project_config
from .index import append_task_log, load_index, record_failure, record_warning, save_index
from .model_provider import ModelConfigurationError, ModelProvider, ModelProviderError, create_provider
from .utils import ensure_dir, utc_now_iso


def transcription_enabled(model_config: dict[str, Any] | None) -> bool:
    return bool((model_config or {}).get("transcription_model"))


def transcribe_project(
    config_path: str | Path,
    *,
    force: bool = False,
    provider: ModelProvider | None = None,
) -> dict[str, Any]:
    config = load_project_config(config_path)
    materialize_project_config(config)
    data = load_index(config.project_dir, config)
    data["failures"] = [failure for failure in data.get("failures", []) if failure.get("stage") != "transcribe"]
    data["warnings"] = [warning for warning in data.get("warnings", []) if warning.get("stage") != "transcribe"]

    if not data.get("assets"):
        record_failure(
            data,
            "transcribe",
            reason="项目还没有可转写素材。",
            suggestion="请先执行 Stage 1 扫描，再执行音频文本提取。",
            blocking=True,
        )
        _finish_transcription(data, "failed", "缺少可转写素材。", 0, 0, 0)
        append_task_log(data, "transcribe", "缺少可转写素材，音频文本提取未执行。", "error")
        save_index(config.project_dir, data)
        return data

    try:
        model_provider = provider or create_provider(
            config.model_config,
            require_analysis_model=False,
            require_transcription_model=True,
        )
    except ModelConfigurationError as exc:
        record_failure(
            data,
            "transcribe",
            reason=str(exc),
            suggestion="请补齐 model_config.transcription_model，并确认 api_key_env 指向的环境变量已设置。",
            blocking=True,
        )
        _finish_transcription(data, "failed", str(exc), 0, 0, 0)
        append_task_log(data, "transcribe", "音频转写模型配置不可用。", "error")
        save_index(config.project_dir, data)
        return data

    result = transcribe_assets(config, data, data.get("assets", []), model_provider, force=force)
    status = "completed"
    error_summary = None
    if result["transcribed"] == 0 and result["failed"]:
        status = "failed"
        error_summary = f"{result['failed']} 个素材转写失败。"
    elif result["failed"]:
        status = "completed_with_failures"
        error_summary = f"{result['failed']} 个素材转写失败，{result['transcribed']} 个素材成功。"
    elif result["transcribed"] == 0 and any(warning.get("stage") == "transcribe" for warning in data.get("warnings", [])):
        status = "completed_with_warnings"
        error_summary = "音频文本提取被跳过，请查看 warning。"
    _finish_transcription(data, status, error_summary, result["transcribed"], result["skipped"], result["failed"])
    append_task_log(
        data,
        "transcribe",
        f"音频文本提取完成：成功 {result['transcribed']}，跳过 {result['skipped']}，失败 {result['failed']}。",
    )
    save_index(config.project_dir, data)
    return data


def transcribe_assets(
    config: ProjectConfig,
    data: dict[str, Any],
    assets: list[dict[str, Any]],
    provider: ModelProvider,
    *,
    force: bool = False,
) -> dict[str, int]:
    targets = _select_transcription_targets(assets, force=force)
    result = {"transcribed": 0, "skipped": 0, "failed": 0}
    if not targets:
        result["skipped"] = len(assets)
        return result

    ffmpeg_path = shutil.which("ffmpeg")
    capabilities = data.setdefault("capabilities", {})
    capabilities["ffmpeg"] = bool(ffmpeg_path)
    capabilities["ffmpeg_path"] = ffmpeg_path
    if not ffmpeg_path:
        record_warning(
            data,
            "transcribe",
            "未找到 ffmpeg，无法从视频或音频文件中抽取音轨。",
            "请安装 ffmpeg 后重新执行音频文本提取。",
        )
        result["skipped"] = len(targets)
        return result

    for asset in targets:
        _clear_asset_transcription_records(asset)
        try:
            transcript_path = _transcribe_asset(config.project_dir, asset, provider)
            asset["transcript_path"] = str(transcript_path)
            asset["transcription_status"] = "transcribed"
            asset["transcribed_at"] = utc_now_iso()
            result["transcribed"] += 1
        except Exception as exc:
            asset["transcription_status"] = "failed"
            asset["transcribed_at"] = utc_now_iso()
            asset.setdefault("failures", []).append(
                {
                    "stage": "transcribe",
                    "reason": str(exc),
                    "suggestion": "请检查 ffmpeg、转写模型配置、模型服务能力或素材音轨后重试。",
                    "blocking": False,
                    "created_at": utc_now_iso(),
                }
            )
            record_failure(
                data,
                "transcribe",
                reason=f"{asset.get('file')} 音频文本提取失败：{exc}",
                suggestion="请检查 ffmpeg、转写模型配置、模型服务能力或素材音轨后重试。",
                asset_id=asset.get("asset_id"),
                blocking=False,
            )
            result["failed"] += 1

    result["skipped"] += len(assets) - len(targets)
    return result


def _select_transcription_targets(assets: list[dict[str, Any]], *, force: bool) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    for asset in assets:
        if not _asset_can_have_audio(asset):
            asset.setdefault("transcription_status", "not_applicable")
            continue
        if not force and _transcript_available(asset):
            asset["transcription_status"] = "transcribed"
            continue
        targets.append(asset)
    return targets


def _asset_can_have_audio(asset: dict[str, Any]) -> bool:
    media_type = asset.get("type")
    if media_type == "audio":
        return True
    if media_type != "video":
        return False
    metadata = asset.get("metadata") or {}
    return metadata.get("has_audio") is not False


def _transcript_available(asset: dict[str, Any]) -> bool:
    path = asset.get("transcript_path")
    return bool(path and Path(path).exists() and Path(path).stat().st_size > 0)


def _transcribe_asset(project_dir: Path, asset: dict[str, Any], provider: ModelProvider) -> Path:
    asset_id = str(asset.get("asset_id") or "asset")
    transcript_dir = ensure_dir(project_dir / "cache" / "transcripts")
    transcript_path = transcript_dir / f"{asset_id}.txt"
    audio_cache_dir = ensure_dir(project_dir / "cache" / "audio")
    with tempfile.TemporaryDirectory(prefix=f"{asset_id}_", dir=audio_cache_dir) as tmp:
        audio_path = Path(tmp) / "audio.wav"
        _extract_audio(Path(str(asset.get("path"))), audio_path)
        text = _normalize_transcript_text(provider.transcribe_audio(audio_path))
    if not text:
        raise ModelProviderError("音频转写结果为空。")
    transcript_path.write_text(text + "\n", encoding="utf-8")
    return transcript_path


def _extract_audio(source_path: Path, audio_path: Path) -> None:
    if not source_path.exists():
        raise ModelProviderError(f"素材文件不存在：{source_path}")
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(source_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-f",
        "wav",
        str(audio_path),
    ]
    try:
        subprocess.run(command, capture_output=True, text=True, check=True, timeout=600)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        raise ModelProviderError(f"ffmpeg 音轨抽取失败：{detail[:500]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ModelProviderError("ffmpeg 音轨抽取超时。") from exc
    if not audio_path.exists() or audio_path.stat().st_size <= 0:
        raise ModelProviderError("ffmpeg 未生成可用音频文件。")


def _normalize_transcript_text(value: Any) -> str:
    return "\n".join(line.rstrip() for line in str(value or "").strip().splitlines()).strip()


def _clear_asset_transcription_records(asset: dict[str, Any]) -> None:
    asset["failures"] = [
        failure for failure in asset.get("failures", []) if failure.get("stage") != "transcribe"
    ]


def _finish_transcription(
    data: dict[str, Any],
    status: str,
    error_summary: str | None,
    transcribed: int,
    skipped: int,
    failed: int,
) -> None:
    data["transcription"] = {
        "status": status,
        "transcribed": transcribed,
        "skipped": skipped,
        "failed": failed,
        "finished_at": utc_now_iso(),
        "error_summary": error_summary,
    }
