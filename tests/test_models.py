"""Tests for cut_index.json data models and enum constraints."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tripclipper.models import (
    Asset,
    AssetType,
    PeoplePresence,
    Segment,
    ShotScale,
    SubjectType,
)


def test_construct_asset_with_valid_enums() -> None:
    asset = Asset(
        asset_id="asset_abc123",
        file="clip.mp4",
        type=AssetType.video,
        subject_type=SubjectType.people_landscape,
        people_presence=PeoplePresence.small_group,
        shot_scale=ShotScale.wide,
        segments=[Segment(**{"in": "00:00:01", "out": "00:00:05"})],
    )
    assert asset.type is AssetType.video
    assert asset.subject_type is SubjectType.people_landscape
    # default analysis_status
    assert asset.analysis_status.value == "scanned"
    # segment alias round-trips into in_
    assert asset.segments[0].in_ == "00:00:01"
    # list defaults are independent / empty
    assert asset.tags == []
    assert asset.frame_paths == []


def test_invalid_subject_type_rejected() -> None:
    with pytest.raises(ValidationError):
        Asset(asset_id="asset_x", subject_type="not_a_real_subject")


def test_invalid_asset_type_rejected() -> None:
    with pytest.raises(ValidationError):
        Asset(asset_id="asset_x", type="hologram")
