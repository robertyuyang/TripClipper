"""Tests for Eagle smart-folder client and planner support."""

from __future__ import annotations

import json

import httpx
import pytest

from tripclipper.eagle_sync import (
    EagleClientError,
    EagleV2Client,
    SmartFolderPlanner,
    SmartFolderPreset,
    SmartFolderRule,
)


def _client_with(handler) -> EagleV2Client:
    transport = httpx.MockTransport(handler)
    return EagleV2Client(transport=transport)


def test_smart_folder_list_returns_data_array() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/api/v2/smartFolder/get")
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": [
                    {
                        "id": "SF1",
                        "name": "TC · demo · 精选高光",
                        "conditions": [],
                        "match": "AND",
                        "iconColor": "green",
                    }
                ],
            },
        )

    result = _client_with(handler).smart_folder_list()
    assert len(result) == 1
    assert result[0]["name"] == "TC · demo · 精选高光"


def test_smart_folder_list_empty() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "success", "data": []})

    assert _client_with(handler).smart_folder_list() == []


def test_smart_folder_list_unwraps_paginated_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": {
                    "data": [
                        {
                            "id": "SF1",
                            "name": "TC · demo · 精选高光",
                            "conditions": [],
                            "match": "AND",
                        }
                    ],
                    "total": 1,
                    "offset": 0,
                    "limit": 50,
                },
            },
        )

    result = _client_with(handler).smart_folder_list()
    assert len(result) == 1
    assert result[0]["id"] == "SF1"


def test_smart_folder_create_returns_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/api/v2/smartFolder/create")
        return httpx.Response(
            200, json={"status": "success", "data": {"id": "SF_UUID"}}
        )

    assert (
        _client_with(handler).smart_folder_create(
            {"name": "x", "conditions": []}
        )
        == "SF_UUID"
    )


def test_smart_folder_create_5xx_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"status": "error"})

    with pytest.raises(EagleClientError):
        _client_with(handler).smart_folder_create({"name": "x", "conditions": []})


def test_smart_folder_update_sends_id_in_body() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode("utf-8"))
        assert request.url.path.endswith("/api/v2/smartFolder/update")
        return httpx.Response(200, json={"status": "success"})

    _client_with(handler).smart_folder_update("XX", {"name": "renamed"})
    assert captured["body"]["id"] == "XX"
    assert captured["body"]["name"] == "renamed"


def test_smart_folder_update_no_return() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "success"})

    _client_with(handler).smart_folder_update("XX", {})


def _preset(
    key: str,
    name: str,
    rules: list[tuple[str, str, str]],
    *,
    icon: str | None = "green",
    match: str = "AND",
) -> SmartFolderPreset:
    return SmartFolderPreset(
        key=key,
        name=name,
        icon_color=icon,
        match=match,
        rules=tuple(
            SmartFolderRule(property=prop, method=method, value=value)
            for prop, method, value in rules
        ),
    )


class _StubClient:
    def __init__(
        self,
        *,
        existing: list[dict] | None = None,
        create_error_on: set[str] | None = None,
        update_error_on: set[str] | None = None,
    ) -> None:
        self.existing = existing or []
        self.create_calls: list[dict] = []
        self.update_calls: list[tuple[str, dict]] = []
        self.create_error_on = create_error_on or set()
        self.update_error_on = update_error_on or set()

    def smart_folder_list(self) -> list[dict]:
        return list(self.existing)

    def smart_folder_create(self, payload: dict) -> str:
        self.create_calls.append(payload)
        if payload["name"] in self.create_error_on:
            raise EagleClientError(stage="smart_folder_create", http_status=500)
        return "new-smart-folder-id"

    def smart_folder_update(self, folder_id: str, payload: dict) -> None:
        self.update_calls.append((folder_id, payload))
        if payload["name"] in self.update_error_on:
            raise EagleClientError(stage="smart_folder_update", http_status=500)


def test_render_payload_substitutes_slug() -> None:
    preset = _preset(
        "highlights",
        "TC · {project_slug} · 精选",
        [("tag", "equal", "tc:project:{project_slug}")],
    )
    payload = SmartFolderPlanner(_StubClient(), (preset,), "demo-scan").render_payload(
        preset
    )
    assert payload["name"] == "TC · demo-scan · 精选"
    assert payload["conditions"][0]["rules"][0]["value"] == ["tc:project:demo-scan"]


def test_render_payload_wraps_value_as_array() -> None:
    preset = _preset("h", "TC · x", [("tag", "equal", "tc:project:demo")])
    payload = SmartFolderPlanner(_StubClient(), (preset,), "demo").render_payload(
        preset
    )
    assert payload["conditions"][0]["rules"][0]["value"] == ["tc:project:demo"]


def test_reconcile_all_new_creates() -> None:
    p1 = _preset("h", "TC · demo · A", [("tag", "equal", "tc:x")])
    p2 = _preset("d", "TC · demo · B", [("tag", "equal", "tc:y")])
    stub = _StubClient(existing=[])
    result = SmartFolderPlanner(stub, (p1, p2), "demo").reconcile()
    assert len(stub.create_calls) == 2
    assert result.created == ["TC · demo · A", "TC · demo · B"]
    assert result.updated == []
    assert result.unchanged == []


def test_reconcile_unchanged_when_conditions_match() -> None:
    preset = _preset(
        "h",
        "TC · demo · A",
        [("tag", "equal", "tc:x"), ("tag", "equal", "tc:y")],
    )
    existing_conditions = [
        {
            "match": "AND",
            "rules": [
                {"property": "tag", "method": "equal", "value": ["tc:y"]},
                {"property": "tag", "method": "equal", "value": ["tc:x"]},
            ],
        }
    ]
    stub = _StubClient(
        existing=[{"id": "SF1", "name": "TC · demo · A", "conditions": existing_conditions}]
    )
    result = SmartFolderPlanner(stub, (preset,), "demo").reconcile()
    assert stub.create_calls == []
    assert stub.update_calls == []
    assert result.unchanged == ["TC · demo · A"]


def test_reconcile_update_when_conditions_differ() -> None:
    preset = _preset(
        "h",
        "TC · demo · A",
        [("tag", "equal", "tc:x"), ("tag", "equal", "tc:y")],
    )
    existing_conditions = [
        {
            "match": "AND",
            "rules": [{"property": "tag", "method": "equal", "value": ["tc:x"]}],
        }
    ]
    stub = _StubClient(
        existing=[{"id": "SF1", "name": "TC · demo · A", "conditions": existing_conditions}]
    )
    result = SmartFolderPlanner(stub, (preset,), "demo").reconcile()
    assert len(stub.update_calls) == 1
    assert stub.update_calls[0][0] == "SF1"
    assert result.updated == ["TC · demo · A"]


def test_reconcile_ignores_user_smart_folders() -> None:
    preset = _preset("h", "TC · demo · A", [("tag", "equal", "tc:x")])
    stub = _StubClient(existing=[{"id": "USER", "name": "我的收藏", "conditions": []}])
    result = SmartFolderPlanner(stub, (preset,), "demo").reconcile()
    assert result.created == ["TC · demo · A"]
    assert stub.update_calls == []


def test_reconcile_single_failure_becomes_warning() -> None:
    p1 = _preset("h", "TC · demo · A", [("tag", "equal", "tc:x")])
    p2 = _preset("d", "TC · demo · B", [("tag", "equal", "tc:y")])
    stub = _StubClient(existing=[], create_error_on={"TC · demo · A"})
    result = SmartFolderPlanner(stub, (p1, p2), "demo").reconcile()
    assert result.created == ["TC · demo · B"]
    assert len(result.warnings) == 1
    assert result.warnings[0].name == "TC · demo · A"


def test_conditions_equal_semantic_ignores_order() -> None:
    planner = SmartFolderPlanner(_StubClient(), (), "demo")
    left = [
        {
            "match": "AND",
            "rules": [
                {"property": "tag", "method": "equal", "value": ["x"]},
                {"property": "tag", "method": "equal", "value": ["y"]},
            ],
        }
    ]
    right = [
        {
            "match": "AND",
            "rules": [
                {"property": "tag", "method": "equal", "value": ["y"]},
                {"property": "tag", "method": "equal", "value": ["x"]},
            ],
        }
    ]
    assert planner._conditions_equal(left, right) is True
