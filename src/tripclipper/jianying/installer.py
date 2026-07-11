"""Jianying 10 draft installer."""

from __future__ import annotations

import json
import shutil
from copy import deepcopy
from pathlib import Path
from typing import Any

from .models import (
    DraftInstallError,
    DraftInstallRequest,
    DraftInstallResult,
    InstallValidationItem,
)
from .paths import (
    bundled_template_dir,
    discover_jianying_drafts_dir,
    install_report_path,
    resolve_media_path,
    template_timeline_dir,
    unique_draft_dir,
)

_MEDIA_CONTAINERS = ("videos", "audios", "images")
_TEMPLATE_PLACEHOLDER = "__TRIPCLIPPER_JIANYING10_TEMPLATE__"
_COPIED_MEDIA_FACT_FIELDS = ("check_flag", "duration", "height", "width")


class Jianying10Installer:
    """Install an existing ``draft_content.json`` into a Jianying 10 draft shell."""

    def install(self, request: DraftInstallRequest) -> DraftInstallResult:
        report_path = install_report_path(request.draft_content_path)
        validation_items: list[InstallValidationItem] = []
        draft_dir: Path | None = None
        timeline_id: str | None = None

        try:
            draft_content_path, template_dir, drafts_dir = self._preflight_paths(
                request, validation_items
            )
            draft_content = self._load_draft_content(draft_content_path, validation_items)
            media_refs = self._collect_media_refs(
                draft_content, draft_content_path, validation_items
            )

            drafts_dir.mkdir(parents=True, exist_ok=True)
            draft_dir = unique_draft_dir(drafts_dir, request.draft_name)
            shutil.copytree(template_dir, draft_dir)
            validation_items.append(
                InstallValidationItem(
                    "copy_template", "ok", "Copied Jianying template shell", draft_dir
                )
            )

            timeline_id = template_timeline_dir(template_dir).name
            template_content = self._load_template_draft_content(template_dir)
            if template_content is not None and self._contains_template_placeholder(template_content):
                rewritten, copied_media_paths = self._fill_template_draft_content(
                    template_content,
                    draft_content,
                    draft_content_path,
                    draft_dir,
                    request.draft_name,
                    validation_items,
                )
            else:
                copied_media_paths = self._copy_media(media_refs, draft_dir)
                rewritten = self._rewrite_media_paths(draft_content, media_refs, copied_media_paths)
            rewritten["id"] = timeline_id
            rewritten["name"] = request.draft_name

            self._write_required_content_files(draft_dir, timeline_id, rewritten)
            self._update_structured_metadata(draft_dir, timeline_id, request.draft_name)

            result = DraftInstallResult(
                draft_dir=draft_dir,
                timeline_id=timeline_id,
                report_path=report_path,
                copied_media_paths={
                    source: copied_media_paths[source]
                    for source in sorted(copied_media_paths, key=str)
                },
                validation_items=validation_items,
            )
            self._write_report(
                report_path,
                status="success",
                message="Installed Jianying draft",
                request=request,
                template_dir=template_dir,
                drafts_dir=drafts_dir,
                result=result,
                validation_items=validation_items,
            )
            return result
        except Exception as exc:
            if draft_dir is not None and draft_dir.exists():
                shutil.rmtree(draft_dir, ignore_errors=True)

            if isinstance(exc, DraftInstallError):
                error = exc
            else:
                error = DraftInstallError(
                    str(exc),
                    validation_items=validation_items,
                    draft_dir=draft_dir,
                    timeline_id=timeline_id,
                )
            error.report_path = report_path
            error.draft_dir = draft_dir
            error.timeline_id = timeline_id

            self._write_report(
                report_path,
                status="failure",
                message=error.message,
                request=request,
                template_dir=request.template_draft_dir,
                drafts_dir=request.jianying_drafts_dir,
                result=None,
                validation_items=error.validation_items or validation_items,
            )
            raise error

    def _preflight_paths(
        self,
        request: DraftInstallRequest,
        validation_items: list[InstallValidationItem],
    ) -> tuple[Path, Path, Path]:
        draft_content_path = request.draft_content_path.expanduser()
        if not draft_content_path.is_file():
            validation_items.append(
                InstallValidationItem(
                    "draft_content_path",
                    "error",
                    "draft_content_path must point to an existing file",
                    draft_content_path,
                )
            )
            raise DraftInstallError(
                f"Invalid draft_content_path: {draft_content_path}",
                validation_items=validation_items,
            )
        validation_items.append(
            InstallValidationItem("draft_content_path", "ok", "Found draft content", draft_content_path)
        )

        template_dir = (
            request.template_draft_dir.expanduser()
            if request.template_draft_dir is not None
            else bundled_template_dir()
        )
        if not template_dir.is_dir():
            validation_items.append(
                InstallValidationItem(
                    "template_draft_dir",
                    "error",
                    "template_draft_dir must point to an existing Jianying draft shell",
                    template_dir,
                )
            )
            raise DraftInstallError(
                f"Invalid template_draft_dir: {template_dir}",
                validation_items=validation_items,
            )
        try:
            template_timeline_dir(template_dir)
        except FileNotFoundError as exc:
            validation_items.append(
                InstallValidationItem("template_draft_dir", "error", str(exc), template_dir)
            )
            raise DraftInstallError(str(exc), validation_items=validation_items) from exc
        validation_items.append(
            InstallValidationItem("template_draft_dir", "ok", "Found Jianying template shell", template_dir)
        )

        if request.jianying_drafts_dir is None:
            drafts_dir = discover_jianying_drafts_dir()
            if drafts_dir is None:
                validation_items.append(
                    InstallValidationItem(
                        "jianying_drafts_dir",
                        "error",
                        "Could not discover one local Jianying drafts directory; pass jianying_drafts_dir",
                    )
                )
                raise DraftInstallError(
                    "Could not discover jianying_drafts_dir",
                    validation_items=validation_items,
                )
        else:
            drafts_dir = request.jianying_drafts_dir.expanduser()

        if drafts_dir.exists() and not drafts_dir.is_dir():
            validation_items.append(
                InstallValidationItem(
                    "jianying_drafts_dir",
                    "error",
                    "jianying_drafts_dir must be a directory",
                    drafts_dir,
                )
            )
            raise DraftInstallError(
                f"Invalid jianying_drafts_dir: {drafts_dir}",
                validation_items=validation_items,
            )
        validation_items.append(
            InstallValidationItem(
                "jianying_drafts_dir", "ok", "Resolved Jianying drafts directory", drafts_dir
            )
        )

        return draft_content_path, template_dir, drafts_dir

    def _load_draft_content(
        self,
        draft_content_path: Path,
        validation_items: list[InstallValidationItem],
    ) -> dict[str, Any]:
        try:
            with draft_content_path.open("r", encoding="utf-8") as fh:
                payload = json.load(fh)
        except Exception as exc:
            validation_items.append(
                InstallValidationItem(
                    "draft_content_json", "error", f"Unable to read draft content JSON: {exc}"
                )
            )
            raise DraftInstallError(
                f"Unable to read draft_content_path: {draft_content_path}",
                validation_items=validation_items,
            ) from exc
        if not isinstance(payload, dict):
            raise DraftInstallError(
                "draft_content.json must contain a JSON object",
                validation_items=validation_items,
            )
        validation_items.append(
            InstallValidationItem("draft_content_json", "ok", "Loaded draft content JSON")
        )
        return payload

    def _collect_media_refs(
        self,
        draft_content: dict[str, Any],
        draft_content_path: Path,
        validation_items: list[InstallValidationItem],
    ) -> list[tuple[str, int, str, Path]]:
        materials = draft_content.get("materials", {})
        refs: list[tuple[str, int, str, Path]] = []
        errors: list[str] = []
        if not isinstance(materials, dict):
            return refs

        for container in _MEDIA_CONTAINERS:
            items = materials.get(container, [])
            if not isinstance(items, list):
                continue
            for index, item in enumerate(items):
                if not isinstance(item, dict):
                    continue
                raw_path = item.get("path")
                if not isinstance(raw_path, str) or not raw_path:
                    continue
                resolved = resolve_media_path(raw_path, draft_content_path=draft_content_path)
                if resolved is None or not resolved.is_file():
                    errors.append(f"materials.{container}[{index}].path media not readable: {raw_path}")
                    continue
                refs.append((container, index, raw_path, resolved))

        if errors:
            for message in errors:
                validation_items.append(InstallValidationItem("media", "error", message))
            raise DraftInstallError(
                "One or more referenced media files are not readable",
                validation_items=validation_items,
            )
        validation_items.append(
            InstallValidationItem("media", "ok", f"Validated {len(refs)} media references")
        )
        return refs

    def _copy_media(
        self,
        media_refs: list[tuple[str, int, str, Path]],
        draft_dir: Path,
    ) -> dict[Path, Path]:
        assets_dir = draft_dir / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        copied: dict[Path, Path] = {}
        used_names: set[str] = set()

        for _, _, _, source in media_refs:
            if source in copied:
                continue
            stem = source.stem or "media"
            suffix = source.suffix
            candidate_name = f"{stem}{suffix}"
            counter = 1
            while candidate_name in used_names or (assets_dir / candidate_name).exists():
                candidate_name = f"{stem}-{counter}{suffix}"
                counter += 1
            used_names.add(candidate_name)
            target = assets_dir / candidate_name
            shutil.copy2(source, target)
            copied[source] = target
        return copied

    def _rewrite_media_paths(
        self,
        draft_content: dict[str, Any],
        media_refs: list[tuple[str, int, str, Path]],
        copied_media_paths: dict[Path, Path],
    ) -> dict[str, Any]:
        rewritten = deepcopy(draft_content)
        materials = rewritten.get("materials", {})
        if not isinstance(materials, dict):
            return rewritten

        for container, index, _, source in media_refs:
            items = materials.get(container, [])
            if not isinstance(items, list) or index >= len(items):
                continue
            item = items[index]
            if not isinstance(item, dict):
                continue
            copied_path = str(copied_media_paths[source])
            item["path"] = copied_path
            if "remote_url" in item:
                item["remote_url"] = copied_path
        return rewritten

    def _load_template_draft_content(self, template_dir: Path) -> dict[str, Any] | None:
        for path in (
            template_dir / "draft_content.json",
            template_timeline_dir(template_dir) / "draft_content.json",
        ):
            payload = self._read_json_if_parseable(path)
            if payload is not None:
                return payload
        return None

    def _contains_template_placeholder(self, value: Any) -> bool:
        if isinstance(value, str):
            return _TEMPLATE_PLACEHOLDER in value
        if isinstance(value, dict):
            return any(self._contains_template_placeholder(item) for item in value.values())
        if isinstance(value, list):
            return any(self._contains_template_placeholder(item) for item in value)
        return False

    def _fill_template_draft_content(
        self,
        template_content: dict[str, Any],
        source_content: dict[str, Any],
        draft_content_path: Path,
        draft_dir: Path,
        draft_name: str,
        validation_items: list[InstallValidationItem],
    ) -> tuple[dict[str, Any], dict[Path, Path]]:
        rewritten = deepcopy(template_content)
        copied: dict[Path, Path] = {}

        source_videos = self._ordered_source_materials(source_content, container="videos", media_type="video")
        source_photos = self._ordered_source_materials(source_content, container="videos", media_type="photo")
        if not source_photos:
            source_photos = self._ordered_source_materials(source_content, container="images")
        source_audios = self._ordered_source_materials(source_content, container="audios", track_type="audio")

        video_slots = self._template_material_slots(rewritten, "videos", media_type="video")
        photo_slots = self._template_material_slots(rewritten, "videos", media_type="photo")
        image_slots = self._template_material_slots(rewritten, "images")
        audio_slots = self._template_material_slots(rewritten, "audios")

        self._fill_template_material_slots(
            slots=video_slots,
            source_items=source_videos,
            draft_content_path=draft_content_path,
            draft_dir=draft_dir,
            asset_kind="video",
            copied=copied,
        )
        self._fill_template_material_slots(
            slots=photo_slots + image_slots,
            source_items=source_photos,
            draft_content_path=draft_content_path,
            draft_dir=draft_dir,
            asset_kind="image",
            copied=copied,
        )
        self._fill_template_material_slots(
            slots=audio_slots,
            source_items=source_audios,
            draft_content_path=draft_content_path,
            draft_dir=draft_dir,
            asset_kind="audio",
            copied=copied,
        )

        rewritten = self._replace_template_placeholders(rewritten, draft_dir)
        validation_items.append(
            InstallValidationItem(
                "template_slots",
                "ok",
                f"Filled {len(video_slots)} video, {len(photo_slots) + len(image_slots)} image, "
                f"and {len(audio_slots)} audio template slots",
            )
        )
        return rewritten, copied

    def _ordered_source_materials(
        self,
        draft_content: dict[str, Any],
        *,
        container: str,
        media_type: str | None = None,
        track_type: str = "video",
    ) -> list[dict[str, Any]]:
        items = self._material_items(draft_content, container)
        if media_type is not None:
            items = [item for item in items if item.get("type") == media_type]

        by_id = {
            item["id"]: item
            for item in items
            if isinstance(item.get("id"), str)
        }
        if not by_id:
            return items

        ordered_ids = self._best_track_material_ids(draft_content, by_id, track_type=track_type)
        if ordered_ids:
            return [by_id[item_id] for item_id in ordered_ids]
        return items

    def _best_track_material_ids(
        self,
        draft_content: dict[str, Any],
        materials_by_id: dict[str, dict[str, Any]],
        *,
        track_type: str,
    ) -> list[str]:
        tracks = draft_content.get("tracks", [])
        if not isinstance(tracks, list):
            return []

        best: list[str] = []
        for track in tracks:
            if not isinstance(track, dict) or track.get("type") != track_type:
                continue
            segments = track.get("segments", [])
            if not isinstance(segments, list):
                continue
            ids = [
                material_id
                for segment in segments
                if isinstance(segment, dict)
                and isinstance((material_id := segment.get("material_id")), str)
                and material_id in materials_by_id
            ]
            if len(ids) > len(best):
                best = ids
        return best

    def _material_items(self, draft_content: dict[str, Any], container: str) -> list[dict[str, Any]]:
        materials = draft_content.get("materials", {})
        if not isinstance(materials, dict):
            return []
        items = materials.get(container, [])
        if not isinstance(items, list):
            return []
        return [item for item in items if isinstance(item, dict)]

    def _template_material_slots(
        self,
        draft_content: dict[str, Any],
        container: str,
        *,
        media_type: str | None = None,
    ) -> list[dict[str, Any]]:
        items = self._material_items(draft_content, container)
        if media_type is None:
            return items
        return [item for item in items if item.get("type") == media_type]

    def _fill_template_material_slots(
        self,
        *,
        slots: list[dict[str, Any]],
        source_items: list[dict[str, Any]],
        draft_content_path: Path,
        draft_dir: Path,
        asset_kind: str,
        copied: dict[Path, Path],
    ) -> None:
        if slots and not source_items:
            raise DraftInstallError(
                f"Template requires {len(slots)} {asset_kind} media items, "
                "but draft_content provides none"
            )

        for index, slot in enumerate(slots):
            source_item = source_items[index % len(source_items)]
            source_path = self._resolve_source_item_path(source_item, draft_content_path)
            target = self._template_asset_target(slot, draft_dir, asset_kind, index, source_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target)
            copied.setdefault(source_path, target)

            copied_path = str(target)
            slot["path"] = copied_path
            slot["remote_url"] = copied_path
            for field in _COPIED_MEDIA_FACT_FIELDS:
                if field in source_item:
                    slot[field] = source_item[field]

    def _resolve_source_item_path(self, source_item: dict[str, Any], draft_content_path: Path) -> Path:
        raw_path = source_item.get("path")
        if not isinstance(raw_path, str) or not raw_path:
            raise DraftInstallError("Source media item is missing path")

        resolved = resolve_media_path(raw_path, draft_content_path=draft_content_path)
        if resolved is None or not resolved.is_file():
            raise DraftInstallError(f"Source media file is not readable: {raw_path}")
        return resolved

    def _template_asset_target(
        self,
        slot: dict[str, Any],
        draft_dir: Path,
        asset_kind: str,
        index: int,
        source_path: Path,
    ) -> Path:
        path_value = slot.get("path")
        if isinstance(path_value, str) and _TEMPLATE_PLACEHOLDER in path_value:
            relative = path_value.split(_TEMPLATE_PLACEHOLDER, 1)[1].lstrip("/\\")
            if relative:
                return draft_dir / Path(relative)

        suffix = source_path.suffix or ".bin"
        return draft_dir / "assets" / asset_kind / f"{asset_kind}_{index}{suffix}"

    def _replace_template_placeholders(self, value: Any, draft_dir: Path) -> Any:
        if isinstance(value, str):
            return value.replace(_TEMPLATE_PLACEHOLDER, str(draft_dir))
        if isinstance(value, dict):
            return {
                key: self._replace_template_placeholders(item, draft_dir)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self._replace_template_placeholders(item, draft_dir) for item in value]
        return value

    def _write_required_content_files(
        self,
        draft_dir: Path,
        timeline_id: str,
        draft_content: dict[str, Any],
    ) -> None:
        timeline_dir = draft_dir / "Timelines" / timeline_id
        required = [
            draft_dir / "draft_content.json",
            draft_dir / "draft_content.json.bak",
            timeline_dir / "draft_content.json",
            timeline_dir / "draft_content.json.bak",
        ]
        for path in required:
            self._write_json(path, draft_content)

    def _update_structured_metadata(self, draft_dir: Path, timeline_id: str, draft_name: str) -> None:
        for rel_path in (
            Path("project.json"),
            Path("project.json.bak"),
            Path("Timelines") / "project.json",
            Path("Timelines") / "project.json.bak",
        ):
            path = draft_dir / rel_path
            payload = self._read_json_if_parseable(path)
            if payload is None:
                continue
            self._update_project_payload(payload, timeline_id, draft_name, draft_dir)
            self._write_json(path, payload)

        path = draft_dir / "timeline_layout.json"
        payload = self._read_json_if_parseable(path)
        if payload is not None:
            self._update_timeline_layout_payload(payload, timeline_id, draft_name)
            self._write_json(path, payload)

        path = draft_dir / "draft_meta_info.json"
        payload = self._read_json_if_parseable(path)
        if payload is not None:
            self._update_draft_meta_payload(payload, timeline_id, draft_name, draft_dir)
            self._write_json(path, payload)

    def _update_project_payload(
        self,
        payload: dict[str, Any],
        timeline_id: str,
        draft_name: str,
        draft_dir: Path,
    ) -> None:
        if "id" in payload:
            payload["id"] = timeline_id
        if "timeline_id" in payload:
            payload["timeline_id"] = timeline_id
        if "main_timeline_id" in payload:
            payload["main_timeline_id"] = timeline_id
        if "name" in payload:
            payload["name"] = draft_name
        if "draft_fold_path" in payload:
            payload["draft_fold_path"] = str(draft_dir)
        timelines = payload.get("timelines")
        if isinstance(timelines, list):
            for item in timelines:
                if isinstance(item, dict):
                    item["id"] = timeline_id
                    item["name"] = draft_name

    def _update_timeline_layout_payload(
        self,
        payload: dict[str, Any],
        timeline_id: str,
        draft_name: str,
    ) -> None:
        if "timeline_id" in payload:
            payload["timeline_id"] = timeline_id
        if "activeTimeline" in payload:
            payload["activeTimeline"] = timeline_id
        dock_items = payload.get("dockItems")
        if isinstance(dock_items, list):
            for item in dock_items:
                if isinstance(item, dict):
                    if "timelineIds" in item:
                        item["timelineIds"] = [timeline_id]
                    if "timelineNames" in item:
                        item["timelineNames"] = [draft_name]

    def _update_draft_meta_payload(
        self,
        payload: dict[str, Any],
        timeline_id: str,
        draft_name: str,
        draft_dir: Path,
    ) -> None:
        if "draft_id" in payload:
            payload["draft_id"] = timeline_id
        if "draft_name" in payload:
            payload["draft_name"] = draft_name
        if "draft_timeline_id" in payload:
            payload["draft_timeline_id"] = timeline_id
        if "draft_fold_path" in payload:
            payload["draft_fold_path"] = str(draft_dir)

    def _read_json_if_parseable(self, path: Path) -> dict[str, Any] | None:
        if not path.is_file():
            return None
        try:
            with path.open("r", encoding="utf-8") as fh:
                payload = json.load(fh)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        if isinstance(payload, dict):
            return payload
        return None

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
            fh.write("\n")

    def _write_report(
        self,
        report_path: Path,
        *,
        status: str,
        message: str,
        request: DraftInstallRequest,
        template_dir: Path | None,
        drafts_dir: Path | None,
        result: DraftInstallResult | None,
        validation_items: list[InstallValidationItem],
    ) -> None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "status": status,
            "message": message,
            "draft_content_path": str(request.draft_content_path),
            "draft_name": request.draft_name,
            "template_draft_dir": str(template_dir) if template_dir is not None else None,
            "jianying_drafts_dir": str(drafts_dir) if drafts_dir is not None else None,
            "validation_items": [item.to_report() for item in validation_items],
        }
        if result is not None:
            payload.update(result.to_report())
        with report_path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
            fh.write("\n")


__all__ = ["Jianying10Installer"]
