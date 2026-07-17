"""Tests for the asset mapper (Layer 3)."""

from __future__ import annotations

import dataclasses
from pathlib import Path

from tripclipper.eagle_sync import AssetMapper, load_mapping_config
from tripclipper.models import (
    AnalysisStatus,
    Asset,
    ClipSuggestion,
    EditCandidateStatus,
    ShotFunction,
    SpeechQuality,
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


def test_plan_maps_clear_speech_to_tag_and_annotation(tmp_path: Path) -> None:
    transcript = tmp_path / "cache" / "transcripts" / "asset_x.json"
    transcript.parent.mkdir(parents=True)
    transcript.write_text(
        '{"speech_quality":"clear","speech_segments":['
        '{"start_sec":3.5,"end_sec":8.2,"text":"你好 Eagle"}]}',
        encoding="utf-8",
    )
    asset = Asset(
        speech_quality=SpeechQuality.clear,
        transcript_path="cache/transcripts/asset_x.json",
        analysis_status=AnalysisStatus.analyzed,
    )

    plan = AssetMapper(load_mapping_config(), SLUG, TS, tmp_path).plan(asset)

    assert "tc:speech_quality:clear" in plan.tags
    assert "## 语音识别" in plan.annotation
    assert "`00:00:03.5 → 00:00:08.2` 你好 Eagle" in plan.annotation
    assert all("你好 Eagle" not in tag for tag in plan.tags)


def test_plan_maps_no_speech_to_tag_and_explicit_annotation(tmp_path: Path) -> None:
    asset = Asset(
        speech_quality=SpeechQuality.none,
        analysis_status=AnalysisStatus.analyzed,
    )

    plan = AssetMapper(load_mapping_config(), SLUG, TS, tmp_path).plan(asset)

    assert "tc:speech_quality:none" in plan.tags
    assert "## 语音识别\n未检测到人声" in plan.annotation


def test_plan_skips_speech_output_when_not_analyzed(tmp_path: Path) -> None:
    asset = Asset(analysis_status=AnalysisStatus.analyzed)

    plan = AssetMapper(load_mapping_config(), SLUG, TS, tmp_path).plan(asset)

    assert all("speech_quality" not in tag for tag in plan.tags)
    assert "## 语音识别" not in plan.annotation


def test_plan_degrades_invalid_transcript_without_leaking_text_to_tags(
    tmp_path: Path,
) -> None:
    transcript = tmp_path / "cache" / "transcripts" / "asset_bad.json"
    transcript.parent.mkdir(parents=True)
    transcript.write_text("not-json 私密转写", encoding="utf-8")
    asset = Asset(
        speech_quality=SpeechQuality.unclear,
        transcript_path="cache/transcripts/asset_bad.json",
        analysis_status=AnalysisStatus.analyzed,
    )

    plan = AssetMapper(load_mapping_config(), SLUG, TS, tmp_path).plan(asset)

    assert "tc:speech_quality:unclear" in plan.tags
    assert "## 语音识别\n转写文件不可用" in plan.annotation
    assert all("私密转写" not in tag for tag in plan.tags)
