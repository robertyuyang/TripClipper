"""Read/write, schema validation and stable id generation for cut_index.json."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Union

from . import SCHEMA_VERSION
from .config import ProjectConfig
from .models import CutIndex, ProjectInfo
from .security import summarize_model_config

_PathLike = Union[str, Path]


class SchemaVersionError(Exception):
    """Raised when a cut_index.json schema_version is incompatible."""


def _utc_now_iso() -> str:
    """Current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _major(version: str) -> str:
    """Return the major component (before the first dot) of a version string."""
    return str(version).split(".")[0]


def check_schema_compatible(version: str) -> bool:
    """Return True when ``version`` is compatible with the current schema.

    Compatibility rule: the major version (the segment before the first dot)
    must equal the current major version. Minor versions are backward
    compatible. Raises :class:`SchemaVersionError` on incompatibility.
    """
    if version is None:
        raise SchemaVersionError("Missing schema_version in cut_index.json")
    if _major(version) != _major(SCHEMA_VERSION):
        raise SchemaVersionError(
            f"Incompatible schema_version {version!r}; "
            f"this build supports major version {_major(SCHEMA_VERSION)!r} "
            f"(current schema {SCHEMA_VERSION!r}). Refusing to migrate silently."
        )
    return True


def generate_asset_id(relative_path: str) -> str:
    """Deterministically derive an ``asset_id`` from a relative path.

    ``"asset_" + sha1(relative_path)[:12]``. Stable across runs for the same
    path; distinct paths yield distinct ids.
    """
    digest = hashlib.sha1(relative_path.encode("utf-8")).hexdigest()
    return "asset_" + digest[:12]


def init_cut_index(config: ProjectConfig) -> CutIndex:
    """Build an empty :class:`CutIndex` from a :class:`ProjectConfig`."""
    now = _utc_now_iso()
    project = ProjectInfo(
        project_name=config.project_name,
        project_slug=config.project_slug,
        source_folder=config.source_folder,
        config_path=config.config_path,
        editing_intent=config.editing_intent.model_dump(),
        model_config_summary=summarize_model_config(config.llm),
        eagle_sync=config.eagle_sync.model_dump(),
        created_at=now,
        updated_at=now,
    )
    return CutIndex(schema_version=SCHEMA_VERSION, project=project)


def write_cut_index(path: _PathLike, cut_index: CutIndex) -> None:
    """Serialise ``cut_index`` to ``path`` as UTF-8 JSON (creating parents)."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = cut_index.model_dump(mode="json", by_alias=True, exclude_none=False)
    with target.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)


def read_cut_index(path: _PathLike) -> CutIndex:
    """Read, version-check and validate a ``cut_index.json`` file.

    Raises :class:`SchemaVersionError` on incompatible major version and a
    pydantic ``ValidationError`` on invalid field values (e.g. illegal enums).
    """
    source = Path(path)
    with source.open("r", encoding="utf-8") as fh:
        data = json.load(fh)

    check_schema_compatible(data.get("schema_version"))
    return CutIndex.model_validate(data)


__all__ = [
    "SchemaVersionError",
    "check_schema_compatible",
    "generate_asset_id",
    "init_cut_index",
    "write_cut_index",
    "read_cut_index",
]
