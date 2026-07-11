"""Tests for the pyJianYingDraft-backed Jianying draft adapter."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tripclipper.roughcut import read_rough_cut_plan

ROOT = Path(__file__).resolve().parents[1]
ROUGH_FIXTURES = ROOT / "tests" / "fixtures" / "roughcut"
JIANYING_FIXTURES = ROOT / "tests" / "fixtures" / "jianying"
PLAN_PATH = ROUGH_FIXTURES / "minimal_rough_cut_plan.json"
REALISTIC_DRAFT = JIANYING_FIXTURES / "realistic_draft_content.json"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _fixture_plan():
    return read_rough_cut_plan(PLAN_PATH)


def _media_paths_for_plan(plan) -> dict[str, Path]:
    return {
        segment.segment_id: ROOT / segment.asset_path
        for segment in plan.timeline
        if segment.track_type != "text" and segment.asset_path is not None
    }


def _time_range(payload: dict[str, int] | None) -> tuple[int, int] | None:
    if payload is None:
        return None
    return (payload["start"], payload["duration"])


def _text_content(material: dict[str, Any]) -> str:
    return json.loads(material["content"])["text"]


def draft_content_semantics(payload: dict[str, Any]) -> dict[str, list[tuple[Any, ...]]]:
    videos = {item["id"]: item for item in payload["materials"].get("videos", [])}
    audios = {item["id"]: item for item in payload["materials"].get("audios", [])}
    texts = {item["id"]: item for item in payload["materials"].get("texts", [])}
    semantics: dict[str, list[tuple[Any, ...]]] = {
        "main_videos": [],
        "audio": [],
        "images": [],
        "texts": [],
    }

    for track in payload.get("tracks", []):
        for segment in track.get("segments", []):
            material_id = segment["material_id"]
            if track["type"] == "video" and material_id in videos:
                material = videos[material_id]
                entry = (
                    Path(material["path"]).name,
                    _time_range(segment.get("source_timerange")),
                    _time_range(segment.get("target_timerange")),
                    segment.get("volume"),
                )
                if material["type"] == "photo":
                    semantics["images"].append(entry)
                else:
                    semantics["main_videos"].append(entry)
            elif track["type"] == "audio" and material_id in audios:
                material = audios[material_id]
                semantics["audio"].append(
                    (
                        Path(material["path"]).name,
                        _time_range(segment.get("source_timerange")),
                        _time_range(segment.get("target_timerange")),
                        segment.get("volume"),
                    )
                )
            elif track["type"] == "text" and material_id in texts:
                semantics["texts"].append(
                    (
                        _text_content(texts[material_id]),
                        _time_range(segment.get("target_timerange")),
                    )
                )

    return semantics


def test_pyjianyingdraft_dependency_is_declared_and_importable() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert "pyjianyingdraft>=0.3.0" in pyproject.lower()
    import pyJianYingDraft as draft

    assert draft.ScriptFile


def test_pyjianyingdraft_adapter_keeps_work_dir_and_reports_warnings(tmp_path: Path) -> None:
    from tripclipper.jianying import JianyingDraftExporter

    plan = _fixture_plan()

    result = JianyingDraftExporter().export(plan, tmp_path)

    assert result.draft_content_path == tmp_path / "draft_content.json"
    assert result.draft_content_path.is_file()
    assert (tmp_path / "pyjianying_work").is_dir()
    assert any("text style" in warning for warning in result.warnings)


def test_adapter_consumes_selected_segments_without_reading_cut_index(tmp_path: Path) -> None:
    from tripclipper.jianying.adapters.pyjianyingdraft import PyJianYingDraftAdapter

    plan = _fixture_plan().model_copy(deep=True)
    plan.project.cut_index_path = "tests/fixtures/roughcut/adapter-must-not-read-this.json"

    result = PyJianYingDraftAdapter().export(
        plan=plan,
        media_paths=_media_paths_for_plan(plan),
        output_dir=tmp_path,
        engine="pyjianyingdraft",
    )

    payload = _load_json(result.draft_content_path)
    media_segment_ids = [segment.segment_id for segment in plan.timeline if segment.track_type != "text"]
    material_paths = [
        Path(item["path"]).name
        for item in payload["materials"]["videos"] + payload["materials"]["audios"]
    ]

    assert len(material_paths) == len(media_segment_ids)
    assert material_paths == [
        Path(segment.asset_path).name
        for segment in plan.timeline
        if segment.track_type != "text"
    ]


def test_fixture_export_matches_realistic_draft_semantics(tmp_path: Path) -> None:
    from tripclipper.jianying import JianyingDraftExporter

    result = JianyingDraftExporter().export(_fixture_plan(), tmp_path)

    assert draft_content_semantics(_load_json(result.draft_content_path)) == draft_content_semantics(
        _load_json(REALISTIC_DRAFT)
    )


def test_exported_fixture_draft_content_can_be_installed(tmp_path: Path) -> None:
    from tripclipper.jianying import DraftInstallRequest, Jianying10Installer, JianyingDraftExporter

    result = JianyingDraftExporter().export(_fixture_plan(), tmp_path / "exported")
    install_result = Jianying10Installer().install(
        DraftInstallRequest(
            draft_content_path=result.draft_content_path,
            draft_name="Exported Fixture",
            jianying_drafts_dir=tmp_path / "drafts",
        )
    )

    assert install_result.draft_dir.is_dir()
    assert (install_result.draft_dir / "draft_content.json").is_file()
