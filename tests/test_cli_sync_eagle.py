"""CLI tests for ``tripclipper sync-eagle <slug>`` (M6)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
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
    Session,
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
        self.folders_created: list[str] = []
        self.smart_folders_list_payload: list[dict] = []
        self.smart_folders_created: list[dict] = []
        self.smart_folders_updated: list[tuple[str, dict]] = []
        FakeClient.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def fetch_library(self):
        return {"path": "/tmp/lib.library", "tag_groups": []}

    def health_check(self):
        return {"library": "/tmp/lib.library", "tagsGroups": []}

    def add_from_path(self, path, name, tags, rating, annotation, folder_id=None):
        self.added.append((path, tags, rating, folder_id))
        return "item_" + str(len(self.added))

    def folder_create(self, name, parent_id=None):
        self.folders_created.append(name)
        return "folder_" + str(len(self.folders_created))

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

    def smart_folder_list(self):
        return list(self.smart_folders_list_payload)

    def smart_folder_create(self, payload):
        self.smart_folders_created.append(payload)
        return "sf_" + str(len(self.smart_folders_created))

    def smart_folder_update(self, folder_id, payload):
        self.smart_folders_updated.append((folder_id, payload))


class FailingSecondAddClient(FakeClient):
    """add_from_path raises EagleClientError on the 2nd call."""

    def add_from_path(self, path, name, tags, rating, annotation, folder_id=None):
        self.added.append((path, tags, rating, folder_id))
        if len(self.added) == 2:
            raise EagleClientError(stage="item/addFromPath")
        return "item_" + str(len(self.added))


class FailingTagGroupCreateClient(FakeClient):
    """tagGroup/create raises after item writes, yielding a maintenance warning."""

    def tag_group_create(self, name, tags):
        raise EagleClientError(
            stage="tagGroup/create",
            cause=RuntimeError("tag group write failed"),
            http_status=500,
        )


class FailingOneSmartFolderClient(FakeClient):
    def smart_folder_create(self, payload):
        self.smart_folders_created.append(payload)
        if payload["name"] == "TC · demo · 精选高光":
            raise EagleClientError(
                stage="smart_folder_create",
                cause=RuntimeError("smart folder write failed"),
                http_status=500,
            )
        return "sf_" + str(len(self.smart_folders_created))


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


def test_apply_prints_tag_group_warning_details(
    tmp_path: Path, monkeypatch
) -> None:
    slug = "demo"
    _seed(tmp_path, slug, [_analyzed_asset(1)])
    monkeypatch.setattr("tripclipper.cli.EagleV2Client", FailingTagGroupCreateClient)

    runner = CliRunner()
    result = runner.invoke(
        main, ["sync-eagle", slug, "--base-dir", str(tmp_path), "--apply"]
    )

    assert result.exit_code == 0, result.output
    assert "tag group 维护警告" in result.output
    assert "tagGroup/create" in result.output
    assert "tag group write failed" in result.output


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
    assert "4.0 Build 22" in result.output


def test_apply_prints_smart_folder_summary(tmp_path: Path, monkeypatch) -> None:
    slug = "demo"
    _seed(tmp_path, slug, [_analyzed_asset(1), _analyzed_asset(2)])
    monkeypatch.setattr("tripclipper.cli.EagleV2Client", FakeClient)

    runner = CliRunner()
    result = runner.invoke(
        main, ["sync-eagle", slug, "--base-dir", str(tmp_path), "--apply"]
    )

    assert result.exit_code == 0, result.output
    assert "Smart Folder: 5 个已就绪" in result.output


def test_apply_with_warnings_prints_warning_line(
    tmp_path: Path, monkeypatch
) -> None:
    slug = "demo"
    _seed(tmp_path, slug, [_analyzed_asset(1)])
    monkeypatch.setattr(
        "tripclipper.cli.EagleV2Client", FailingOneSmartFolderClient
    )

    runner = CliRunner()
    result = runner.invoke(
        main, ["sync-eagle", slug, "--base-dir", str(tmp_path), "--apply"]
    )

    assert result.exit_code == 0, result.output
    assert "⚠️ Smart Folder:" in result.output
    assert "1 个失败" in result.output


def test_no_smart_folders_flag_omits_summary(tmp_path: Path, monkeypatch) -> None:
    slug = "demo"
    _seed(tmp_path, slug, [_analyzed_asset(1)])
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
            "--no-smart-folders",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Smart Folder" not in result.output


def test_dry_run_prints_smart_folder_plan_line(
    tmp_path: Path, monkeypatch
) -> None:
    slug = "demo"
    _seed(tmp_path, slug, [_analyzed_asset(1)])
    monkeypatch.setattr("tripclipper.cli.EagleV2Client", FakeClient)

    runner = CliRunner()
    result = runner.invoke(main, ["sync-eagle", slug, "--base-dir", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "Smart Folder 计划: 将建/更新 5 个" in result.output


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
    _, tags, _, _ = added[0]
    assert "tc:tags:custom" not in tags


# ---------------------------------------------------------------------------
# Library-path guard: --library-path CLI flag with project.yaml fallback
# ---------------------------------------------------------------------------


def _write_project_yaml(tmp_path: Path, *, library_path: str | None) -> None:
    """Write a real project.yaml at the config_path _project_info points to."""
    cfg_path = tmp_path / "source" / "project.yaml"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        'project_name: "Demo"',
        f'source_folder: "{tmp_path / "source"}"',
        "model_config:",
        '  provider: "openai_compatible"',
        "eagle_sync:",
    ]
    if library_path is not None:
        lines.append(f'  library_path: "{library_path}"')
    cfg_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_library_path_from_config_matches(tmp_path: Path, monkeypatch) -> None:
    slug = "demo"
    _seed(tmp_path, slug, [_analyzed_asset(1)])
    _write_project_yaml(tmp_path, library_path="/tmp/lib.library")
    monkeypatch.setattr("tripclipper.cli.EagleV2Client", FakeClient)

    runner = CliRunner()
    result = runner.invoke(
        main, ["sync-eagle", slug, "--base-dir", str(tmp_path), "--apply"]
    )

    assert result.exit_code == 0, result.output
    assert "已同步" in result.output


def test_library_path_from_config_mismatch_aborts(tmp_path: Path, monkeypatch) -> None:
    slug = "demo"
    _seed(tmp_path, slug, [_analyzed_asset(1)])
    _write_project_yaml(tmp_path, library_path="/tmp/other.library")
    monkeypatch.setattr("tripclipper.cli.EagleV2Client", FakeClient)

    runner = CliRunner()
    result = runner.invoke(
        main, ["sync-eagle", slug, "--base-dir", str(tmp_path), "--apply"]
    )

    assert result.exit_code == 2, result.output
    assert "不一致" in result.output
    # error must attribute the expected value to project.yaml, not --library-path
    assert "project.yaml" in result.output
    assert FakeClient.instances[0].added == []


def test_library_path_cli_overrides_config(tmp_path: Path, monkeypatch) -> None:
    slug = "demo"
    _seed(tmp_path, slug, [_analyzed_asset(1)])
    # config points at a stale library, but the CLI flag matches the live one.
    _write_project_yaml(tmp_path, library_path="/tmp/other.library")
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
            "--library-path",
            "/tmp/lib.library",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "已同步" in result.output


def test_library_path_cli_mismatch_attributes_flag(
    tmp_path: Path, monkeypatch
) -> None:
    slug = "demo"
    _seed(tmp_path, slug, [_analyzed_asset(1)])
    _write_project_yaml(tmp_path, library_path=None)
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
            "--library-path",
            "/tmp/other.library",
        ],
    )

    assert result.exit_code == 2, result.output
    assert "--library-path" in result.output


# ---------------------------------------------------------------------------
# dry-run "Sessions preview" (session-splitting spec Task 6 / Q11)
# ---------------------------------------------------------------------------


def _seed_with_sessions(
    tmp_path: Path,
    slug: str,
    assets: list[Asset],
    sessions: list[Session],
) -> Path:
    ensure_project_dirs(slug, base_dir=tmp_path)
    ci = CutIndex(
        schema_version=SCHEMA_VERSION,
        project=_project_info(slug, tmp_path),
        assets=assets,
        sessions=sessions,
    )
    write_cut_index(cut_index_path(slug, base_dir=tmp_path), ci)
    return tmp_path / slug


def test_dry_run_sessions_preview(tmp_path: Path, monkeypatch) -> None:
    slug = "demo"
    start = datetime(2026, 6, 15, 9, 30, tzinfo=timezone.utc)
    end = datetime(2026, 6, 15, 10, 15, tzinfo=timezone.utc)
    assets = [
        _analyzed_asset(1, session_id="session_01"),
        _analyzed_asset(2, session_id="session_01"),
    ]
    sessions = [
        Session(
            session_id="session_01",
            asset_ids=["asset_1", "asset_2"],
            started_at=start,
            ended_at=end,
            asset_count=2,
        )
    ]
    _seed_with_sessions(tmp_path, slug, assets, sessions)
    monkeypatch.setattr("tripclipper.cli.EagleV2Client", FakeClient)

    runner = CliRunner()
    result = runner.invoke(main, ["sync-eagle", slug, "--base-dir", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "Sessions preview (gap=1h):" in result.output
    assert "session_01" in result.output
    assert start.astimezone().strftime("%Y-%m-%d %H:%M") in result.output
    assert "n=2" in result.output


def test_dry_run_sessions_preview_unknown_no_time(
    tmp_path: Path, monkeypatch
) -> None:
    slug = "demo"
    assets = [_analyzed_asset(1, session_id="session_00_unknown")]
    sessions = [
        Session(
            session_id="session_00_unknown",
            asset_ids=["asset_1"],
            asset_count=1,
        )
    ]
    _seed_with_sessions(tmp_path, slug, assets, sessions)
    monkeypatch.setattr("tripclipper.cli.EagleV2Client", FakeClient)

    runner = CliRunner()
    result = runner.invoke(main, ["sync-eagle", slug, "--base-dir", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "Sessions preview (gap=1h):" in result.output
    assert "session_00_unknown" in result.output
    assert "n=1" in result.output
    # unknown session has no timestamp arrow
    unknown_line = next(
        line for line in result.output.splitlines() if "session_00_unknown" in line
    )
    assert "→" not in unknown_line


def test_dry_run_sessions_preview_truncated(tmp_path: Path, monkeypatch) -> None:
    slug = "demo"
    base = datetime(2026, 6, 15, 8, 0, tzinfo=timezone.utc)
    assets = []
    sessions = []
    for i in range(1, 16):  # 15 sessions -> truncated (>12)
        sid = f"session_{i:02d}"
        assets.append(_analyzed_asset(i, session_id=sid))
        start = base + timedelta(hours=2 * i)
        sessions.append(
            Session(
                session_id=sid,
                asset_ids=[f"asset_{i}"],
                started_at=start,
                ended_at=start + timedelta(minutes=30),
                asset_count=1,
            )
        )
    _seed_with_sessions(tmp_path, slug, assets, sessions)
    monkeypatch.setattr("tripclipper.cli.EagleV2Client", FakeClient)

    runner = CliRunner()
    result = runner.invoke(main, ["sync-eagle", slug, "--base-dir", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "Sessions preview (gap=1h):" in result.output
    # head 5 + tail 5, middle omitted marker
    assert "... (5 sessions omitted) ..." in result.output
    assert "session_01" in result.output
    assert "session_15" in result.output
    # a middle session is omitted
    assert "session_08" not in result.output
