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
from datetime import datetime
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
    _format_session_cell,
    _format_similar_cell,
    _format_status_class,
    _format_tags,
    _render_overview_section,
    _render_project_header,
    _render_similar_groups_section,
    _render_summary_cell,
    _summarise_for_stdout,
    _thumbnail_uri,
    copy_cut_index,
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
    Session,
    ShotFunction,
    ShotScale,
    SimilarGroup,
    SimilarSelection,
    SubjectType,
)
from tripclipper.paths import cut_index_path, ensure_project_dirs, exported_cut_index_path


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


def test_asset_to_row_thumbnail_strip_caps_at_nine_frames() -> None:
    frames = [f"/tmp/frame_{i:02d}.jpg" for i in range(12)]
    asset = Asset(
        asset_id="asset_frames",
        filename="frames.mp4",
        frame_paths=frames,
        analysis_status=AnalysisStatus.analyzed,
    )
    html = _asset_to_row(asset, Path("/tmp/proj"))

    assert html.count("<img ") == 9
    assert 'class="thumb-overflow">+3</span>' in html
    assert "file:///tmp/frame_08.jpg" in html
    assert "file:///tmp/frame_09.jpg" not in html


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


def test_render_project_header_includes_overview_section() -> None:
    # Task 3：_render_project_header 在 <dl> 之后拼入 _render_overview_section 的输出。
    ci = _make_cut_index(
        assets=[
            Asset(
                asset_id="a",
                filename="a.mp4",
                type=AssetType.video,
                analysis_status=AnalysisStatus.analyzed,
                rating=5,
            )
        ]
    )
    html = _render_project_header(ci)
    assert 'class="overview"' in html
    assert 'class="overview-row"' in html
    # 确认 overview 区块在 <dl>...</dl> 之后出现
    assert html.index("</dl>") < html.index('class="overview"')


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


# ---------------------------------------------------------------------------
# M5 Task 2: _render_overview_section
# ---------------------------------------------------------------------------


def _counts(
    *,
    rating: dict[int | None, int] | None = None,
    similar_group_count: int = 0,
    similar_member_count: int = 0,
    similar_needs_review_count: int = 0,
    candidates: dict[str, int] | None = None,
    total_assets: int = 0,
) -> OverviewCounts:
    base_rating = {5: 0, 4: 0, 3: 0, 2: 0, 1: 0, None: 0}
    if rating:
        base_rating.update(rating)
    base_cand = {"default_selected": 0, "alternate": 0, "excluded": 0, "needs_review": 0}
    if candidates:
        base_cand.update(candidates)
    return OverviewCounts(
        rating_distribution=base_rating,
        similar_group_count=similar_group_count,
        similar_member_count=similar_member_count,
        similar_needs_review_count=similar_needs_review_count,
        candidate_counts=base_cand,
        total_assets=total_assets,
    )


def test_render_overview_section_full_data_renders_three_rows() -> None:
    counts = _counts(
        rating={5: 2, 4: 3, 3: 1, 2: 1, 1: 0, None: 3},
        similar_group_count=1,
        similar_member_count=3,
        similar_needs_review_count=0,
        candidates={"default_selected": 6, "alternate": 3, "excluded": 0, "needs_review": 1},
        total_assets=10,
    )
    html_out = _render_overview_section(counts)
    assert html_out.startswith('<div class="overview">')
    assert html_out.count('class="overview-row"') == 3
    assert "★5 ×2 · ★4 ×3 · ★3 ×1 · ★2 ×1 · ★1 ×0 · 未评级 ×3" in html_out
    assert "相似组 1 个（共 3 条；0 条待人工确认）" in html_out
    assert "候选池：default_selected ×6 · alternate ×3 · excluded ×0 · needs_review ×1" in html_out


def test_render_overview_section_no_similar_groups_omits_row() -> None:
    counts = _counts(
        rating={5: 1, 4: 0, 3: 0, 2: 0, 1: 0, None: 0},
        similar_group_count=0,
        candidates={"default_selected": 1, "alternate": 0, "excluded": 0, "needs_review": 0},
        total_assets=1,
    )
    html_out = _render_overview_section(counts)
    assert html_out.count('class="overview-row"') == 2
    assert "相似组" not in html_out
    assert "★5 ×1" in html_out
    assert "候选池：" in html_out


def test_render_overview_section_no_candidates_omits_row() -> None:
    counts = _counts(
        rating={5: 1, 4: 0, 3: 0, 2: 0, 1: 0, None: 0},
        similar_group_count=1,
        similar_member_count=2,
        candidates={"default_selected": 0, "alternate": 0, "excluded": 0, "needs_review": 0},
        total_assets=2,
    )
    html_out = _render_overview_section(counts)
    assert "候选池：" not in html_out
    assert "相似组 1 个" in html_out
    assert html_out.count('class="overview-row"') == 2


def test_render_overview_section_empty_state_only_rating_zeros() -> None:
    counts = _counts(total_assets=0)
    html_out = _render_overview_section(counts)
    assert html_out.count('class="overview-row"') == 1
    assert "★5 ×0 · ★4 ×0 · ★3 ×0 · ★2 ×0 · ★1 ×0 · 未评级 ×0" in html_out
    assert "相似组" not in html_out
    assert "候选池：" not in html_out


# ---------------------------------------------------------------------------
# M5 Task 4: copy_cut_index
# ---------------------------------------------------------------------------


def _seed_cut_index_for_copy(
    tmp_path: Path,
    slug: str,
    *,
    model_config_summary: dict | None = None,
    extra_assets: list[Asset] | None = None,
) -> Path:
    ensure_project_dirs(slug, base_dir=tmp_path)
    project = ProjectInfo(
        project_name="Demo",
        project_slug=slug,
        source_folder=str(tmp_path / "source"),
        config_path=str(tmp_path / "source" / "project.yaml"),
        model_config_summary=model_config_summary
        or {
            "provider": "openai",
            "vision_model": "gpt-vision",
            "api_key_env": "TRIPCLIPPER_MODEL_API_KEY",
        },
    )
    assets = extra_assets if extra_assets is not None else [
        Asset(
            asset_id="a1",
            filename="a1.mp4",
            type=AssetType.video,
            analysis_status=AnalysisStatus.scanned,
        )
    ]
    ci = CutIndex(schema_version=SCHEMA_VERSION, project=project, assets=assets)
    target = cut_index_path(slug, base_dir=tmp_path)
    payload = ci.model_dump(mode="json", by_alias=True, exclude_none=False)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def test_copy_cut_index_writes_valid_redacted_json(tmp_path: Path) -> None:
    slug = "demo"
    _seed_cut_index_for_copy(tmp_path, slug)

    out = copy_cut_index(slug, base_dir=tmp_path)
    assert out == exported_cut_index_path(slug, base_dir=tmp_path)
    assert out.is_file()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["project"]["project_slug"] == slug
    assert data["project"]["model_config_summary"] == {}


def test_copy_cut_index_decoupled_from_active_file(tmp_path: Path) -> None:
    slug = "demo"
    _seed_cut_index_for_copy(tmp_path, slug)
    first = copy_cut_index(slug, base_dir=tmp_path)
    snapshot_text = first.read_text(encoding="utf-8")
    snapshot_mtime = first.stat().st_mtime

    # Mutate the active cut_index by re-seeding with a different asset list.
    _seed_cut_index_for_copy(
        tmp_path,
        slug,
        extra_assets=[
            Asset(
                asset_id="b1",
                filename="b1.mp4",
                type=AssetType.video,
                analysis_status=AnalysisStatus.analyzed,
                rating=5,
            ),
            Asset(
                asset_id="b2",
                filename="b2.mp4",
                type=AssetType.image,
                analysis_status=AnalysisStatus.analyzed,
            ),
        ],
    )

    # Copy is unchanged: same content + same mtime.
    assert first.read_text(encoding="utf-8") == snapshot_text
    assert first.stat().st_mtime == snapshot_mtime


def test_copy_cut_index_missing_slug_raises_export_error(tmp_path: Path) -> None:
    with pytest.raises(ExportError) as excinfo:
        copy_cut_index("does-not-exist", base_dir=tmp_path)
    assert "尚未初始化" in str(excinfo.value)


def test_copy_cut_index_redacts_model_config_summary(tmp_path: Path) -> None:
    slug = "demo"
    _seed_cut_index_for_copy(
        tmp_path,
        slug,
        model_config_summary={
            "provider": "openrouter",
            "secret": "DUMMY-LEAK-TOKEN",
            "api_key_env": "TRIPCLIPPER_MODEL_API_KEY",
        },
    )
    out = copy_cut_index(slug, base_dir=tmp_path)
    raw = out.read_text(encoding="utf-8")
    assert "DUMMY-LEAK-TOKEN" not in raw
    assert "openrouter" not in raw
    data = json.loads(raw)
    assert data["project"]["model_config_summary"] == {}


# ---------------------------------------------------------------------------
# M5 Task 5: _summarise_for_stdout
# ---------------------------------------------------------------------------


def test_summarise_for_stdout_full_dataset_six_lines() -> None:
    ratings = [5, 5, 4, 4, 4, 3, 2, None, None, None]
    candidates = (
        [EditCandidateStatus.default_selected] * 6
        + [EditCandidateStatus.alternate] * 3
        + [EditCandidateStatus.needs_review] * 1
    )
    assets = [
        Asset(
            asset_id=f"a{i}",
            filename=f"a{i}.mp4",
            type=AssetType.video,
            analysis_status=AnalysisStatus.analyzed,
            rating=ratings[i],
            edit_candidate_status=candidates[i],
        )
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

    out = _summarise_for_stdout(ci)
    lines = out.split("\n")
    assert len(lines) == 6
    assert lines[0] == "📊 项目「Demo」总览"
    assert "素材总数：10" in lines[1]
    assert "video=10" in lines[1]
    assert "analyzed=10" in lines[2]
    assert "★5 ×2 · ★4 ×3 · ★3 ×1 · ★2 ×1 · ★1 ×0 · 未评级 ×3" in lines[3]
    assert lines[4].lstrip().startswith("相似组：1 个（共 3 条；0 条待人工确认）")
    assert "default_selected ×6" in lines[5]
    assert "alternate ×3" in lines[5]
    assert "needs_review ×1" in lines[5]


def test_summarise_for_stdout_no_similar_groups_five_lines() -> None:
    asset = Asset(
        asset_id="a",
        filename="a.mp4",
        type=AssetType.video,
        analysis_status=AnalysisStatus.analyzed,
        rating=5,
        edit_candidate_status=EditCandidateStatus.default_selected,
    )
    ci = _make_cut_index(assets=[asset])
    ci.similar_groups = []

    out = _summarise_for_stdout(ci)
    lines = out.split("\n")
    assert len(lines) == 5
    assert "相似组" not in out
    assert "候选池" in out


def test_summarise_for_stdout_no_groups_no_candidates_four_lines() -> None:
    asset = Asset(
        asset_id="a",
        filename="a.mp4",
        type=AssetType.image,
        analysis_status=AnalysisStatus.analyzed,
        rating=3,
    )
    ci = _make_cut_index(assets=[asset])
    ci.similar_groups = []

    out = _summarise_for_stdout(ci)
    lines = out.split("\n")
    assert len(lines) == 4
    assert "相似组" not in out
    assert "候选池" not in out
    assert lines[0].startswith("📊 项目「Demo」总览")


# ---------------------------------------------------------------------------
# Task 9：端到端 demo-scan / 手工 cut_index 渲染断言
# ---------------------------------------------------------------------------


def test_render_review_html_includes_overview_section_with_groups_and_pool(
    tmp_path: Path,
) -> None:
    """Task 9.1：有相似组 + 候选池时，三行总览全显示。"""
    slug = "demo_overview"
    primary = Asset(
        asset_id="asset_primary",
        filename="primary.mp4",
        relative_path="primary.mp4",
        type=AssetType.video,
        analysis_status=AnalysisStatus.analyzed,
        similar_group_id="group_1",
        similar_selection=SimilarSelection.primary,
        similar_rank=1,
        edit_candidate_status=EditCandidateStatus.default_selected,
        rating=5,
    )
    alt = Asset(
        asset_id="asset_alt",
        filename="alt.mp4",
        relative_path="alt.mp4",
        type=AssetType.video,
        analysis_status=AnalysisStatus.analyzed,
        similar_group_id="group_1",
        similar_selection=SimilarSelection.alternate,
        edit_candidate_status=EditCandidateStatus.alternate,
        rating=4,
    )
    ci = _make_cut_index(
        assets=[primary, alt],
        analysis=AnalysisInfo(stage="sample", status="completed"),
    )
    ci.similar_groups = [
        SimilarGroup(
            similar_group_id="group_1",
            asset_ids=["asset_primary", "asset_alt"],
            primary_asset_id="asset_primary",
            alternate_asset_ids=["asset_alt"],
            confidence=0.9,
            needs_review=False,
        )
    ]
    _write_cut_index(tmp_path, slug, ci)

    out = render_review_html(slug, base_dir=tmp_path)
    text = out.read_text(encoding="utf-8")

    assert 'class="overview"' in text
    assert "★5 ×" in text
    assert "相似组 1 个" in text
    assert "候选池：default_selected ×" in text


def test_render_no_groups_omits_overview_similar_row(tmp_path: Path) -> None:
    """Task 9.2：无相似组时，overview 区块在但「相似组」行不在。"""
    slug = "demo_no_groups"
    asset = Asset(
        asset_id="asset_solo",
        filename="solo.mp4",
        relative_path="solo.mp4",
        type=AssetType.video,
        analysis_status=AnalysisStatus.analyzed,
        rating=4,
    )
    ci = _make_cut_index(
        assets=[asset],
        analysis=AnalysisInfo(stage="sample", status="completed"),
    )
    ci.similar_groups = []
    _write_cut_index(tmp_path, slug, ci)

    out = render_review_html(slug, base_dir=tmp_path)
    text = out.read_text(encoding="utf-8")

    assert 'class="overview"' in text
    # overview 区块不包含相似组聚合行（无 group → 该行被省略）
    overview_html = _render_overview_section(_compute_overview_counts(ci))
    assert "相似组" not in overview_html
    # 同时确认 review.html 里这块 HTML 字面也不含「相似组 N 个」字样
    assert "相似组 " not in text or "相似组 0 个" not in text
    assert overview_html in text


def test_copy_cut_index_demo_scan_end_to_end(tmp_path: Path) -> None:
    """Task 9.3：用真 demo-scan 数据 → 副本里 model_config_summary 为 {}、
    asset 数量与原值一致。"""
    real_path = Path("projects/demo-scan/cut_index.json")
    if not real_path.is_file():
        pytest.skip("demo-scan baseline not present")
    slug = "demo-scan"
    ensure_project_dirs(slug, base_dir=tmp_path)
    target = cut_index_path(slug, base_dir=tmp_path)
    target.write_text(real_path.read_text(encoding="utf-8"), encoding="utf-8")

    copied = copy_cut_index(slug, base_dir=tmp_path)
    assert copied == exported_cut_index_path(slug, base_dir=tmp_path)
    assert copied.is_file()

    copied_payload = json.loads(copied.read_text(encoding="utf-8"))
    original_payload = json.loads(real_path.read_text(encoding="utf-8"))
    assert copied_payload["project"]["model_config_summary"] == {}
    assert len(copied_payload["assets"]) == len(original_payload["assets"])


# ---------------------------------------------------------------------------
# session-splitting Task 7: flat session column + overview
# ---------------------------------------------------------------------------


def test_format_session_cell_variants() -> None:
    # no session -> empty
    assert _format_session_cell(Asset(asset_id="a")) == ""
    assert _format_session_cell(Asset(asset_id="a", session_id="")) == ""
    # numbered session -> blue badge
    numbered = _format_session_cell(Asset(asset_id="a", session_id="session_01"))
    assert 'class="session-badge"' in numbered
    assert "session_01" in numbered
    assert "session-unknown" not in numbered
    # unknown -> grey badge
    unknown = _format_session_cell(
        Asset(asset_id="a", session_id="session_00_unknown")
    )
    assert 'class="session-badge session-unknown"' in unknown
    assert "session_00_unknown" in unknown


def test_render_overview_section_includes_session_summary_with_unknown() -> None:
    counts = OverviewCounts(session_count=3, session_unknown_count=2)
    html_out = _render_overview_section(counts)
    assert "共 3 个 session（含 unknown 2 张）" in html_out


def test_render_overview_section_session_summary_omits_unknown_when_zero() -> None:
    counts = OverviewCounts(session_count=2, session_unknown_count=0)
    html_out = _render_overview_section(counts)
    assert "共 2 个 session" in html_out
    assert "unknown" not in html_out


def test_compute_overview_counts_counts_sessions_and_unknown() -> None:
    ci = _make_cut_index(assets=[_make_asset(asset_id="a", rating=3)])
    ci.sessions = [
        Session(session_id="session_01", asset_ids=["a"], asset_count=1),
        Session(
            session_id="session_00_unknown",
            asset_ids=["u1", "u2"],
            asset_count=2,
        ),
    ]
    counts = _compute_overview_counts(ci)
    assert counts.session_count == 2
    assert counts.session_unknown_count == 2


def test_render_review_html_with_sessions_end_to_end(tmp_path: Path) -> None:
    slug = "demo_sessions"
    assets = [
        Asset(
            asset_id="asset_1",
            filename="morning.mp4",
            relative_path="morning.mp4",
            type=AssetType.video,
            analysis_status=AnalysisStatus.analyzed,
            session_id="session_01",
            rating=4,
        ),
        Asset(
            asset_id="asset_2",
            filename="afternoon.mp4",
            relative_path="afternoon.mp4",
            type=AssetType.video,
            analysis_status=AnalysisStatus.analyzed,
            session_id="session_02",
            rating=3,
        ),
        Asset(
            asset_id="asset_u",
            filename="unknown.mp4",
            relative_path="unknown.mp4",
            type=AssetType.video,
            analysis_status=AnalysisStatus.analyzed,
            session_id="session_00_unknown",
        ),
    ]
    ci = _make_cut_index(
        assets=assets,
        analysis=AnalysisInfo(stage="sample", status="completed"),
    )
    ci.sessions = [
        Session(
            session_id="session_01",
            asset_ids=["asset_1"],
            started_at=datetime(2026, 7, 2, 9, 0),
            ended_at=datetime(2026, 7, 2, 9, 30),
            asset_count=1,
        ),
        Session(
            session_id="session_02",
            asset_ids=["asset_2"],
            started_at=datetime(2026, 7, 2, 14, 0),
            ended_at=datetime(2026, 7, 2, 14, 45),
            asset_count=1,
        ),
        Session(
            session_id="session_00_unknown",
            asset_ids=["asset_u"],
            started_at=None,
            ended_at=None,
            asset_count=1,
        ),
    ]
    _write_cut_index(tmp_path, slug, ci)

    out = render_review_html(slug, base_dir=tmp_path)
    text = out.read_text(encoding="utf-8")

    # single flat view only: no tabs and no duplicated session card view
    assert "扁平视图" not in text
    assert "Session 视图" not in text
    assert 'class="view-tab' not in text
    assert 'id="sessions-view"' not in text
    assert 'class="session-card"' not in text
    # flat table session column: blue badge + grey unknown badge + data attr
    assert 'class="session-badge"' in text
    assert 'class="session-badge session-unknown"' in text
    assert 'data-session-id="session_01"' in text
    assert 'data-session-id="session_00_unknown"' in text
    # overview summary line
    assert "共 3 个 session（含 unknown 1 张）" in text
    # session filter select present; option labels are expanded client-side
    # from embedded session metadata, while values remain the stable session_id.
    assert 'id="filter-session"' in text
    assert "formatSessionOptionLabel" in text
    assert "sessionLabelsById" in text
    assert "2026-07-02T09:00:00" in text
    assert "时间信息缺失" in text


def test_render_review_html_no_sessions_collapses_view(tmp_path: Path) -> None:
    slug = "demo_no_sessions"
    assets = [
        Asset(
            asset_id="asset_1",
            filename="ok.mp4",
            relative_path="ok.mp4",
            type=AssetType.video,
            analysis_status=AnalysisStatus.analyzed,
            rating=4,
        )
    ]
    ci = _make_cut_index(
        assets=assets,
        analysis=AnalysisInfo(stage="sample", status="completed"),
    )
    ci.sessions = []
    _write_cut_index(tmp_path, slug, ci)

    out = render_review_html(slug, base_dir=tmp_path)
    text = out.read_text(encoding="utf-8")

    # no session card view is rendered
    assert 'id="sessions-view"' not in text
    assert 'class="session-card"' not in text
    # overview has no session summary line
    assert "个 session" not in text
    # flat table session column is empty for this asset (no badge)
    assert 'class="session-badge"' not in text
