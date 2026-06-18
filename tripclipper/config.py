from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .utils import ensure_dir, slugify, utc_now_iso


@dataclass(frozen=True)
class ProjectConfig:
    project_name: str
    project_slug: str
    source_folder: Path
    config_path: Path
    project_dir: Path
    output_style: str = "travel_vlog"
    target_length: str = "3min"
    audience: str = "friends"
    people_focus: str = "medium"
    audio_priority: str = "medium"
    model_config: dict[str, Any] | None = None
    eagle_sync: dict[str, Any] | None = None

    @property
    def editing_intent(self) -> dict[str, str]:
        return {
            "output_style": self.output_style,
            "target_length": self.target_length,
            "audience": self.audience,
            "people_focus": self.people_focus,
            "audio_priority": self.audio_priority,
        }

    @property
    def model_config_summary(self) -> dict[str, Any]:
        config = dict(self.model_config or {})
        config.pop("api_key", None)
        return config


def _resolve_source_folder(raw: str, config_path: Path) -> Path:
    source = Path(raw).expanduser()
    if not source.is_absolute():
        source = (config_path.parent / source).resolve()
    return source.resolve()


def _project_dir_for_config(config_path: Path, slug: str, raw: dict[str, Any]) -> Path:
    if raw.get("project_dir"):
        project_dir = Path(raw["project_dir"]).expanduser()
        if not project_dir.is_absolute():
            project_dir = (config_path.parent / project_dir).resolve()
        return project_dir
    if config_path.name == "project.yaml" and config_path.parent.name == slug:
        return config_path.parent.resolve()
    output_root = Path(raw.get("output_root", "projects"))
    if not output_root.is_absolute():
        output_root = (Path.cwd() / output_root).resolve()
    return output_root / slug


def load_project_config(config_path: str | Path) -> ProjectConfig:
    path = Path(config_path).expanduser().resolve()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    project_name = str(raw.get("project_name") or "").strip()
    if not project_name:
        raise ValueError("project_name 是必填项。")
    if not raw.get("source_folder"):
        raise ValueError("source_folder 是必填项。")
    slug = str(raw.get("project_slug") or slugify(project_name))
    return ProjectConfig(
        project_name=project_name,
        project_slug=slug,
        source_folder=_resolve_source_folder(str(raw["source_folder"]), path),
        config_path=path,
        project_dir=_project_dir_for_config(path, slug, raw),
        output_style=str(raw.get("output_style") or "travel_vlog"),
        target_length=str(raw.get("target_length") or "3min"),
        audience=str(raw.get("audience") or "friends"),
        people_focus=str(raw.get("people_focus") or "medium"),
        audio_priority=str(raw.get("audio_priority") or "medium"),
        model_config=dict(raw.get("model_config") or {}),
        eagle_sync={**{"enabled": True, "mode": "dry-run"}, **dict(raw.get("eagle_sync") or {})},
    )


def validate_model_config(model_config: dict[str, Any] | None) -> list[str]:
    config = model_config or {}
    errors: list[str] = []
    provider = config.get("provider")
    if provider != "openai_compatible":
        errors.append("model_config.provider 必须是 openai_compatible。")
    if not config.get("base_url"):
        errors.append("model_config.base_url 缺失。")
    if not (config.get("vision_model") or config.get("text_model")):
        errors.append("model_config.vision_model 或 text_model 至少需要一个。")
    api_key_env = config.get("api_key_env")
    if not api_key_env:
        errors.append("model_config.api_key_env 缺失。")
    elif not os.environ.get(str(api_key_env)):
        errors.append(f"环境变量 {api_key_env} 未设置，Stage 2 无法调用真实模型。")
    return errors


def create_project_config(payload: dict[str, Any], base_dir: str | Path | None = None) -> Path:
    base = Path(base_dir or Path.cwd()).resolve()
    project_name = str(payload.get("project_name") or "").strip()
    source_folder = str(payload.get("source_folder") or "").strip()
    if not project_name:
        raise ValueError("project_name 是必填项。")
    if not source_folder:
        raise ValueError("source_folder 是必填项。")

    slug = str(payload.get("project_slug") or slugify(project_name))
    project_dir = ensure_dir(base / "projects" / slug)
    source_path = Path(source_folder).expanduser()
    if not source_path.is_absolute():
        source_path = (base / source_path).resolve()
    config = {
        "project_name": project_name,
        "project_slug": slug,
        "source_folder": str(source_path),
        "output_style": payload.get("output_style", "travel_vlog"),
        "target_length": payload.get("target_length", "3min"),
        "audience": payload.get("audience", "friends"),
        "people_focus": payload.get("people_focus", "medium"),
        "audio_priority": payload.get("audio_priority", "medium"),
        "model_config": payload.get("model_config") or {},
        "eagle_sync": {
            **{"enabled": True, "mode": "dry-run", "base_url": "http://127.0.0.1:41595/api"},
            **dict(payload.get("eagle_sync") or {}),
        },
        "created_at": utc_now_iso(),
    }
    config_path = project_dir / "project.yaml"
    config_path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return config_path


def materialize_project_config(config: ProjectConfig) -> Path:
    ensure_dir(config.project_dir)
    target = config.project_dir / "project.yaml"
    if config.config_path != target:
        shutil.copyfile(config.config_path, target)
    return target
