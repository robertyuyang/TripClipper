"""CLI tests for ``tripclipper export <slug>`` (M5)."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from tripclipper import SCHEMA_VERSION
from tripclipper.cli import main
from tripclipper.cut_index import write_cut_index
from tripclipper.models import (
    AnalysisStatus,
    Asset,
    AssetType,
    CutIndex,
    EditCandidateStatus,
    ProjectInfo,
    SimilarGroup,
    SimilarSelection,
)
from tripclipper.paths import cut_index_path, ensure_project_dirs


def _seed_project(tmp_path: Path, slug: str) -> Path:
    ensure_project_dirs(slug, base_dir=tmp_path)
    project = ProjectInfo(
        project_name="Demo",
        project_slug=slug,
        source_folder=str(tmp_path / "source"),
        config_path=str(tmp_path / "source" / "project.yaml"),
        model_config_summary={
            "provider": "openai",
            "vision_model": "gpt-vision",
            "api_key_env": "TRIPCLIPPER_MODEL_API_KEY",
        },
    )
    ci = CutIndex(
        schema_version=SCHEMA_VERSION,
        project=project,
        assets=[
            Asset(
                asset_id="asset_1",
                filename="x.mp4",
                relative_path="x.mp4",
                type=AssetType.video,
                analysis_status=AnalysisStatus.scanned,
            )
        ],
    )
    write_cut_index(cut_index_path(slug, base_dir=tmp_path), ci)
    return tmp_path / slug


def test_export_html_writes_review_file(tmp_path: Path, monkeypatch) -> None:
    slug = "demo"
    pdir = _seed_project(tmp_path, slug)

    monkeypatch.setattr("tripclipper.cli.webbrowser.open", lambda *a, **kw: True)

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["export", slug, "--base-dir", str(tmp_path)],
    )
    assert result.exit_code == 0, result.output
    assert "已生成 review.html" in result.output
    out_file = pdir / "exports" / "review.html"
    assert out_file.is_file()


def test_export_missing_project_exits_nonzero(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["export", "no-such-slug", "--base-dir", str(tmp_path)],
    )
    assert result.exit_code != 0
    assert "尚未初始化" in result.output


def test_export_default_invokes_webbrowser(tmp_path: Path, monkeypatch) -> None:
    slug = "demo"
    _seed_project(tmp_path, slug)

    calls: list[str] = []

    def fake_open(url: str, *args, **kwargs) -> bool:
        calls.append(url)
        return True

    monkeypatch.setattr("tripclipper.cli.webbrowser.open", fake_open)

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["export", slug, "--base-dir", str(tmp_path)],
    )
    assert result.exit_code == 0, result.output
    assert len(calls) == 1
    assert calls[0].startswith("file://")
    assert calls[0].endswith("review.html")


def _seed_project_with_m4(tmp_path: Path, slug: str) -> Path:
    ensure_project_dirs(slug, base_dir=tmp_path)
    project = ProjectInfo(
        project_name="Demo",
        project_slug=slug,
        source_folder=str(tmp_path / "source"),
        config_path=str(tmp_path / "source" / "project.yaml"),
        model_config_summary={
            "provider": "openai",
            "vision_model": "gpt-vision",
            "api_key_env": "TRIPCLIPPER_MODEL_API_KEY",
        },
    )
    primary = Asset(
        asset_id="asset_primary",
        filename="primary.mp4",
        relative_path="primary.mp4",
        type=AssetType.video,
        analysis_status=AnalysisStatus.analyzed,
        similar_group_id="group_1",
        similar_selection=SimilarSelection.primary,
        similar_rank=1,
        similar_reason="画面清晰",
        edit_candidate_status=EditCandidateStatus.default_selected,
        edit_candidate_priority=1,
        edit_candidate_reason="组『group_1』主选，默认入选",
        rating=4,
    )
    alt = Asset(
        asset_id="asset_alt",
        filename="alt.mp4",
        relative_path="alt.mp4",
        type=AssetType.video,
        analysis_status=AnalysisStatus.analyzed,
        similar_group_id="group_1",
        similar_selection=SimilarSelection.alternate,
        similar_rank=2,
        similar_reason="备选",
        edit_candidate_status=EditCandidateStatus.alternate,
        edit_candidate_reason="组『group_1』备选",
        rating=3,
    )
    solo = Asset(
        asset_id="asset_solo",
        filename="solo.mp4",
        relative_path="solo.mp4",
        type=AssetType.video,
        analysis_status=AnalysisStatus.analyzed,
        edit_candidate_status=EditCandidateStatus.default_selected,
        edit_candidate_priority=2,
        edit_candidate_reason="非雷同高星素材，默认入选",
        rating=4,
    )
    ci = CutIndex(
        schema_version=SCHEMA_VERSION,
        project=project,
        assets=[primary, alt, solo],
        similar_groups=[
            SimilarGroup(
                similar_group_id="group_1",
                asset_ids=["asset_primary", "asset_alt"],
                basis=["同一景点", "相近构图"],
                primary_asset_id="asset_primary",
                alternate_asset_ids=["asset_alt"],
                confidence=0.85,
                needs_review=False,
            )
        ],
    )
    write_cut_index(cut_index_path(slug, base_dir=tmp_path), ci)
    return tmp_path / slug


def test_export_with_m4_data_renders_group_card(
    tmp_path: Path, monkeypatch
) -> None:
    slug = "demo_m4"
    pdir = _seed_project_with_m4(tmp_path, slug)

    monkeypatch.setattr("tripclipper.cli.webbrowser.open", lambda *a, **kw: True)

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["export", slug, "--base-dir", str(tmp_path)],
    )
    assert result.exit_code == 0, result.output
    out_file = pdir / "exports" / "review.html"
    assert out_file.is_file()
    text = out_file.read_text(encoding="utf-8")

    assert 'class="group-card"' in text
    assert "group_1" in text
    assert "85%" in text
    assert 'class="sel-primary"' in text
    assert 'class="cand-default"' in text
    assert 'class="cand-alternate"' in text
    assert "（待 M4）" not in text
    assert "__SIMILAR_GROUPS_HTML__" not in text


# ---------------------------------------------------------------------------
# Task 10：CLI 端到端
# ---------------------------------------------------------------------------


def test_export_writes_both_files_and_prints_summary(
    tmp_path: Path, monkeypatch
) -> None:
    slug = "demo"
    pdir = _seed_project(tmp_path, slug)

    monkeypatch.setattr("tripclipper.cli.webbrowser.open", lambda *a, **kw: True)

    runner = CliRunner()
    result = runner.invoke(main, ["export", slug, "--base-dir", str(tmp_path)])

    assert result.exit_code == 0, result.output
    review = pdir / "exports" / "review.html"
    cut_copy = pdir / "exports" / "cut_index.json"
    assert review.is_file()
    assert cut_copy.is_file()

    assert "已生成 cut_index 副本:" in result.output
    assert "已生成 review.html:" in result.output
    assert "📊 项目「Demo」总览" in result.output
    assert "rating 分布：★5 ×" in result.output

    payload = json.loads(cut_copy.read_text(encoding="utf-8"))
    assert payload["project"]["model_config_summary"] == {}


def test_export_cut_index_only(tmp_path: Path) -> None:
    slug = "demo"
    pdir = _seed_project(tmp_path, slug)

    runner = CliRunner()
    result = runner.invoke(
        main, ["export", slug, "--base-dir", str(tmp_path), "--cut-index-only"]
    )

    assert result.exit_code == 0, result.output
    cut_copy = pdir / "exports" / "cut_index.json"
    review = pdir / "exports" / "review.html"
    assert cut_copy.is_file()
    assert not review.exists()

    assert "已生成 cut_index 副本:" in result.output
    assert "已生成 review.html:" not in result.output
    assert "📊 项目「Demo」总览" in result.output


def test_export_cut_index_only_does_not_open_browser(
    tmp_path: Path, monkeypatch
) -> None:
    slug = "demo"
    _seed_project(tmp_path, slug)

    calls: list[str] = []

    def fake_open(url: str, *args, **kwargs) -> bool:
        calls.append(url)
        return True

    monkeypatch.setattr("tripclipper.cli.webbrowser.open", fake_open)

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "export",
            slug,
            "--base-dir",
            str(tmp_path),
            "--cut-index-only",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls == []
