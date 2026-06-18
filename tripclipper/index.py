from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import ProjectConfig
from .utils import ensure_dir, read_json, utc_now_iso, write_json


SCHEMA_VERSION = "0.2"


def index_path(project_dir: str | Path) -> Path:
    return Path(project_dir) / "cut_index.json"


def project_dir_from_slug(slug: str, base_dir: str | Path | None = None) -> Path:
    return Path(base_dir or Path.cwd()).resolve() / "projects" / slug


def empty_index(config: ProjectConfig) -> dict[str, Any]:
    now = utc_now_iso()
    return {
        "schema_version": SCHEMA_VERSION,
        "project": {
            "project_name": config.project_name,
            "project_slug": config.project_slug,
            "source_folder": str(config.source_folder),
            "config_path": str(config.project_dir / "project.yaml"),
            "editing_intent": config.editing_intent,
            "model_config_summary": config.model_config_summary,
            "eagle_sync": config.eagle_sync or {},
            "created_at": now,
            "updated_at": now,
        },
        "capabilities": {},
        "analysis": {
            "provider": (config.model_config or {}).get("provider"),
            "vision_model": (config.model_config or {}).get("vision_model"),
            "text_model": (config.model_config or {}).get("text_model"),
            "transcription_model": (config.model_config or {}).get("transcription_model"),
            "stage": None,
            "sample_size": (config.model_config or {}).get("sample_size", 25),
            "started_at": None,
            "finished_at": None,
            "status": "not_started",
            "error_summary": None,
        },
        "assets": [],
        "similar_groups": [],
        "default_candidates": [],
        "failures": [],
        "warnings": [],
        "task_log": [],
    }


def load_index(project_dir: str | Path, config: ProjectConfig | None = None) -> dict[str, Any]:
    path = index_path(project_dir)
    data = read_json(path)
    if data is None:
        if config is None:
            raise FileNotFoundError(f"未找到项目索引：{path}")
        data = empty_index(config)
    return data


def save_index(project_dir: str | Path, data: dict[str, Any]) -> Path:
    data.setdefault("project", {})["updated_at"] = utc_now_iso()
    path = index_path(project_dir)
    ensure_dir(path.parent)
    write_json(path, data)
    return path


def record_failure(
    data: dict[str, Any],
    stage: str,
    reason: str,
    suggestion: str,
    asset_id: str | None = None,
    blocking: bool = False,
) -> dict[str, Any]:
    failure = {
        "stage": stage,
        "asset_id": asset_id,
        "reason": reason,
        "suggestion": suggestion,
        "blocking": blocking,
        "created_at": utc_now_iso(),
    }
    data.setdefault("failures", []).append(failure)
    return failure


def record_warning(
    data: dict[str, Any],
    stage: str,
    reason: str,
    suggestion: str,
    asset_id: str | None = None,
) -> dict[str, Any]:
    warning = {
        "stage": stage,
        "asset_id": asset_id,
        "reason": reason,
        "suggestion": suggestion,
        "created_at": utc_now_iso(),
    }
    data.setdefault("warnings", []).append(warning)
    return warning


def append_task_log(data: dict[str, Any], stage: str, message: str, level: str = "info") -> None:
    data.setdefault("task_log", []).append(
        {
            "stage": stage,
            "level": level,
            "message": message,
            "created_at": utc_now_iso(),
        }
    )
    data["task_log"] = data["task_log"][-100:]
