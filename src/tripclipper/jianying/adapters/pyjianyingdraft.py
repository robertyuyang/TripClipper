"""pyJianYingDraft adapter for rough-cut plan export."""

from __future__ import annotations

import importlib
import json
import uuid
from importlib import resources
from pathlib import Path
from typing import Any, Mapping

from tripclipper.roughcut import RoughCutPlan, RoughCutSegment, TimeRange

from ..models import AdapterCapabilities, DraftExportError, DraftExportResult
from .base import JianyingDraftAdapter

_US_PER_SECOND = 1_000_000


class PyJianYingDraftAdapter(JianyingDraftAdapter):
    """Export selected rough-cut timeline segments with pyJianYingDraft."""

    capabilities = AdapterCapabilities(
        supports_video=True,
        supports_audio=True,
        supports_image=True,
        supports_text=True,
        supports_transitions=False,
        supports_text_style=False,
    )

    def __init__(self, draft_module: Any | None = None) -> None:
        if draft_module is None:
            try:
                draft_module = importlib.import_module("pyJianYingDraft")
            except ImportError as exc:
                raise DraftExportError(
                    "pyJianYingDraft is required for the default pyjianyingdraft export engine"
                ) from exc
        self._draft = draft_module
        self._track_module = importlib.import_module("pyJianYingDraft.track")

    def export(
        self,
        *,
        plan: RoughCutPlan,
        media_paths: Mapping[str, Path],
        output_dir: Path,
        engine: str,
    ) -> DraftExportResult:
        output_dir.mkdir(parents=True, exist_ok=True)
        work_dir = output_dir / "pyjianying_work"
        work_dir.mkdir(parents=True, exist_ok=True)

        script = self._draft.ScriptFile(1920, 1080, 30, True)
        track_refs = self._create_tracks(script, plan)
        warnings: list[str] = []

        for segment in plan.timeline:
            self._append_segment(script, track_refs, segment, media_paths, warnings)

        draft_json = script.dumps()
        work_draft_content_path = work_dir / "draft_content.json"
        draft_content_path = output_dir / "draft_content.json"
        work_draft_content_path.write_text(draft_json + "\n", encoding="utf-8")
        draft_content_path.write_text(draft_json + "\n", encoding="utf-8")

        draft_meta_info_path = self._write_meta_info(output_dir, work_dir)
        return DraftExportResult(
            engine=engine,
            draft_content_path=draft_content_path,
            draft_meta_info_path=draft_meta_info_path,
            media_paths=dict(media_paths),
            warnings=warnings,
        )

    def _create_tracks(self, script: Any, plan: RoughCutPlan) -> dict[tuple[str, int], Any]:
        keys = sorted(
            {(segment.track_type, segment.track_index) for segment in plan.timeline},
            key=self._track_sort_key,
        )
        track_refs: dict[tuple[str, int], Any] = {}
        for track_type, track_index in keys:
            draft_track_type = self._draft_track_type(track_type)
            track_name = "main_video" if (track_type, track_index) == ("video", 0) else f"{track_type}_{track_index}"
            track_refs[(track_type, track_index)] = script.append_track(
                self._track_module.TrackSpec(draft_track_type, track_name)
            )
        return track_refs

    @staticmethod
    def _track_sort_key(key: tuple[str, int]) -> tuple[int, int]:
        order = {"audio": 0, "video": 1, "image": 2, "text": 3}
        track_type, track_index = key
        return (order[track_type], track_index)

    def _draft_track_type(self, track_type: str) -> Any:
        if track_type == "audio":
            return self._draft.TrackType.audio
        if track_type == "text":
            return self._draft.TrackType.text
        return self._draft.TrackType.video

    def _append_segment(
        self,
        script: Any,
        track_refs: Mapping[tuple[str, int], Any],
        segment: RoughCutSegment,
        media_paths: Mapping[str, Path],
        warnings: list[str],
    ) -> None:
        track_ref = track_refs[(segment.track_type, segment.track_index)]
        if segment.track_type == "video":
            material = self._make_video_material(segment, media_paths[segment.segment_id], "video")
            script.add_segment(
                self._draft.VideoSegment(
                    material,
                    self._timerange(segment.timeline_range),
                    source_timerange=self._timerange(segment.source_range),
                    volume=segment.volume if segment.volume is not None else 1.0,
                ),
                track_ref,
            )
        elif segment.track_type == "image":
            material = self._make_video_material(segment, media_paths[segment.segment_id], "photo")
            script.add_segment(
                self._draft.VideoSegment(
                    material,
                    self._timerange(segment.timeline_range),
                    volume=segment.volume if segment.volume is not None else 1.0,
                ),
                track_ref,
            )
        elif segment.track_type == "audio":
            material = self._make_audio_material(segment, media_paths[segment.segment_id])
            script.add_segment(
                self._draft.AudioSegment(
                    material,
                    self._timerange(segment.timeline_range),
                    source_timerange=self._timerange(segment.source_range),
                    volume=segment.volume if segment.volume is not None else 1.0,
                ),
                track_ref,
            )
        elif segment.track_type == "text":
            assert segment.text_overlay is not None
            if segment.text_overlay.style:
                warnings.append(
                    f"{segment.segment_id}: text style {segment.text_overlay.style!r} "
                    "simplified by pyjianyingdraft adapter"
                )
            script.add_segment(
                self._draft.TextSegment(
                    segment.text_overlay.text,
                    self._timerange(segment.timeline_range),
                    style=self._draft.TextStyle(size=7.2, bold=segment.text_overlay.style == "title"),
                ),
                track_ref,
            )

        self._collect_transition_warnings(segment, warnings)

    def _collect_transition_warnings(self, segment: RoughCutSegment, warnings: list[str]) -> None:
        for field_name in ("transition_in", "transition_out"):
            transition = getattr(segment, field_name)
            if transition is None:
                continue
            if transition.kind == "cut" and (transition.duration_sec is None or transition.duration_sec == 0):
                continue
            warnings.append(
                f"{segment.segment_id}: {field_name} {transition.kind!r} simplified to cut "
                "by pyjianyingdraft adapter"
            )

    def _make_video_material(
        self,
        segment: RoughCutSegment,
        resolved_path: Path,
        material_type: str,
    ) -> Any:
        material = self._draft.VideoMaterial.__new__(self._draft.VideoMaterial)
        material.material_id = uuid.uuid4().hex
        material.local_material_id = material.material_id
        material.material_name = resolved_path.name
        material.path = self._path_for_draft(resolved_path)
        material.duration = self._media_duration(segment, image=material_type == "photo")
        material.height = 1080
        material.width = 1920
        material.crop_settings = self._draft.CropSettings()
        material.material_type = material_type
        return material

    def _make_audio_material(self, segment: RoughCutSegment, resolved_path: Path) -> Any:
        material = self._draft.AudioMaterial.__new__(self._draft.AudioMaterial)
        material.material_id = uuid.uuid4().hex
        material.material_name = resolved_path.name
        material.path = self._path_for_draft(resolved_path)
        material.duration = self._media_duration(segment, image=False)
        return material

    @staticmethod
    def _media_duration(segment: RoughCutSegment, *, image: bool) -> int:
        if image:
            return 10_800_000_000
        ranges = [segment.source_range, segment.timeline_range]
        end_sec = max(time_range.end_sec for time_range in ranges if time_range is not None)
        return int(round(end_sec * _US_PER_SECOND))

    @staticmethod
    def _path_for_draft(resolved_path: Path) -> str:
        try:
            return str(resolved_path.resolve().relative_to(Path.cwd().resolve()))
        except ValueError:
            return str(resolved_path)

    def _timerange(self, time_range: TimeRange | None) -> Any:
        if time_range is None:
            return None
        start = int(round(time_range.start_sec * _US_PER_SECOND))
        duration = int(round((time_range.end_sec - time_range.start_sec) * _US_PER_SECOND))
        return self._draft.trange(start, duration)

    @staticmethod
    def _write_meta_info(output_dir: Path, work_dir: Path) -> Path | None:
        try:
            meta_info = resources.files("pyJianYingDraft.assets").joinpath(
                "draft_meta_info.json"
            ).read_text(encoding="utf-8")
        except (FileNotFoundError, ModuleNotFoundError):
            return None

        # Validate before writing so a broken package asset does not leak invalid JSON.
        json.loads(meta_info)
        output_path = output_dir / "draft_meta_info.json"
        work_path = work_dir / "draft_meta_info.json"
        output_path.write_text(meta_info, encoding="utf-8")
        work_path.write_text(meta_info, encoding="utf-8")
        return output_path
