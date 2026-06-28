"""CLI tests for ``tripclipper export <slug>`` (M5-early)."""

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
    ProjectInfo,
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


def test_export_html_writes_review_file(tmp_path: Path) -> None:
    slug = "demo"
    pdir = _seed_project(tmp_path, slug)

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["export", slug, "--base-dir", str(tmp_path), "--html"],
    )
    assert result.exit_code == 0, result.output
    assert "已生成 review.html" in result.output
    out_file = pdir / "exports" / "review.html"
    assert out_file.is_file()


def test_export_missing_project_exits_nonzero(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["export", "no-such-slug", "--base-dir", str(tmp_path), "--html"],
    )
    assert result.exit_code != 0
    assert "尚未初始化" in result.output


def test_export_no_html_flag_returns_2(tmp_path: Path) -> None:
    slug = "demo"
    _seed_project(tmp_path, slug)

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["export", slug, "--base-dir", str(tmp_path), "--no-html"],
    )
    assert result.exit_code == 2
    assert "M5-early 当前只支持 HTML 导出" in result.output


def test_export_open_invokes_webbrowser(tmp_path: Path, monkeypatch) -> None:
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
        ["export", slug, "--base-dir", str(tmp_path), "--html", "--open"],
    )
    assert result.exit_code == 0, result.output
    assert len(calls) == 1
    assert calls[0].startswith("file://")
    assert calls[0].endswith("review.html")
