from __future__ import annotations

from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from .config import load_project_config, materialize_project_config
from .index import append_task_log, load_index, record_failure, save_index
from .model_provider import ModelConfigurationError, ModelProvider, ModelProviderError, create_provider
from .postprocess import apply_postprocessing
from .scanner import scan_project
from .utils import safe_int, utc_now_iso


def analyze_project(
    config_path: str | Path,
    stage: str,
    *,
    force: bool = False,
    provider: ModelProvider | None = None,
) -> dict[str, Any]:
    if stage == "scan":
        return scan_project(config_path)
    if stage not in {"sample", "full"}:
        raise ValueError("stage 必须是 scan、sample 或 full。")

    config = load_project_config(config_path)
    materialize_project_config(config)
    data = load_index(config.project_dir, config)
    if not data.get("assets"):
        record_failure(
            data,
            stage=stage,
            reason="项目还没有可分析素材。",
            suggestion="请先执行 Stage 1 扫描，再执行样本或全量分析。",
            blocking=True,
        )
        _finish_analysis(data, stage, status="failed", error_summary="缺少可分析素材。")
        append_task_log(data, stage, "缺少可分析素材，Stage 2 未执行。", "error")
        save_index(config.project_dir, data)
        return data

    try:
        model_provider = provider or create_provider(config.model_config)
    except ModelConfigurationError as exc:
        record_failure(
            data,
            stage=stage,
            reason=str(exc),
            suggestion="请补齐 model_config，并确认 api_key_env 指向的环境变量已设置。",
            blocking=True,
        )
        _finish_analysis(data, stage, status="failed", error_summary=str(exc))
        append_task_log(data, stage, "模型配置不可用，Stage 2 未执行。", "error")
        save_index(config.project_dir, data)
        return data

    targets = _select_targets(data.get("assets", []), config.model_config or {}, stage, force)
    if not targets:
        _finish_analysis(data, stage, status="completed", error_summary=None)
        append_task_log(data, stage, "没有待分析素材。")
        apply_postprocessing(data)
        save_index(config.project_dir, data)
        return data

    _start_analysis(data, config.model_config or {}, stage)
    success_count = 0
    failure_count = 0
    for asset in targets:
        try:
            result = model_provider.analyze_asset(data["project"], asset)
            _apply_analysis_result(asset, result)
            success_count += 1
        except ModelProviderError as exc:
            _mark_asset_analysis_failed(asset, stage, str(exc), "请检查模型输出、模型能力或访问配置后重试。")
            record_failure(
                data,
                stage=stage,
                reason=f"{asset.get('file')} 分析失败：{exc}",
                suggestion="请检查模型配置、模型返回格式或素材可读性。",
                asset_id=asset.get("asset_id"),
                blocking=False,
            )
            failure_count += 1
        except Exception as exc:  # pragma: no cover - keeps batch runs recoverable.
            _mark_asset_analysis_failed(asset, stage, str(exc), "请查看错误详情后重试。")
            record_failure(
                data,
                stage=stage,
                reason=f"{asset.get('file')} 分析失败：{exc}",
                suggestion="请检查模型服务状态或素材可读性。",
                asset_id=asset.get("asset_id"),
                blocking=False,
            )
            failure_count += 1

    apply_postprocessing(data)
    if success_count == 0 and failure_count:
        status = "failed"
        error_summary = f"{failure_count} 个素材分析失败。"
    elif failure_count:
        status = "completed_with_failures"
        error_summary = f"{failure_count} 个素材分析失败，{success_count} 个素材成功。"
    else:
        status = "completed"
        error_summary = None
    _finish_analysis(data, stage, status=status, error_summary=error_summary)
    append_task_log(data, stage, f"Stage 2 {stage} 完成：成功 {success_count}，失败 {failure_count}。")
    save_index(config.project_dir, data)
    return data


def _select_targets(
    assets: list[dict[str, Any]],
    model_config: dict[str, Any],
    stage: str,
    force: bool,
) -> list[dict[str, Any]]:
    candidates = [
        asset
        for asset in assets
        if asset.get("type") in {"video", "image", "audio"}
        and (force or asset.get("analysis_status") != "analyzed")
    ]
    if stage == "full":
        return sorted(candidates, key=lambda asset: asset.get("relative_path") or "")

    sample_size = safe_int(model_config.get("sample_size"), 25)
    sample_size = max(1, min(sample_size, 30))
    return _balanced_sample(candidates, sample_size)


def _balanced_sample(assets: list[dict[str, Any]], sample_size: int) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, str], deque[dict[str, Any]]] = defaultdict(deque)
    for asset in sorted(assets, key=lambda item: (item.get("type") or "", item.get("relative_path") or "")):
        parent = str(Path(asset.get("relative_path") or "").parent)
        buckets[(asset.get("type") or "unknown", parent)].append(asset)
    result: list[dict[str, Any]] = []
    keys = sorted(buckets)
    while len(result) < sample_size and any(buckets.values()):
        for key in keys:
            if len(result) >= sample_size:
                break
            if buckets[key]:
                result.append(buckets[key].popleft())
    return result


def _apply_analysis_result(asset: dict[str, Any], result: dict[str, Any]) -> None:
    asset.update(
        {
            "analysis_status": "analyzed",
            "scene": result.get("scene"),
            "summary": result["summary"],
            "tags": result["tags"],
            "rating": result["rating"],
            "subject_type": result["subject_type"],
            "primary_subject": result["primary_subject"],
            "people_presence": result["people_presence"],
            "shot_scale": result["shot_scale"],
            "shot_function": result["shot_function"],
            "segments": result["segments"],
            "audio_suggestion": result["audio_suggestion"],
            "audio_strategy": result["audio_strategy"],
        }
    )


def _mark_asset_analysis_failed(asset: dict[str, Any], stage: str, reason: str, suggestion: str) -> None:
    asset["analysis_status"] = "analysis_failed"
    asset.setdefault("failures", []).append(
        {
            "stage": stage,
            "reason": reason,
            "suggestion": suggestion,
            "blocking": False,
            "created_at": utc_now_iso(),
        }
    )


def _start_analysis(data: dict[str, Any], model_config: dict[str, Any], stage: str) -> None:
    data["analysis"] = {
        "provider": model_config.get("provider"),
        "vision_model": model_config.get("vision_model"),
        "text_model": model_config.get("text_model"),
        "transcription_model": model_config.get("transcription_model"),
        "stage": stage,
        "sample_size": safe_int(model_config.get("sample_size"), 25),
        "started_at": utc_now_iso(),
        "finished_at": None,
        "status": "running",
        "error_summary": None,
    }


def _finish_analysis(data: dict[str, Any], stage: str, status: str, error_summary: str | None) -> None:
    analysis = data.setdefault("analysis", {})
    analysis["stage"] = stage
    analysis.setdefault("started_at", utc_now_iso())
    analysis["finished_at"] = utc_now_iso()
    analysis["status"] = status
    analysis["error_summary"] = error_summary
