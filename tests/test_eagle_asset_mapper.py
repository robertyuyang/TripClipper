"""Tests for the asset mapper (Layer 3)."""

from __future__ import annotations

import dataclasses

from tripclipper.eagle_sync import AssetMapper, load_mapping_config
from tripclipper.models import (
    AnalysisStatus,
    Asset,
    ClipSuggestion,
    EditCandidateStatus,
    ShotFunction,
)

SLUG = "2026-japan-trip"
TS = "2026-06-30T14:23:11+09:00"


def _mapper(config=None) -> AssetMapper:
    return AssetMapper(config or load_mapping_config(), SLUG, TS)


def test_plan_default_selected_full() -> None:
    asset = Asset(
        rating=5,
        edit_candidate_status=EditCandidateStatus.default_selected,
        shot_function=ShotFunction.highlight,
        similar_group_id="grp_001",
        edit_candidate_reason="组主选",
        clip_suggestions=[
            ClipSuggestion(
                in_="00:00:03.5", out="00:00:08.2", reason="好镜头", rating=4
            )
        ],
        filename="a.mp4",
        path="/x/a.mp4",
        analysis_status=AnalysisStatus.analyzed,
    )
    plan = _mapper().plan(asset)

    assert "tc:edit_candidate_status:default_selected" in plan.tags
    assert "tc:shot_function:highlight" in plan.tags
    assert plan.rating == 5
    assert "TripClipper" in plan.annotation
    assert plan.annotation.startswith("_TripClipper")
    # Section ordering: 候选池理由 (order 1) before 建议剪辑片段 (order 4).
    idx_reason = plan.annotation.index("## 候选池理由")
    idx_clips = plan.annotation.index("## 建议剪辑片段")
    assert idx_reason < idx_clips
    # Backtick-wrapped timecode present.
    assert "`00:00:03.5 → 00:00:08.2`" in plan.annotation


def test_plan_excluded_asset() -> None:
    asset = Asset(
        edit_candidate_status=EditCandidateStatus.excluded,
        clip_suggestions=[],
        filename="b.mp4",
        path="/x/b.mp4",
        analysis_status=AnalysisStatus.analyzed,
    )
    plan = _mapper().plan(asset)
    assert "tc:edit_candidate_status:excluded" in plan.tags
    assert "## 建议剪辑片段" not in plan.annotation


def test_plan_auto_map_unknown_via_tags_list() -> None:
    asset = Asset(tags=["custom_tag"], analysis_status=AnalysisStatus.analyzed)
    plan = _mapper().plan(asset)
    assert "tc:tags:custom_tag" in plan.tags


def test_plan_skip_fields_excluded() -> None:
    asset = Asset(
        asset_id="asset_x",
        path="/secret/p.mp4",
        analysis_status=AnalysisStatus.analyzed,
    )
    plan = _mapper().plan(asset)
    for tag in plan.tags:
        assert "asset_x" not in tag
        assert "/secret/" not in tag


def test_plan_clip_order_preserved() -> None:
    clips = [
        ClipSuggestion(in_="00:00:01", out="00:00:02", reason="one"),
        ClipSuggestion(in_="00:00:03", out="00:00:04", reason="two"),
        ClipSuggestion(in_="00:00:05", out="00:00:06", reason="three"),
    ]
    asset = Asset(
        clip_suggestions=clips, analysis_status=AnalysisStatus.analyzed
    )
    plan = _mapper().plan(asset)
    section = plan.annotation.split("## 建议剪辑片段", 1)[1]
    lines = [ln for ln in section.splitlines() if ln.startswith("- `")]
    assert len(lines) == 3
    assert "one" in lines[0]
    assert "two" in lines[1]
    assert "three" in lines[2]


def test_plan_project_tag_present() -> None:
    asset = Asset(analysis_status=AnalysisStatus.analyzed)
    plan = _mapper().plan(asset)
    assert f"tc:project:{SLUG}" in plan.tags


def test_plan_tag_group_updates_grouped_by_field() -> None:
    asset = Asset(
        edit_candidate_status=EditCandidateStatus.default_selected,
        analysis_status=AnalysisStatus.analyzed,
    )
    plan = _mapper().plan(asset)
    assert plan.tag_group_updates["tc:edit_candidate_status"] == [
        "tc:edit_candidate_status:default_selected"
    ]


def test_plan_strict_mapping_skips_unknown() -> None:
    config = dataclasses.replace(load_mapping_config(), auto_map_unknown=False)
    asset = Asset(tags=["x"], analysis_status=AnalysisStatus.analyzed)
    plan = _mapper(config).plan(asset)
    assert "tc:tags:x" not in plan.tags
    assert "tags" in plan.unknown_warnings
