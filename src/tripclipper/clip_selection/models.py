"""选片任务自己的状态模型，不写入 ``cut_index.json``。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class CategoryDraft(BaseModel):
    category_id: str | None = None
    name: str
    required: bool = True
    purpose: str
    missing_reason: str | None = None


class SelectionCategory(CategoryDraft):
    category_id: str


class SelectionCandidate(BaseModel):
    candidate_id: str
    asset_id: str
    start_sec: float
    end_sec: float
    status: Literal["primary", "alternate", "needs_review"] = "primary"
    category_ids: list[str] = Field(default_factory=list)
    recommended_use: str | None = None
    reason: str
    alternative_to_ids: list[str] = Field(default_factory=list)
    review_reason: str | None = None


class AssetInspection(BaseModel):
    asset_id: str
    category_ids: list[str] = Field(default_factory=list)
    shortlist_reason: str


class SampledRange(BaseModel):
    asset_id: str
    start_sec: float
    end_sec: float
    count: int
    frame_paths: list[str] = Field(default_factory=list)


class AssetProgress(BaseModel):
    listed_pages: list[int] = Field(default_factory=list)
    opened_asset_ids: list[str] = Field(default_factory=list)
    inspections: list[AssetInspection] = Field(default_factory=list)
    sampled_ranges: list[SampledRange] = Field(default_factory=list)


class SelectionState(BaseModel):
    schema_version: int = 1
    task_name: str
    status: Literal["running", "completed"] = "running"
    target_duration_sec: float
    categories: list[SelectionCategory] = Field(default_factory=list)
    asset_progress: AssetProgress = Field(default_factory=AssetProgress)
    candidates: list[SelectionCandidate] = Field(default_factory=list)
    unresolved: list[dict] = Field(default_factory=list)


__all__ = [
    "AssetInspection",
    "AssetProgress",
    "CategoryDraft",
    "SampledRange",
    "SelectionCandidate",
    "SelectionCategory",
    "SelectionState",
]
