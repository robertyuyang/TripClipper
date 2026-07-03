"""Tests for project.yaml configuration loading and validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from tripclipper.config import (
    AnalysisConfig,
    ConfigError,
    load_software_config,
    generate_project_slug,
    load_config,
    repo_root,
    software_config_path,
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
    assert config.config_path == str(Path(cfg).resolve())


def test_missing_source_folder_raises(tmp_path: Path) -> None:
    cfg = _write_yaml(
        tmp_path / "project.yaml",
        """
project_name: "Demo"
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
""",
    )
    config = load_config(cfg)
    assert Path(config.source_folder).is_absolute()
    assert config.source_folder == str((tmp_path / "media").resolve())


def test_load_software_config_valid(tmp_path: Path) -> None:
    cfg = _write_yaml(
        tmp_path / "software.yaml",
        """
model_config:
  provider: "openai_compatible"
  base_url: "https://api.example.com/v1"
  api_key_env: "TRIPCLIPPER_MODEL_API_KEY"
  vision_model: "vision-model-name"
  text_model: "text-model-name"
  transcription_model: "audio-model-name"
analysis_config:
  sample_size: 25
  language: "zh-CN"
""",
    )

    config = load_software_config(cfg)
    assert config.llm.is_usable() is True
    assert config.analysis.sample_size == 25
    assert config.analysis.language == "zh-CN"
    assert config.config_path == str(Path(cfg).resolve())


def test_legacy_model_config_sample_size_falls_back_to_analysis(tmp_path: Path) -> None:
    cfg = _write_yaml(
        tmp_path / "software.yaml",
        """
model_config:
  sample_size: 7
""",
    )

    config = load_software_config(cfg)
    assert config.analysis.sample_size == 7


def test_legacy_model_config_language_falls_back_to_analysis(tmp_path: Path) -> None:
    cfg = _write_yaml(
        tmp_path / "software.yaml",
        """
model_config:
  language: "en-US"
""",
    )

    config = load_software_config(cfg)
    assert config.analysis.language == "en-US"


def test_missing_software_config_returns_defaults(tmp_path: Path) -> None:
    missing = tmp_path / "missing.yaml"
    config = load_software_config(missing)
    assert config.llm.is_usable() is False
    assert config.analysis == AnalysisConfig()
    assert config.config_path == str(missing.resolve())


def test_software_config_path_uses_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = tmp_path / "override.yaml"
    monkeypatch.setenv("TRIPCLIPPER_SOFTWARE_CONFIG", str(cfg))
    assert software_config_path() == cfg.resolve()


def test_software_config_path_defaults_to_repo_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TRIPCLIPPER_SOFTWARE_CONFIG", raising=False)
    assert software_config_path() == (repo_root() / "config" / "config.yaml").resolve()


def test_repo_ships_software_config_template() -> None:
    template = repo_root() / "config" / "config.template.yaml"
    assert template.is_file()
    text = template.read_text(encoding="utf-8")
    assert "model_config:" in text
    assert "analysis_config:" in text
    assert "api_key_env:" in text
    assert "sample_size:" in text


def test_generate_project_slug_deterministic() -> None:
    assert generate_project_slug("2026 Team Event") == "2026-team-event"
    # multiple calls are consistent
    assert generate_project_slug("2026 Team Event") == generate_project_slug(
        "2026 Team Event"
    )
    # collapses runs and trims
    assert generate_project_slug("  Hello   World!! ") == "hello-world"


def test_config_eagle_sync_defaults(tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    cfg = _write_yaml(
        tmp_path / "project.yaml",
        f"""
project_name: "Demo"
source_folder: "{source}"
""",
    )
    config = load_config(cfg)
    assert config.eagle_sync.api_base_url == "http://localhost:41595"
    assert config.eagle_sync.connection_failure_threshold == 5
    assert config.eagle_sync.api_token is None
    assert config.eagle_sync.mapping_overrides is None
    assert config.eagle_sync.library_path is None
    # existing default still holds.
    assert config.eagle_sync.mode == "dry-run"


def test_config_eagle_sync_from_yaml(tmp_path: Path) -> None:
    source = tmp_path / "media"
    source.mkdir()
    cfg = _write_yaml(
        tmp_path / "project.yaml",
        f"""
project_name: "Demo"
source_folder: "{source}"
eagle_sync:
  api_base_url: "http://host:9/api/v2/"
  connection_failure_threshold: 9
  api_token: "tok"
  library_path: "/Users/me/Trip.library"
""",
    )
    config = load_config(cfg)
    assert config.eagle_sync.api_base_url == "http://host:9/api/v2/"
    assert config.eagle_sync.connection_failure_threshold == 9
    assert config.eagle_sync.api_token == "tok"
    assert config.eagle_sync.library_path == "/Users/me/Trip.library"
