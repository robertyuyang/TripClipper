"""Contract tests for rough-cut and Jianying fixture files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ROUGH_FIXTURES = ROOT / "tests" / "fixtures" / "roughcut"
JIANYING_FIXTURES = ROOT / "tests" / "fixtures" / "jianying"
MEDIA_FIXTURES = ROOT / "tests" / "fixtures" / "media"


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _walk_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        found: list[str] = []
        for item in value:
            found.extend(_walk_strings(item))
        return found
    if isinstance(value, dict):
        found = []
        for item in value.values():
            found.extend(_walk_strings(item))
        return found
    return []


def test_fixture_json_files_exist_and_are_portable() -> None:
    fixture_paths = [
        ROUGH_FIXTURES / "minimal_cut_index.json",
        ROUGH_FIXTURES / "minimal_rough_cut_plan.json",
        ROUGH_FIXTURES / "legacy_eval_rough_cut_source.json",
        JIANYING_FIXTURES / "realistic_draft_content.json",
    ]

    for path in fixture_paths:
        payload = _load_json(path)
        assert "/Users/bytedance/" not in json.dumps(payload, ensure_ascii=False)


def test_minimal_cut_index_covers_video_image_and_audio_assets() -> None:
    payload = _load_json(ROUGH_FIXTURES / "minimal_cut_index.json")
    asset_types = {asset["type"] for asset in payload["assets"]}

    assert payload["schema_version"] == "0.3"
    assert {"video", "image", "audio"}.issubset(asset_types)
    assert len([asset for asset in payload["assets"] if asset["type"] == "video"]) >= 2
    assert payload["default_candidates"]


def test_minimal_plan_covers_timeline_contract() -> None:
    payload = _load_json(ROUGH_FIXTURES / "minimal_rough_cut_plan.json")
    timeline = payload["timeline"]
    track_types = {segment["track_type"] for segment in timeline}

    assert payload["schema_version"] == "0.1"
    assert track_types == {"video", "image", "audio", "text"}
    assert not {"text_overlays", "bgm", "transitions"} & payload.keys()

    for segment in timeline:
        if segment["track_type"] in {"video", "audio"}:
            assert "source_range" in segment
        else:
            assert "source_range" not in segment

        if segment["track_type"] == "text":
            assert "text_overlay" in segment
        else:
            assert "text_overlay" not in segment


def test_fixture_media_paths_resolve_inside_repo() -> None:
    payloads = [
        _load_json(ROUGH_FIXTURES / "minimal_cut_index.json"),
        _load_json(ROUGH_FIXTURES / "minimal_rough_cut_plan.json"),
        _load_json(ROUGH_FIXTURES / "legacy_eval_rough_cut_source.json"),
        _load_json(JIANYING_FIXTURES / "realistic_draft_content.json"),
    ]
    media_strings = [
        value
        for payload in payloads
        for value in _walk_strings(payload)
        if value.startswith("tests/fixtures/media/")
    ]

    assert media_strings
    for media_path in media_strings:
        assert (ROOT / media_path).exists(), media_path
    assert any(MEDIA_FIXTURES.iterdir())


def test_minimal_template_draft_contains_installer_shell_files() -> None:
    template = JIANYING_FIXTURES / "minimal_template_draft"
    required = [
        template / "project.json",
        template / "timeline_layout.json",
        template / "draft_meta_info.json",
        template / "Timelines" / "template_timeline_id" / "draft_content.json",
        template / "Timelines" / "template_timeline_id" / "draft_content.json.bak",
        template / "Timelines" / "template_timeline_id" / "template.tmp",
        template / "Timelines" / "template_timeline_id" / "template-2.tmp",
    ]

    for path in required:
        assert path.exists(), path
