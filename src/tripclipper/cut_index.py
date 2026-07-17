"""Read/write, schema validation and stable id generation for cut_index.json."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Union

from . import SCHEMA_VERSION
from .config import ProjectConfig, SoftwareConfig, load_software_config
from .models import CutIndex, ProjectInfo
from .security import summarize_model_config

_PathLike = Union[str, Path]


class SchemaVersionError(Exception):
    """Raised when a cut_index.json schema_version is incompatible."""


def _utc_now_iso() -> str:
    """Current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def check_schema_compatible(version: str) -> bool:
    """Return True when ``version`` is compatible with the current schema.

    Schema 0.4 explicitly accepts 0.3 so audio fields can be populated
    incrementally. Older or newer versions remain incompatible.
    """
    if version is None:
        raise SchemaVersionError("Missing schema_version in cut_index.json")
    if str(version) not in {"0.3", SCHEMA_VERSION}:
        raise SchemaVersionError(
            f"Incompatible schema_version {version!r}; "
            f"this build requires {SCHEMA_VERSION!r}. Refusing to migrate silently. "
            f"Suggestion: run `tripclipper analyze <slug> --stage full --force` "
            f"to regenerate analysis under the current schema."
        )
    return True


def generate_asset_id(relative_path: str) -> str:
    """Deterministically derive an ``asset_id`` from a relative path.

    ``"asset_" + sha1(relative_path)[:12]``. Stable across runs for the same
    path; distinct paths yield distinct ids.
    """
    digest = hashlib.sha1(relative_path.encode("utf-8")).hexdigest()
    return "asset_" + digest[:12]


def init_cut_index(
    config: ProjectConfig, software: SoftwareConfig | None = None
) -> CutIndex:
    """Build an empty :class:`CutIndex` from a :class:`ProjectConfig`."""
    resolved_software = software or load_software_config(
        legacy_project_path=config.config_path
    )
    now = _utc_now_iso()
    project = ProjectInfo(
        project_name=config.project_name,
        project_slug=config.project_slug,
        source_folder=config.source_folder,
        config_path=config.config_path,
        editing_intent=config.editing_intent.model_dump(),
        model_config_summary=summarize_model_config(resolved_software.llm),
        eagle_sync=config.eagle_sync.model_dump(),
        created_at=now,
        updated_at=now,
    )
    return CutIndex(schema_version=SCHEMA_VERSION, project=project)


def write_cut_index(path: _PathLike, cut_index: CutIndex) -> None:
    """Serialise ``cut_index`` to ``path`` as UTF-8 JSON (creating parents)."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    cut_index.schema_version = SCHEMA_VERSION
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
    data["schema_version"] = SCHEMA_VERSION
    return CutIndex.model_validate(data)


__all__ = [
    "SchemaVersionError",
    "check_schema_compatible",
    "generate_asset_id",
    "init_cut_index",
    "write_cut_index",
    "read_cut_index",
]
