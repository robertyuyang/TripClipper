"""Project-level and software-level configuration models and loaders."""

from __future__ import annotations

import os
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


class AnalysisConfig(BaseModel):
    """Analysis/runtime settings for Stage 2 orchestration."""

    model_config = ConfigDict(populate_by_name=True)

    sample_size: int = 25
    language: str = "zh-CN"


class SoftwareConfig(BaseModel):
    """Software-level config loaded from repo-local ``config/config.yaml``."""

    model_config = ConfigDict(populate_by_name=True)

    llm: ModelConfig = Field(default_factory=ModelConfig, alias="model_config")
    analysis: AnalysisConfig = Field(
        default_factory=AnalysisConfig, alias="analysis_config"
    )
    config_path: Optional[str] = None


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
    # Expected Eagle library path (ends with ``.library``). Acts as a guard:
    # if set, sync-eagle aborts when it differs from the library Eagle currently
    # has open. The ``--library-path`` CLI flag overrides this when provided.
    library_path: Optional[str] = None
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
    editing_intent: EditingIntent = Field(default_factory=EditingIntent)
    eagle_sync: EagleSync = Field(default_factory=EagleSync)
    config_path: Optional[str] = None


# Required top-level keys in project.yaml.
_REQUIRED_KEYS = ("project_name", "source_folder")

# Editing-intent keys aggregated from the top level of project.yaml.
_EDITING_INTENT_KEYS = (
    "output_style",
    "target_length",
    "audience",
    "people_focus",
    "audio_priority",
)

_DEFAULT_SOFTWARE_CONFIG_ENV = "TRIPCLIPPER_SOFTWARE_CONFIG"
_DEFAULT_SOFTWARE_CONFIG_RELATIVE = Path("config") / "config.yaml"


def repo_root() -> Path:
    """Return the repository root for this source checkout."""
    return Path(__file__).resolve().parents[2]


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


def _read_yaml_mapping(
    path: Union[str, Path], *, missing_ok: bool = False
) -> tuple[Path, dict[str, Any]]:
    """Read a YAML mapping from ``path`` and return ``(resolved_path, data)``."""
    yaml_path = Path(path).expanduser().resolve()
    if not yaml_path.is_file():
        if missing_ok:
            return yaml_path, {}
        raise ConfigError(f"Config file not found: {yaml_path}")

    with yaml_path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ConfigError(
            f"Config root must be a mapping/object, got {type(data).__name__}"
        )
    return yaml_path, data


def software_config_path(path: Optional[Union[str, Path]] = None) -> Path:
    """Return the resolved software-config path."""
    if path is not None:
        return Path(path).expanduser().resolve()

    env_path = os.environ.get(_DEFAULT_SOFTWARE_CONFIG_ENV, "").strip()
    if env_path:
        return Path(env_path).expanduser().resolve()

    return (repo_root() / _DEFAULT_SOFTWARE_CONFIG_RELATIVE).resolve()


def _parse_software_sections(
    data: dict[str, Any]
) -> tuple[ModelConfig, AnalysisConfig]:
    raw_model_config = data.get("model_config") or {}
    if not isinstance(raw_model_config, dict):
        raise ConfigError("model_config must be a mapping/object")
    llm = ModelConfig.model_validate(raw_model_config)

    raw_analysis_config = data.get("analysis_config") or {}
    if not isinstance(raw_analysis_config, dict):
        raise ConfigError("analysis_config must be a mapping/object")
    if (
        "sample_size" not in raw_analysis_config
        and raw_model_config.get("sample_size") is not None
    ):
        raw_analysis_config = dict(raw_analysis_config)
        raw_analysis_config["sample_size"] = raw_model_config["sample_size"]
    if (
        "language" not in raw_analysis_config
        and raw_model_config.get("language") is not None
    ):
        raw_analysis_config = dict(raw_analysis_config)
        raw_analysis_config["language"] = raw_model_config["language"]
    analysis = AnalysisConfig.model_validate(raw_analysis_config)
    return llm, analysis


def load_software_config(
    path: Optional[Union[str, Path]] = None,
    *,
    legacy_project_path: Optional[Union[str, Path]] = None,
) -> SoftwareConfig:
    """Load software-level config, optionally falling back to legacy project keys."""
    resolved_path = software_config_path(path)
    _, data = _read_yaml_mapping(resolved_path, missing_ok=True)

    if legacy_project_path is not None:
        _, legacy_data = _read_yaml_mapping(legacy_project_path, missing_ok=False)
        if not data.get("model_config") and legacy_data.get("model_config"):
            data = dict(data)
            data["model_config"] = legacy_data.get("model_config")
        if not data.get("analysis_config") and legacy_data.get("analysis_config"):
            data = dict(data)
            data["analysis_config"] = legacy_data.get("analysis_config")

    llm, analysis = _parse_software_sections(data)
    return SoftwareConfig(
        llm=llm,
        analysis=analysis,
        config_path=str(resolved_path),
    )


def load_config(path: Union[str, Path]) -> ProjectConfig:
    """Load and validate ``project.yaml`` into a :class:`ProjectConfig`."""
    yaml_path, data = _read_yaml_mapping(path)

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
        editing_intent=editing_intent,
        eagle_sync=eagle_sync,
        config_path=str(yaml_path),
    )


__all__ = [
    "ConfigError",
    "ModelConfig",
    "AnalysisConfig",
    "SoftwareConfig",
    "EagleSync",
    "EditingIntent",
    "ProjectConfig",
    "generate_project_slug",
    "repo_root",
    "software_config_path",
    "load_software_config",
    "load_config",
]
