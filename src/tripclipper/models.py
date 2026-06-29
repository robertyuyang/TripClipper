"""Data models and field enums for ``cut_index.json`` (schema_version 0.3).

This module is the single source of truth for every field name and every
enumerated value used across TripClipper. Other modules MUST import these
definitions instead of re-declaring them.

Field shape is aligned with the technical design document, chapter 7
("数据包结构" / data package structure).
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from . import SCHEMA_VERSION

# ---------------------------------------------------------------------------
# Enums (str subclasses so they serialise to their string value in JSON)
# ---------------------------------------------------------------------------


class AssetType(str, Enum):
    video = "video"
    image = "image"
    audio = "audio"


class AnalysisStatus(str, Enum):
    scanned = "scanned"
    analyzing = "analyzing"
    analyzed = "analyzed"
    analysis_failed = "analysis_failed"


class SubjectType(str, Enum):
    landscape = "landscape"
    people = "people"
    people_landscape = "people_landscape"
    food = "food"
    building = "building"
    activity = "activity"
    object = "object"
    other = "other"


class PeoplePresence(str, Enum):
    none = "none"
    single = "single"
    multiple = "multiple"
    small_group = "small_group"
    crowd = "crowd"


class ShotScale(str, Enum):
    extreme_wide = "extreme_wide"
    wide = "wide"
    full = "full"
    medium = "medium"
    close_up = "close_up"
    extreme_close_up = "extreme_close_up"


class ShotFunction(str, Enum):
    establishing = "establishing"
    highlight = "highlight"
    transition = "transition"
    detail = "detail"
    reaction = "reaction"
    dialogue = "dialogue"
    b_roll = "b_roll"
    other = "other"


class SimilarSelection(str, Enum):
    primary = "primary"
    alternate = "alternate"
    rejected = "rejected"
    needs_review = "needs_review"
    none = "none"


class EditCandidateStatus(str, Enum):
    default_selected = "default_selected"
    alternate = "alternate"
    excluded = "excluded"
    needs_review = "needs_review"


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

# Shared config: allow population by field name as well as alias, so models with
# aliased fields (e.g. ClipSuggestion.in_) can be built either way.
_MODEL_CONFIG = ConfigDict(populate_by_name=True)


class ClipSuggestion(BaseModel):
    """A recommended sub-clip suggestion produced by Stage 2 vision analysis.

    Each suggestion is a time range inside the asset; ``in_`` / ``out`` use
    timecode strings (``HH:MM:SS`` or ``MM:SS``). The 4 asset-level enum
    fields are duplicated here so a clip can describe itself independently
    of the asset envelope (TD 7 ``clip_suggestion``).
    """

    model_config = _MODEL_CONFIG

    # ``in`` is a Python keyword, so the attribute is ``in_`` with alias "in".
    in_: Optional[str] = Field(default=None, alias="in")
    out: Optional[str] = None
    role: Optional[str] = None
    subject_type: Optional[SubjectType] = None
    shot_scale: Optional[ShotScale] = None
    rating: Optional[int] = None
    reason: Optional[str] = None
    audio_strategy: Optional[str] = None
    tags: list[str] = Field(default_factory=list)


class Asset(BaseModel):
    """A single media asset (TD 7 ``asset``)."""

    model_config = _MODEL_CONFIG

    asset_id: Optional[str] = None
    file: Optional[str] = None
    filename: Optional[str] = None
    path: Optional[str] = None
    relative_path: Optional[str] = None
    type: Optional[AssetType] = None
    extension: Optional[str] = None
    size: Optional[int] = None
    modified_time: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    thumbnail_path: Optional[str] = None
    frame_paths: list[str] = Field(default_factory=list)
    # Seconds-since-start for each entry in ``frame_paths``; the two lists
    # are written together and must have matching length and ordering.
    frame_timestamps: list[float] = Field(default_factory=list)
    transcript_path: Optional[str] = None
    analysis_status: AnalysisStatus = AnalysisStatus.scanned
    scene: Optional[str] = None
    summary: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    rating: Optional[int] = None
    subject_type: Optional[SubjectType] = None
    primary_subject: Optional[str] = None
    people_presence: Optional[PeoplePresence] = None
    shot_scale: Optional[ShotScale] = None
    shot_function: Optional[ShotFunction] = None
    clip_suggestions: list[ClipSuggestion] = Field(default_factory=list)
    audio_suggestion: Optional[str] = None
    audio_strategy: Optional[str] = None
    similar_group_id: Optional[str] = None
    similar_selection: Optional[SimilarSelection] = None
    similar_rank: Optional[int] = None
    similar_reason: Optional[str] = None
    edit_candidate_status: Optional[EditCandidateStatus] = None
    edit_candidate_priority: Optional[int] = None
    edit_candidate_reason: Optional[str] = None
    eagle_item_id: Optional[str] = None
    eagle_sync_status: Optional[str] = None
    warnings: list[Any] = Field(default_factory=list)
    failures: list[Any] = Field(default_factory=list)


class SimilarGroup(BaseModel):
    """A group of near-duplicate assets (TD 7 ``similar_group``)."""

    model_config = _MODEL_CONFIG

    similar_group_id: Optional[str] = None
    asset_ids: list[str] = Field(default_factory=list)
    basis: list[str] = Field(default_factory=list)
    primary_asset_id: Optional[str] = None
    alternate_asset_ids: list[str] = Field(default_factory=list)
    rejected_asset_ids: list[str] = Field(default_factory=list)
    default_candidate_asset_id: Optional[str] = None
    confidence: Optional[float] = None
    needs_review: bool = False
    reason: Optional[str] = None


class DefaultCandidate(BaseModel):
    """An entry in the de-duplicated default edit candidate pool (TD 7)."""

    model_config = _MODEL_CONFIG

    asset_id: Optional[str] = None
    priority: Optional[int] = None
    role: Optional[str] = None
    reason: Optional[str] = None
    similar_group_id: Optional[str] = None
    subject_type: Optional[SubjectType] = None
    shot_scale: Optional[ShotScale] = None


class Failure(BaseModel):
    """A blocking or non-blocking failure record (TD 12)."""

    model_config = _MODEL_CONFIG

    stage: Optional[str] = None
    target: Optional[str] = None  # related project or asset id
    reason: Optional[str] = None
    suggestion: Optional[str] = None
    blocking: bool = False


class WarningItem(BaseModel):
    """A warning record.

    Named ``WarningItem`` to avoid clashing with the builtin ``Warning``.
    """

    model_config = _MODEL_CONFIG

    stage: Optional[str] = None
    target: Optional[str] = None
    reason: Optional[str] = None
    suggestion: Optional[str] = None
    blocking: bool = False


class ProjectInfo(BaseModel):
    """Project block of ``cut_index.json`` (TD 7 ``project``)."""

    model_config = _MODEL_CONFIG

    project_name: Optional[str] = None
    project_slug: Optional[str] = None
    source_folder: Optional[str] = None
    config_path: Optional[str] = None
    editing_intent: dict[str, Any] = Field(default_factory=dict)
    # NOTE: ``model_config_summary`` is a regular business field; it is distinct
    # from Pydantic's reserved ``model_config`` attribute and does not conflict.
    model_config_summary: dict[str, Any] = Field(default_factory=dict)
    eagle_sync: dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class Capabilities(BaseModel):
    """Local capability flags (TD 5: ffmpeg / ffprobe availability)."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    ffmpeg: bool = False
    ffprobe: bool = False
    notes: Optional[str] = None


class AnalysisInfo(BaseModel):
    """Analysis block of ``cut_index.json`` (TD 7 ``analysis``)."""

    model_config = _MODEL_CONFIG

    provider: Optional[str] = None
    vision_model: Optional[str] = None
    text_model: Optional[str] = None
    transcription_model: Optional[str] = None
    stage: Optional[str] = None
    sample_size: Optional[int] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    status: Optional[str] = None
    error_summary: Optional[str] = None


class ClusteringInfo(BaseModel):
    """Clustering block of ``cut_index.json`` (M4 similar-group clustering stage)."""

    model_config = _MODEL_CONFIG

    provider: Optional[str] = None
    vision_model: Optional[str] = None
    text_model: Optional[str] = None
    stage: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    status: Optional[str] = None
    error_summary: Optional[str] = None
    groups_count: int = 0
    arbitration_failures: int = 0


class CutIndex(BaseModel):
    """Top-level ``cut_index.json`` model (TD 7)."""

    model_config = _MODEL_CONFIG

    schema_version: str = SCHEMA_VERSION
    project: ProjectInfo
    capabilities: Capabilities = Field(default_factory=Capabilities)
    analysis: AnalysisInfo = Field(default_factory=AnalysisInfo)
    clustering: Optional[ClusteringInfo] = None
    assets: list[Asset] = Field(default_factory=list)
    similar_groups: list[SimilarGroup] = Field(default_factory=list)
    default_candidates: list[DefaultCandidate] = Field(default_factory=list)
    failures: list[Failure] = Field(default_factory=list)
    warnings: list[WarningItem] = Field(default_factory=list)


__all__ = [
    "AssetType",
    "AnalysisStatus",
    "SubjectType",
    "PeoplePresence",
    "ShotScale",
    "ShotFunction",
    "SimilarSelection",
    "EditCandidateStatus",
    "ClipSuggestion",
    "Asset",
    "SimilarGroup",
    "DefaultCandidate",
    "Failure",
    "WarningItem",
    "ProjectInfo",
    "Capabilities",
    "AnalysisInfo",
    "ClusteringInfo",
    "CutIndex",
]
