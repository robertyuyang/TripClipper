"""Pydantic models for ``rough_cut_plan.json`` schema version 0.1."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from tripclipper.models import AssetType, EditCandidateStatus

ROUGH_CUT_PLAN_SCHEMA_VERSION = "0.1"

_STRICT_CONFIG = ConfigDict(extra="forbid", populate_by_name=True)
_EXTENSIBLE_CONFIG = ConfigDict(extra="allow", populate_by_name=True)

TrackType = Literal["video", "audio", "image", "text"]


class TimeRange(BaseModel):
    """A half-open time range in float seconds."""

    model_config = _STRICT_CONFIG

    start_sec: float
    end_sec: float

    @model_validator(mode="after")
    def _end_must_be_after_start(self) -> "TimeRange":
        if self.end_sec <= self.start_sec:
            raise ValueError("end_sec must be greater than start_sec")
        return self


class RoughCutProjectRef(BaseModel):
    """Project source references captured when the plan was generated."""

    model_config = _STRICT_CONFIG

    project_slug: str
    cut_index_path: str
    project_config_path: str


class RoughCutIntent(BaseModel):
    """User and edit intent for a rough-cut plan."""

    model_config = _STRICT_CONFIG

    target_duration_sec: Optional[float] = None
    output_style: Optional[str] = None
    audience: Optional[str] = None
    people_focus: Optional[str] = None
    audio_priority: Optional[str] = None


class RoughCutSourceSnapshot(BaseModel):
    """Counts from the source index at plan generation time."""

    model_config = _STRICT_CONFIG

    asset_count: int
    candidate_count: int
    similar_group_count: int


class TextOverlay(BaseModel):
    """Text overlay intent for text timeline segments."""

    model_config = _EXTENSIBLE_CONFIG

    text: str
    style: Optional[str] = None


class TransitionPlan(BaseModel):
    """Transition intent attached to a timeline segment."""

    model_config = _EXTENSIBLE_CONFIG

    kind: str
    duration_sec: Optional[float] = None


class RoughCutSegment(BaseModel):
    """One timeline item in a rough-cut plan."""

    model_config = _STRICT_CONFIG

    segment_id: str
    asset_id: Optional[str] = None
    asset_path: Optional[str] = None
    asset_relative_path: Optional[str] = None
    asset_type: Optional[AssetType] = None
    source_range: Optional[TimeRange] = None
    timeline_range: TimeRange
    track_type: TrackType
    track_index: int = Field(ge=0)
    audio_mode: Optional[str] = None
    volume: Optional[float] = None
    text_overlay: Optional[TextOverlay] = None
    transition_in: Optional[TransitionPlan] = None
    transition_out: Optional[TransitionPlan] = None
    reason: Optional[str] = None
    candidate_status_snapshot: Optional[EditCandidateStatus] = None
    selection_override_reason: Optional[str] = None
    tags: list[str] = Field(default_factory=list)


class UnusedAsset(BaseModel):
    """An unused source asset worth explaining in the plan."""

    model_config = _EXTENSIBLE_CONFIG

    asset_id: str
    asset_relative_path: Optional[str] = None
    reason: Optional[str] = None
    candidate_status_snapshot: Optional[EditCandidateStatus] = None


class PlanWarning(BaseModel):
    """A warning emitted while producing or validating the plan."""

    model_config = _EXTENSIBLE_CONFIG

    stage: Optional[str] = None
    target: Optional[str] = None
    reason: str
    suggestion: Optional[str] = None


class RoughCutPlan(BaseModel):
    """Top-level rough-cut plan contract."""

    model_config = _STRICT_CONFIG

    schema_version: str = ROUGH_CUT_PLAN_SCHEMA_VERSION
    project: RoughCutProjectRef
    intent: RoughCutIntent
    source_snapshot: RoughCutSourceSnapshot
    timeline: list[RoughCutSegment]
    unused_assets: list[UnusedAsset] = Field(default_factory=list)
    warnings: list[PlanWarning] = Field(default_factory=list)
    created_at: str

    @field_validator("schema_version")
    @classmethod
    def _schema_version_must_match(cls, value: str) -> str:
        if value != ROUGH_CUT_PLAN_SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported rough cut plan schema_version {value!r}; "
                f"expected {ROUGH_CUT_PLAN_SCHEMA_VERSION!r}"
            )
        return value

    @field_validator("timeline")
    @classmethod
    def _timeline_must_not_be_empty(cls, value: list[RoughCutSegment]) -> list[RoughCutSegment]:
        if not value:
            raise ValueError("timeline must contain at least one segment")
        return value


__all__ = [
    "ROUGH_CUT_PLAN_SCHEMA_VERSION",
    "TrackType",
    "TimeRange",
    "RoughCutProjectRef",
    "RoughCutIntent",
    "RoughCutSourceSnapshot",
    "TextOverlay",
    "TransitionPlan",
    "RoughCutSegment",
    "UnusedAsset",
    "PlanWarning",
    "RoughCutPlan",
]
