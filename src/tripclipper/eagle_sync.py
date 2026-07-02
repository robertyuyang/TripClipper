"""M6 Eagle sync — a thin cut_index-field to Eagle-write-dimension mapping layer.

Per ADR-004 (`docs/adr/ADR-004-eagle-sync-as-thin-mapping-layer.md`) and the
M6 spec (`docs/specs/M6-eagle-sync/spec.md`), this module maps each
``cut_index`` asset field to an Eagle write dimension (rating / tag / note)
WITHOUT inventing tag names, business filters, or folder structure. Semantics
stay upstream in the cut_index field values.

The module is organised as four layers:

1. ``EagleV2Client`` — a thin ``httpx``-based wrapper over the Eagle Web API
   (``http://localhost:41595``). Eagle 4.x exposes a hybrid V1/V2 API: item
   read/write mutations (``item/addFromPath``, ``item/moveToTrash``) still
   live under the ``/api/`` prefix, while ``library/info``, ``item/update``
   and the ``tagGroup/*`` family live under ``/api/v2/``. Authentication is
   done via the ``?token=`` query parameter (not an Authorization header).
   Version < 4.0 Build 22 (no V2 endpoints reachable) surfaces as
   :class:`EagleVersionError`; an unreachable Eagle surfaces as
   :class:`EagleUnavailableError`.
2. Mapping loader — :func:`load_mapping_config` reads the packaged default
   ``eagle_mapping.default.yaml`` and shallow-merges optional project overrides
   into an immutable :class:`MappingConfig`.
3. ``AssetMapper`` — turns one :class:`~tripclipper.models.Asset` plus a
   :class:`MappingConfig` into an :class:`AssetWritePlan` (tags / rating /
   annotation / item name / source path / tag-group updates).
4. ``EagleSyncRunner`` — walks a ``CutIndex``, plans each asset, drives the
   client (dry-run vs apply), maintains tag groups idempotently (server does
   NOT dedupe tag groups by name, so we build a name→id map from the initial
   ``library/info`` snapshot), tolerates per-asset failures, hard-aborts
   after N consecutive network failures, and produces an
   :class:`EagleApplyResult`.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import httpx
import yaml

from .config import ConfigError
from .paths import eagle_mapping_default_template_path

# ---------------------------------------------------------------------------
# LAYER 1: EagleV2Client
# ---------------------------------------------------------------------------

_VALID_TARGETS = frozenset({"tag", "eagle_rating", "note_section"})
_VALID_SMART_FOLDER_ICON_COLORS = frozenset(
    {"red", "orange", "yellow", "green", "aqua", "blue", "purple", "pink"}
)
_VALID_SMART_FOLDER_MATCH = frozenset({"AND", "OR"})


@dataclass
class EagleClientError(Exception):
    """Base error for Eagle V2 client calls. Never carries secrets."""

    stage: str
    cause: Optional[Exception] = None
    http_status: Optional[int] = None

    def __str__(self) -> str:  # human-readable, no secrets
        parts = [f"Eagle API call failed at stage {self.stage!r}"]
        if self.http_status is not None:
            parts.append(f"HTTP {self.http_status}")
        if self.cause is not None:
            parts.append(f"cause: {type(self.cause).__name__}: {self.cause}")
        return "; ".join(parts)


class EagleUnavailableError(EagleClientError):
    """Eagle is unreachable (connection refused / timeout)."""


class EagleVersionError(EagleClientError):
    """Eagle is running but the V2 API is unavailable (V1-only / too old)."""

    def __str__(self) -> str:
        return (
            f"Eagle V2 API unavailable at stage {self.stage!r}"
            f"{f' (HTTP {self.http_status})' if self.http_status is not None else ''}"
            "：需要 Eagle V2 API（≥ 4.0 Build 22），请升级 Eagle。"
        )


@dataclass(frozen=True)
class EagleItem:
    item_id: str
    name: str
    path: str
    tags: list[str]
    rating: Optional[int]
    annotation: str


_TIMEOUT_EXCEPTIONS = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.TimeoutException,
)


class EagleV2Client:
    """Thin wrapper over the Eagle Web API using ``httpx``.

    Eagle 4.x exposes a hybrid V1/V2 API on ``http://localhost:41595``:

    - ``/api/v2/library/info`` (used for both health and tag group snapshot),
      ``/api/v2/item/update``, ``/api/v2/tagGroup/{create,update,remove}``
    - ``/api/item/addFromPath``, ``/api/item/moveToTrash`` (V2 does not have
      these; they still live under ``/api/``)

    Authentication uses the ``?token=<uuid>`` query parameter — Eagle rejects
    ``Authorization: Bearer`` headers. All requests get the token appended
    automatically when ``api_token`` is set.
    """

    _V2 = "api/v2/"
    _V1 = "api/"

    def __init__(
        self,
        base_url: str = "http://localhost:41595",
        api_token: Optional[str] = None,
        timeout: float = 30.0,
        transport: Optional[httpx.BaseTransport] = None,
    ) -> None:
        # Tolerate old configs that still point at /api/v2/ or /api/ — we
        # route the prefix per-endpoint, so the client's ``base_url`` should
        # just be the host root.
        base_url = base_url.rstrip("/")
        for suffix in ("/api/v2", "/api"):
            if base_url.endswith(suffix):
                base_url = base_url[: -len(suffix)]
                break
        base_url = base_url.rstrip("/") + "/"
        self._api_token = api_token
        self._client = httpx.Client(
            base_url=base_url,
            timeout=timeout,
            transport=transport,
        )

    # -- context management -------------------------------------------------
    def __enter__(self) -> "EagleV2Client":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    # -- internal helpers ---------------------------------------------------
    def _with_token(self, params: Optional[dict]) -> Optional[dict]:
        if not self._api_token:
            return params
        merged = dict(params or {})
        merged.setdefault("token", self._api_token)
        return merged

    def _unwrap(self, resp: httpx.Response, path: str) -> Any:
        if resp.status_code >= 400:
            raise EagleClientError(stage=path, http_status=resp.status_code)
        try:
            payload = resp.json()
        except Exception as exc:  # noqa: BLE001 - defensive JSON parse
            raise EagleClientError(stage=path, cause=exc) from exc
        if isinstance(payload, dict) and payload.get("status") != "success":
            raise EagleClientError(stage=path, http_status=resp.status_code)
        if isinstance(payload, dict):
            return payload.get("data")
        return payload

    def _post(self, path: str, json: dict) -> Any:
        try:
            resp = self._client.post(path, json=json, params=self._with_token(None))
        except _TIMEOUT_EXCEPTIONS as exc:
            raise EagleUnavailableError(stage=path, cause=exc) from exc
        return self._unwrap(resp, path)

    def _get(self, path: str, params: Optional[dict] = None) -> Any:
        try:
            resp = self._client.get(path, params=self._with_token(params))
        except _TIMEOUT_EXCEPTIONS as exc:
            raise EagleUnavailableError(stage=path, cause=exc) from exc
        return self._unwrap(resp, path)

    @staticmethod
    def _extract_id(data: Any) -> str:
        if isinstance(data, str):
            return data
        if isinstance(data, dict):
            return str(data.get("id") or data.get("itemId") or "")
        return ""

    # -- public API ---------------------------------------------------------
    def fetch_library(self) -> dict:
        """GET ``/api/v2/library/info``.

        Doubles as both the startup health check (a 404 here means Eagle is
        running but too old to expose V2) and the source of truth for the
        current library's tag groups (Eagle has no independent
        ``tagGroup/list`` endpoint in either V1 or V2, so we read them from
        ``library/info`` instead).

        Returns a normalised dict::

            {"path": "/.../foo.library", "tag_groups": [{"id","name","tags"}...]}
        """
        path = self._V2 + "library/info"
        try:
            resp = self._client.get(path, params=self._with_token(None))
        except _TIMEOUT_EXCEPTIONS as exc:
            raise EagleUnavailableError(stage=path, cause=exc) from exc
        if resp.status_code == 404:
            raise EagleVersionError(stage=path, http_status=404)
        data = self._unwrap(resp, path)
        if not isinstance(data, dict):
            return {"path": None, "tag_groups": []}
        raw_groups = data.get("tagsGroups") or []
        tag_groups = [
            {
                "id": str(g.get("id") or ""),
                "name": g.get("name") or "",
                "tags": list(g.get("tags") or []),
            }
            for g in raw_groups
            if isinstance(g, dict)
        ]
        return {
            "path": data.get("path") or data.get("library"),
            "tag_groups": tag_groups,
        }

    # Back-compat alias so callers that still say ``health_check()`` keep
    # working. Returns the raw upstream ``data`` dict (with ``tagsGroups``
    # etc.) — matches the pre-refactor contract.
    def health_check(self) -> dict:
        path = self._V2 + "library/info"
        try:
            resp = self._client.get(path, params=self._with_token(None))
        except _TIMEOUT_EXCEPTIONS as exc:
            raise EagleUnavailableError(stage=path, cause=exc) from exc
        if resp.status_code == 404:
            raise EagleVersionError(stage=path, http_status=404)
        data = self._unwrap(resp, path)
        return data if isinstance(data, dict) else {}

    def add_from_path(
        self,
        path: str,
        name: str,
        tags: list[str],
        rating: Optional[int],
        annotation: str,
        folder_id: Optional[str] = None,
    ) -> str:
        body: dict[str, Any] = {
            "path": path,
            "name": name,
            "tags": tags,
            "annotation": annotation,
        }
        if rating is not None:
            body["star"] = rating
        if folder_id:
            body["folderId"] = folder_id
        # V1-only endpoint (V2 returns 404 "method not allowed").
        data = self._post(self._V1 + "item/addFromPath", body)
        return self._extract_id(data)

    def update_item(
        self,
        item_id: str,
        *,
        tags: Optional[list[str]] = None,
        rating: Optional[int] = None,
        annotation: Optional[str] = None,
    ) -> None:
        body: dict[str, Any] = {"id": item_id}
        if tags is not None:
            body["tags"] = tags
        if rating is not None:
            body["star"] = rating
        if annotation is not None:
            body["annotation"] = annotation
        self._post(self._V2 + "item/update", body)

    def move_to_trash(self, item_ids: list[str]) -> None:
        # V1-only endpoint.
        self._post(self._V1 + "item/moveToTrash", {"itemIds": item_ids})

    def tag_group_create(self, name: str, tags: list[str]) -> str:
        data = self._post(
            self._V2 + "tagGroup/create", {"name": name, "tags": tags}
        )
        return self._extract_id(data)

    def folder_create(self, name: str, parent_id: Optional[str] = None) -> str:
        """Create an Eagle folder and return its id.

        Wraps ``POST /api/v2/folder/create``; symmetric with
        :meth:`tag_group_create`. ``parent_id`` is optional — session folders
        are created flat (session-splitting spec Q13).
        """
        body: dict[str, Any] = {"name": name}
        if parent_id:
            body["parent"] = parent_id
        data = self._post(self._V2 + "folder/create", body)
        return self._extract_id(data)

    def smart_folder_list(self) -> list[dict]:
        """Return the raw smart-folder list from Eagle V2."""
        data = self._get(self._V2 + "smartFolder/get")
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and isinstance(data.get("data"), list):
            return data["data"]
        return []

    def smart_folder_create(self, payload: dict) -> str:
        """Create one smart folder and return its id."""
        data = self._post(self._V2 + "smartFolder/create", payload)
        folder_id = self._extract_id(data)
        if not folder_id:
            raise EagleClientError(stage=self._V2 + "smartFolder/create")
        return folder_id

    def smart_folder_update(self, folder_id: str, payload: dict) -> None:
        """Update one smart folder; caller supplies payload without ``id``."""
        body = dict(payload)
        body["id"] = folder_id
        self._post(self._V2 + "smartFolder/update", body)

    def tag_group_update(
        self,
        group_id: str,
        *,
        name: Optional[str] = None,
        tags: Optional[list[str]] = None,
    ) -> None:
        """Full-overwrite update: pass the desired ``tags`` list to replace
        the group's tag membership. Used by the idempotency path in the
        runner (server does NOT dedupe tag groups by name, so we always
        overwrite rather than accumulate)."""
        body: dict[str, Any] = {"id": group_id}
        if name is not None:
            body["name"] = name
        if tags is not None:
            body["tags"] = tags
        self._post(self._V2 + "tagGroup/update", body)

    def tag_group_remove(self, group_ids: list[str]) -> None:
        """Delete tag groups by id. Used only by cleanup tooling; the normal
        sync loop never removes groups."""
        self._post(self._V2 + "tagGroup/remove", {"itemIds": group_ids})


# ---------------------------------------------------------------------------
# LAYER 2: MappingConfig + loader
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TargetSpec:
    target: str  # "tag" | "eagle_rating" | "note_section"
    title: Optional[str] = None
    order: Optional[int] = None
    renderer: Optional[str] = None


@dataclass(frozen=True)
class NoteTemplate:
    header: str
    empty_section_behavior: str  # "skip" | "render_empty"
    section_format: str


@dataclass(frozen=True)
class SmartFolderRule:
    property: str
    method: str
    value: str


@dataclass(frozen=True)
class SmartFolderPreset:
    key: str
    name: str
    icon_color: Optional[str]
    match: str
    rules: tuple[SmartFolderRule, ...]


@dataclass(frozen=True)
class MappingConfig:
    tag_prefix: str
    project_tag_field: str
    auto_map_unknown: bool
    mappings: dict[str, TargetSpec]
    skip_fields: frozenset[str]
    note_template: NoteTemplate
    connection_failure_threshold: int
    smart_folder_presets: tuple[SmartFolderPreset, ...] = ()


def _build_target_spec(field_name: str, raw: dict) -> TargetSpec:
    target = raw.get("target")
    if target not in _VALID_TARGETS:
        raise ConfigError(
            f"Invalid mapping target: {target!r} for field {field_name}"
        )
    return TargetSpec(
        target=target,
        title=raw.get("title"),
        order=raw.get("order"),
        renderer=raw.get("renderer"),
    )


def _build_smart_folder_preset(raw: dict) -> SmartFolderPreset:
    key = raw.get("key")
    name = raw.get("name")
    icon_color = raw.get("icon_color")
    match = raw.get("match")
    rules_raw = raw.get("rules") or []

    if not isinstance(key, str) or not key:
        raise ConfigError(f"smart_folder preset missing valid 'key': {raw!r}")
    if not isinstance(name, str) or not name:
        raise ConfigError(
            f"smart_folder preset {key!r} missing valid 'name': {raw!r}"
        )
    if icon_color is not None and icon_color not in _VALID_SMART_FOLDER_ICON_COLORS:
        raise ConfigError(
            f"smart_folder preset {key!r} has invalid icon_color={icon_color!r}"
        )
    if match not in _VALID_SMART_FOLDER_MATCH:
        raise ConfigError(
            f"smart_folder preset {key!r} has invalid match={match!r}"
        )
    if not rules_raw:
        raise ConfigError(f"smart_folder preset {key!r} has empty rules")

    rules: list[SmartFolderRule] = []
    for rule in rules_raw:
        if not isinstance(rule, dict):
            raise ConfigError(
                f"smart_folder preset {key!r} has invalid rule: {rule!r}"
            )
        value = rule.get("value")
        if isinstance(value, list):
            if not value or not isinstance(value[0], str):
                raise ConfigError(
                    f"smart_folder preset {key!r} has invalid rule value: {value!r}"
                )
            value = value[0]
        if not isinstance(value, str) or not value:
            raise ConfigError(
                f"smart_folder preset {key!r} has invalid rule value: {value!r}"
            )
        rules.append(
            SmartFolderRule(
                property=str(rule.get("property") or ""),
                method=str(rule.get("method") or ""),
                value=value,
            )
        )

    return SmartFolderPreset(
        key=key,
        name=name,
        icon_color=icon_color,
        match=match,
        rules=tuple(rules),
    )


def load_mapping_config(project_overrides: Optional[dict] = None) -> MappingConfig:
    """Load the packaged default mapping and shallow-merge project overrides."""
    with eagle_mapping_default_template_path().open("r", encoding="utf-8") as fh:
        base = yaml.safe_load(fh) or {}
    if not isinstance(base, dict):
        raise ConfigError("Default eagle mapping must be a mapping/object")

    overrides = project_overrides or {}
    if not isinstance(overrides, dict):
        raise ConfigError("mapping overrides must be a mapping/object")

    # -- top-level scalars --------------------------------------------------
    tag_prefix = overrides.get("tag_prefix", base.get("tag_prefix"))
    if not isinstance(tag_prefix, str) or not tag_prefix:
        raise ConfigError("tag_prefix must be a non-empty string")

    project_tag_field = overrides.get(
        "project_tag_field", base.get("project_tag_field", "project")
    )
    auto_map_unknown = bool(
        overrides.get("auto_map_unknown", base.get("auto_map_unknown", True))
    )
    connection_failure_threshold = int(
        overrides.get(
            "connection_failure_threshold",
            base.get("connection_failure_threshold", 5),
        )
    )

    # -- mappings (field-level merge) --------------------------------------
    raw_mappings: dict[str, dict] = dict(base.get("mappings") or {})
    for name, spec in (overrides.get("mappings") or {}).items():
        raw_mappings[name] = spec  # override the whole TargetSpec for the field
    mappings = {
        name: _build_target_spec(name, raw or {})
        for name, raw in raw_mappings.items()
    }

    # -- skip_fields (union) -----------------------------------------------
    skip_fields = set(base.get("skip_fields") or [])
    skip_fields.update(overrides.get("skip_fields") or [])

    # -- note_template (key-wise merge) ------------------------------------
    raw_note = dict(base.get("note_template") or {})
    raw_note.update(overrides.get("note_template") or {})
    note_template = NoteTemplate(
        header=raw_note.get(
            "header", "_TripClipper · {project_slug} · synced {sync_timestamp}_"
        ),
        empty_section_behavior=raw_note.get("empty_section_behavior", "skip"),
        section_format=raw_note.get("section_format", "markdown_h2"),
    )

    # -- smart folders (default + key-based full replacement) --------------
    base_smart_folders = [
        _build_smart_folder_preset(raw)
        for raw in (base.get("smart_folders") or [])
    ]
    merged_by_key = {preset.key: preset for preset in base_smart_folders}
    default_order = [preset.key for preset in base_smart_folders]
    appended_order: list[str] = []
    for raw in overrides.get("smart_folders") or []:
        preset = _build_smart_folder_preset(raw)
        if preset.key not in merged_by_key:
            appended_order.append(preset.key)
        merged_by_key[preset.key] = preset
    smart_folder_presets = tuple(
        [merged_by_key[key] for key in default_order]
        + [merged_by_key[key] for key in appended_order]
    )

    return MappingConfig(
        tag_prefix=tag_prefix,
        project_tag_field=project_tag_field,
        auto_map_unknown=auto_map_unknown,
        mappings=mappings,
        skip_fields=frozenset(skip_fields),
        note_template=note_template,
        connection_failure_threshold=connection_failure_threshold,
        smart_folder_presets=smart_folder_presets,
    )


# ---------------------------------------------------------------------------
# Smart folder reconcile support
# ---------------------------------------------------------------------------


@dataclass
class SmartFolderWarning:
    key: str
    name: str
    error: str

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


@dataclass
class SmartFolderReconcileResult:
    created: list[str] = dataclasses.field(default_factory=list)
    updated: list[str] = dataclasses.field(default_factory=list)
    unchanged: list[str] = dataclasses.field(default_factory=list)
    warnings: list[SmartFolderWarning] = dataclasses.field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "created": list(self.created),
            "updated": list(self.updated),
            "unchanged": list(self.unchanged),
            "warnings": [warning.to_dict() for warning in self.warnings],
        }


class SmartFolderPlanner:
    """Render and reconcile Eagle smart-folder presets."""

    _NAMESPACE_PREFIX = "TC · "

    def __init__(
        self,
        client: Any,
        presets: tuple[SmartFolderPreset, ...],
        project_slug: str,
    ) -> None:
        self.client = client
        self.presets = presets
        self.project_slug = project_slug

    def render_conditions(self, preset: SmartFolderPreset) -> list[dict]:
        return [
            {
                "match": preset.match,
                "rules": [
                    {
                        "property": rule.property,
                        "method": rule.method,
                        "value": [
                            rule.value.format(project_slug=self.project_slug)
                        ],
                    }
                    for rule in preset.rules
                ],
            }
        ]

    def render_payload(self, preset: SmartFolderPreset) -> dict:
        payload: dict[str, Any] = {
            "name": preset.name.format(project_slug=self.project_slug),
            "conditions": self.render_conditions(preset),
        }
        if preset.icon_color is not None:
            payload["iconColor"] = preset.icon_color
        return payload

    def _conditions_equal(
        self, existing_conditions: list[dict], target_conditions: list[dict]
    ) -> bool:
        def _normalize(conditions: list[dict]) -> list[tuple[Any, tuple[Any, ...]]]:
            normalized: list[tuple[Any, tuple[Any, ...]]] = []
            for condition in conditions or []:
                rules = tuple(
                    sorted(
                        (
                            rule.get("property"),
                            rule.get("method"),
                            tuple(rule.get("value") or []),
                        )
                        for rule in (condition.get("rules") or [])
                    )
                )
                normalized.append((condition.get("match"), rules))
            return sorted(normalized)

        return _normalize(existing_conditions) == _normalize(target_conditions)

    def reconcile(self) -> SmartFolderReconcileResult:
        result = SmartFolderReconcileResult()
        existing = self.client.smart_folder_list()
        existing_by_name = {
            folder["name"]: folder
            for folder in existing
            if isinstance(folder, dict)
            and str(folder.get("name", "")).startswith(self._NAMESPACE_PREFIX)
        }

        for preset in self.presets:
            payload = self.render_payload(preset)
            name = payload["name"]
            existing_folder = existing_by_name.get(name)
            try:
                if existing_folder is None:
                    self.client.smart_folder_create(payload)
                    result.created.append(name)
                elif self._conditions_equal(
                    existing_folder.get("conditions", []),
                    payload["conditions"],
                ):
                    result.unchanged.append(name)
                else:
                    self.client.smart_folder_update(existing_folder["id"], payload)
                    result.updated.append(name)
            except EagleClientError as exc:
                result.warnings.append(
                    SmartFolderWarning(key=preset.key, name=name, error=str(exc))
                )

        return result


# ---------------------------------------------------------------------------
# LAYER 3: AssetMapper
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AssetWritePlan:
    tags: list[str]
    rating: Optional[int]
    annotation: str
    item_name: str
    source_path: str
    tag_group_updates: dict[str, list[str]]  # group_name -> [tags]
    unknown_warnings: list[str]  # fields skipped due to strict mapping


def _get(obj: Any, key: str) -> Any:
    """Attribute/dict accessor that also handles the ClipSuggestion ``in``
    alias (attribute ``in_``)."""
    if isinstance(obj, dict):
        if key == "in":
            return obj.get("in", obj.get("in_"))
        return obj.get(key)
    if key == "in":
        return getattr(obj, "in_", None)
    return getattr(obj, key, None)


def _render_text_block(value: Any) -> str:
    if not value:
        return ""
    return str(value).strip()


def _render_clip_suggestions_list(value: Any) -> str:
    if not value:
        return ""
    lines: list[str] = []
    for clip in value:
        in_v = _get(clip, "in")
        out_v = _get(clip, "out")
        rating = _get(clip, "rating")
        reason = _get(clip, "reason")
        line = f"- `{in_v} → {out_v}`"
        if rating is not None:
            line += f" [★{rating}]"
        if reason:
            line += f" {reason}"
        lines.append(line)
    return "\n".join(lines)


def _render_failures_list(value: Any) -> str:
    if not value:
        return ""
    lines: list[str] = []
    for item in value:
        reason = _get(item, "reason") if not isinstance(item, str) else item
        if reason is None:
            reason = str(item)
        lines.append(f"- {reason}")
    return "\n".join(lines)


_RENDERERS = {
    "clip_suggestions_list": _render_clip_suggestions_list,
    "failures_list": _render_failures_list,
    "text_block": _render_text_block,
}


def _scalar_str(value: Any) -> str:
    if isinstance(value, Enum):
        return value.value
    return str(value)


class AssetMapper:
    """Maps one :class:`Asset` to an :class:`AssetWritePlan`."""

    def __init__(
        self, config: MappingConfig, project_slug: str, sync_timestamp: str
    ) -> None:
        self.config = config
        self.project_slug = project_slug
        self.sync_timestamp = sync_timestamp

    def plan(self, asset: Any) -> AssetWritePlan:
        cfg = self.config
        tags: list[str] = []
        rating: Optional[int] = None
        sections: list[tuple[int, str, str]] = []
        tag_group_updates: dict[str, list[str]] = {}
        unknown_warnings: list[str] = []

        def emit_tag(field_name: str, val: str) -> None:
            tag = f"{cfg.tag_prefix}:{field_name}:{val}"
            tags.append(tag)
            group = f"{cfg.tag_prefix}:{field_name}"
            tag_group_updates.setdefault(group, []).append(tag)

        def emit_value(field_name: str, value: Any) -> None:
            if value is None:
                return
            if isinstance(value, Enum):
                emit_tag(field_name, value.value)
            elif isinstance(value, bool):
                emit_tag(field_name, str(value).lower())
            elif isinstance(value, str):
                if value:
                    emit_tag(field_name, value)
            elif isinstance(value, (int, float)):
                emit_tag(field_name, str(value))
            elif isinstance(value, list):
                for element in value:
                    if isinstance(element, Enum):
                        emit_tag(field_name, element.value)
                    elif isinstance(element, str) and element:
                        emit_tag(field_name, element)
            # dict values are skipped silently

        # 2. project tag
        project_tag = (
            f"{cfg.tag_prefix}:{cfg.project_tag_field}:{self.project_slug}"
        )
        tags.append(project_tag)
        tag_group_updates[f"{cfg.tag_prefix}:{cfg.project_tag_field}"] = [
            project_tag
        ]

        # 3. iterate model fields
        for name in type(asset).model_fields:
            if name in cfg.skip_fields:
                continue
            value = getattr(asset, name, None)
            spec = cfg.mappings.get(name)

            if spec is not None:
                if spec.target == "eagle_rating":
                    if isinstance(value, int):
                        rating = value
                    continue
                if spec.target == "tag":
                    emit_value(name, value)
                    continue
                if spec.target == "note_section":
                    renderer = _RENDERERS.get(spec.renderer or "", _render_text_block)
                    rendered = renderer(value)
                    if rendered:
                        sections.append(
                            (spec.order or 999, spec.title or name, rendered)
                        )
                    elif cfg.note_template.empty_section_behavior == "render_empty":
                        sections.append((spec.order or 999, spec.title or name, ""))
                    continue

            # no spec
            if value is None or (isinstance(value, list) and not value):
                continue
            if cfg.auto_map_unknown:
                emit_value(name, value)
            else:
                unknown_warnings.append(name)

        # 4. annotation
        header = cfg.note_template.header.format(
            project_slug=self.project_slug, sync_timestamp=self.sync_timestamp
        )
        ordered = sorted(sections, key=lambda s: s[0])
        parts = [f"## {title}\n{rendered}" for _, title, rendered in ordered]
        annotation = header + ("\n\n" + "\n\n".join(parts) if parts else "")

        # 5. item name
        item_name = (
            getattr(asset, "filename", None)
            or (Path(asset.path).name if getattr(asset, "path", None) else None)
            or getattr(asset, "asset_id", None)
            or "unknown"
        )

        # 6. source path
        source_path = getattr(asset, "path", None) or ""

        return AssetWritePlan(
            tags=tags,
            rating=rating,
            annotation=annotation,
            item_name=item_name,
            source_path=source_path,
            tag_group_updates=tag_group_updates,
            unknown_warnings=unknown_warnings,
        )


# ---------------------------------------------------------------------------
# LAYER 4: EagleSyncRunner
# ---------------------------------------------------------------------------


@dataclass
class SyncOptions:
    apply: bool = False
    skip_synced: bool = False
    reset: bool = False
    retry_failed: bool = False
    skip_unanalyzed: bool = False
    strict_mapping: bool = False
    no_smart_folders: bool = False


@dataclass
class SyncFailure:
    asset_id: str
    asset_path: str
    stage: str
    error: str
    retryable: bool

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


@dataclass
class TagGroupWarning:
    tag_group: str
    missing_tags: int
    error: str

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


@dataclass
class EagleApplyResult:
    synced_at: str
    project_slug: str
    eagle_library_path: Optional[str]
    totals: dict
    failures: list  # of SyncFailure
    tag_group_warnings: list  # of TagGroupWarning
    aborted: bool
    abort_reason: Optional[str]
    folder_warnings: list = dataclasses.field(default_factory=list)  # of str
    smart_folders: Optional[SmartFolderReconcileResult] = None

    def to_dict(self) -> dict:
        payload = {
            "synced_at": self.synced_at,
            "project_slug": self.project_slug,
            "eagle_library_path": self.eagle_library_path,
            "totals": self.totals,
            "failures": [f.to_dict() for f in self.failures],
            "tag_group_warnings": [w.to_dict() for w in self.tag_group_warnings],
            "aborted": self.aborted,
            "abort_reason": self.abort_reason,
            "folder_warnings": list(self.folder_warnings),
        }
        if self.smart_folders is not None:
            payload["smart_folders"] = self.smart_folders.to_dict()
        return payload


class SyncPreconditionError(Exception):
    """Raised at startup when preconditions block the whole sync."""


class EagleAbortError(Exception):
    """Raised (or signalled) when the sync hard-aborts mid-run."""


def _dedupe(seq: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in seq:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


# Separator for Eagle session folder names (U+00B7 middle dot, space-padded);
# avoids characters Eagle rejects in folder names (session-splitting spec Q14).
SESSION_FOLDER_SEP = " · "

# Warning emitted when an already-synced asset can't be moved into a folder
# (Eagle's item/update has no folderId; session-splitting spec Q5=B).
FOLDER_SKIP_WARNING = "item already synced; folder assignment skipped"


def session_folder_name(slug: str, session: Any) -> str:
    """Human-readable Eagle folder name for one session (spec Q14).

    ``{slug} · {session_id} · {started_at:%Y-%m-%d %H:%M}`` for timed sessions;
    ``{slug} · session_00_unknown`` (no time) for the unknown bucket.
    """
    parts = [slug, session.session_id]
    started_at = getattr(session, "started_at", None)
    if started_at is not None:
        # started_at is stored in UTC; show local wall-clock time.
        if started_at.tzinfo is not None:
            started_at = started_at.astimezone()
        parts.append(started_at.strftime("%Y-%m-%d %H:%M"))
    return SESSION_FOLDER_SEP.join(parts)


class EagleSyncRunner:
    """Drives a full sync run over a ``CutIndex``."""

    def __init__(
        self,
        client: EagleV2Client,
        mapper: AssetMapper,
        config: MappingConfig,
        options: SyncOptions,
        eagle_library_path: Optional[str] = None,
    ) -> None:
        self.client = client
        self.mapper = mapper
        self.config = config
        self.options = options
        self.eagle_library_path = eagle_library_path

    def run(self, cut_index: Any) -> tuple[Any, EagleApplyResult]:
        opts = self.options
        assets = list(cut_index.assets)

        # 1. fetch library (health check + tag-group snapshot in one call).
        #    Raises EagleUnavailableError / EagleVersionError.
        library = self.client.fetch_library()
        existing_tag_groups_by_name: dict[str, dict] = {
            g["name"]: g for g in library.get("tag_groups", []) if g.get("name")
        }
        library_path = library.get("path")

        # 2. scanned precondition check
        if not opts.skip_unanalyzed:
            for asset in assets:
                if asset.analysis_status.value == "scanned":
                    raise SyncPreconditionError(
                        "存在未分析(scanned)素材；请先运行 analyze，"
                        "或加 --skip-unanalyzed。"
                    )

        # 3. totals
        totals = {
            "total": len(assets),
            "synced": 0,
            "failed": 0,
            "skipped": 0,
            "skipped_unanalyzed": 0,
        }

        failures: list[SyncFailure] = []
        tag_group_warnings: list[TagGroupWarning] = []

        # 4. reset branch
        if opts.apply and opts.reset:
            item_ids = [a.eagle_item_id for a in assets if a.eagle_item_id]
            if item_ids:
                self.client.move_to_trash(item_ids)
            for a in assets:
                if a.eagle_item_id:
                    a.eagle_item_id = None
                    a.eagle_sync_status = None

        # 5. merged tag groups
        merged_tag_groups: dict[str, list[str]] = {}

        # 6. failure tracking
        consecutive_network_failures = 0
        aborted = False
        abort_reason: Optional[str] = None

        # 6b. session folders (spec §4 / Q13 flat + Q14 naming). Old projects
        #     with no sessions degrade to plain root-level adds.
        cut_sessions = list(getattr(cut_index, "sessions", []) or [])
        sessions_by_id = {s.session_id: s for s in cut_sessions}
        session_folders_enabled = bool(cut_sessions)
        session_folder_id: dict[str, str] = {}
        folder_warnings: list[str] = []

        # 7. iterate assets
        for asset in assets:
            status = asset.analysis_status.value

            if status == "scanned":
                # only reachable when skip_unanalyzed is True
                totals["skipped_unanalyzed"] += 1
                continue
            if status not in {"analyzed", "analysis_failed"}:
                totals["skipped"] += 1
                continue
            if opts.retry_failed and asset.eagle_sync_status != "failed":
                totals["skipped"] += 1
                continue
            if opts.skip_synced and asset.eagle_sync_status == "synced":
                totals["skipped"] += 1
                continue

            plan = self.mapper.plan(asset)

            for group, group_tags in plan.tag_group_updates.items():
                merged_tag_groups.setdefault(group, []).extend(group_tags)

            if not opts.apply:
                # dry-run: count as "would sync", make no API calls
                totals["synced"] += 1
                continue

            # resolve session folder for the (new-item) apply path
            folder_id: Optional[str] = None
            if session_folders_enabled:
                if asset.eagle_item_id:
                    # Q5=B: item/update has no folderId; existing items stay put.
                    folder_warnings.append(
                        f"{asset.asset_id or asset.path or '?'}: {FOLDER_SKIP_WARNING}"
                    )
                elif asset.session_id and asset.session_id in sessions_by_id:
                    folder_id = session_folder_id.get(asset.session_id)
                    if folder_id is None:
                        session = sessions_by_id[asset.session_id]
                        try:
                            folder_id = self.client.folder_create(
                                session_folder_name(
                                    self.mapper.project_slug, session
                                )
                            )
                            session_folder_id[asset.session_id] = folder_id
                        except (EagleClientError, EagleUnavailableError) as exc:
                            folder_warnings.append(
                                f"session {asset.session_id}: "
                                f"folder_create failed: {exc}"
                            )
                            folder_id = None

            # apply path
            try:
                if asset.eagle_item_id:
                    self.client.update_item(
                        asset.eagle_item_id,
                        tags=plan.tags,
                        rating=plan.rating,
                        annotation=plan.annotation,
                    )
                else:
                    new_id = self.client.add_from_path(
                        plan.source_path,
                        plan.item_name,
                        plan.tags,
                        plan.rating,
                        plan.annotation,
                        folder_id=folder_id,
                    )
                    asset.eagle_item_id = new_id
                asset.eagle_sync_status = "synced"
                totals["synced"] += 1
                consecutive_network_failures = 0
            except EagleUnavailableError as exc:
                consecutive_network_failures += 1
                if (
                    consecutive_network_failures
                    >= self.config.connection_failure_threshold
                ):
                    aborted = True
                    abort_reason = (
                        "eagle_disconnected_after_5_consecutive_failures"
                    )
                    break
                asset.eagle_sync_status = "failed"
                totals["failed"] += 1
                failures.append(
                    SyncFailure(
                        asset.asset_id or "",
                        asset.path or "",
                        "network",
                        str(exc),
                        True,
                    )
                )
            except EagleClientError as exc:
                asset.eagle_sync_status = "failed"
                totals["failed"] += 1
                consecutive_network_failures = 0
                failures.append(
                    SyncFailure(
                        asset.asset_id or "",
                        asset.path or "",
                        getattr(exc, "stage", "apply"),
                        str(exc),
                        True,
                    )
                )

        # 8. tag group maintenance (idempotent).
        #    Eagle's server does NOT dedupe tag groups by name: POSTing the
        #    same name to tagGroup/create N times creates N distinct groups.
        #    We use the snapshot taken at step 1 to decide create-vs-update,
        #    and always full-overwrite existing groups' tags to match the
        #    current cut_index state (matches item/update overwrite semantics).
        if opts.apply and not aborted:
            for group_name, group_tags in merged_tag_groups.items():
                deduped = _dedupe(group_tags)
                try:
                    match = existing_tag_groups_by_name.get(group_name)
                    if match is not None:
                        group_id = match.get("id") or ""
                        if not group_id:
                            # Snapshot entry lacked an id (shouldn't happen);
                            # fall back to creating a fresh one.
                            self.client.tag_group_create(group_name, deduped)
                        else:
                            self.client.tag_group_update(
                                group_id, tags=deduped
                            )
                    else:
                        new_id = self.client.tag_group_create(group_name, deduped)
                        # Record so a subsequent call in the same run wouldn't
                        # duplicate — currently the loop only visits each name
                        # once, but this keeps the invariant honest.
                        existing_tag_groups_by_name[group_name] = {
                            "id": new_id,
                            "name": group_name,
                            "tags": deduped,
                        }
                except (EagleClientError, EagleUnavailableError) as exc:
                    tag_group_warnings.append(
                        TagGroupWarning(group_name, len(deduped), str(exc))
                    )

        # 9. smart folder maintenance (idempotent; post tag-group stage).
        smart_folders_result: Optional[SmartFolderReconcileResult] = None
        if opts.apply and not opts.no_smart_folders:
            if aborted:
                smart_folders_result = SmartFolderReconcileResult(
                    warnings=[
                        SmartFolderWarning(
                            key="_all",
                            name="",
                            error="skipped due to aborted sync",
                        )
                    ]
                )
            else:
                try:
                    planner = SmartFolderPlanner(
                        self.client,
                        self.config.smart_folder_presets,
                        self.mapper.project_slug,
                    )
                    smart_folders_result = planner.reconcile()
                except EagleUnavailableError as exc:
                    smart_folders_result = SmartFolderReconcileResult(
                        warnings=[
                            SmartFolderWarning(
                                key="_all",
                                name="",
                                error=f"Eagle unavailable during smart folder stage: {exc}",
                            )
                        ]
                    )

        # 10. build result
        project_slug = self.mapper.project_slug or getattr(
            getattr(cut_index, "project", None), "project_slug", None
        )
        effective_library_path = self.eagle_library_path or library_path
        result = EagleApplyResult(
            synced_at=datetime.now(timezone.utc).astimezone().isoformat(),
            project_slug=project_slug,
            eagle_library_path=effective_library_path,
            totals=totals,
            failures=failures,
            tag_group_warnings=tag_group_warnings,
            aborted=aborted,
            abort_reason=abort_reason,
            folder_warnings=folder_warnings,
            smart_folders=smart_folders_result,
        )
        return cut_index, result


__all__ = [
    # Layer 1
    "EagleV2Client",
    "EagleItem",
    "EagleClientError",
    "EagleUnavailableError",
    "EagleVersionError",
    # Layer 2
    "TargetSpec",
    "NoteTemplate",
    "SmartFolderRule",
    "SmartFolderPreset",
    "SmartFolderWarning",
    "SmartFolderReconcileResult",
    "SmartFolderPlanner",
    "MappingConfig",
    "load_mapping_config",
    # Layer 3
    "AssetWritePlan",
    "AssetMapper",
    # Layer 4
    "SyncOptions",
    "SyncFailure",
    "TagGroupWarning",
    "EagleApplyResult",
    "SyncPreconditionError",
    "EagleAbortError",
    "EagleSyncRunner",
    "session_folder_name",
    "SESSION_FOLDER_SEP",
    "FOLDER_SKIP_WARNING",
]
