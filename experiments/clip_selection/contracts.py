"""四套选片 Harness 共用的数据契约与端口。"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ClipStatus(str, Enum):
    primary = "primary"
    alternate = "alternate"
    excluded = "excluded"
    needs_review = "needs_review"


class RunStatus(str, Enum):
    running = "running"
    completed = "completed"
    incomplete = "incomplete"


class SelectionBrief(StrictModel):
    target_duration_sec: float = Field(gt=0)
    style: str = Field(min_length=1)
    max_review_clips: int = Field(ge=0)
    audience: str | None = None
    people_focus: str | None = None
    audio_priority: str | None = None


class CandidateClip(StrictModel):
    clip_id: str = Field(min_length=1)
    asset_id: str = Field(min_length=1)
    start_sec: float = Field(ge=0)
    end_sec: float = Field(gt=0)
    source: str
    status: ClipStatus
    evidence: str = ""
    project_role: str = ""
    categories: list[str] = Field(default_factory=list)
    alternate_for: str | None = None
    review_reason: str | None = None

    @model_validator(mode="after")
    def validate_range(self) -> "CandidateClip":
        if self.end_sec <= self.start_sec:
            raise ValueError("end_sec must be greater than start_sec")
        return self


class ContentCategory(StrictModel):
    category_id: str
    label: str
    required: bool = False


class AgentAction(StrictModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class AgentDecision(StrictModel):
    action: AgentAction
    rationale: str = ""


class SelectionRun(StrictModel):
    schema_version: int = 1
    selection_id: str
    project_slug: str
    brief: SelectionBrief
    source_cut_index: str | None = None
    source_cut_index_sha256: str | None = None
    run_status: RunStatus = RunStatus.running
    clips: list[CandidateClip] = Field(default_factory=list)
    categories: list[ContentCategory] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)
    observations: list[str] = Field(default_factory=list)
    action_trace: list[str] = Field(default_factory=list)
    rounds: int = 0
    frame_requests: int = 0
    rejected_actions: int = 0
    checkpoint_count: int = 0


class RunBudget(StrictModel):
    max_rounds: int = Field(default=20, ge=1)
    max_frame_requests: int = Field(default=8, ge=0)


class AssetSnapshot(StrictModel):
    asset_id: str
    duration_sec: float | None = None
    path: str | None = None
    relative_path: str | None = None
    summary: str | None = None
    rating: int | None = None
    clip_suggestions: list[dict[str, Any]] = Field(default_factory=list)
    frame_paths: list[str] = Field(default_factory=list)
    frame_timestamps: list[float] = Field(default_factory=list)


class FrameObservation(StrictModel):
    asset_id: str
    start_sec: float
    end_sec: float
    frame_paths: list[str] = Field(default_factory=list)
    description: str = ""


class ModelClient(Protocol):
    def decide(
        self,
        system_prompt: str,
        context: dict[str, Any],
        images: list[Path] | None = None,
    ) -> AgentDecision: ...


class FrameSource(Protocol):
    def inspect(self, asset_id: str, start_sec: float, end_sec: float) -> FrameObservation: ...

