"""Tests for cut_index read/write, schema checks and stable asset_id."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tripclipper.config import load_config
from tripclipper.cut_index import (
    SchemaVersionError,
    generate_asset_id,
    init_cut_index,
    read_cut_index,
    write_cut_index,
)

TOP_LEVEL_BLOCKS = (
    "project",
    "capabilities",
    "analysis",
    "assets",
    "similar_groups",
    "default_candidates",
    "failures",
    "warnings",
)


def _make_config(tmp_path: Path):
    source = tmp_path / "media"
    source.mkdir()
    cfg = tmp_path / "project.yaml"
    cfg.write_text(
        f"""
project_name: "2026 Team Event"
source_folder: "{source}"
output_style: "activity_recap"
model_config:
  provider: "openai_compatible"
  base_url: "https://api.example.com/v1"
  api_key_env: "TRIPCLIPPER_MODEL_API_KEY"
  vision_model: "vision-model-name"
  text_model: "text-model-name"
""",
        encoding="utf-8",
    )
    return load_config(cfg)


def test_init_write_read_roundtrip(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    cut = init_cut_index(config)
    out = tmp_path / "cut_index.json"
    write_cut_index(out, cut)

    # Raw JSON has the eight top-level blocks plus schema_version.
    raw = json.loads(out.read_text(encoding="utf-8"))
    assert raw["schema_version"] == "0.2"
    for block in TOP_LEVEL_BLOCKS:
        assert block in raw
    # Empty list blocks are arrays.
    for block in ("assets", "similar_groups", "default_candidates", "failures", "warnings"):
        assert raw[block] == []

    # Read back and check round-trip on key fields.
    loaded = read_cut_index(out)
    assert loaded.schema_version == "0.2"
    assert loaded.project.project_name == config.project_name
    assert loaded.project.project_slug == config.project_slug
    assert loaded.project.source_folder == config.source_folder
    assert loaded.assets == []


def test_incompatible_schema_version_raises(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    cut = init_cut_index(config)
    out = tmp_path / "cut_index.json"
    write_cut_index(out, cut)

    data = json.loads(out.read_text(encoding="utf-8"))
    data["schema_version"] = "1.0"
    out.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(SchemaVersionError):
        read_cut_index(out)


def test_generate_asset_id_stable_and_distinct() -> None:
    a = generate_asset_id("sub/clip.mp4")
    b = generate_asset_id("sub/clip.mp4")
    c = generate_asset_id("sub/other.mp4")
    assert a == b
    assert a != c
    assert a.startswith("asset_")
    assert len(a) == len("asset_") + 12


def test_model_config_summary_has_no_plaintext_secret(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    cut = init_cut_index(config)
    summary = cut.project.model_config_summary
    # Summary contains only the env var NAME, not a plaintext key.
    assert summary["api_key_env"] == "TRIPCLIPPER_MODEL_API_KEY"
    # No plaintext secret field present.
    assert "api_key" not in summary
    assert "secret" not in summary
    # Serialised form does not contain a plaintext key field name.
    serialized = json.dumps(summary, ensure_ascii=False)
    assert '"api_key"' not in serialized
