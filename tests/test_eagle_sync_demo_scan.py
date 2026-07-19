"""End-to-end tests for M6 Eagle sync driven over the REAL demo-scan cut_index.

These tests read the real ``projects/demo-scan/cut_index.json`` via the library
and drive :class:`EagleSyncRunner` against a mocked Eagle V2 backend
(``httpx.MockTransport``). No ``src/`` code is modified and nothing is ever
written back to disk (we never call ``write_cut_index``), so the on-disk
cut_index stays byte-identical across the whole run.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx

from tripclipper.cut_index import read_cut_index
from tripclipper.eagle_sync import (
    AssetMapper,
    EagleSyncRunner,
    EagleV2Client,
    SyncOptions,
    load_mapping_config,
)

DEMO_CUT_INDEX = (
    Path(__file__).parent.parent / "projects" / "demo-scan" / "cut_index.json"
)
FAILURE_FIXTURE = (
    Path(__file__).parent / "fixtures" / "eagle_sync" / "cut_index_with_failures.json"
)


class RecordingBackend:
    """Mock Eagle V2 backend that records every request for later assertions."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []  # (method, path, body)
        self.tag_groups: list[str] = []  # names passed to tagGroup/create
        self.smart_folder_list_payload: list[dict] = []
        self.smart_folder_create_payloads: list[dict] = []
        self.smart_folder_update_payloads: list[tuple[str, dict]] = []
        self._next_id = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path  # e.g. /api/v2/item/add
        body: dict = {}
        if request.content:
            try:
                body = json.loads(request.content)
            except Exception:  # noqa: BLE001 - defensive parse in test double
                body = {}
        self.calls.append((request.method, path, body))

        if path.endswith("library/info"):
            return httpx.Response(
                200,
                json={
                    "status": "success",
                    "data": {
                        "path": "/tmp/demo.library",
                        "library": "/tmp/demo.library",
                        "tagsGroups": [],
                    },
                },
            )
        if path.endswith("folder/get"):
            return httpx.Response(
                200,
                json={
                    "status": "success",
                    "data": {"data": [], "total": 0, "offset": 0, "limit": 1000},
                },
            )
        if path.endswith("folder/create"):
            self._next_id += 1
            return httpx.Response(
                200,
                json={"status": "success", "data": {"id": f"folder_{self._next_id}"}},
            )
        if path.endswith("item/get"):
            return httpx.Response(
                200,
                json={"status": "success", "data": {"folders": []}},
            )
        if path.endswith("item/add"):
            self._next_id += 1
            return httpx.Response(
                200,
                json={"status": "success", "data": {"id": f"item_{self._next_id}"}},
            )
        if path.endswith("item/update"):
            return httpx.Response(200, json={"status": "success", "data": {}})
        if path.endswith("item/moveToTrash"):
            return httpx.Response(200, json={"status": "success", "data": {}})
        if path.endswith("tagGroup/create"):
            name = body.get("name")
            self.tag_groups.append(name)
            return httpx.Response(
                200, json={"status": "success", "data": {"id": f"grp_{name}"}}
            )
        if path.endswith("tagGroup/update"):
            return httpx.Response(200, json={"status": "success", "data": {}})
        if path.endswith("smartFolder/get"):
            return httpx.Response(
                200,
                json={"status": "success", "data": self.smart_folder_list_payload},
            )
        if path.endswith("smartFolder/create"):
            self.smart_folder_create_payloads.append(body)
            return httpx.Response(
                200,
                json={
                    "status": "success",
                    "data": {"id": f"sf_{len(self.smart_folder_create_payloads)}"},
                },
            )
        if path.endswith("smartFolder/update"):
            self.smart_folder_update_payloads.append(
                (str(body.get("id") or ""), body)
            )
            return httpx.Response(200, json={"status": "success", "data": {}})
        return httpx.Response(404, json={"status": "error"})


def _make(apply: bool, **opt):
    """Build and run a sync runner over the real demo-scan cut_index.

    Note: the on-disk cut_index may have ``eagle_item_id`` populated from a
    previous *real-Eagle* apply run (M6 task 15 acceptance). To keep this
    fixture-driven test deterministic, we always start from a
    ``eagle_item_id=None`` state so the runner walks the item/add branch
    for fresh items — real-machine idempotency is covered separately by
    :func:`test_reapply_updates_not_creates`.
    """
    backend = RecordingBackend()
    client = EagleV2Client(transport=httpx.MockTransport(backend.handler))
    cut = read_cut_index(DEMO_CUT_INDEX)
    for a in cut.assets:
        a.eagle_item_id = None
        a.eagle_sync_status = None
    config = load_mapping_config()
    mapper = AssetMapper(
        config, project_slug="demo-scan", sync_timestamp="2026-06-30T00:00:00+00:00"
    )
    runner = EagleSyncRunner(client, mapper, config, SyncOptions(apply=apply, **opt))
    updated, result = runner.run(cut)
    return backend, updated, result


def _analyzed_count() -> int:
    return sum(
        1
        for a in read_cut_index(DEMO_CUT_INDEX).assets
        if a.analysis_status.value == "analyzed"
    )


def _addfrompath_bodies(backend: RecordingBackend) -> list[dict]:
    return [
        body
        for _method, path, body in backend.calls
        if path.endswith("item/add")
    ]


def test_dry_run_on_demo_scan():
    backend, _updated, result = _make(apply=False)

    # dry-run must never create items
    assert not any(p.endswith("item/add") for _m, p, _b in backend.calls)

    expected = _analyzed_count()
    assert expected == 12
    assert result.totals["synced"] == expected
    assert result.totals["total"] == expected


def test_apply_on_demo_scan_writes_expected_tags():
    backend, _updated, _result = _make(apply=True)

    bodies = _addfrompath_bodies(backend)
    assert len(bodies) == _analyzed_count()

    created_folder_names = {
        body.get("name")
        for _method, path, body in backend.calls
        if path.endswith("folder/create")
    }
    assert {"Baymax-Phone", "mydji", "我的记录仪"} <= created_folder_names

    all_tags = [tag for body in bodies for tag in body.get("tags", [])]
    assert any("tc:project:demo-scan" in body.get("tags", []) for body in bodies)
    assert "tc:project:demo-scan" in all_tags
    assert "tc:edit_candidate_status:default_selected" in all_tags
    assert "tc:analysis_status:analyzed" in all_tags

    # ratings are present on demo-scan assets, so at least one body carries a
    # star, and it must be an int mirroring the asset rating.
    starred = [body for body in bodies if "star" in body]
    assert starred, "expected at least one item/add body with a star"
    for body in starred:
        assert isinstance(body["star"], int)


def test_apply_creates_tag_groups():
    backend, _updated, _result = _make(apply=True)

    assert "tc:edit_candidate_status" in backend.tag_groups
    assert "tc:shot_function" in backend.tag_groups
    assert "tc:project" in backend.tag_groups


def test_reapply_updates_not_creates():
    backend1 = RecordingBackend()
    client1 = EagleV2Client(transport=httpx.MockTransport(backend1.handler))
    cut = read_cut_index(DEMO_CUT_INDEX)
    config = load_mapping_config()
    mapper = AssetMapper(config, "demo-scan", "2026-06-30T00:00:00+00:00")
    cut, _ = EagleSyncRunner(client1, mapper, config, SyncOptions(apply=True)).run(cut)

    # second apply on the same (now eagle_item_id-populated) cut object
    backend2 = RecordingBackend()
    client2 = EagleV2Client(transport=httpx.MockTransport(backend2.handler))
    cut, _ = EagleSyncRunner(client2, mapper, config, SyncOptions(apply=True)).run(cut)

    paths = [p for _m, p, _b in backend2.calls]
    assert any(p.endswith("item/update") for p in paths)
    assert not any(p.endswith("item/add") for p in paths)


def test_dry_run_does_not_touch_disk():
    before = DEMO_CUT_INDEX.read_bytes()
    _make(apply=False)
    after = DEMO_CUT_INDEX.read_bytes()
    assert before == after


def test_analysis_failed_fixture_synced_with_failure_note():
    backend = RecordingBackend()
    client = EagleV2Client(transport=httpx.MockTransport(backend.handler))
    cut = read_cut_index(FAILURE_FIXTURE)
    config = load_mapping_config()
    mapper = AssetMapper(
        config, project_slug="failure-fixture", sync_timestamp="2026-06-30T00:00:00+00:00"
    )
    _updated, result = EagleSyncRunner(
        client, mapper, config, SyncOptions(apply=True)
    ).run(cut)

    bodies = _addfrompath_bodies(backend)
    # both the analyzed AND the analysis_failed asset get synced
    assert len(bodies) == 2
    assert result.totals["synced"] == 2

    failed_bodies = [
        body
        for body in bodies
        if "tc:analysis_status:analysis_failed" in body.get("tags", [])
    ]
    assert len(failed_bodies) == 1
    failed_body = failed_bodies[0]
    assert "LLM timeout" in failed_body["annotation"]


def test_apply_creates_five_default_smart_folders():
    backend, _updated, result = _make(apply=True)

    assert len(backend.smart_folder_create_payloads) == 5
    assert {payload["name"] for payload in backend.smart_folder_create_payloads} == {
        "TC · demo-scan · 精选高光",
        "TC · demo-scan · 候选主选",
        "TC · demo-scan · 建议删除",
        "TC · demo-scan · 待复核",
        "TC · demo-scan · 分析失败",
    }
    assert len(result.smart_folders.created) == 5


def test_reapply_smart_folder_reconcile_all_unchanged():
    backend1, _updated1, _result1 = _make(apply=True)

    backend2 = RecordingBackend()
    backend2.smart_folder_list_payload = [
        {
            "id": f"sf_{index}",
            "name": payload["name"],
            "conditions": payload["conditions"],
            "iconColor": payload.get("iconColor"),
        }
        for index, payload in enumerate(backend1.smart_folder_create_payloads, start=1)
    ]
    client2 = EagleV2Client(transport=httpx.MockTransport(backend2.handler))
    cut2 = read_cut_index(DEMO_CUT_INDEX)
    for asset in cut2.assets:
        asset.eagle_item_id = None
        asset.eagle_sync_status = None
    config = load_mapping_config()
    mapper = AssetMapper(config, "demo-scan", "2026-06-30T00:00:00+00:00")
    _updated2, result2 = EagleSyncRunner(
        client2, mapper, config, SyncOptions(apply=True)
    ).run(cut2)

    assert backend2.smart_folder_create_payloads == []
    assert backend2.smart_folder_update_payloads == []
    assert len(result2.smart_folders.unchanged) == 5


def test_project_override_triggers_update():
    backend = RecordingBackend()
    backend.smart_folder_list_payload = [
        {
            "id": "sf_1",
            "name": "TC · demo-scan · 精选高光",
            "conditions": [
                {
                    "match": "AND",
                    "rules": [
                        {
                            "property": "tag",
                            "method": "equal",
                            "value": ["tc:project:demo-scan"],
                        },
                        {
                            "property": "tag",
                            "method": "equal",
                            "value": [
                                "tc:edit_candidate_status:default_selected"
                            ],
                        },
                        {
                            "property": "tag",
                            "method": "equal",
                            "value": ["tc:shot_function:highlight"],
                        },
                    ],
                }
            ],
            "iconColor": "green",
        }
    ]
    client = EagleV2Client(transport=httpx.MockTransport(backend.handler))
    cut = read_cut_index(DEMO_CUT_INDEX)
    for asset in cut.assets:
        asset.eagle_item_id = None
        asset.eagle_sync_status = None
    config = load_mapping_config(
        {
            "smart_folders": [
                {
                    "key": "highlights",
                    "name": "TC · {project_slug} · 精选高光",
                    "icon_color": "purple",
                    "match": "AND",
                    "rules": [
                        {
                            "property": "tag",
                            "method": "equal",
                            "value": "tc:project:{project_slug}",
                        },
                        {
                            "property": "tag",
                            "method": "equal",
                            "value": "tc:shot_function:highlight",
                        },
                    ],
                }
            ]
        }
    )
    mapper = AssetMapper(config, "demo-scan", "2026-06-30T00:00:00+00:00")
    _updated, result = EagleSyncRunner(
        client, mapper, config, SyncOptions(apply=True)
    ).run(cut)

    assert len(backend.smart_folder_update_payloads) == 1
    assert backend.smart_folder_update_payloads[0][1]["iconColor"] == "purple"
    assert result.smart_folders.updated == ["TC · demo-scan · 精选高光"]
