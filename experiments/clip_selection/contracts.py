"""选片 Harness 的数据契约与端口。"""

from __future__ import annotations

from enum import Enum
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal, Protocol

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
    source: Literal["cut_index", "selection_agent"]
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
    latest_frame_paths: list[str] = Field(default_factory=list)
    last_finish_fingerprint: str | None = None


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


class ProjectSnapshot(StrictModel):
    project_slug: str
    cut_index_path: Path
    sha256: str
    source_folder: str | None = None
    assets: list[AssetSnapshot] = Field(default_factory=list)

    @classmethod
    def from_cut_index(cls, path: str | Path) -> "ProjectSnapshot":
        from tripclipper.cut_index import read_cut_index

        source = Path(path)
        raw = source.read_bytes()
        cut = read_cut_index(source)
        assets: list[AssetSnapshot] = []
        for asset in cut.assets:
            if not asset.asset_id:
                continue
            metadata = asset.metadata or {}
            duration_raw = metadata.get("duration", metadata.get("duration_s"))
            try:
                duration = float(duration_raw) if duration_raw is not None else None
            except (TypeError, ValueError):
                duration = None
            assets.append(
                AssetSnapshot(
                    asset_id=asset.asset_id,
                    duration_sec=duration,
                    path=asset.path,
                    relative_path=asset.relative_path,
                    summary=asset.summary,
                    rating=asset.rating,
                    clip_suggestions=[
                        item.model_dump(mode="json", by_alias=True)
                        for item in asset.clip_suggestions
                    ],
                    frame_paths=list(asset.frame_paths),
                    frame_timestamps=list(asset.frame_timestamps),
                )
            )
        return cls(
            project_slug=cut.project.project_slug or source.parent.name,
            cut_index_path=source,
            sha256=sha256(raw).hexdigest(),
            source_folder=cut.project.source_folder,
            assets=assets,
        )

    def asset(self, asset_id: str) -> AssetSnapshot:
        for item in self.assets:
            if item.asset_id == asset_id:
                return item
        raise ValueError(f"未知 asset_id: {asset_id}")


class FrameObservation(StrictModel):
    asset_id: str
    start_sec: float
    end_sec: float
    frame_paths: list[str] = Field(default_factory=list)
    description: str = ""


class SelectionRequest(StrictModel):
    selection_id: str
    project_slug: str
    cut_index_path: Path
    output_path: Path
    brief: SelectionBrief
    budget: RunBudget = Field(default_factory=RunBudget)


class ModelClient(Protocol):
    def decide(
        self,
        system_prompt: str,
        context: dict[str, Any],
        images: list[Path] | None = None,
    ) -> AgentDecision: ...


class FrameSource(Protocol):
    def inspect(self, asset_id: str, start_sec: float, end_sec: float) -> FrameObservation: ...
