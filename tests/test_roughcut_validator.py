"""Tests for RoughCutPlan semantic validation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tripclipper.models import CutIndex
from tripclipper.roughcut import (
    RoughCutPlan,
    RoughCutValidationError,
    validate_rough_cut_plan,
)

ROOT = Path(__file__).resolve().parents[1]
ROUGH_FIXTURES = ROOT / "tests" / "fixtures" / "roughcut"


def _load_plan_payload() -> dict:
    return json.loads((ROUGH_FIXTURES / "minimal_rough_cut_plan.json").read_text(encoding="utf-8"))


def _load_cut_index() -> CutIndex:
    payload = json.loads((ROUGH_FIXTURES / "minimal_cut_index.json").read_text(encoding="utf-8"))
    return CutIndex.model_validate(payload)


def _validate_payload(payload: dict) -> None:
    validate_rough_cut_plan(RoughCutPlan.model_validate(payload), _load_cut_index())


def test_valid_fixture_plan_passes_validation() -> None:
    _validate_payload(_load_plan_payload())


def test_missing_asset_id_fails_validation() -> None:
    payload = _load_plan_payload()
    payload["timeline"][0]["asset_id"] = "asset_missing"

    with pytest.raises(RoughCutValidationError, match="asset_missing"):
        _validate_payload(payload)


def test_asset_relative_path_mismatch_fails_validation() -> None:
    payload = _load_plan_payload()
    payload["timeline"][0]["asset_relative_path"] = "wrong.mp4"

    with pytest.raises(RoughCutValidationError, match="relative path"):
        _validate_payload(payload)


def test_same_track_overlap_fails_but_different_track_overlap_is_allowed() -> None:
    payload = _load_plan_payload()
    payload["timeline"][1]["timeline_range"] = {"start_sec": 3.0, "end_sec": 6.0}

    with pytest.raises(RoughCutValidationError, match="overlap"):
        _validate_payload(payload)

    payload = _load_plan_payload()
    payload["timeline"][2]["track_type"] = "video"
    payload["timeline"][2]["track_index"] = 1
    payload["timeline"][2]["source_range"] = {"start_sec": 0.0, "end_sec": 4.0}

    _validate_payload(payload)


def test_excluded_status_requires_selection_override_reason() -> None:
    payload = _load_plan_payload()
    segment = payload["timeline"][0]
    segment["asset_id"] = "asset_fixture_excluded"
    segment["asset_relative_path"] = "NO20250612-114346-064578F.mp4"
    segment["asset_path"] = "tests/fixtures/media/NO20250612-114346-064578F.mp4"
    segment["candidate_status_snapshot"] = "excluded"
    segment["selection_override_reason"] = None

    with pytest.raises(RoughCutValidationError, match="selection_override_reason"):
        _validate_payload(payload)

    segment["selection_override_reason"] = "Manual fixture override for regression coverage"
    _validate_payload(payload)


def test_video_and_audio_require_source_range() -> None:
    for index in (0, 3):
        payload = _load_plan_payload()
        payload["timeline"][index].pop("source_range")

        with pytest.raises(RoughCutValidationError, match="source_range"):
            _validate_payload(payload)


def test_image_and_text_reject_source_range() -> None:
    for index in (2, 4):
        payload = _load_plan_payload()
        payload["timeline"][index]["source_range"] = {"start_sec": 0.0, "end_sec": 1.0}

        with pytest.raises(RoughCutValidationError, match="source_range"):
            _validate_payload(payload)


def test_text_overlay_rules_follow_track_type() -> None:
    payload = _load_plan_payload()
    payload["timeline"][4].pop("text_overlay")

    with pytest.raises(RoughCutValidationError, match="text_overlay"):
        _validate_payload(payload)

    payload = _load_plan_payload()
    payload["timeline"][0]["text_overlay"] = {"text": "not allowed"}

    with pytest.raises(RoughCutValidationError, match="text_overlay"):
        _validate_payload(payload)
