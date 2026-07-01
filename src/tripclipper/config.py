"""``project.yaml`` configuration models, loading and validation (TD 4).

Naming note: Pydantic v2 reserves the ``model_config`` attribute name for the
per-model ``ConfigDict``. The YAML key ``model_config`` therefore cannot be a
field literally named ``model_config``. Worse, field names beginning with the
``model_`` prefix are protected and emit warnings. To stay clear of both
problems the model configuration is stored in a field named ``llm`` with
``alias="model_config"`` (plus ``populate_by_name=True``), so it can be read
from the YAML ``model_config`` key while keeping a safe Python attribute name.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Union

import yaml
from pydantic import BaseModel, ConfigDict, Field


class ConfigError(Exception):
    """Raised when ``project.yaml`` is missing required fields or invalid."""


class ModelConfig(BaseModel):
    """Real model-access configuration (TD 4 ``model_config``).

    All fields are optional so an incomplete configuration can still be saved
    and loaded; usability is reflected by :meth:`is_usable`.
    """

    model_config = ConfigDict(populate_by_name=True)

    provider: Optional[str] = None
    base_url: Optional[str] = None
    api_key_env: Optional[str] = None
    vision_model: Optional[str] = None
    text_model: Optional[str] = None
    transcription_model: Optional[str] = None
    language: Optional[str] = "zh-CN"
    sample_size: Optional[int] = 25

    def is_usable(self) -> bool:
        """Return True only when the key model-access fields are all present."""
        return all(
            bool(value)
            for value in (
                self.provider,
                self.base_url,
                self.api_key_env,
                self.vision_model,
            )
        )


class EagleSync(BaseModel):
    """Eagle adapter sync settings (TD 4 ``eagle_sync``)."""

    model_config = ConfigDict(populate_by_name=True)

    enabled: bool = True
    mode: str = "dry-run"
    base_url: str = "http://127.0.0.1:41595/api"
    # M6: Eagle Web API client settings. Eagle 4.x uses a hybrid V1/V2 API on
    # the same host root (item/addFromPath is V1-only, item/update and the
    # tagGroup/* family are V2), so the client takes the host root only and
    # routes the /api/v2/ vs /api/ prefix internally. The tolerant loader in
    # EagleV2Client still accepts old configs that ended in /api/v2/ or /api/.
    api_base_url: str = "http://localhost:41595"
    api_token: Optional[str] = None
    connection_failure_threshold: int = 5
    mapping_overrides: Optional[dict] = None


class EditingIntent(BaseModel):
    """Aggregated editing intent (TD 4)."""

    model_config = ConfigDict(populate_by_name=True)

    output_style: Optional[str] = None
    target_length: Optional[str] = None
    audience: Optional[str] = None
    people_focus: Optional[str] = None
    audio_priority: Optional[str] = None


class ProjectConfig(BaseModel):
    """Parsed ``project.yaml`` (TD 4)."""

    model_config = ConfigDict(populate_by_name=True)

    project_name: str
    source_folder: str  # resolved to an absolute path by load_config
    project_slug: Optional[str] = None
    # See module docstring: ``llm`` with alias "model_config" sidesteps the
    # Pydantic reserved/protected name conflict.
    llm: ModelConfig = Field(default_factory=ModelConfig, alias="model_config")
    editing_intent: EditingIntent = Field(default_factory=EditingIntent)
    eagle_sync: EagleSync = Field(default_factory=EagleSync)
    config_path: Optional[str] = None


# Required top-level keys in project.yaml.
_REQUIRED_KEYS = ("project_name", "source_folder", "model_config")

# Editing-intent keys aggregated from the top level of project.yaml.
_EDITING_INTENT_KEYS = (
    "output_style",
    "target_length",
    "audience",
    "people_focus",
    "audio_priority",
)


def generate_project_slug(project_name: str) -> str:
    """Deterministically derive a URL/path-safe slug from ``project_name``.

    Lower-cases, strips, collapses runs of non-alphanumeric characters into a
    single ``-`` and trims leading/trailing ``-``. Pure and deterministic.

    Example: ``"2026 Team Event"`` -> ``"2026-team-event"``.
    """
    import re

    text = (project_name or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    return text


def load_config(path: Union[str, Path]) -> ProjectConfig:
    """Load and validate ``project.yaml`` into a :class:`ProjectConfig`.

    - Validates the required keys ``project_name``, ``source_folder`` and
      ``model_config``; missing keys raise :class:`ConfigError` naming them.
    - Resolves a relative ``source_folder`` against the YAML file's directory.
    - Generates ``project_slug`` from ``project_name`` when absent.
    - Aggregates editing-intent fields into :class:`EditingIntent`.
    - An incomplete ``model_config`` still loads successfully; usability is
      reflected by ``config.llm.is_usable()``.
    """
    yaml_path = Path(path).expanduser().resolve()
    if not yaml_path.is_file():
        raise ConfigError(f"Config file not found: {yaml_path}")

    with yaml_path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ConfigError(
            f"Config root must be a mapping/object, got {type(data).__name__}"
        )

    missing = [key for key in _REQUIRED_KEYS if not data.get(key)]
    if missing:
        raise ConfigError(
            "Missing required field(s) in project.yaml: " + ", ".join(missing)
        )

    base_dir = yaml_path.parent

    # Resolve source_folder relative to the YAML file's directory.
    source_folder = Path(str(data["source_folder"])).expanduser()
    if not source_folder.is_absolute():
        source_folder = (base_dir / source_folder).resolve()
    else:
        source_folder = source_folder.resolve()

    project_name = str(data["project_name"])
    project_slug = data.get("project_slug") or generate_project_slug(project_name)

    # Model config: tolerate incomplete content.
    raw_model_config = data.get("model_config") or {}
    if not isinstance(raw_model_config, dict):
        raise ConfigError("model_config must be a mapping/object")
    llm = ModelConfig.model_validate(raw_model_config)

    # Aggregate editing intent from top-level keys.
    editing_intent = EditingIntent(
        **{key: data.get(key) for key in _EDITING_INTENT_KEYS}
    )

    # Eagle sync settings (defaults: enabled=True, mode=dry-run).
    raw_eagle = data.get("eagle_sync") or {}
    if not isinstance(raw_eagle, dict):
        raise ConfigError("eagle_sync must be a mapping/object")
    eagle_sync = EagleSync.model_validate(raw_eagle)

    return ProjectConfig(
        project_name=project_name,
        source_folder=str(source_folder),
        project_slug=project_slug,
        llm=llm,
        editing_intent=editing_intent,
        eagle_sync=eagle_sync,
        config_path=str(yaml_path),
    )


__all__ = [
    "ConfigError",
    "ModelConfig",
    "EagleSync",
    "EditingIntent",
    "ProjectConfig",
    "generate_project_slug",
    "load_config",
]
