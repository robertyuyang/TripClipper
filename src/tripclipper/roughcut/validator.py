"""Semantic validation for ``RoughCutPlan`` objects."""

from __future__ import annotations

from pathlib import Path

from tripclipper.models import Asset, CutIndex, EditCandidateStatus

from .models import RoughCutPlan, RoughCutSegment


class RoughCutValidationError(Exception):
    """Raised when a rough-cut plan violates semantic contract rules."""


def validate_rough_cut_plan(plan: RoughCutPlan, cut_index: CutIndex) -> None:
    """Validate ``plan`` against its source ``cut_index``.

    Pydantic models cover local shape and time-range ordering. This function
    covers rules that require cross-segment or cross-file context.
    """
    assets_by_id = {
        asset.asset_id: asset
        for asset in cut_index.assets
        if asset.asset_id is not None
    }

    seen_segment_ids: set[str] = set()
    by_track: dict[tuple[str, int], list[RoughCutSegment]] = {}

    for segment in plan.timeline:
        if segment.segment_id in seen_segment_ids:
            raise RoughCutValidationError(f"Duplicate segment_id {segment.segment_id!r}")
        seen_segment_ids.add(segment.segment_id)

        _validate_type_specific_fields(segment)
        _validate_excluded_override(segment)
        _validate_asset_identity(segment, assets_by_id)

        by_track.setdefault((segment.track_type, segment.track_index), []).append(segment)

    _validate_track_overlaps(by_track)


def _validate_type_specific_fields(segment: RoughCutSegment) -> None:
    if segment.track_type in {"video", "audio"}:
        if segment.source_range is None:
            raise RoughCutValidationError(
                f"{segment.segment_id}: {segment.track_type} segment requires source_range"
            )
    else:
        if segment.source_range is not None:
            raise RoughCutValidationError(
                f"{segment.segment_id}: {segment.track_type} segment must not include source_range"
            )

    if segment.track_type == "text":
        if segment.text_overlay is None:
            raise RoughCutValidationError(
                f"{segment.segment_id}: text segment requires text_overlay"
            )
    elif segment.text_overlay is not None:
        raise RoughCutValidationError(
            f"{segment.segment_id}: non-text segment must not include text_overlay"
        )

    if segment.track_type != "text":
        missing = [
            field
            for field in ("asset_id", "asset_relative_path", "asset_path", "asset_type")
            if getattr(segment, field) is None
        ]
        if missing:
            raise RoughCutValidationError(
                f"{segment.segment_id}: media segment missing {', '.join(missing)}"
            )


def _validate_excluded_override(segment: RoughCutSegment) -> None:
    if (
        segment.candidate_status_snapshot is EditCandidateStatus.excluded
        and not segment.selection_override_reason
    ):
        raise RoughCutValidationError(
            f"{segment.segment_id}: excluded asset requires selection_override_reason"
        )


def _validate_asset_identity(segment: RoughCutSegment, assets_by_id: dict[str, Asset]) -> None:
    if segment.track_type == "text":
        return

    assert segment.asset_id is not None
    assert segment.asset_relative_path is not None
    assert segment.asset_path is not None

    asset = assets_by_id.get(segment.asset_id)
    if asset is None:
        raise RoughCutValidationError(
            f"{segment.segment_id}: asset_id {segment.asset_id!r} not found in cut_index"
        )

    if asset.relative_path and asset.relative_path != segment.asset_relative_path:
        raise RoughCutValidationError(
            f"{segment.segment_id}: asset relative path {segment.asset_relative_path!r} "
            f"does not match cut_index relative path {asset.relative_path!r}"
        )

    if asset.type is not None and segment.asset_type is not None and asset.type != segment.asset_type:
        raise RoughCutValidationError(
            f"{segment.segment_id}: asset_type {segment.asset_type!r} does not match cut_index"
        )

    if not Path(segment.asset_path).exists():
        raise RoughCutValidationError(
            f"{segment.segment_id}: asset_path {segment.asset_path!r} does not exist"
        )


def _validate_track_overlaps(by_track: dict[tuple[str, int], list[RoughCutSegment]]) -> None:
    for (track_type, track_index), segments in by_track.items():
        ordered = sorted(segments, key=lambda item: item.timeline_range.start_sec)
        for previous, current in zip(ordered, ordered[1:]):
            if current.timeline_range.start_sec < previous.timeline_range.end_sec:
                raise RoughCutValidationError(
                    f"timeline overlap on ({track_type}, {track_index}) between "
                    f"{previous.segment_id!r} and {current.segment_id!r}"
                )


__all__ = ["RoughCutValidationError", "validate_rough_cut_plan"]
