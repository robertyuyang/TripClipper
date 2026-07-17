"""Rough-cut plan contract models, IO, and validation."""

from .io import read_rough_cut_plan, write_rough_cut_plan
from .models import (
    ROUGH_CUT_PLAN_SCHEMA_VERSION,
    PlanWarning,
    RoughCutIntent,
    RoughCutPlan,
    RoughCutProjectRef,
    RoughCutSegment,
    RoughCutSourceSnapshot,
    TextOverlay,
    TimeRange,
    TransitionPlan,
    UnusedAsset,
)
from .planner import HeuristicRoughCutPlanner, RoughCutPlanRequest
from .validator import RoughCutValidationError, validate_rough_cut_plan

__all__ = [
    "ROUGH_CUT_PLAN_SCHEMA_VERSION",
    "PlanWarning",
    "RoughCutIntent",
    "RoughCutPlan",
    "RoughCutProjectRef",
    "RoughCutSegment",
    "RoughCutSourceSnapshot",
    "TextOverlay",
    "TimeRange",
    "TransitionPlan",
    "UnusedAsset",
    "HeuristicRoughCutPlanner",
    "RoughCutPlanRequest",
    "read_rough_cut_plan",
    "write_rough_cut_plan",
    "RoughCutValidationError",
    "validate_rough_cut_plan",
]
