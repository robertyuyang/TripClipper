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
    _asset_to_row,
    _dump_cut_index_json,
    _format_duration,
    _format_rating,
    _format_row_class,
    _format_segments,
    _format_status_class,
    _format_tags,
    _render_project_header,
    _render_summary_cell,
    _thumbnail_uri,
    render_review_html,
)
from tripclipper.models import (
    AnalysisInfo,
    AnalysisStatus,
    Asset,
    AssetType,
    CutIndex,
    Failure,
    PeoplePresence,
    ProjectInfo,
    Segment,
    ShotFunction,
    ShotScale,
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


def test_format_segments_empty_returns_placeholder() -> None:
    assert _format_segments(None) == "（无）"
    assert _format_segments([]) == "（无）"


def test_format_segments_renders_multi_segments_html() -> None:
    segs = [
        Segment(in_="00:01", out="00:05", role="hook"),
        Segment(in_="00:10", out="00:20", role="b_roll"),
    ]
    rendered = _format_segments(segs)
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

    # M4 placeholders rendered twice
    assert html.count("（待 M4）") == 2

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

    # M4 placeholders
    assert text.count("（待 M4）") >= 6  # 2 placeholders × 3 rows

    # header has project name
    assert "Demo" in text

    # API key value never leaks into the HTML
    assert "sk-leak-test" not in text


def test_render_review_html_raises_when_project_missing(tmp_path: Path) -> None:
    with pytest.raises(ExportError) as excinfo:
        render_review_html("does-not-exist", base_dir=tmp_path)
    assert "尚未初始化" in str(excinfo.value)
