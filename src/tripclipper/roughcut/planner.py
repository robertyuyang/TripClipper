"""Deterministic heuristic planner for ``rough_cut_plan.json``."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

import yaml
from pydantic import BaseModel, ConfigDict, Field

from tripclipper.cut_index import read_cut_index
from tripclipper.models import (
    Asset,
    AssetType,
    ClipSuggestion,
    CutIndex,
    EditCandidateStatus,
)
from tripclipper.paths import cut_index_path, project_config_path

from .models import (
    PlanWarning,
    RoughCutIntent,
    RoughCutPlan,
    RoughCutProjectRef,
    RoughCutSegment,
    RoughCutSourceSnapshot,
    TextOverlay,
    TimeRange,
)
from .validator import validate_rough_cut_plan

_PathLike = Union[str, Path]

_DEFAULT_TARGET_DURATION_SEC = 90.0
_FALLBACK_CLIP_DURATION_SEC = 5.0
_TITLE_DURATION_SEC = 5.0
_EDITING_INTENT_KEYS = (
    "output_style",
    "target_length",
    "audience",
    "people_focus",
    "audio_priority",
)
_TIMECODE_HMS_RE = re.compile(r"^(\d{1,2}):(\d{2}):(\d{2})(?:\.(\d+))?$")
_TIMECODE_MS_RE = re.compile(r"^(\d{1,3}):(\d{2})(?:\.(\d+))?$")


class RoughCutPlanRequest(BaseModel):
    """Input for the first-pass heuristic rough-cut planner."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    slug: str
    base_dir: Optional[_PathLike] = None
    target_duration_sec: Optional[float] = Field(default=None, gt=0)
    max_segments: Optional[int] = Field(default=None, ge=1)
    include_alternates: bool = False
    allow_needs_review: bool = False


class HeuristicRoughCutPlanner:
    """Build a simple rough-cut plan from existing default video candidates."""

    def plan(self, request: RoughCutPlanRequest) -> RoughCutPlan:
        index_path = cut_index_path(request.slug, request.base_dir)
        config_path = project_config_path(request.slug, request.base_dir)
        cut_index = read_cut_index(index_path)
        project_intent = self._load_project_intent(config_path)
        target_duration_sec = self._resolve_target_duration_sec(
            request,
            cut_index,
            project_intent,
        )

        timeline: list[RoughCutSegment] = []
        elapsed_sec = 0.0

        for asset in self._ordered_video_candidates(cut_index, request):
            if (
                request.max_segments is not None
                and len(timeline) >= request.max_segments
            ):
                break
            if elapsed_sec >= target_duration_sec:
                break

            source_range, reason, tags = self._source_range_for(asset)
            if source_range is None:
                continue

            duration_sec = source_range.end_sec - source_range.start_sec
            timeline.append(
                RoughCutSegment(
                    segment_id=f"seg_video_{len(timeline) + 1:03d}",
                    asset_id=asset.asset_id,
                    asset_path=self._asset_path_snapshot(asset, cut_index),
                    asset_relative_path=asset.relative_path,
                    asset_type=asset.type,
                    source_range=source_range,
                    timeline_range=TimeRange(
                        start_sec=elapsed_sec,
                        end_sec=elapsed_sec + duration_sec,
                    ),
                    track_type="video",
                    track_index=0,
                    audio_mode="keep",
                    volume=1.0,
                    reason=reason,
                    candidate_status_snapshot=asset.edit_candidate_status,
                    tags=tags,
                )
            )
            elapsed_sec += duration_sec

        timeline.append(
            RoughCutSegment(
                segment_id="seg_title_project_slug",
                timeline_range=TimeRange(start_sec=0.0, end_sec=_TITLE_DURATION_SEC),
                track_type="text",
                track_index=0,
                audio_mode="none",
                volume=1.0,
                text_overlay=TextOverlay(text=request.slug, style="title"),
                reason="Project slug title for the first five seconds",
                tags=["title"],
            )
        )

        warnings = self._warnings(elapsed_sec, target_duration_sec)
        plan = RoughCutPlan(
            project=RoughCutProjectRef(
                project_slug=request.slug,
                cut_index_path=str(index_path),
                project_config_path=str(config_path),
            ),
            intent=RoughCutIntent(
                target_duration_sec=target_duration_sec,
                output_style=self._intent_value(cut_index, project_intent, "output_style"),
                audience=self._intent_value(cut_index, project_intent, "audience"),
                people_focus=self._intent_value(cut_index, project_intent, "people_focus"),
                audio_priority=self._intent_value(cut_index, project_intent, "audio_priority"),
            ),
            source_snapshot=RoughCutSourceSnapshot(
                asset_count=len(cut_index.assets),
                candidate_count=sum(
                    1
                    for asset in cut_index.assets
                    if asset.edit_candidate_status is EditCandidateStatus.default_selected
                ),
                similar_group_count=len(cut_index.similar_groups),
            ),
            timeline=timeline,
            warnings=warnings,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        validate_rough_cut_plan(plan, cut_index)
        return plan

    def _ordered_video_candidates(
        self,
        cut_index: CutIndex,
        request: RoughCutPlanRequest,
    ) -> list[Asset]:
        default_priority = {
            candidate.asset_id: candidate.priority
            for candidate in cut_index.default_candidates
            if candidate.asset_id is not None
        }
        allowed = {EditCandidateStatus.default_selected}
        if request.include_alternates:
            allowed.add(EditCandidateStatus.alternate)
        if request.allow_needs_review:
            allowed.add(EditCandidateStatus.needs_review)

        candidates = [
            asset
            for asset in cut_index.assets
            if asset.type is AssetType.video
            and asset.asset_id is not None
            and asset.relative_path is not None
            and asset.edit_candidate_status in allowed
        ]

        def sort_key(asset: Asset) -> tuple[int, int, int, str, str]:
            status_rank = {
                EditCandidateStatus.default_selected: 0,
                EditCandidateStatus.alternate: 1,
                EditCandidateStatus.needs_review: 2,
            }.get(asset.edit_candidate_status, 9)
            priority = asset.edit_candidate_priority
            if priority is None:
                priority = default_priority.get(asset.asset_id, 1_000_000)
            rating_rank = -(asset.rating or 0)
            return (
                status_rank,
                priority,
                rating_rank,
                asset.relative_path or "",
                asset.asset_id or "",
            )

        return sorted(candidates, key=sort_key)

    def _source_range_for(
        self,
        asset: Asset,
    ) -> tuple[TimeRange | None, str, list[str]]:
        duration_sec = self._asset_duration_sec(asset)
        for suggestion in asset.clip_suggestions:
            start_sec = _parse_timecode(suggestion.in_)
            end_sec = _parse_timecode(suggestion.out)
            if start_sec is None or end_sec is None or end_sec <= start_sec:
                continue
            return (
                TimeRange(start_sec=start_sec, end_sec=end_sec),
                self._clip_reason(suggestion),
                list(suggestion.tags or asset.tags),
            )

        if duration_sec is None:
            return None, "no clip_suggestions and no readable duration", list(asset.tags)

        end_sec = min(duration_sec, _FALLBACK_CLIP_DURATION_SEC)
        if end_sec <= 0:
            return None, "no clip_suggestions and non-positive duration", list(asset.tags)
        return (
            TimeRange(start_sec=0.0, end_sec=end_sec),
            "no clip_suggestions, used conservative opening range",
            list(asset.tags),
        )

    @staticmethod
    def _clip_reason(suggestion: ClipSuggestion) -> str:
        details = suggestion.reason or suggestion.role or "selected clip_suggestions[0]"
        return f"clip_suggestions[0]: {details}"

    @staticmethod
    def _asset_duration_sec(asset: Asset) -> float | None:
        metadata = asset.metadata or {}
        raw = metadata.get("duration")
        if raw is None:
            raw = metadata.get("duration_s")
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return None
        return value if value > 0 else None

    @staticmethod
    def _asset_path_snapshot(asset: Asset, cut_index: CutIndex) -> str | None:
        if asset.path:
            return asset.path
        if cut_index.project.source_folder and asset.relative_path:
            return str(Path(cut_index.project.source_folder) / asset.relative_path)
        return asset.relative_path

    @staticmethod
    def _load_project_intent(path: Path) -> dict[str, object]:
        try:
            with path.open("r", encoding="utf-8") as fh:
                payload = yaml.safe_load(fh) or {}
        except (OSError, yaml.YAMLError):
            return {}
        if not isinstance(payload, dict):
            return {}
        return {key: payload.get(key) for key in _EDITING_INTENT_KEYS}

    @staticmethod
    def _resolve_target_duration_sec(
        request: RoughCutPlanRequest,
        cut_index: CutIndex,
        project_intent: dict[str, object],
    ) -> float:
        if request.target_duration_sec is not None:
            return request.target_duration_sec
        parsed = _parse_duration_value(project_intent.get("target_length"))
        if parsed is not None:
            return parsed
        parsed = _parse_duration_value(
            (cut_index.project.editing_intent or {}).get("target_length")
        )
        return parsed or _DEFAULT_TARGET_DURATION_SEC

    @staticmethod
    def _intent_value(
        cut_index: CutIndex,
        project_intent: dict[str, object],
        key: str,
    ) -> str | None:
        value = project_intent.get(key)
        if value is not None:
            return str(value)
        value = (cut_index.project.editing_intent or {}).get(key)
        return str(value) if value is not None else None

    @staticmethod
    def _warnings(
        planned_duration_sec: float,
        target_duration_sec: float,
    ) -> list[PlanWarning]:
        if planned_duration_sec >= target_duration_sec:
            return []
        return [
            PlanWarning(
                stage="planner",
                reason=(
                    "default video candidates insufficient: "
                    f"planned {planned_duration_sec:.3f}s below target "
                    f"{target_duration_sec:.3f}s"
                ),
                suggestion="Review default_selected videos or lower target_duration_sec.",
            )
        ]


def _parse_duration_value(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) if value > 0 else None
    if not isinstance(value, str):
        return None

    text = value.strip().lower()
    if not text:
        return None
    for suffix in ("seconds", "second", "secs", "sec", "s"):
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
            break
    return _parse_timecode(text)


def _parse_timecode(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if number >= 0 else None
    if not isinstance(value, str):
        return None

    text = value.strip()
    if not text:
        return None

    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        return float(text)

    hms = _TIMECODE_HMS_RE.fullmatch(text)
    if hms:
        hours, minutes, seconds, fraction = hms.groups()
        if int(minutes) >= 60 or int(seconds) >= 60:
            return None
        return (
            int(hours) * 3600
            + int(minutes) * 60
            + int(seconds)
            + _fraction_to_seconds(fraction)
        )

    ms = _TIMECODE_MS_RE.fullmatch(text)
    if ms:
        minutes, seconds, fraction = ms.groups()
        if int(seconds) >= 60:
            return None
        return int(minutes) * 60 + int(seconds) + _fraction_to_seconds(fraction)

    return None


def _fraction_to_seconds(value: str | None) -> float:
    return float(f"0.{value}") if value else 0.0


__all__ = ["HeuristicRoughCutPlanner", "RoughCutPlanRequest"]
