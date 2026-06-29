"""Tests for cut_index.json data models and enum constraints."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tripclipper import SCHEMA_VERSION
from tripclipper.models import (
    Asset,
    AssetType,
    ClipSuggestion,
    PeoplePresence,
    ShotScale,
    SubjectType,
)


def test_schema_version_is_0_3() -> None:
    assert SCHEMA_VERSION == "0.3"


def test_construct_asset_with_valid_enums() -> None:
    asset = Asset(
        asset_id="asset_abc123",
        file="clip.mp4",
        type=AssetType.video,
        subject_type=SubjectType.people_landscape,
        people_presence=PeoplePresence.small_group,
        shot_scale=ShotScale.wide,
        clip_suggestions=[ClipSuggestion(**{"in": "00:00:01", "out": "00:00:05"})],
    )
    assert asset.type is AssetType.video
    assert asset.subject_type is SubjectType.people_landscape
    # default analysis_status
    assert asset.analysis_status.value == "scanned"
    # clip_suggestion alias round-trips into in_
    assert asset.clip_suggestions[0].in_ == "00:00:01"
    # list defaults are independent / empty
    assert asset.tags == []
    assert asset.frame_paths == []
    assert asset.frame_timestamps == []


def test_frame_paths_and_timestamps_default_empty_and_independent() -> None:
    asset = Asset(asset_id="asset_x")
    assert asset.frame_paths == []
    assert asset.frame_timestamps == []
    # Mutating one default does not bleed into another instance.
    asset.frame_paths.append("a.jpg")
    asset.frame_timestamps.append(1.0)
    other = Asset(asset_id="asset_y")
    assert other.frame_paths == []
    assert other.frame_timestamps == []


def test_frame_paths_and_timestamps_written_together() -> None:
    asset = Asset(
        asset_id="asset_z",
        frame_paths=["f0.jpg", "f1.jpg", "f2.jpg"],
        frame_timestamps=[1.0, 2.5, 4.0],
    )
    assert len(asset.frame_paths) == len(asset.frame_timestamps) == 3
    assert asset.frame_timestamps == [1.0, 2.5, 4.0]


def test_invalid_subject_type_rejected() -> None:
    with pytest.raises(ValidationError):
        Asset(asset_id="asset_x", subject_type="not_a_real_subject")


def test_invalid_asset_type_rejected() -> None:
    with pytest.raises(ValidationError):
        Asset(asset_id="asset_x", type="hologram")
