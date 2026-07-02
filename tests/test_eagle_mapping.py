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


def test_load_default_smart_folders() -> None:
    cfg = load_mapping_config()
    keys = [p.key for p in cfg.smart_folder_presets]
    assert keys == [
        "highlights",
        "default_selected",
        "excluded",
        "needs_review",
        "analysis_failed",
    ]


def test_smart_folder_override_replaces_by_key() -> None:
    overrides = {
        "smart_folders": [
            {
                "key": "highlights",
                "name": "TC · {project_slug} · Hero",
                "icon_color": "purple",
                "match": "AND",
                "rules": [
                    {
                        "property": "tag",
                        "method": "equal",
                        "value": "tc:project:{project_slug}",
                    }
                ],
            }
        ]
    }
    cfg = load_mapping_config(project_overrides=overrides)
    hi = next(p for p in cfg.smart_folder_presets if p.key == "highlights")
    assert hi.icon_color == "purple"
    assert hi.name == "TC · {project_slug} · Hero"
    others = [p.key for p in cfg.smart_folder_presets if p.key != "highlights"]
    assert others == [
        "default_selected",
        "excluded",
        "needs_review",
        "analysis_failed",
    ]


def test_smart_folder_override_appends_new_key() -> None:
    overrides = {
        "smart_folders": [
            {
                "key": "extreme_wide",
                "name": "TC · {project_slug} · 大远景",
                "icon_color": None,
                "match": "AND",
                "rules": [
                    {
                        "property": "tag",
                        "method": "equal",
                        "value": "tc:shot_scale:extreme_wide",
                    }
                ],
            }
        ]
    }
    cfg = load_mapping_config(project_overrides=overrides)
    keys = [p.key for p in cfg.smart_folder_presets]
    assert keys == [
        "highlights",
        "default_selected",
        "excluded",
        "needs_review",
        "analysis_failed",
        "extreme_wide",
    ]


def test_smart_folder_invalid_icon_color_rejected() -> None:
    overrides = {
        "smart_folders": [
            {
                "key": "highlights",
                "name": "x",
                "icon_color": "magenta",
                "match": "AND",
                "rules": [{"property": "tag", "method": "equal", "value": "x"}],
            }
        ]
    }
    with pytest.raises(ConfigError):
        load_mapping_config(project_overrides=overrides)


def test_smart_folder_invalid_match_rejected() -> None:
    overrides = {
        "smart_folders": [
            {
                "key": "highlights",
                "name": "x",
                "icon_color": None,
                "match": "XOR",
                "rules": [{"property": "tag", "method": "equal", "value": "x"}],
            }
        ]
    }
    with pytest.raises(ConfigError):
        load_mapping_config(project_overrides=overrides)


def test_smart_folder_empty_rules_rejected() -> None:
    overrides = {
        "smart_folders": [
            {
                "key": "highlights",
                "name": "x",
                "icon_color": None,
                "match": "AND",
                "rules": [],
            }
        ]
    }
    with pytest.raises(ConfigError):
        load_mapping_config(project_overrides=overrides)
