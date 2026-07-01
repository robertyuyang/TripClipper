"""Tests for the mapping loader (Layer 2)."""

from __future__ import annotations

import pytest

from tripclipper.config import ConfigError
from tripclipper.eagle_sync import load_mapping_config


def test_load_default_mapping() -> None:
    config = load_mapping_config()
    assert config.tag_prefix == "tc"
    assert config.project_tag_field == "project"
    assert config.auto_map_unknown is True
    assert config.mappings["edit_candidate_status"].target == "tag"
    assert "asset_id" in config.skip_fields
    assert config.mappings["clip_suggestions"].renderer == "clip_suggestions_list"
    assert config.mappings["rating"].target == "eagle_rating"
    assert config.connection_failure_threshold == 5


def test_project_overrides_shallow_merge() -> None:
    config = load_mapping_config({"tag_prefix": "custom"})
    assert config.tag_prefix == "custom"
    # Other top-level values remain default.
    assert config.project_tag_field == "project"
    assert config.auto_map_unknown is True
    assert "asset_id" in config.skip_fields


def test_project_overrides_extends_skip_fields() -> None:
    config = load_mapping_config({"skip_fields": ["extra_field"]})
    assert "extra_field" in config.skip_fields
    assert "asset_id" in config.skip_fields


def test_invalid_target_rejected() -> None:
    with pytest.raises(ConfigError):
        load_mapping_config({"mappings": {"foo": {"target": "bogus"}}})
