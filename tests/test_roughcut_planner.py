"""Tests for the heuristic rough-cut planner."""

from __future__ import annotations

import json
from pathlib import Path

from tripclipper.cut_index import read_cut_index
from tripclipper.models import EditCandidateStatus
from tripclipper.roughcut import (
    HeuristicRoughCutPlanner,
    RoughCutPlanRequest,
    validate_rough_cut_plan,
)

ROOT = Path(__file__).resolve().parents[1]
ROUGH_FIXTURES = ROOT / "tests" / "fixtures" / "roughcut"


def _fixture_cut_index_payload() -> dict:
    return json.loads((ROUGH_FIXTURES / "minimal_cut_index.json").read_text(encoding="utf-8"))


def _write_project(
    tmp_path: Path,
    payload: dict,
    *,
    slug: str = "roughcut-fixture",
    target_length: float = 12.0,
) -> Path:
    project_dir = tmp_path / slug
    project_dir.mkdir(parents=True)
    (project_dir / "project.yaml").write_text(
        "\n".join(
            [
                "project_name: Rough Cut Fixture",
                "source_folder: tests/fixtures/media",
                f"target_length: {target_length}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (project_dir / "cut_index.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return project_dir


def test_planner_builds_simple_video_plan_with_slug_title(tmp_path: Path) -> None:
    payload = _fixture_cut_index_payload()
    _write_project(tmp_path, payload)

    plan = HeuristicRoughCutPlanner().plan(
        RoughCutPlanRequest(
            slug="roughcut-fixture",
            base_dir=tmp_path,
            target_duration_sec=6.0,
        )
    )

    media_segments = [segment for segment in plan.timeline if segment.track_type != "text"]
    text_segments = [segment for segment in plan.timeline if segment.track_type == "text"]

    assert [segment.asset_id for segment in media_segments] == [
        "asset_fixture_video_opening",
        "asset_fixture_video_scene",
    ]
    assert {segment.track_type for segment in media_segments} == {"video"}
    assert len(text_segments) == 1
    assert text_segments[0].text_overlay is not None
    assert text_segments[0].text_overlay.text == "roughcut-fixture"
    assert text_segments[0].timeline_range.start_sec == 0.0
    assert text_segments[0].timeline_range.end_sec == 5.0

    assert media_segments[0].source_range is not None
    assert media_segments[0].source_range.start_sec == 0.0
    assert media_segments[0].source_range.end_sec == 3.8
    assert media_segments[1].source_range is not None
    assert media_segments[1].source_range.start_sec == 2.75
    assert media_segments[1].source_range.end_sec == 6.75
    assert media_segments[1].timeline_range.start_sec == 3.8
    assert media_segments[1].timeline_range.end_sec == 7.8
    assert all(segment.reason for segment in plan.timeline)

    validate_rough_cut_plan(plan, read_cut_index(tmp_path / "roughcut-fixture" / "cut_index.json"))


def test_planner_defaults_to_project_target_length_and_warns_when_short(
    tmp_path: Path,
) -> None:
    payload = _fixture_cut_index_payload()
    payload["project"]["editing_intent"]["target_length"] = 12.0
    _write_project(tmp_path, payload, target_length=9.0)

    plan = HeuristicRoughCutPlanner().plan(
        RoughCutPlanRequest(slug="roughcut-fixture", base_dir=tmp_path)
    )

    assert plan.intent.target_duration_sec == 9.0
    assert any("insufficient" in warning.reason for warning in plan.warnings)


def test_planner_does_not_auto_fill_with_alternates(tmp_path: Path) -> None:
    payload = _fixture_cut_index_payload()
    alternate = dict(payload["assets"][4])
    alternate["asset_id"] = "asset_fixture_alternate"
    alternate["relative_path"] = "NO20250612-114346-064578F.mp4"
    alternate["path"] = "tests/fixtures/media/NO20250612-114346-064578F.mp4"
    alternate["edit_candidate_status"] = EditCandidateStatus.alternate.value
    alternate["edit_candidate_priority"] = 0
    alternate["rating"] = 5
    payload["assets"].append(alternate)
    _write_project(tmp_path, payload)

    plan = HeuristicRoughCutPlanner().plan(
        RoughCutPlanRequest(
            slug="roughcut-fixture",
            base_dir=tmp_path,
            target_duration_sec=30.0,
        )
    )

    assert "asset_fixture_alternate" not in {
        segment.asset_id for segment in plan.timeline if segment.asset_id
    }
    assert any("insufficient" in warning.reason for warning in plan.warnings)


def test_planner_uses_conservative_opening_when_clip_suggestions_are_missing(
    tmp_path: Path,
) -> None:
    payload = _fixture_cut_index_payload()
    payload["assets"][0]["clip_suggestions"] = []
    _write_project(tmp_path, payload)

    plan = HeuristicRoughCutPlanner().plan(
        RoughCutPlanRequest(
            slug="roughcut-fixture",
            base_dir=tmp_path,
            target_duration_sec=3.0,
        )
    )

    first_video = next(segment for segment in plan.timeline if segment.track_type == "video")

    assert first_video.source_range is not None
    assert first_video.source_range.start_sec == 0.0
    assert first_video.source_range.end_sec == 4.330667
    assert first_video.timeline_range.start_sec == 0.0
    assert first_video.timeline_range.end_sec == 4.330667
    assert "no clip_suggestions" in (first_video.reason or "")
