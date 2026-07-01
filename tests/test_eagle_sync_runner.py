"""Tests for the sync runner (Layer 4) using httpx.MockTransport."""

from __future__ import annotations

import httpx

from tripclipper.eagle_sync import (
    AssetMapper,
    EagleSyncRunner,
    EagleV2Client,
    SyncOptions,
    SyncPreconditionError,
    load_mapping_config,
)
from tripclipper.models import (
    AnalysisStatus,
    Asset,
    CutIndex,
    EditCandidateStatus,
    ProjectInfo,
)

SLUG = "2026-japan-trip"
TS = "2026-06-30T14:23:11+09:00"


def _cut_index(assets: list[Asset]) -> CutIndex:
    return CutIndex(project=ProjectInfo(project_slug=SLUG), assets=assets)


def _runner(client: EagleV2Client, options: SyncOptions) -> EagleSyncRunner:
    config = load_mapping_config()
    mapper = AssetMapper(config, SLUG, TS)
    return EagleSyncRunner(client, mapper, config, options)


class Recorder:
    """Records API calls and drives configurable responses."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.addfrompath_count = 0
        # path suffix -> callable(request, count) -> httpx.Response
        self.fail_addfrompath_on: set[int] = set()
        self.connect_error_addfrompath = False
        self.error_on_taggroup = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append(path)

        if path.endswith("library/info"):
            return httpx.Response(
                200,
                json={
                    "status": "success",
                    "data": {
                        "path": "/tmp/Lib",
                        "library": "/tmp/Lib",
                        "tagsGroups": [],
                    },
                },
            )
        if path.endswith("item/addFromPath"):
            self.addfrompath_count += 1
            if self.connect_error_addfrompath:
                raise httpx.ConnectError("refused", request=request)
            if self.addfrompath_count in self.fail_addfrompath_on:
                return httpx.Response(500, text="boom")
            new_id = f"item-{self.addfrompath_count}"
            return httpx.Response(
                200, json={"status": "success", "data": {"id": new_id}}
            )
        if path.endswith("item/update"):
            return httpx.Response(200, json={"status": "success", "data": None})
        if path.endswith("item/moveToTrash"):
            return httpx.Response(200, json={"status": "success", "data": None})
        if path.endswith("tagGroup/create") or path.endswith("tagGroup/update"):
            if self.error_on_taggroup:
                return httpx.Response(500, text="taggroup boom")
            return httpx.Response(
                200, json={"status": "success", "data": {"id": "grp-x"}}
            )
        return httpx.Response(200, json={"status": "success", "data": None})


def _make_client(rec: Recorder) -> EagleV2Client:
    return EagleV2Client(transport=httpx.MockTransport(rec.handler))


def _called(rec: Recorder, suffix: str) -> bool:
    return any(path.endswith(suffix) for path in rec.calls)


def _analyzed(**kwargs) -> Asset:
    kwargs.setdefault("analysis_status", AnalysisStatus.analyzed)
    kwargs.setdefault("filename", "a.mp4")
    kwargs.setdefault("path", "/x/a.mp4")
    kwargs.setdefault("edit_candidate_status", EditCandidateStatus.default_selected)
    return Asset(**kwargs)


def test_dry_run_no_write() -> None:
    rec = Recorder()
    assets = [_analyzed(asset_id="a1"), _analyzed(asset_id="a2")]
    cut = _cut_index(assets)
    _, result = _runner(_make_client(rec), SyncOptions(apply=False)).run(cut)

    assert not _called(rec, "item/addFromPath")
    assert all(a.eagle_item_id is None for a in assets)
    assert result.totals["synced"] == 2


def test_apply_full_success() -> None:
    rec = Recorder()
    assets = [_analyzed(asset_id=f"a{i}") for i in range(3)]
    cut = _cut_index(assets)
    _, result = _runner(_make_client(rec), SyncOptions(apply=True)).run(cut)

    assert rec.addfrompath_count == 3
    assert all(a.eagle_sync_status == "synced" for a in assets)
    assert result.totals["synced"] == 3


def test_apply_update_existing() -> None:
    rec = Recorder()
    asset = _analyzed(asset_id="a1", eagle_item_id="existing-1")
    cut = _cut_index([asset])
    _runner(_make_client(rec), SyncOptions(apply=True)).run(cut)

    assert _called(rec, "item/update")
    assert not _called(rec, "item/addFromPath")


def test_skip_synced_flag() -> None:
    rec = Recorder()
    synced = _analyzed(
        asset_id="a1", eagle_item_id="existing-1", eagle_sync_status="synced"
    )
    fresh = _analyzed(asset_id="a2")
    cut = _cut_index([synced, fresh])
    _, result = _runner(
        _make_client(rec), SyncOptions(apply=True, skip_synced=True)
    ).run(cut)

    assert result.totals["skipped"] >= 1
    # The synced asset should not be updated.
    assert not _called(rec, "item/update")
    assert rec.addfrompath_count == 1


def test_scanned_hard_abort() -> None:
    rec = Recorder()
    assets = [_analyzed(asset_id="a1", analysis_status=AnalysisStatus.scanned)]
    cut = _cut_index(assets)
    runner = _runner(_make_client(rec), SyncOptions(apply=True))
    try:
        runner.run(cut)
        raise AssertionError("expected SyncPreconditionError")
    except SyncPreconditionError:
        pass
    assert not _called(rec, "item/addFromPath")


def test_scanned_soft_skip() -> None:
    rec = Recorder()
    scanned = _analyzed(asset_id="a1", analysis_status=AnalysisStatus.scanned)
    cut = _cut_index([scanned])
    _, result = _runner(
        _make_client(rec), SyncOptions(apply=True, skip_unanalyzed=True)
    ).run(cut)
    assert result.totals["skipped_unanalyzed"] == 1


def test_analysis_failed_included() -> None:
    rec = Recorder()
    asset = _analyzed(
        asset_id="a1", analysis_status=AnalysisStatus.analysis_failed
    )
    cut = _cut_index([asset])
    _runner(_make_client(rec), SyncOptions(apply=True)).run(cut)

    assert asset.eagle_sync_status == "synced"
    assert "tc:analysis_status:analysis_failed" in _runner(
        _make_client(Recorder()), SyncOptions(apply=True)
    ).mapper.plan(asset).tags


def test_single_business_failure_continues() -> None:
    rec = Recorder()
    rec.fail_addfrompath_on = {2}  # only the 2nd addFromPath fails
    assets = [_analyzed(asset_id=f"a{i}") for i in range(3)]
    cut = _cut_index(assets)
    _, result = _runner(_make_client(rec), SyncOptions(apply=True)).run(cut)

    assert result.totals["failed"] == 1
    assert result.totals["synced"] == 2
    assert len(result.failures) == 1


def test_five_consecutive_network_failures_abort() -> None:
    rec = Recorder()
    rec.connect_error_addfrompath = True
    assets = [_analyzed(asset_id=f"a{i}") for i in range(6)]
    cut = _cut_index(assets)
    _, result = _runner(_make_client(rec), SyncOptions(apply=True)).run(cut)

    assert result.aborted is True
    assert "eagle_disconnected" in result.abort_reason


def test_reset_moves_to_trash() -> None:
    rec = Recorder()
    asset = _analyzed(
        asset_id="a1", eagle_item_id="existing-1", eagle_sync_status="synced"
    )
    cut = _cut_index([asset])
    _runner(
        _make_client(rec), SyncOptions(apply=True, reset=True)
    ).run(cut)

    assert _called(rec, "item/moveToTrash")
    # Item id was cleared then re-created via addFromPath.
    assert _called(rec, "item/addFromPath")
    assert asset.eagle_item_id == "item-1"


def test_tag_group_maintained() -> None:
    rec = Recorder()
    assets = [
        _analyzed(
            asset_id="a1",
            edit_candidate_status=EditCandidateStatus.default_selected,
        ),
        _analyzed(
            asset_id="a2", edit_candidate_status=EditCandidateStatus.excluded
        ),
    ]
    cut = _cut_index(assets)
    _runner(_make_client(rec), SyncOptions(apply=True)).run(cut)

    assert _called(rec, "tagGroup/create") or _called(rec, "tagGroup/update")


def test_tag_group_failure_warning_only() -> None:
    rec = Recorder()
    rec.error_on_taggroup = True
    assets = [_analyzed(asset_id="a1"), _analyzed(asset_id="a2")]
    cut = _cut_index(assets)
    _, result = _runner(_make_client(rec), SyncOptions(apply=True)).run(cut)

    # Main sync still succeeds.
    assert result.totals["synced"] == 2
    assert result.tag_group_warnings
