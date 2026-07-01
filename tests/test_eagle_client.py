"""Tests for the Eagle V2 client (Layer 1) using httpx.MockTransport."""

from __future__ import annotations

import json

import httpx
import pytest

from tripclipper.eagle_sync import (
    EagleClientError,
    EagleUnavailableError,
    EagleV2Client,
    EagleVersionError,
)


def _client(handler) -> EagleV2Client:
    return EagleV2Client(transport=httpx.MockTransport(handler))


def test_health_check_ok() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("library/info")
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": {"library": "/tmp/Lib", "tagsGroups": []},
            },
        )

    with _client(handler) as client:
        data = client.health_check()
    assert data["library"] == "/tmp/Lib"


def test_fetch_library_normalises_tag_groups() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("library/info")
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": {
                    "path": "/tmp/lib.library",
                    "tagsGroups": [
                        {"id": "g1", "name": "tc:project", "tags": ["tc:project:x"]},
                        {"id": "g2", "name": "other", "tags": []},
                    ],
                },
            },
        )

    with _client(handler) as client:
        info = client.fetch_library()

    assert info["path"] == "/tmp/lib.library"
    assert info["tag_groups"] == [
        {"id": "g1", "name": "tc:project", "tags": ["tc:project:x"]},
        {"id": "g2", "name": "other", "tags": []},
    ]


def test_fetch_library_falls_back_to_library_field() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"status": "success", "data": {"library": "/tmp/legacy.library"}},
        )

    with _client(handler) as client:
        info = client.fetch_library()

    assert info["path"] == "/tmp/legacy.library"
    assert info["tag_groups"] == []


def test_client_tolerates_old_base_url_with_api_v2_suffix() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        # Old configs used ``/api/v2/`` as base_url; we still need to end up
        # calling the correct hybrid paths (``/api/v2/library/info``,
        # ``/api/item/addFromPath``).
        assert request.url.path.endswith("library/info")
        assert "/api/v2/" in request.url.path
        return httpx.Response(
            200, json={"status": "success", "data": {"library": "/tmp/L"}}
        )

    client = EagleV2Client(
        base_url="http://localhost:41595/api/v2/",
        transport=httpx.MockTransport(handler),
    )
    with client:
        client.health_check()


def test_token_appended_as_query_param() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(
            200, json={"status": "success", "data": {"library": "/tmp/L"}}
        )

    client = EagleV2Client(
        api_token="secret-token",
        transport=httpx.MockTransport(handler),
    )
    with client:
        client.health_check()

    assert "token=secret-token" in seen["url"]


def test_health_check_v1_only() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    with _client(handler) as client:
        with pytest.raises(EagleVersionError) as excinfo:
            client.health_check()
    assert "Eagle V2 API" in str(excinfo.value)


def test_health_check_connection_refused() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with _client(handler) as client:
        with pytest.raises(EagleUnavailableError):
            client.health_check()


def test_add_from_path_returns_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("item/addFromPath")
        return httpx.Response(
            200, json={"status": "success", "data": {"id": "UUID-123"}}
        )

    with _client(handler) as client:
        item_id = client.add_from_path(
            "/x/a.mp4", "a.mp4", ["tc:project:p"], 5, "note"
        )
    assert item_id == "UUID-123"


def test_update_item_omits_none_fields() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={"status": "success", "data": None})

    with _client(handler) as client:
        client.update_item("item-1", tags=["a"], rating=None, annotation=None)

    body = captured["body"]
    assert body["id"] == "item-1"
    assert "tags" in body
    assert body["tags"] == ["a"]
    assert "star" not in body
    assert "annotation" not in body


def test_move_to_trash_batch() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={"status": "success", "data": None})

    with _client(handler) as client:
        client.move_to_trash(["id1", "id2"])

    assert captured["body"] == {"itemIds": ["id1", "id2"]}


def test_tag_group_update_overwrites_tags() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={"status": "success", "data": None})

    with _client(handler) as client:
        client.tag_group_update("grp-1", tags=["tc:x:a", "tc:x:b"])

    assert captured["path"].endswith("tagGroup/update")
    body = captured["body"]
    assert body["id"] == "grp-1"
    assert body["tags"] == ["tc:x:a", "tc:x:b"]
    # No newTags field: this endpoint overwrites, not appends.
    assert "newTags" not in body


def test_tag_group_remove_batch() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={"status": "success", "data": None})

    with _client(handler) as client:
        client.tag_group_remove(["g1", "g2", "g3"])

    assert captured["path"].endswith("tagGroup/remove")
    # Eagle's remove endpoint reuses the ``itemIds`` key for group ids.
    assert captured["body"] == {"itemIds": ["g1", "g2", "g3"]}


def test_business_error_status_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "error", "data": None})

    with _client(handler) as client:
        with pytest.raises(EagleClientError):
            client.add_from_path("/x", "x", [], None, "")
