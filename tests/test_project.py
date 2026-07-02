"""Tests for M1 project creation/initialisation orchestration (FR-1).

All inputs are synthetic: ``project.yaml`` strings are written into ``tmp_path``
and ``source_folder`` is an empty directory created with ``mkdir()``. No real
media files, no real model calls and no real secrets are used — a secret only
ever appears as an ``api_key_env`` *name*, and a fake literal (``"secret123"``)
is used to assert it never leaks into on-disk files or summaries.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from tripclipper.cli import main
from tripclipper.config import load_config
from tripclipper.paths import (
    cut_index_path,
    frames_dir,
    project_config_path,
    project_dir,
    thumbnails_dir,
    transcripts_dir,
)
from tripclipper.project import (
    ProjectError,
    ProjectSummary,
    init_project,
    scaffold_config_file,
)

# Deterministic slug for the canonical project name used across these tests.
PROJECT_NAME = "2026 Team Event"
SLUG = "2026-team-event"


# ---------------------------------------------------------------------------
# Synthetic-data helpers (M0 ``_write_yaml`` + tmp_path style)
# ---------------------------------------------------------------------------


def _write_yaml(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def _full_model_block(extra_lines: str = "") -> str:
    """A complete (usable) software ``model_config`` block; no plaintext key."""
    block = (
        "model_config:\n"
        '  provider: "openai_compatible"\n'
        '  base_url: "https://api.example.com/v1"\n'
        '  api_key_env: "TRIPCLIPPER_MODEL_API_KEY"\n'
        '  vision_model: "vision-model-name"\n'
        '  text_model: "text-model-name"\n'
        '  transcription_model: "audio-model-name"\n'
    )
    return block + extra_lines


def _software_yaml(model_block: str | None = None) -> str:
    if model_block is None:
        model_block = _full_model_block()
    return "analysis_config:\n  sample_size: 25\n  language: \"zh-CN\"\n" + model_block


def _project_yaml(
    source_folder: Path | str,
    *,
    project_name: str = PROJECT_NAME,
    target_length: str = "3min",
) -> str:
    """Render a syntactically valid ``project.yaml`` string from parameters."""
    return (
        f'project_name: "{project_name}"\n'
        f'source_folder: "{source_folder}"\n'
        'output_style: "activity_recap"\n'
        f'target_length: "{target_length}"\n'
        'audience: "internal_team"\n'
        'people_focus: "high"\n'
        'audio_priority: "high"\n'
    )


def _make_source(tmp_path: Path) -> Path:
    source = tmp_path / "media"
    source.mkdir()
    return source


def _base(tmp_path: Path) -> Path:
    """Project root base dir, kept inside tmp_path to avoid polluting cwd."""
    return tmp_path / "projects"


def _set_software_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    content: str | None = None,
) -> Path:
    if content is None:
        content = _software_yaml()
    path = tmp_path / "software.yaml"
    path.write_text(content, encoding="utf-8")
    monkeypatch.setenv("TRIPCLIPPER_SOFTWARE_CONFIG", str(path))
    return path


# ---------------------------------------------------------------------------
# Project creation / structure
# ---------------------------------------------------------------------------


def test_init_project_creates_structure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_software_config(tmp_path, monkeypatch)
    source = _make_source(tmp_path)
    base = _base(tmp_path)
    cfg = _write_yaml(tmp_path / "project.yaml", _project_yaml(source))

    summary = init_project(cfg, base_dir=base)

    assert isinstance(summary, ProjectSummary)
    assert summary.project_name == PROJECT_NAME
    assert summary.project_slug == SLUG
    assert summary.source_folder_exists is True
    assert summary.model_usable is True

    # Project directory and the cache sub-directories exist.
    assert project_dir(SLUG, base_dir=base).is_dir()
    assert thumbnails_dir(SLUG, base_dir=base).is_dir()
    assert frames_dir(SLUG, base_dir=base).is_dir()
    assert transcripts_dir(SLUG, base_dir=base).is_dir()

    # project.yaml copy + cut_index.json are written in the project directory.
    assert project_config_path(SLUG, base_dir=base).is_file()
    assert cut_index_path(SLUG, base_dir=base).is_file()


def test_init_project_cut_index_project_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_software_config(tmp_path, monkeypatch)
    source = _make_source(tmp_path)
    base = _base(tmp_path)
    cfg = _write_yaml(tmp_path / "project.yaml", _project_yaml(source))

    init_project(cfg, base_dir=base)

    raw = json.loads(
        cut_index_path(SLUG, base_dir=base).read_text(encoding="utf-8")
    )
    project = raw["project"]
    for key in (
        "project_name",
        "project_slug",
        "source_folder",
        "config_path",
        "editing_intent",
        "model_config_summary",
        "eagle_sync",
        "created_at",
        "updated_at",
    ):
        assert key in project

    # config_path points at the in-project canonical copy.
    assert project["config_path"] == str(project_config_path(SLUG, base_dir=base))

    # Collection blocks start empty.
    for block in ("assets", "similar_groups", "default_candidates", "failures"):
        assert raw[block] == []


# ---------------------------------------------------------------------------
# Summary visibility + no secret leakage
# ---------------------------------------------------------------------------


def test_summary_has_model_usable_and_no_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _make_source(tmp_path)
    base = _base(tmp_path)
    # Deliberately (mis)place a plaintext key in software model_config — it must
    # never surface in the summary or on disk.
    _set_software_config(
        tmp_path,
        monkeypatch,
        content=_software_yaml(_full_model_block('  api_key: "secret123"\n')),
    )
    cfg = _write_yaml(tmp_path / "project.yaml", _project_yaml(source))

    summary = init_project(cfg, base_dir=base)

    assert isinstance(summary.model_usable, bool)
    assert isinstance(summary.source_folder_exists, bool)
    # Summary keeps only the env-var NAME, never a plaintext key field.
    assert summary.model_config_summary["api_key_env"] == "TRIPCLIPPER_MODEL_API_KEY"
    assert "api_key" not in summary.model_config_summary

    # The on-disk cut_index.json never contains the fake secret value.
    index_text = cut_index_path(SLUG, base_dir=base).read_text(encoding="utf-8")
    assert "secret123" not in index_text

    # Neither does the serialised summary.
    assert "secret123" not in summary.model_dump_json()


# ---------------------------------------------------------------------------
# source_folder validation
# ---------------------------------------------------------------------------


def test_source_folder_missing_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_software_config(tmp_path, monkeypatch)
    base = _base(tmp_path)
    missing = tmp_path / "does-not-exist"
    cfg = _write_yaml(tmp_path / "project.yaml", _project_yaml(missing))

    with pytest.raises(ProjectError) as excinfo:
        init_project(cfg, base_dir=base)
    message = str(excinfo.value)
    assert "不存在" in message or str(missing) in message


def test_source_folder_is_file_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_software_config(tmp_path, monkeypatch)
    base = _base(tmp_path)
    as_file = tmp_path / "media.txt"
    as_file.write_text("not a directory", encoding="utf-8")
    cfg = _write_yaml(tmp_path / "project.yaml", _project_yaml(as_file))

    with pytest.raises(ProjectError) as excinfo:
        init_project(cfg, base_dir=base)
    assert "不是目录" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Incomplete model config still creates the project
# ---------------------------------------------------------------------------


def test_incomplete_model_config_still_creates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_software_config(
        tmp_path,
        monkeypatch,
        content=_software_yaml('model_config:\n  provider: "openai_compatible"\n'),
    )
    source = _make_source(tmp_path)
    base = _base(tmp_path)
    cfg = _write_yaml(tmp_path / "project.yaml", _project_yaml(source))

    summary = init_project(cfg, base_dir=base)

    assert summary.model_usable is False

    raw = json.loads(
        cut_index_path(SLUG, base_dir=base).read_text(encoding="utf-8")
    )
    warnings = raw["warnings"]
    assert len(warnings) >= 1
    config_warnings = [w for w in warnings if w.get("stage") == "config"]
    assert config_warnings
    assert all(w.get("blocking") is False for w in config_warnings)


# ---------------------------------------------------------------------------
# Idempotent / re-entrant initialisation
# ---------------------------------------------------------------------------


def test_idempotent_init_preserves_assets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_software_config(tmp_path, monkeypatch)
    source = _make_source(tmp_path)
    base = _base(tmp_path)
    cfg = _write_yaml(tmp_path / "project.yaml", _project_yaml(source))

    # First init.
    init_project(cfg, base_dir=base)

    # Inject a fake asset + analysis result directly into cut_index.json.
    index_path = cut_index_path(SLUG, base_dir=base)
    raw = json.loads(index_path.read_text(encoding="utf-8"))
    raw["assets"].append(
        {"asset_id": "asset_test", "file": "x.mp4", "analysis_status": "scanned"}
    )
    raw["analysis"]["status"] = "done"
    index_path.write_text(
        json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Change the config (target_length 3min -> 5min) and re-init same base_dir.
    _write_yaml(
        tmp_path / "project.yaml", _project_yaml(source, target_length="5min")
    )
    init_project(cfg, base_dir=base)

    after = json.loads(index_path.read_text(encoding="utf-8"))
    asset_ids = [a.get("asset_id") for a in after["assets"]]
    assert "asset_test" in asset_ids  # existing result preserved
    assert after["analysis"]["status"] == "done"  # analysis preserved
    assert after["project"]["editing_intent"]["target_length"] == "5min"  # refreshed
    assert after["project"]["updated_at"]


def test_idempotent_init_no_error_twice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_software_config(tmp_path, monkeypatch)
    source = _make_source(tmp_path)
    base = _base(tmp_path)
    cfg = _write_yaml(tmp_path / "project.yaml", _project_yaml(source))

    first = init_project(cfg, base_dir=base)
    second = init_project(cfg, base_dir=base)

    assert isinstance(first, ProjectSummary)
    assert isinstance(second, ProjectSummary)
    assert second.project_slug == SLUG


# ---------------------------------------------------------------------------
# scaffold_config_file
# ---------------------------------------------------------------------------


def test_scaffold_creates_loadable_template(tmp_path: Path) -> None:
    source = _make_source(tmp_path)
    out = tmp_path / "gen.yaml"

    written = scaffold_config_file(
        out, project_name="My Project", source_folder=str(source)
    )

    assert written.is_file()
    text = out.read_text(encoding="utf-8")
    assert "secret" not in text
    assert "api_key_env" not in text
    assert "analysis_config:" not in text
    assert "model_config:" not in text

    config = load_config(out)
    assert config.project_name == "My Project"
    assert config.source_folder == str(source.resolve())


def test_scaffold_existing_without_force_raises(tmp_path: Path) -> None:
    source = _make_source(tmp_path)
    out = tmp_path / "gen.yaml"
    out.write_text("placeholder", encoding="utf-8")

    with pytest.raises(ProjectError):
        scaffold_config_file(
            out, project_name="X", source_folder=str(source), force=False
        )


# ---------------------------------------------------------------------------
# CLI (click.testing.CliRunner)
# ---------------------------------------------------------------------------


def test_cli_init_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _set_software_config(tmp_path, monkeypatch)
    source = _make_source(tmp_path)
    base = _base(tmp_path)
    cfg = _write_yaml(tmp_path / "project.yaml", _project_yaml(source))

    result = CliRunner().invoke(
        main, ["init", "--config", str(cfg), "--base-dir", str(base)]
    )

    assert result.exit_code == 0, result.output
    assert PROJECT_NAME in result.output or SLUG in result.output


def test_cli_init_missing_source_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_software_config(tmp_path, monkeypatch)
    base = _base(tmp_path)
    missing = tmp_path / "does-not-exist"
    cfg = _write_yaml(tmp_path / "project.yaml", _project_yaml(missing))

    result = CliRunner().invoke(
        main, ["init", "--config", str(cfg), "--base-dir", str(base)]
    )

    assert result.exit_code == 1
    assert "失败" in result.output or "不存在" in result.output
    # No uncaught application exception leaked: CliRunner records sys.exit as
    # SystemExit, never a raw ProjectError.
    assert not isinstance(result.exception, ProjectError)


def test_cli_scaffold(tmp_path: Path) -> None:
    source = _make_source(tmp_path)
    out = tmp_path / "scaffold.yaml"

    result = CliRunner().invoke(
        main,
        [
            "init",
            "--scaffold",
            str(out),
            "--project-name",
            "X",
            "--source-folder",
            str(source),
        ],
    )

    assert result.exit_code == 0, result.output
    assert out.is_file()
