"""Tests for RoughCutPlan models and JSON IO."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from tripclipper.models import EditCandidateStatus
from tripclipper.roughcut import (
    ROUGH_CUT_PLAN_SCHEMA_VERSION,
    RoughCutPlan,
    read_rough_cut_plan,
    write_rough_cut_plan,
)

ROOT = Path(__file__).resolve().parents[1]
PLAN_FIXTURE = ROOT / "tests" / "fixtures" / "roughcut" / "minimal_rough_cut_plan.json"


def _fixture_payload() -> dict:
    return json.loads(PLAN_FIXTURE.read_text(encoding="utf-8"))


def test_read_rough_cut_plan_loads_fixture_with_typed_status() -> None:
    plan = read_rough_cut_plan(PLAN_FIXTURE)

    assert ROUGH_CUT_PLAN_SCHEMA_VERSION == "0.1"
    assert plan.schema_version == ROUGH_CUT_PLAN_SCHEMA_VERSION
    assert plan.project.project_slug == "roughcut-fixture"
    assert plan.timeline[0].candidate_status_snapshot is EditCandidateStatus.default_selected


def test_write_rough_cut_plan_round_trips_without_data_loss(tmp_path: Path) -> None:
    original_payload = _fixture_payload()
    plan = RoughCutPlan.model_validate(original_payload)
    out = tmp_path / "rough_cut_plan.json"

    write_rough_cut_plan(out, plan)

    assert json.loads(out.read_text(encoding="utf-8")) == original_payload
    assert read_rough_cut_plan(out).model_dump(mode="json", exclude_none=True) == original_payload


def test_invalid_time_range_is_rejected() -> None:
    payload = _fixture_payload()
    payload["timeline"][0]["timeline_range"] = {"start_sec": 3.0, "end_sec": 3.0}

    with pytest.raises(ValidationError):
        RoughCutPlan.model_validate(payload)


def test_top_level_text_bgm_and_transition_fields_are_rejected() -> None:
    payload = _fixture_payload()
    payload["text_overlays"] = []
    payload["bgm"] = {}
    payload["transitions"] = []

    with pytest.raises(ValidationError):
        RoughCutPlan.model_validate(payload)


def test_text_segment_does_not_require_asset_identity() -> None:
    plan = read_rough_cut_plan(PLAN_FIXTURE)
    text_segment = next(segment for segment in plan.timeline if segment.track_type == "text")

    assert text_segment.asset_id is None
    assert text_segment.asset_relative_path is None
    assert text_segment.text_overlay is not None
