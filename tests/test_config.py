"""Tests for project.yaml configuration loading and validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from tripclipper.config import (
    ConfigError,
    generate_project_slug,
    load_config,
)


def _write_yaml(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_load_valid_config(tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    cfg = _write_yaml(
        tmp_path / "project.yaml",
        f"""
project_name: "2026 Team Event"
source_folder: "{source}"
output_style: "activity_recap"
target_length: "3min"
audience: "internal_team"
people_focus: "high"
audio_priority: "high"
model_config:
  provider: "openai_compatible"
  base_url: "https://api.example.com/v1"
  api_key_env: "TRIPCLIPPER_MODEL_API_KEY"
  vision_model: "vision-model-name"
  text_model: "text-model-name"
  transcription_model: "audio-model-name"
  language: "zh-CN"
  sample_size: 25
""",
    )

    config = load_config(cfg)

    assert config.project_name == "2026 Team Event"
    assert config.project_slug == "2026-team-event"
    # editing_intent aggregates the five fields.
    assert config.editing_intent.output_style == "activity_recap"
    assert config.editing_intent.target_length == "3min"
    assert config.editing_intent.audience == "internal_team"
    assert config.editing_intent.people_focus == "high"
    assert config.editing_intent.audio_priority == "high"
    # eagle_sync defaults.
    assert config.eagle_sync.enabled is True
    assert config.eagle_sync.mode == "dry-run"
    # sample_size default present.
    assert config.llm.sample_size == 25
    assert config.llm.is_usable() is True
    assert config.config_path == str(Path(cfg).resolve())


def test_missing_source_folder_raises(tmp_path: Path) -> None:
    cfg = _write_yaml(
        tmp_path / "project.yaml",
        """
project_name: "Demo"
model_config:
  provider: "openai_compatible"
""",
    )
    with pytest.raises(ConfigError) as excinfo:
        load_config(cfg)
    assert "source_folder" in str(excinfo.value)


def test_relative_source_folder_resolved_against_yaml_dir(tmp_path: Path) -> None:
    (tmp_path / "media").mkdir()
    cfg = _write_yaml(
        tmp_path / "project.yaml",
        """
project_name: "Demo"
source_folder: "./media"
model_config:
  provider: "openai_compatible"
  base_url: "https://api.example.com/v1"
  api_key_env: "KEY_ENV"
  vision_model: "v"
""",
    )
    config = load_config(cfg)
    assert Path(config.source_folder).is_absolute()
    assert config.source_folder == str((tmp_path / "media").resolve())


def test_incomplete_model_config_loads_but_unusable(tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    cfg = _write_yaml(
        tmp_path / "project.yaml",
        f"""
project_name: "Demo"
source_folder: "{source}"
model_config:
  provider: "openai_compatible"
""",
    )
    config = load_config(cfg)
    # Loads successfully...
    assert config.project_name == "Demo"
    # ...but is flagged as not usable.
    assert config.llm.is_usable() is False
    # default sample_size still applied
    assert config.llm.sample_size == 25


def test_generate_project_slug_deterministic() -> None:
    assert generate_project_slug("2026 Team Event") == "2026-team-event"
    # multiple calls are consistent
    assert generate_project_slug("2026 Team Event") == generate_project_slug(
        "2026 Team Event"
    )
    # collapses runs and trims
    assert generate_project_slug("  Hello   World!! ") == "hello-world"
