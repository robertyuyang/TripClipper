"""Tests for the sync runner (Layer 4) using httpx.MockTransport."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx

from tripclipper.eagle_sync import (
    AssetMapper,
    EagleSyncRunner,
    EagleApplyResult,
    EagleV2Client,
    SmartFolderReconcileResult,
    SmartFolderWarning,
    SyncOptions,
    SyncPreconditionError,
    eagle_item_name,
    load_mapping_config,
    session_folder_name,
)
from tripclipper.models import (
    AnalysisStatus,
    Asset,
    CutIndex,
    EditCandidateStatus,
    ProjectInfo,
    Session,
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
        self.folder_create_count = 0
        self.folder_names: list[str] = []
        self.folder_create_bodies: list[dict] = []
        self.folder_tree: list[dict] = []
        self.addfrompath_folder_ids: list[list[str]] = []
        self.item_folders: dict[str, list[str]] = {}
        self.item_update_bodies: list[dict] = []
        self.smart_folder_list_payload: list[dict] = []
        self.smart_folder_create_calls: list[dict] = []
        self.smart_folder_update_calls: list[tuple[str, dict]] = []
        self.fail_smart_folder_create_on: set[str] = set()
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
        if path.endswith("item/add"):
            self.addfrompath_count += 1
            body = json.loads(request.content.decode("utf-8"))
            self.addfrompath_folder_ids.append(body.get("folders", []))
            if self.connect_error_addfrompath:
                raise httpx.ConnectError("refused", request=request)
            if self.addfrompath_count in self.fail_addfrompath_on:
                return httpx.Response(500, text="boom")
            new_id = f"item-{self.addfrompath_count}"
            return httpx.Response(
                200, json={"status": "success", "data": {"id": new_id}}
            )
        if path.endswith("folder/create"):
            self.folder_create_count += 1
            body = json.loads(request.content.decode("utf-8"))
            self.folder_names.append(body.get("name", ""))
            self.folder_create_bodies.append(body)
            return httpx.Response(
                200,
                json={
                    "status": "success",
                    "data": {"id": f"folder-{self.folder_create_count}"},
                },
            )
        if path.endswith("folder/get"):
            return httpx.Response(
                200,
                json={
                    "status": "success",
                    "data": {
                        "data": self.folder_tree,
                        "total": len(self.folder_tree),
                        "offset": 0,
                        "limit": 1000,
                    },
                },
            )
        if path.endswith("item/get"):
            item_id = request.url.params.get("id", "")
            return httpx.Response(
                200,
                json={
                    "status": "success",
                    "data": {
                        "id": item_id,
                        "folders": self.item_folders.get(item_id, []),
                    },
                },
            )
        if path.endswith("smartFolder/get"):
            return httpx.Response(
                200,
                json={"status": "success", "data": self.smart_folder_list_payload},
            )
        if path.endswith("smartFolder/create"):
            body = json.loads(request.content.decode("utf-8"))
            self.smart_folder_create_calls.append(body)
            if body.get("name") in self.fail_smart_folder_create_on:
                return httpx.Response(500, text="smart folder boom")
            return httpx.Response(
                200,
                json={"status": "success", "data": {"id": "sf-created"}},
            )
        if path.endswith("smartFolder/update"):
            body = json.loads(request.content.decode("utf-8"))
            self.smart_folder_update_calls.append((str(body.get("id") or ""), body))
            return httpx.Response(200, json={"status": "success", "data": None})
        if path.endswith("item/update"):
            self.item_update_bodies.append(json.loads(request.content.decode("utf-8")))
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

    assert not _called(rec, "item/add")
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


def test_mapper_uses_descriptive_name_only_for_analyzed_video() -> None:
    mapper = _runner(_make_client(Recorder()), SyncOptions(apply=False)).mapper
    video = _analyzed(
        filename="DJI_20260612134026_0001_D.MP4",
        path="/x/DJI_20260612134026_0001_D.MP4",
        type="video",
        content_title="海边日落下两人并肩散步",
    )
    image = _analyzed(
        filename="IMG_0001.JPG",
        path="/x/IMG_0001.JPG",
        type="image",
        content_title="海边日落",
    )

    assert (
        mapper.plan(video).item_name
        == "DJI_20260612134026_0001_D__海边日落下两人并肩散步.MP4"
    )
    assert mapper.plan(image).item_name == "IMG_0001.JPG"


def test_mapper_does_not_turn_content_title_into_unique_tag() -> None:
    mapper = _runner(_make_client(Recorder()), SyncOptions(apply=False)).mapper
    asset = _analyzed(
        filename="clip.mp4",
        type="video",
        content_title="海边两人散步",
    )

    plan = mapper.plan(asset)

    assert not any(tag.startswith("tc:content_title:") for tag in plan.tags)


def test_eagle_item_name_cleans_unsafe_title_characters() -> None:
    asset = _analyzed(
        filename="clip.MP4",
        type="video",
        content_title="  女孩/海边:奔跑?\n  ",
    )

    assert eagle_item_name(asset) == "clip__女孩-海边-奔跑.MP4"


def test_eagle_item_name_marks_unanalyzed_and_failed_video() -> None:
    scanned = _analyzed(
        filename="clip.mp4",
        type="video",
        analysis_status=AnalysisStatus.scanned,
    )
    failed = _analyzed(
        filename="clip.mp4",
        type="video",
        analysis_status=AnalysisStatus.analysis_failed,
    )

    assert eagle_item_name(scanned) == "clip__未分析.mp4"
    assert eagle_item_name(failed) == "clip__分析失败.mp4"


def test_eagle_item_name_keeps_old_analyzed_video_name_without_title() -> None:
    asset = _analyzed(filename="clip.mp4", type="video")

    assert eagle_item_name(asset) == "clip.mp4"


def test_eagle_item_name_truncates_only_title_to_safe_utf8_length() -> None:
    asset = _analyzed(
        filename="DJI_0001.MP4",
        type="video",
        content_title="海" * 200,
    )

    name = eagle_item_name(asset)

    assert len(name.encode("utf-8")) <= 240
    assert name.startswith("DJI_0001__")
    assert name.endswith(".MP4")


def test_apply_update_existing() -> None:
    rec = Recorder()
    asset = _analyzed(asset_id="a1", eagle_item_id="existing-1")
    cut = _cut_index([asset])
    _runner(_make_client(rec), SyncOptions(apply=True)).run(cut)

    assert _called(rec, "item/update")
    assert not _called(rec, "item/add")


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
    assert not _called(rec, "item/add")


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
    # Item id was cleared then re-created via item/add.
    assert _called(rec, "item/add")
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


# ---------------------------------------------------------------------------
# Project folder tree: original source hierarchy + session hierarchy
# ---------------------------------------------------------------------------

_S1_START = datetime(2026, 6, 15, 9, 30, tzinfo=timezone.utc)
_S2_START = datetime(2026, 6, 15, 14, 20, tzinfo=timezone.utc)


def _cut_with_sessions(assets: list[Asset], sessions: list[Session]) -> CutIndex:
    return CutIndex(
        project=ProjectInfo(project_slug=SLUG), assets=assets, sessions=sessions
    )


def test_new_items_share_source_and_session_folder_views() -> None:
    rec = Recorder()
    assets = [
        _analyzed(
            asset_id="a1",
            relative_path="无人机/远景/a1.mp4",
            session_id="session_01",
        ),
        _analyzed(
            asset_id="a2",
            relative_path="无人机/远景/a2.mp4",
            session_id="session_01",
        ),
    ]
    sessions = [
        Session(session_id="session_01", asset_ids=["a1", "a2"], started_at=_S1_START),
    ]
    cut = _cut_with_sessions(assets, sessions)
    _runner(_make_client(rec), SyncOptions(apply=True)).run(cut)

    _s1 = _S1_START.astimezone().strftime("%Y-%m-%d %H:%M")
    assert rec.folder_names == [
        f"TripClipper · {SLUG}",
        "按原始目录",
        "无人机",
        "远景",
        "按拍摄批次",
        f"session_01 · {_s1}",
    ]
    assert rec.folder_create_bodies == [
        {"name": f"TripClipper · {SLUG}"},
        {"name": "按原始目录", "parent": "folder-1"},
        {"name": "无人机", "parent": "folder-2"},
        {"name": "远景", "parent": "folder-3"},
        {"name": "按拍摄批次", "parent": "folder-1"},
        {"name": f"session_01 · {_s1}", "parent": "folder-5"},
    ]
    # 两个展示位置指向同一 Eagle item，而不是导入两个副本。
    assert rec.addfrompath_count == 2
    assert rec.addfrompath_folder_ids == [
        ["folder-4", "folder-6"],
        ["folder-4", "folder-6"],
    ]


def test_missing_session_uses_unknown_bucket_and_root_file_uses_source_branch() -> None:
    rec = Recorder()
    assets = [_analyzed(asset_id="a1", relative_path="a.mp4")]
    cut = _cut_index(assets)
    _runner(_make_client(rec), SyncOptions(apply=True)).run(cut)

    assert rec.folder_names == [
        f"TripClipper · {SLUG}",
        "按原始目录",
        "按拍摄批次",
        "未识别批次",
    ]
    assert rec.addfrompath_folder_ids == [["folder-2", "folder-4"]]


def test_existing_item_reconciles_managed_folders_and_preserves_user_folders() -> None:
    rec = Recorder()
    _s2 = _S2_START.astimezone().strftime("%Y-%m-%d %H:%M")
    rec.folder_tree = [
        {
            "id": "managed-root",
            "name": f"TripClipper · {SLUG}",
            "children": [
                {
                    "id": "source-root",
                    "name": "按原始目录",
                    "children": [
                        {"id": "old-source", "name": "旧目录", "children": []},
                        {"id": "new-source", "name": "新目录", "children": []},
                    ],
                },
                {
                    "id": "session-root",
                    "name": "按拍摄批次",
                    "children": [
                        {"id": "old-session", "name": "session_01", "children": []},
                        {
                            "id": "new-session",
                            "name": f"session_02 · {_s2}",
                            "children": [],
                        },
                    ],
                },
            ],
        }
    ]
    rec.item_folders["existing-1"] = ["user-folder", "old-source", "old-session"]
    assets = [
        _analyzed(
            asset_id="a1",
            relative_path="新目录/a.mp4",
            session_id="session_02",
            eagle_item_id="existing-1",
        ),
    ]
    sessions = [
        Session(session_id="session_02", asset_ids=["a1"], started_at=_S2_START),
    ]
    cut = _cut_with_sessions(assets, sessions)
    _runner(_make_client(rec), SyncOptions(apply=True)).run(cut)

    assert rec.folder_create_count == 0
    assert rec.item_update_bodies[0]["folders"] == [
        "user-folder",
        "new-source",
        "new-session",
    ]


def test_unknown_session_folder_has_no_time() -> None:
    session = Session(session_id="session_00_unknown", asset_ids=["a1"])
    assert session_folder_name(SLUG, session) == "未识别批次"


def test_timed_session_folder_name_format() -> None:
    session = Session(session_id="session_01", asset_ids=["a1"], started_at=_S1_START)
    expected_time = _S1_START.astimezone().strftime("%Y-%m-%d %H:%M")
    assert session_folder_name(SLUG, session) == f"session_01 · {expected_time}"


def test_result_omits_smart_folders_when_none() -> None:
    result = EagleApplyResult(
        synced_at="2026-07-02T00:00:00Z",
        project_slug="demo",
        eagle_library_path=None,
        totals={"total": 0, "synced": 0, "failed": 0, "skipped": 0, "skipped_unanalyzed": 0},
        failures=[],
        tag_group_warnings=[],
        aborted=False,
        abort_reason=None,
        folder_warnings=[],
        smart_folders=None,
    )
    payload = result.to_dict()
    assert "smart_folders" not in payload


def test_result_serializes_smart_folder_warnings() -> None:
    smart_folders = SmartFolderReconcileResult(
        created=["TC · demo · A"],
        warnings=[
            SmartFolderWarning(
                key="excluded", name="TC · demo · X", error="HTTP 500"
            )
        ],
    )
    result = EagleApplyResult(
        synced_at="t",
        project_slug="demo",
        eagle_library_path=None,
        totals={"total": 0, "synced": 0, "failed": 0, "skipped": 0, "skipped_unanalyzed": 0},
        failures=[],
        tag_group_warnings=[],
        aborted=False,
        abort_reason=None,
        folder_warnings=[],
        smart_folders=smart_folders,
    )
    payload = result.to_dict()
    assert payload["smart_folders"]["created"] == ["TC · demo · A"]
    assert payload["smart_folders"]["warnings"][0]["key"] == "excluded"


def test_apply_runs_smart_folder_reconcile() -> None:
    rec = Recorder()
    assets = [_analyzed(asset_id="a1")]
    cut = _cut_index(assets)
    _, result = _runner(_make_client(rec), SyncOptions(apply=True)).run(cut)

    assert result.smart_folders is not None
    assert len(rec.smart_folder_create_calls) == 5


def test_dry_run_skips_smart_folder_reconcile() -> None:
    rec = Recorder()
    assets = [_analyzed(asset_id="a1")]
    cut = _cut_index(assets)
    _, result = _runner(_make_client(rec), SyncOptions(apply=False)).run(cut)

    assert result.smart_folders is None
    assert rec.smart_folder_create_calls == []


def test_no_smart_folders_flag_skips_stage() -> None:
    rec = Recorder()
    assets = [_analyzed(asset_id="a1")]
    cut = _cut_index(assets)
    _, result = _runner(
        _make_client(rec), SyncOptions(apply=True, no_smart_folders=True)
    ).run(cut)

    assert result.smart_folders is None
    assert "smart_folders" not in result.to_dict()
    assert rec.smart_folder_create_calls == []


def test_aborted_sync_records_smart_folder_skip_warning() -> None:
    rec = Recorder()
    rec.connect_error_addfrompath = True
    assets = [_analyzed(asset_id=f"a{i}") for i in range(6)]
    cut = _cut_index(assets)
    _, result = _runner(_make_client(rec), SyncOptions(apply=True)).run(cut)

    assert result.aborted is True
    assert result.smart_folders is not None
    assert len(result.smart_folders.warnings) == 1
    assert result.smart_folders.warnings[0].key == "_all"
    assert "skipped due to aborted sync" in result.smart_folders.warnings[0].error
    assert rec.smart_folder_create_calls == []
