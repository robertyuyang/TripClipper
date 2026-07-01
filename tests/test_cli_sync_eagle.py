"""CLI tests for ``tripclipper sync-eagle <slug>`` (M6)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from tripclipper import SCHEMA_VERSION
from tripclipper.cli import main
from tripclipper.cut_index import read_cut_index, write_cut_index
from tripclipper.eagle_sync import (
    EagleClientError,
    EagleUnavailableError,
    EagleVersionError,
)
from tripclipper.models import (
    AnalysisStatus,
    Asset,
    AssetType,
    CutIndex,
    ProjectInfo,
)
from tripclipper.paths import (
    cut_index_path,
    eagle_apply_result_path,
    ensure_project_dirs,
)


# ---------------------------------------------------------------------------
# Fake Eagle clients
# ---------------------------------------------------------------------------


class FakeClient:
    """Records the calls the runner makes; every op succeeds."""

    instances: list["FakeClient"] = []

    def __init__(self, *a, **k):
        self.added: list[tuple] = []
        self.updated: list[str] = []
        self.trashed: list[str] = []
        self.tag_groups_created: list[tuple[str, list[str]]] = []
        self.tag_groups_updated: list[tuple[str, list[str]]] = []
        self.tag_groups_removed: list[str] = []
        FakeClient.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def fetch_library(self):
        return {"path": "/tmp/lib.library", "tag_groups": []}

    def health_check(self):
        return {"library": "/tmp/lib.library", "tagsGroups": []}

    def add_from_path(self, path, name, tags, rating, annotation):
        self.added.append((path, tags, rating))
        return "item_" + str(len(self.added))

    def update_item(self, item_id, *, tags=None, rating=None, annotation=None):
        self.updated.append(item_id)

    def move_to_trash(self, item_ids):
        self.trashed.extend(item_ids)

    def tag_group_create(self, name, tags):
        self.tag_groups_created.append((name, list(tags)))
        return "grp_" + name

    def tag_group_update(self, group_id, *, name=None, tags=None):
        self.tag_groups_updated.append((group_id, list(tags or [])))

    def tag_group_remove(self, group_ids):
        self.tag_groups_removed.extend(group_ids)


class FailingSecondAddClient(FakeClient):
    """add_from_path raises EagleClientError on the 2nd call."""

    def add_from_path(self, path, name, tags, rating, annotation):
        self.added.append((path, tags, rating))
        if len(self.added) == 2:
            raise EagleClientError(stage="item/addFromPath")
        return "item_" + str(len(self.added))


class UnavailableClient(FakeClient):
    def fetch_library(self):
        raise EagleUnavailableError(stage="library/info")

    def health_check(self):
        raise EagleUnavailableError(stage="library/info")


class VersionErrorClient(FakeClient):
    def fetch_library(self):
        raise EagleVersionError(stage="library/info", http_status=404)

    def health_check(self):
        raise EagleVersionError(stage="library/info", http_status=404)


# ---------------------------------------------------------------------------
# Seeding helpers
# ---------------------------------------------------------------------------


def _project_info(slug: str, tmp_path: Path) -> ProjectInfo:
    return ProjectInfo(
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


def _seed(tmp_path: Path, slug: str, assets: list[Asset]) -> Path:
    ensure_project_dirs(slug, base_dir=tmp_path)
    ci = CutIndex(
        schema_version=SCHEMA_VERSION,
        project=_project_info(slug, tmp_path),
        assets=assets,
    )
    write_cut_index(cut_index_path(slug, base_dir=tmp_path), ci)
    return tmp_path / slug


def _analyzed_asset(idx: int, **kw) -> Asset:
    return Asset(
        asset_id=f"asset_{idx}",
        filename=f"clip_{idx}.mp4",
        relative_path=f"clip_{idx}.mp4",
        path=f"/src/clip_{idx}.mp4",
        type=AssetType.video,
        analysis_status=AnalysisStatus.analyzed,
        **kw,
    )


@pytest.fixture(autouse=True)
def _reset_instances():
    FakeClient.instances = []
    yield
    FakeClient.instances = []


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_dry_run_default(tmp_path: Path, monkeypatch) -> None:
    slug = "demo"
    _seed(tmp_path, slug, [_analyzed_asset(1), _analyzed_asset(2)])
    monkeypatch.setattr("tripclipper.cli.EagleV2Client", FakeClient)

    runner = CliRunner()
    result = runner.invoke(main, ["sync-eagle", slug, "--base-dir", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "待同步" in result.output
    # no writes happened
    assert FakeClient.instances[0].added == []
    assert not eagle_apply_result_path(slug, base_dir=tmp_path).exists()


def test_apply_success(tmp_path: Path, monkeypatch) -> None:
    slug = "demo"
    _seed(tmp_path, slug, [_analyzed_asset(1), _analyzed_asset(2)])
    monkeypatch.setattr("tripclipper.cli.EagleV2Client", FakeClient)

    runner = CliRunner()
    result = runner.invoke(
        main, ["sync-eagle", slug, "--base-dir", str(tmp_path), "--apply"]
    )

    assert result.exit_code == 0, result.output
    assert "已同步" in result.output

    result_path = eagle_apply_result_path(slug, base_dir=tmp_path)
    assert result_path.exists()
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert payload["totals"]["synced"] == 2

    reloaded = read_cut_index(cut_index_path(slug, base_dir=tmp_path))
    assert all(a.eagle_sync_status == "synced" for a in reloaded.assets)


def test_apply_partial_failure(tmp_path: Path, monkeypatch) -> None:
    slug = "demo"
    _seed(tmp_path, slug, [_analyzed_asset(1), _analyzed_asset(2)])
    monkeypatch.setattr("tripclipper.cli.EagleV2Client", FailingSecondAddClient)

    runner = CliRunner()
    result = runner.invoke(
        main, ["sync-eagle", slug, "--base-dir", str(tmp_path), "--apply"]
    )

    assert result.exit_code == 0, result.output
    assert "⚠️" in result.output

    payload = json.loads(
        eagle_apply_result_path(slug, base_dir=tmp_path).read_text(encoding="utf-8")
    )
    assert len(payload["failures"]) == 1


def test_eagle_unavailable(tmp_path: Path, monkeypatch) -> None:
    slug = "demo"
    _seed(tmp_path, slug, [_analyzed_asset(1)])
    monkeypatch.setattr("tripclipper.cli.EagleV2Client", UnavailableClient)

    runner = CliRunner()
    result = runner.invoke(
        main, ["sync-eagle", slug, "--base-dir", str(tmp_path), "--apply"]
    )

    assert result.exit_code == 2, result.output
    assert "无法连接到 Eagle" in result.output


def test_eagle_version_too_low(tmp_path: Path, monkeypatch) -> None:
    slug = "demo"
    _seed(tmp_path, slug, [_analyzed_asset(1)])
    monkeypatch.setattr("tripclipper.cli.EagleV2Client", VersionErrorClient)

    runner = CliRunner()
    result = runner.invoke(
        main, ["sync-eagle", slug, "--base-dir", str(tmp_path), "--apply"]
    )

    assert result.exit_code == 2, result.output
    assert "4.0 Build 21" in result.output


def test_scanned_present_without_flag(tmp_path: Path, monkeypatch) -> None:
    slug = "demo"
    scanned = Asset(
        asset_id="asset_scanned",
        filename="raw.mp4",
        relative_path="raw.mp4",
        path="/src/raw.mp4",
        type=AssetType.video,
        analysis_status=AnalysisStatus.scanned,
    )
    _seed(tmp_path, slug, [scanned])
    monkeypatch.setattr("tripclipper.cli.EagleV2Client", FakeClient)

    runner = CliRunner()
    result = runner.invoke(
        main, ["sync-eagle", slug, "--base-dir", str(tmp_path), "--apply"]
    )

    assert result.exit_code == 2, result.output
    assert ("scanned" in result.output) or ("未分析" in result.output)


def test_scanned_skip_unanalyzed(tmp_path: Path, monkeypatch) -> None:
    slug = "demo"
    scanned = Asset(
        asset_id="asset_scanned",
        filename="raw.mp4",
        relative_path="raw.mp4",
        path="/src/raw.mp4",
        type=AssetType.video,
        analysis_status=AnalysisStatus.scanned,
    )
    _seed(tmp_path, slug, [scanned, _analyzed_asset(1)])
    monkeypatch.setattr("tripclipper.cli.EagleV2Client", FakeClient)

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "sync-eagle",
            slug,
            "--base-dir",
            str(tmp_path),
            "--apply",
            "--skip-unanalyzed",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(
        eagle_apply_result_path(slug, base_dir=tmp_path).read_text(encoding="utf-8")
    )
    assert payload["totals"]["synced"] == 1
    assert payload["totals"]["skipped_unanalyzed"] == 1


def test_reset_confirm_no_aborts(tmp_path: Path, monkeypatch) -> None:
    slug = "demo"
    asset = _analyzed_asset(1, eagle_item_id="existing_1", eagle_sync_status="synced")
    _seed(tmp_path, slug, [asset])
    monkeypatch.setattr("tripclipper.cli.EagleV2Client", FakeClient)

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["sync-eagle", slug, "--base-dir", str(tmp_path), "--apply", "--reset"],
        input="n\n",
    )

    assert result.exit_code != 0
    # aborted before any client is constructed
    assert FakeClient.instances == []


def test_reset_yes_bypasses_confirm(tmp_path: Path, monkeypatch) -> None:
    slug = "demo"
    asset = _analyzed_asset(1, eagle_item_id="existing_1", eagle_sync_status="synced")
    _seed(tmp_path, slug, [asset])
    monkeypatch.setattr("tripclipper.cli.EagleV2Client", FakeClient)

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "sync-eagle",
            slug,
            "--base-dir",
            str(tmp_path),
            "--apply",
            "--reset",
            "--yes",
        ],
    )

    assert result.exit_code == 0, result.output
    assert FakeClient.instances[0].trashed == ["existing_1"]


def test_strict_mapping_passes_flag(tmp_path: Path, monkeypatch) -> None:
    slug = "demo"
    # ``tags`` is not a declared mapping field; auto_map_unknown would normally
    # emit a tc:tags:custom tag. --strict-mapping must suppress it.
    asset = _analyzed_asset(1, tags=["custom"])
    _seed(tmp_path, slug, [asset])
    monkeypatch.setattr("tripclipper.cli.EagleV2Client", FakeClient)

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "sync-eagle",
            slug,
            "--base-dir",
            str(tmp_path),
            "--apply",
            "--strict-mapping",
        ],
    )

    assert result.exit_code == 0, result.output
    added = FakeClient.instances[0].added
    assert len(added) == 1
    _, tags, _ = added[0]
    assert "tc:tags:custom" not in tags
