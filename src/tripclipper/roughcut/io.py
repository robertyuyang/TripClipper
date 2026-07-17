"""JSON read/write helpers for ``rough_cut_plan.json``."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Union

from .models import RoughCutPlan

_PathLike = Union[str, Path]


def read_rough_cut_plan(path: _PathLike) -> RoughCutPlan:
    """Read and validate a rough-cut plan JSON file."""
    source = Path(path)
    with source.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    return RoughCutPlan.model_validate(payload)


def write_rough_cut_plan(path: _PathLike, plan: RoughCutPlan) -> None:
    """Serialize ``plan`` as stable UTF-8 JSON, creating parents as needed."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = plan.model_dump(mode="json", exclude_none=True)
    with target.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
