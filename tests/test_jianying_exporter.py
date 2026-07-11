"""Tests for exporting rough-cut plans to Jianying draft content."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping

import pytest

from tripclipper.cut_index import read_cut_index
from tripclipper.roughcut import read_rough_cut_plan, validate_rough_cut_plan

ROOT = Path(__file__).resolve().parents[1]
ROUGH_FIXTURES = ROOT / "tests" / "fixtures" / "roughcut"
PLAN_PATH = ROUGH_FIXTURES / "minimal_rough_cut_plan.json"
CUT_INDEX_PATH = ROUGH_FIXTURES / "minimal_cut_index.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture_plan():
    return read_rough_cut_plan(PLAN_PATH)


def _recording_adapter(engine: str = "pyjianyingdraft"):
    from tripclipper.jianying import DraftExportResult, JianyingDraftAdapter

    class RecordingAdapter(JianyingDraftAdapter):
        def __init__(self) -> None:
            self.segments: list[str] = []
            self.media_paths: dict[str, Path] = {}

        def export(
            self,
            *,
            plan,
            media_paths: Mapping[str, Path],
            output_dir: Path,
            engine: str,
        ) -> DraftExportResult:
            self.segments = [segment.segment_id for segment in plan.timeline]
            self.media_paths = dict(media_paths)
            draft_content_path = output_dir / "draft_content.json"
            draft_content_path.write_text(
                json.dumps({"materials": {}, "tracks": []}) + "\n",
                encoding="utf-8",
            )
            return DraftExportResult(
                engine=engine,
                draft_content_path=draft_content_path,
                media_paths=dict(media_paths),
                warnings=[],
            )

    return RecordingAdapter()


def test_r1_r2_prerequisite_apis_are_importable_and_fixture_validates() -> None:
    from tripclipper.jianying import (
        DraftInstallError,
        DraftInstallRequest,
        DraftInstallResult,
        Jianying10Installer,
    )
    from tripclipper.roughcut import (
        RoughCutPlan,
        read_rough_cut_plan,
        validate_rough_cut_plan,
    )

    plan = read_rough_cut_plan(PLAN_PATH)
    cut_index = read_cut_index(CUT_INDEX_PATH)
    validate_rough_cut_plan(plan, cut_index)

    assert isinstance(plan, RoughCutPlan)
    assert DraftInstallRequest
    assert DraftInstallResult
    assert issubclass(DraftInstallError, RuntimeError)
    assert Jianying10Installer


def test_public_draft_export_symbols_are_exported() -> None:
    from tripclipper.jianying import (
        AdapterCapabilities,
        DraftExportError,
        DraftExportResult,
        JianyingDraftAdapter,
        JianyingDraftExporter,
    )

    result = DraftExportResult(
        engine="pyjianyingdraft",
        draft_content_path=Path("draft_content.json"),
        media_paths={},
    )

    assert JianyingDraftExporter
    assert JianyingDraftAdapter
    assert AdapterCapabilities().supports_video
    assert result.warnings == []
    assert issubclass(DraftExportError, RuntimeError)


def test_exporter_dispatches_default_engine_and_rejects_unknown_engine(tmp_path: Path) -> None:
    from tripclipper.jianying import DraftExportError, JianyingDraftExporter

    plan = _fixture_plan()
    adapter = _recording_adapter()
    exporter = JianyingDraftExporter(adapters={"pyjianyingdraft": adapter})

    result = exporter.export(plan, tmp_path / "default")

    assert result.engine == "pyjianyingdraft"
    assert adapter.segments == [segment.segment_id for segment in plan.timeline]
    assert result.draft_content_path == tmp_path / "default" / "draft_content.json"

    rejected_output = tmp_path / "rejected"
    with pytest.raises(DraftExportError, match="Unsupported export engine"):
        exporter.export(plan, rejected_output, engine="unknown")
    assert not rejected_output.exists()


def test_export_only_writes_output_dir_and_does_not_mutate_inputs_or_install(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tripclipper.jianying import Jianying10Installer, JianyingDraftExporter

    plan = _fixture_plan()
    before_plan = plan.model_dump(mode="json")
    before_media_hashes = {
        Path(segment.asset_path): _sha256(ROOT / segment.asset_path)
        for segment in plan.timeline
        if segment.asset_path is not None
    }
    before_cut_index_hash = _sha256(CUT_INDEX_PATH)

    def fail_install(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("exporter must not call Jianying10Installer.install")

    monkeypatch.setattr(Jianying10Installer, "install", fail_install)
    output_dir = tmp_path / "exported"

    result = JianyingDraftExporter(adapters={"pyjianyingdraft": _recording_adapter()}).export(
        plan,
        output_dir,
    )

    assert result.draft_content_path.is_file()
    assert all(output_dir in path.parents or path == output_dir for path in output_dir.rglob("*"))
    assert plan.model_dump(mode="json") == before_plan
    assert _sha256(CUT_INDEX_PATH) == before_cut_index_hash
    for media_path, before_hash in before_media_hashes.items():
        assert _sha256(ROOT / media_path) == before_hash


def test_media_resolution_uses_cut_index_relative_path_before_asset_path(tmp_path: Path) -> None:
    from tripclipper.jianying import JianyingDraftExporter

    plan = _fixture_plan().model_copy(deep=True)
    first_media_segment = next(segment for segment in plan.timeline if segment.track_type != "text")
    first_media_segment.asset_path = "tests/fixtures/media/not-the-plan-path.mp4"
    adapter = _recording_adapter()

    JianyingDraftExporter(adapters={"pyjianyingdraft": adapter}).export(plan, tmp_path)

    assert adapter.media_paths[first_media_segment.segment_id] == (
        ROOT / "tests" / "fixtures" / "media" / first_media_segment.asset_relative_path
    )


def test_media_resolution_falls_back_to_asset_path_when_cut_index_is_unavailable(
    tmp_path: Path,
) -> None:
    from tripclipper.jianying import JianyingDraftExporter

    plan = _fixture_plan().model_copy(deep=True)
    plan.project.cut_index_path = "tests/fixtures/roughcut/missing_cut_index.json"
    adapter = _recording_adapter()

    JianyingDraftExporter(adapters={"pyjianyingdraft": adapter}).export(plan, tmp_path)

    for segment in plan.timeline:
        if segment.track_type != "text":
            assert adapter.media_paths[segment.segment_id] == ROOT / segment.asset_path


def test_missing_required_media_raises_clear_export_error(tmp_path: Path) -> None:
    from tripclipper.jianying import DraftExportError, JianyingDraftExporter

    plan = _fixture_plan().model_copy(deep=True)
    first_media_segment = next(segment for segment in plan.timeline if segment.track_type != "text")
    plan.project.cut_index_path = "tests/fixtures/roughcut/missing_cut_index.json"
    first_media_segment.asset_path = "tests/fixtures/media/missing-required-media.mp4"

    with pytest.raises(DraftExportError, match=first_media_segment.segment_id):
        JianyingDraftExporter(adapters={"pyjianyingdraft": _recording_adapter()}).export(
            plan,
            tmp_path,
        )
