"""M5-early HTML report renderer tests.

测试纪律（spec Q8 / task_list Task 6）：
- **零 mock**：仅给纯函数喂手工构造的 Pydantic 对象或字符串，断言渲染输出包含/
  不包含特定子串。不替换任何业务函数，不构造伪造分析结果当真结果。
- ``render_review_html`` 端到端测试用 ``tmp_path`` 写入真实的
  ``cut_index.json``，再调用本模块函数读出渲染结果。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tripclipper import SCHEMA_VERSION
from tripclipper.exporter import (
    ExportError,
    OverviewCounts,
    _asset_to_row,
    _compute_overview_counts,
    _dump_cut_index_json,
    _format_candidate_cell,
    _format_clip_suggestions,
    _format_duration,
    _format_rating,
    _format_row_class,
    _format_similar_cell,
    _format_status_class,
    _format_tags,
    _render_project_header,
    _render_similar_groups_section,
    _render_summary_cell,
    _thumbnail_uri,
    render_review_html,
)
from tripclipper.models import (
    AnalysisInfo,
    AnalysisStatus,
    Asset,
    AssetType,
    ClipSuggestion,
    CutIndex,
    EditCandidateStatus,
    Failure,
    PeoplePresence,
    ProjectInfo,
    ShotFunction,
    ShotScale,
    SimilarGroup,
    SimilarSelection,
    SubjectType,
)
from tripclipper.paths import cut_index_path, ensure_project_dirs


# ---------------------------------------------------------------------------
# Pure formatter unit tests
# ---------------------------------------------------------------------------


def test_format_duration_handles_none_zero_and_normal_values() -> None:
    assert _format_duration(None) == ""
    assert _format_duration(0) == ""
    assert _format_duration(0.0) == ""
    assert _format_duration(30.5) == "00:30"
    assert _format_duration(125.0) == "02:05"
    assert _format_duration(3661.0) == "61:01"


def test_format_clip_suggestions_empty_returns_placeholder() -> None:
    assert _format_clip_suggestions(None) == "（无）"
    assert _format_clip_suggestions([]) == "（无）"


def test_format_clip_suggestions_renders_multi_items_html() -> None:
    segs = [
        ClipSuggestion(in_="00:01", out="00:05", role="hook"),
        ClipSuggestion(in_="00:10", out="00:20", role="b_roll"),
    ]
    rendered = _format_clip_suggestions(segs)
    assert rendered.count('<div class="segment">') == 2
    assert "00:01-00:05 hook" in rendered
    assert "00:10-00:20 b_roll" in rendered


def test_format_status_class_for_each_value() -> None:
    assert _format_status_class(AnalysisStatus.analyzed) == "status-analyzed"
    assert _format_status_class(AnalysisStatus.scanned) == "status-scanned"
    assert _format_status_class(AnalysisStatus.analyzing) == "status-scanned"
    assert _format_status_class(AnalysisStatus.analysis_failed) == "status-failed"
    assert _format_status_class(None) == "status-other"


def test_format_row_class_for_each_value() -> None:
    assert _format_row_class(AnalysisStatus.analyzed) == ""
    assert _format_row_class(AnalysisStatus.scanned) == "row-pending"
    assert _format_row_class(AnalysisStatus.analyzing) == "row-pending"
    assert _format_row_class(AnalysisStatus.analysis_failed) == "row-failed"
    assert _format_row_class(None) == ""


def test_render_summary_cell_branches() -> None:
    # analyzed with summary -> escaped + truncated
    asset = Asset(
        analysis_status=AnalysisStatus.analyzed,
        summary="一段足够长的中文摘要" * 20,
    )
    rendered = _render_summary_cell(asset)
    assert "…" in rendered  # truncated

    # analyzed without summary
    asset2 = Asset(analysis_status=AnalysisStatus.analyzed, summary="")
    assert _render_summary_cell(asset2) == "（模型未生成 summary）"

    # scanned -> 待分析
    asset3 = Asset(analysis_status=AnalysisStatus.scanned)
    assert _render_summary_cell(asset3) == "（待分析）"

    # analysis_failed -> reason from last failure
    asset4 = Asset(
        analysis_status=AnalysisStatus.analysis_failed,
        failures=[
            {"stage": "analyze", "reason": "first reason"},
            {"stage": "analyze", "reason": "last reason xxx"},
        ],
    )
    assert "last reason" in _render_summary_cell(asset4)

    # analysis_failed with very long reason -> truncated
    long_reason = "失败原因" * 80
    asset5 = Asset(
        analysis_status=AnalysisStatus.analysis_failed,
        failures=[{"stage": "analyze", "reason": long_reason}],
    )
    rendered5 = _render_summary_cell(asset5)
    assert len(rendered5) <= 100  # truncated to ~80 chars
    assert "…" in rendered5


def test_render_summary_cell_escapes_html() -> None:
    asset = Asset(
        analysis_status=AnalysisStatus.analyzed,
        summary="<script>alert(1)</script>",
    )
    out = _render_summary_cell(asset)
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


def test_format_tags_truncation_and_overflow() -> None:
    assert _format_tags(None) == ""
    assert _format_tags([]) == ""
    assert _format_tags(["a", "b", "c"]) == "a, b, c"
    assert _format_tags(["a", "b", "c", "d", "e"]) == "a, b, c, d, e"
    assert _format_tags(["a", "b", "c", "d", "e", "f", "g", "h"]) == "a, b, c, d, e (+3)"


def test_format_rating_renders_stars() -> None:
    assert _format_rating(None) == ""
    rendered = _format_rating(3)
    assert rendered.count("★") == 3
    assert rendered.count("☆") == 2
    assert len(_format_rating(5)) == 5
    assert len(_format_rating(1)) == 5


def test_thumbnail_uri_returns_none_when_missing() -> None:
    asset = Asset(thumbnail_path=None)
    assert _thumbnail_uri(asset, Path("/tmp/proj")) is None
    asset2 = Asset(thumbnail_path="")
    assert _thumbnail_uri(asset2, Path("/tmp/proj")) is None


def test_thumbnail_uri_handles_relative_and_absolute(tmp_path: Path, monkeypatch) -> None:
    # Relative paths are resolved against cwd (matching scan.py's writer contract).
    monkeypatch.chdir(tmp_path)
    (tmp_path / "projects" / "demo" / "cache" / "thumbnails").mkdir(parents=True)
    rel = Asset(thumbnail_path="projects/demo/cache/thumbnails/x.jpg")
    uri = _thumbnail_uri(rel, tmp_path / "projects" / "demo")
    assert uri == f"file://{tmp_path}/projects/demo/cache/thumbnails/x.jpg"

    absolute = Asset(thumbnail_path="/abs/path/y.jpg")
    uri2 = _thumbnail_uri(absolute, Path("/tmp/proj"))
    assert uri2 == "file:///abs/path/y.jpg"


# ---------------------------------------------------------------------------
# _asset_to_row
# ---------------------------------------------------------------------------


def test_asset_to_row_contains_data_attrs_and_escapes(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "projects" / "demo" / "cache" / "thumbnails").mkdir(parents=True)
    asset = Asset(
        asset_id="asset_abc",
        filename="weird<name>.mp4",
        relative_path="weird<name>.mp4",
        type=AssetType.video,
        analysis_status=AnalysisStatus.analyzed,
        summary="hello",
        tags=["a", "b"],
        rating=4,
        subject_type=SubjectType.people,
        people_presence=PeoplePresence.single,
        shot_scale=ShotScale.medium,
        shot_function=ShotFunction.highlight,
        thumbnail_path="projects/demo/cache/thumbnails/abc.jpg",
        size=23_595_628,
        metadata={
            "duration": 12.5,
            "width": 1920,
            "height": 1080,
            "codec": "hevc",
            "fps": 59.94,
            "has_audio": True,
        },
    )
    html = _asset_to_row(asset, tmp_path / "projects" / "demo")

    # data-attrs present
    assert 'data-asset-id="asset_abc"' in html
    assert 'data-subject-type="people"' in html
    assert 'data-shot-scale="medium"' in html
    assert 'data-status="analyzed"' in html
    assert 'data-rating="4"' in html

    # filename escaped
    assert "weird&lt;name&gt;.mp4" in html
    assert "<weird>" not in html  # raw not present

    # M4 placeholders gone (no group / no candidate status on this asset)
    assert "（待 M4）" not in html
    assert 'data-similar-group-id=""' in html
    assert 'data-edit-candidate-status=""' in html

    # thumbnail rendered as file:// (resolved against cwd, matching scan.py)
    assert f"file://{tmp_path}/projects/demo/cache/thumbnails/abc.jpg" in html

    # media info block (multi-line)
    assert "video · 00:12" in html
    assert "1920×1080" in html
    assert "hevc" in html
    assert "60fps" in html
    assert "22.5 MB" in html
    assert "含音频" in html


def test_asset_to_row_failed_row_has_row_failed_class() -> None:
    asset = Asset(
        asset_id="asset_x",
        filename="x.mp4",
        analysis_status=AnalysisStatus.analysis_failed,
        failures=[Failure(stage="analyze", reason="boom")],
    )
    html = _asset_to_row(asset, Path("/tmp/proj"))
    assert "row-failed" in html
    assert "boom" in html


# ---------------------------------------------------------------------------
# Header & JSON
# ---------------------------------------------------------------------------


def _make_cut_index(
    *,
    assets: list[Asset] | None = None,
    failures: list[Failure] | None = None,
    analysis: AnalysisInfo | None = None,
    model_config_summary: dict | None = None,
) -> CutIndex:
    project = ProjectInfo(
        project_name="Demo",
        project_slug="demo",
        source_folder="/tmp/source",
        config_path="/tmp/source/project.yaml",
        model_config_summary=model_config_summary
        or {
            "provider": "openai",
            "vision_model": "gpt-vision",
            "api_key_env": "TRIPCLIPPER_MODEL_API_KEY",
        },
    )
    ci = CutIndex(
        schema_version=SCHEMA_VERSION,
        project=project,
        assets=assets or [],
        failures=failures or [],
    )
    if analysis is not None:
        ci.analysis = analysis
    return ci


def test_render_project_header_shows_notice_when_analysis_incomplete() -> None:
    ci = _make_cut_index(analysis=AnalysisInfo(stage="sample", status="running"))
    html = _render_project_header(ci)
    assert "尚未运行 sample/full 分析" in html

    ci2 = _make_cut_index()
    ci2.analysis = AnalysisInfo()
    html2 = _render_project_header(ci2)
    assert "尚未运行 sample/full 分析" in html2


def test_render_project_header_hides_notice_when_completed() -> None:
    ci = _make_cut_index(analysis=AnalysisInfo(stage="sample", status="completed"))
    html = _render_project_header(ci)
    assert "尚未运行 sample/full 分析" not in html


def test_render_project_header_lists_project_failures() -> None:
    ci = _make_cut_index(
        failures=[Failure(stage="scan", target="demo", reason="ffprobe missing")]
    )
    html = _render_project_header(ci)
    assert "项目级 failures" in html
    assert "ffprobe missing" in html


def test_dump_cut_index_json_strips_model_config_and_escapes_script() -> None:
    ci = _make_cut_index(
        model_config_summary={
            "provider": "openai",
            "vision_model": "gpt-vision",
            "api_key_env": "TRIPCLIPPER_MODEL_API_KEY",
        },
        assets=[Asset(asset_id="a1", summary="</script><b>x</b>")],
    )
    text = _dump_cut_index_json(ci)
    # original object untouched
    assert ci.project.model_config_summary["api_key_env"] == "TRIPCLIPPER_MODEL_API_KEY"
    # serialised text has model_config_summary cleared
    assert "gpt-vision" not in text
    # </script> escaped
    assert "</script>" not in text
    assert "<\\/script>" in text
    # is valid JSON
    parsed = json.loads(text.replace("<\\/script>", "</script>"))
    assert parsed["project"]["project_slug"] == "demo"


# ---------------------------------------------------------------------------
# render_review_html end-to-end (with tmp_path)
# ---------------------------------------------------------------------------


def _write_cut_index(tmp_path: Path, slug: str, ci: CutIndex) -> Path:
    ensure_project_dirs(slug, base_dir=tmp_path)
    target = cut_index_path(slug, base_dir=tmp_path)
    payload = ci.model_dump(mode="json", by_alias=True, exclude_none=False)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def test_render_review_html_end_to_end(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TRIPCLIPPER_MODEL_API_KEY", "sk-leak-test")
    slug = "demo"
    assets = [
        Asset(
            asset_id="asset_1",
            filename="ok.mp4",
            relative_path="ok.mp4",
            type=AssetType.video,
            analysis_status=AnalysisStatus.analyzed,
            summary="一个分析过的素材",
            tags=["旅行", "海"],
            rating=4,
            subject_type=SubjectType.landscape,
            shot_scale=ShotScale.wide,
            thumbnail_path="cache/thumbnails/asset_1.jpg",
            size=12_345_678,
            metadata={
                "duration": 30.0,
                "width": 1920,
                "height": 1080,
                "codec": "h264",
                "fps": 30.0,
                "has_audio": True,
            },
        ),
        Asset(
            asset_id="asset_2",
            filename="pending.mp4",
            relative_path="pending.mp4",
            type=AssetType.video,
            analysis_status=AnalysisStatus.scanned,
        ),
        Asset(
            asset_id="asset_3",
            filename="bad.mp4",
            relative_path="bad.mp4",
            type=AssetType.video,
            analysis_status=AnalysisStatus.analysis_failed,
            failures=[Failure(stage="analyze", reason="model returned non-json")],
        ),
    ]
    ci = _make_cut_index(
        assets=assets,
        analysis=AnalysisInfo(stage="sample", status="completed"),
    )
    _write_cut_index(tmp_path, slug, ci)

    out = render_review_html(slug, base_dir=tmp_path)
    assert out.exists()
    assert out == tmp_path / slug / "exports" / "review.html"
    text = out.read_text(encoding="utf-8")

    # structural markers
    assert "<table" in text
    assert text.count('class="asset-row') == 3 or text.count("asset-row") >= 3
    for aid in ("asset_1", "asset_2", "asset_3"):
        assert f'data-asset-id="{aid}"' in text

    # analysis_failed row class + reason
    assert "row-failed" in text
    assert "model returned non-json" in text

    # M4 placeholders gone — all assets here have no group / no candidate
    assert "（待 M4）" not in text
    # similar-groups section omitted entirely when groups list is empty
    assert "__SIMILAR_GROUPS_HTML__" not in text
    assert 'class="group-card"' not in text

    # header has project name
    assert "Demo" in text

    # API key value never leaks into the HTML
    assert "sk-leak-test" not in text


def test_render_review_html_raises_when_project_missing(tmp_path: Path) -> None:
    with pytest.raises(ExportError) as excinfo:
        render_review_html("does-not-exist", base_dir=tmp_path)
    assert "尚未初始化" in str(excinfo.value)


# ---------------------------------------------------------------------------
# M4: _format_similar_cell
# ---------------------------------------------------------------------------


def test_format_similar_cell_primary_includes_group_selection_rank_and_reason() -> None:
    asset = Asset(
        asset_id="a1",
        similar_group_id="group_1",
        similar_selection=SimilarSelection.primary,
        similar_rank=1,
        similar_reason="画面清晰稳定，构图完整",
    )
    out = _format_similar_cell(asset)
    assert "group_1" in out
    assert "primary" in out
    assert "rank=1" in out
    assert 'class="sel-primary"' in out
    assert '<span class="muted">画面清晰稳定，构图完整</span>' in out


def test_format_similar_cell_alternate_uses_alternate_class() -> None:
    asset = Asset(
        asset_id="a2",
        similar_group_id="group_1",
        similar_selection=SimilarSelection.alternate,
        similar_rank=2,
        similar_reason="备选",
    )
    out = _format_similar_cell(asset)
    assert 'class="sel-alternate"' in out
    assert "rank=2" in out


def test_format_similar_cell_rejected_uses_rejected_class() -> None:
    asset = Asset(
        asset_id="a3",
        similar_group_id="group_1",
        similar_selection=SimilarSelection.rejected,
        similar_rank=3,
    )
    out = _format_similar_cell(asset)
    assert 'class="sel-rejected"' in out


def test_format_similar_cell_needs_review_uses_needs_review_class() -> None:
    asset = Asset(
        asset_id="a4",
        similar_group_id="group_2",
        similar_selection=SimilarSelection.needs_review,
        similar_reason="组内置信度不足，待人工确认",
    )
    out = _format_similar_cell(asset)
    assert 'class="sel-needs-review"' in out
    assert "组内置信度不足" in out


def test_format_similar_cell_none_returns_empty_string() -> None:
    assert _format_similar_cell(Asset(asset_id="x", similar_selection=None)) == ""
    assert (
        _format_similar_cell(Asset(asset_id="y", similar_selection=SimilarSelection.none))
        == ""
    )


def test_format_similar_cell_truncates_long_reason() -> None:
    long_reason = "原因" * 60  # 120 chars
    asset = Asset(
        asset_id="a",
        similar_group_id="g",
        similar_selection=SimilarSelection.primary,
        similar_rank=1,
        similar_reason=long_reason,
    )
    out = _format_similar_cell(asset)
    assert "…" in out
    # the muted span must contain a truncated payload
    assert long_reason not in out


def test_format_similar_cell_escapes_html_payload() -> None:
    asset = Asset(
        asset_id="a",
        similar_group_id="<g>",
        similar_selection=SimilarSelection.primary,
        similar_rank=1,
        similar_reason="<script>alert(1)</script>",
    )
    out = _format_similar_cell(asset)
    assert "<script>" not in out
    assert "&lt;script&gt;" in out
    assert "&lt;g&gt;" in out


# ---------------------------------------------------------------------------
# M4: _format_candidate_cell
# ---------------------------------------------------------------------------


def test_format_candidate_cell_default_selected_includes_priority_and_reason() -> None:
    asset = Asset(
        asset_id="a",
        edit_candidate_status=EditCandidateStatus.default_selected,
        edit_candidate_priority=3,
        edit_candidate_reason="非雷同高星素材，默认入选",
    )
    out = _format_candidate_cell(asset)
    assert 'class="cand-default"' in out
    assert "default_selected" in out
    assert "priority=3" in out
    assert "非雷同高星素材，默认入选" in out


def test_format_candidate_cell_alternate_has_no_priority_but_keeps_reason() -> None:
    asset = Asset(
        asset_id="a",
        edit_candidate_status=EditCandidateStatus.alternate,
        edit_candidate_priority=9,
        edit_candidate_reason="为景别平衡入选 alternate",
    )
    out = _format_candidate_cell(asset)
    assert 'class="cand-alternate"' in out
    assert "priority" not in out
    assert "为景别平衡入选 alternate" in out


def test_format_candidate_cell_excluded_uses_excluded_class() -> None:
    asset = Asset(
        asset_id="a",
        edit_candidate_status=EditCandidateStatus.excluded,
    )
    out = _format_candidate_cell(asset)
    assert 'class="cand-excluded"' in out


def test_format_candidate_cell_needs_review_uses_needs_review_class() -> None:
    asset = Asset(
        asset_id="a",
        edit_candidate_status=EditCandidateStatus.needs_review,
    )
    out = _format_candidate_cell(asset)
    assert 'class="cand-needs-review"' in out


def test_format_candidate_cell_none_returns_empty_string() -> None:
    assert _format_candidate_cell(Asset(asset_id="x", edit_candidate_status=None)) == ""


# ---------------------------------------------------------------------------
# M4: _render_similar_groups_section
# ---------------------------------------------------------------------------


def _make_group_assets() -> list[Asset]:
    return [
        Asset(
            asset_id="asset_primary",
            filename="a_primary.mp4",
            type=AssetType.video,
            analysis_status=AnalysisStatus.analyzed,
            similar_group_id="group_1",
            similar_selection=SimilarSelection.primary,
            similar_rank=1,
            similar_reason="画面清晰稳定",
            rating=4,
        ),
        Asset(
            asset_id="asset_alt",
            filename="b_alt.mp4",
            type=AssetType.video,
            analysis_status=AnalysisStatus.analyzed,
            similar_group_id="group_1",
            similar_selection=SimilarSelection.alternate,
            similar_rank=2,
            similar_reason="可作为备选",
            rating=3,
        ),
    ]


def test_render_similar_groups_section_renders_one_card_with_basis_and_confidence() -> None:
    assets = _make_group_assets()
    group = SimilarGroup(
        similar_group_id="group_1",
        asset_ids=["asset_primary", "asset_alt"],
        basis=["同一景点", "相近构图"],
        primary_asset_id="asset_primary",
        alternate_asset_ids=["asset_alt"],
        confidence=0.85,
        needs_review=False,
    )
    ci = _make_cut_index(assets=assets)
    ci.similar_groups = [group]

    html = _render_similar_groups_section(ci)
    assert 'class="group-card"' in html
    assert "group_1" in html
    assert "85%" in html
    assert "同一景点" in html
    assert "相近构图" in html
    assert html.count('class="basis-chip"') == 2
    # ordering by similar_rank: primary li before alt li
    assert html.find("asset_primary") < html.find("asset_alt")
    assert "chip-warn" not in html


def test_render_similar_groups_section_needs_review_shows_warn_chip() -> None:
    assets = _make_group_assets()
    group = SimilarGroup(
        similar_group_id="group_1",
        asset_ids=["asset_primary", "asset_alt"],
        basis=["test"],
        confidence=0.4,
        needs_review=True,
    )
    ci = _make_cut_index(assets=assets)
    ci.similar_groups = [group]

    html = _render_similar_groups_section(ci)
    assert 'class="chip-warn"' in html
    assert "待人工确认" in html


def test_render_similar_groups_section_confidence_none_omits_percent() -> None:
    assets = _make_group_assets()
    group = SimilarGroup(
        similar_group_id="group_1",
        asset_ids=["asset_primary", "asset_alt"],
        basis=["x"],
        confidence=None,
    )
    ci = _make_cut_index(assets=assets)
    ci.similar_groups = [group]

    html = _render_similar_groups_section(ci)
    assert "%" not in html
    assert "置信度" not in html


def test_render_similar_groups_section_empty_returns_empty_string() -> None:
    ci = _make_cut_index(assets=[])
    ci.similar_groups = []
    assert _render_similar_groups_section(ci) == ""


# ---------------------------------------------------------------------------
# M4: render_review_html end-to-end with groups
# ---------------------------------------------------------------------------


def test_render_review_html_with_groups_includes_panel_and_real_cells(
    tmp_path: Path,
) -> None:
    slug = "demo_m4"
    assets = _make_group_assets()
    # add an unrelated default_selected asset
    assets.append(
        Asset(
            asset_id="asset_solo",
            filename="solo.mp4",
            type=AssetType.video,
            analysis_status=AnalysisStatus.analyzed,
            edit_candidate_status=EditCandidateStatus.default_selected,
            edit_candidate_priority=1,
            edit_candidate_reason="非雷同高星素材，默认入选",
            rating=4,
        )
    )
    # candidate fields on group members
    assets[0].edit_candidate_status = EditCandidateStatus.default_selected
    assets[0].edit_candidate_priority = 2
    assets[0].edit_candidate_reason = "组『group_1』主选，默认入选"
    assets[1].edit_candidate_status = EditCandidateStatus.alternate
    assets[1].edit_candidate_reason = "组『group_1』备选"

    ci = _make_cut_index(
        assets=assets,
        analysis=AnalysisInfo(stage="full", status="completed"),
    )
    ci.similar_groups = [
        SimilarGroup(
            similar_group_id="group_1",
            asset_ids=["asset_primary", "asset_alt"],
            basis=["同一景点", "相近构图"],
            primary_asset_id="asset_primary",
            alternate_asset_ids=["asset_alt"],
            confidence=0.85,
            needs_review=False,
        )
    ]
    _write_cut_index(tmp_path, slug, ci)

    out = render_review_html(slug, base_dir=tmp_path)
    text = out.read_text(encoding="utf-8")

    # panel rendered
    assert 'class="group-card"' in text
    assert "group_1" in text
    assert "85%" in text
    assert "同一景点" in text
    # table cells: at least one sel-primary chip and 2+ cand-default chips
    assert 'class="sel-primary"' in text
    assert text.count('class="cand-default"') >= 2
    # data-* attrs on rows
    assert 'data-similar-group-id="group_1"' in text
    assert 'data-edit-candidate-status="default_selected"' in text
    assert 'data-edit-candidate-status="alternate"' in text
    # no leftover placeholder
    assert "（待 M4）" not in text
    # placeholder fully substituted
    assert "__SIMILAR_GROUPS_HTML__" not in text


def test_render_review_html_no_groups_omits_panel(tmp_path: Path) -> None:
    slug = "demo_no_groups"
    assets = [
        Asset(
            asset_id="x",
            filename="x.mp4",
            type=AssetType.video,
            analysis_status=AnalysisStatus.analyzed,
            edit_candidate_status=EditCandidateStatus.default_selected,
            edit_candidate_priority=1,
            edit_candidate_reason="非雷同高星素材，默认入选",
            rating=4,
        )
    ]
    ci = _make_cut_index(
        assets=assets,
        analysis=AnalysisInfo(stage="full", status="completed"),
    )
    ci.similar_groups = []
    _write_cut_index(tmp_path, slug, ci)

    out = render_review_html(slug, base_dir=tmp_path)
    text = out.read_text(encoding="utf-8")

    assert 'class="group-card"' not in text
    assert "__SIMILAR_GROUPS_HTML__" not in text
    # cells still rendered with real M4 values
    assert 'class="cand-default"' in text


def test_render_demo_scan_real_data_renders_group_card(tmp_path: Path, monkeypatch) -> None:
    """Use the actual repo's demo-scan cut_index.json (real M4 output)."""
    repo_root = Path(__file__).resolve().parents[1]
    src_index = repo_root / "projects" / "demo-scan" / "cut_index.json"
    if not src_index.is_file():
        pytest.skip("projects/demo-scan/cut_index.json not present in repo")

    slug = "demo-scan"
    ensure_project_dirs(slug, base_dir=tmp_path)
    target = cut_index_path(slug, base_dir=tmp_path)
    target.write_text(src_index.read_text(encoding="utf-8"), encoding="utf-8")

    out = render_review_html(slug, base_dir=tmp_path)
    text = out.read_text(encoding="utf-8")

    assert 'class="group-card"' in text
    assert "group_1" in text
    # demo-scan 的 confidence 由真实模型仲裁决定（M4 真打），具体百分比可能波动；
    # 只断言渲染出了置信度百分比，不锁定数值。
    assert "置信度" in text
    assert "%" in text
    assert "同一景点" in text
    assert "（待 M4）" not in text
    assert 'class="sel-primary"' in text
    # demo-scan 至少有几条 default_selected 入选候选池。
    assert text.count('class="cand-default"') >= 1


# ---------------------------------------------------------------------------
# M5 Task 1: _compute_overview_counts
# ---------------------------------------------------------------------------


def _make_asset(
    *,
    asset_id: str,
    rating: int | None = None,
    asset_type: AssetType = AssetType.video,
    status: AnalysisStatus = AnalysisStatus.analyzed,
    candidate: EditCandidateStatus | None = None,
) -> Asset:
    return Asset(
        asset_id=asset_id,
        filename=f"{asset_id}.mp4",
        type=asset_type,
        analysis_status=status,
        rating=rating,
        edit_candidate_status=candidate,
    )


def test_compute_overview_counts_full_dataset_matches_spec_scenario() -> None:
    # spec ADDED §「完整数据」场景：rating=[5,5,4,4,4,3,2,None,None,None]、
    # 1 组 3 成员 0 待确认、候选池 default×6 / alternate×3 / excluded×0 / needs_review×1。
    ratings = [5, 5, 4, 4, 4, 3, 2, None, None, None]
    candidates = (
        [EditCandidateStatus.default_selected] * 6
        + [EditCandidateStatus.alternate] * 3
        + [EditCandidateStatus.needs_review] * 1
    )
    assets = [
        _make_asset(asset_id=f"a{i}", rating=ratings[i], candidate=candidates[i])
        for i in range(10)
    ]
    ci = _make_cut_index(assets=assets)
    ci.similar_groups = [
        SimilarGroup(
            similar_group_id="group_1",
            asset_ids=["a0", "a1", "a2"],
            confidence=0.9,
            needs_review=False,
        )
    ]

    counts = _compute_overview_counts(ci)
    assert isinstance(counts, OverviewCounts)
    assert counts.rating_distribution == {5: 2, 4: 3, 3: 1, 2: 1, 1: 0, None: 3}
    assert counts.similar_group_count == 1
    assert counts.similar_member_count == 3
    assert counts.similar_needs_review_count == 0
    assert counts.candidate_counts == {
        "default_selected": 6,
        "alternate": 3,
        "excluded": 0,
        "needs_review": 1,
    }
    assert counts.total_assets == 10
    assert counts.counts_by_type == {"video": 10}
    assert counts.counts_by_status == {"analyzed": 10}


def test_compute_overview_counts_empty_similar_groups_keeps_rating() -> None:
    assets = [_make_asset(asset_id="a", rating=5)]
    ci = _make_cut_index(assets=assets)
    ci.similar_groups = []

    counts = _compute_overview_counts(ci)
    assert counts.similar_group_count == 0
    assert counts.similar_member_count == 0
    assert counts.similar_needs_review_count == 0
    assert counts.rating_distribution[5] == 1
    assert counts.rating_distribution[None] == 0


def test_compute_overview_counts_all_candidates_none_keeps_four_keys() -> None:
    assets = [_make_asset(asset_id=f"a{i}", rating=3, candidate=None) for i in range(3)]
    ci = _make_cut_index(assets=assets)
    counts = _compute_overview_counts(ci)
    assert counts.candidate_counts == {
        "default_selected": 0,
        "alternate": 0,
        "excluded": 0,
        "needs_review": 0,
    }


def test_compute_overview_counts_empty_assets_zeroes_everything() -> None:
    ci = _make_cut_index(assets=[])
    counts = _compute_overview_counts(ci)
    assert counts.total_assets == 0
    assert counts.rating_distribution == {5: 0, 4: 0, 3: 0, 2: 0, 1: 0, None: 0}
    assert counts.candidate_counts == {
        "default_selected": 0,
        "alternate": 0,
        "excluded": 0,
        "needs_review": 0,
    }
    assert counts.similar_group_count == 0
    assert counts.counts_by_type == {}
    assert counts.counts_by_status == {}
