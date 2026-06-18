from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .constants import EDIT_CANDIDATE_LABELS, SHOT_FUNCTION_LABELS, SHOT_SCALE_LABELS, SIMILAR_SELECTION_LABELS, SUBJECT_TYPE_LABELS
from .index import append_task_log, load_index, project_dir_from_slug, record_warning, save_index
from .utils import write_json


START_MARKER = "<!-- TripClipper:start -->"
END_MARKER = "<!-- TripClipper:end -->"


def eagle_dry_run(project_slug: str, base_dir: str | Path | None = None) -> dict[str, Any]:
    project_dir = project_dir_from_slug(project_slug, base_dir)
    data = load_index(project_dir)
    plan = build_eagle_plan(data)
    write_json(project_dir / "eagle_dry_run.json", plan)
    append_task_log(data, "eagle_dry_run", "Eagle 同步预览已生成。")
    save_index(project_dir, data)
    return plan


def eagle_apply(project_slug: str, base_dir: str | Path | None = None) -> dict[str, Any]:
    project_dir = project_dir_from_slug(project_slug, base_dir)
    data = load_index(project_dir)
    plan = build_eagle_plan(data)
    base_url = _eagle_base_url(data)
    if not _eagle_available(base_url):
        result = {
            "mode": "apply",
            "status": "skipped",
            "reason": "Eagle API 不可连接；本地数据包和 dry-run 计划仍可使用。",
            "assets": [
                {
                    "file": asset["file"],
                    "path": asset["path"],
                    "status": "skipped",
                    "reason": "Eagle API 不可连接。",
                }
                for asset in plan["assets"]
            ],
        }
        for asset in data.get("assets") or []:
            asset["eagle_sync_status"] = "skipped"
        record_warning(
            data,
            "eagle_apply",
            "Eagle API 不可连接，正式同步已跳过。",
            "请启动 Eagle，确认本地 API 地址后重新执行 sync-eagle --apply。",
        )
        write_json(project_dir / "eagle_apply_result.json", result)
        append_task_log(data, "eagle_apply", "Eagle 不可连接，同步跳过。", "warning")
        save_index(project_dir, data)
        return result

    folder_cache: dict[str, str | None] = {}
    result_assets: list[dict[str, Any]] = []
    assets_by_path = {asset.get("path"): asset for asset in data.get("assets") or []}
    for folder in plan.get("folders_to_create") or []:
        folder_cache[folder] = _ensure_folder(base_url, folder)

    for planned in plan.get("assets") or []:
        asset = assets_by_path.get(planned.get("path"))
        try:
            item = _add_or_update_item(base_url, planned, folder_cache.get(planned.get("target_folder")))
            item_id = _extract_eagle_item_id(item)
            if asset is not None:
                asset["eagle_item_id"] = item_id
                asset["eagle_sync_status"] = "updated"
            result_assets.append(
                {
                    "file": planned["file"],
                    "path": planned["path"],
                    "status": "updated",
                    "eagle_item_id": item_id,
                    "written_fields": ["tags", "rating", "tripclipper_note"],
                    "note_block_status": "managed_block_updated",
                }
            )
        except Exception as exc:  # pragma: no cover - depends on user's Eagle API.
            if asset is not None:
                asset["eagle_sync_status"] = "failed"
            result_assets.append(
                {
                    "file": planned["file"],
                    "path": planned["path"],
                    "status": "failed",
                    "reason": str(exc),
                }
            )

    result = {"mode": "apply", "status": "completed", "assets": result_assets}
    write_json(project_dir / "eagle_apply_result.json", result)
    append_task_log(data, "eagle_apply", "Eagle 同步执行完成。")
    save_index(project_dir, data)
    return result


def build_eagle_plan(data: dict[str, Any]) -> dict[str, Any]:
    project = data.get("project") or {}
    project_name = project.get("project_name") or "TripClipper Project"
    folders = [project_name]
    assets = []
    for asset in data.get("assets") or []:
        if asset.get("analysis_status") not in {"analyzed", "analysis_failed", "scanned"}:
            continue
        function_label = SHOT_FUNCTION_LABELS.get(asset.get("shot_function"), "未分析")
        target_folder = f"{project_name}/{function_label}"
        if target_folder not in folders:
            folders.append(target_folder)
        assets.append(
            {
                "file": asset.get("file"),
                "path": asset.get("path"),
                "target_folder": target_folder,
                "rating": asset.get("rating"),
                "tags_to_add": _tags_for_asset(asset),
                "note_preview": managed_note_block(asset),
            }
        )
    return {"mode": "preview", "folders_to_create": folders, "assets": assets}


def managed_note_block(asset: dict[str, Any]) -> str:
    lines = [
        START_MARKER,
        f"默认候选：{EDIT_CANDIDATE_LABELS.get(asset.get('edit_candidate_status'), asset.get('edit_candidate_status') or '否')}",
        f"主体类型：{SUBJECT_TYPE_LABELS.get(asset.get('subject_type'), asset.get('subject_type') or '未分析')}",
        f"主要主体：{asset.get('primary_subject') or '未分析'}",
        f"景别：{SHOT_SCALE_LABELS.get(asset.get('shot_scale'), asset.get('shot_scale') or '未分析')}",
        f"镜头功能：{SHOT_FUNCTION_LABELS.get(asset.get('shot_function'), asset.get('shot_function') or '未分析')}",
        f"雷同组：{asset.get('similar_group_id') or '无'}",
        f"组内状态：{SIMILAR_SELECTION_LABELS.get(asset.get('similar_selection'), asset.get('similar_selection') or '无')}",
        f"候选理由：{asset.get('edit_candidate_reason') or ''}",
        f"选择理由：{asset.get('similar_reason') or ''}",
        f"声音建议：{asset.get('audio_suggestion') or ''}",
        f"推荐片段：{_segment_summary(asset)}",
        END_MARKER,
    ]
    return "\n".join(lines)


def replace_managed_note_block(existing_note: str | None, managed_block: str) -> str:
    existing = existing_note or ""
    if START_MARKER in existing and END_MARKER in existing:
        before, remainder = existing.split(START_MARKER, 1)
        _, after = remainder.split(END_MARKER, 1)
        return f"{before.rstrip()}\n{managed_block}\n{after.lstrip()}".strip()
    if existing.strip():
        return f"{existing.rstrip()}\n\n{managed_block}"
    return managed_block


def _tags_for_asset(asset: dict[str, Any]) -> list[str]:
    tags = [
        "TripClipper",
        SUBJECT_TYPE_LABELS.get(asset.get("subject_type"), asset.get("subject_type")),
        SHOT_SCALE_LABELS.get(asset.get("shot_scale"), asset.get("shot_scale")),
        SHOT_FUNCTION_LABELS.get(asset.get("shot_function"), asset.get("shot_function")),
        EDIT_CANDIDATE_LABELS.get(asset.get("edit_candidate_status"), asset.get("edit_candidate_status")),
        SIMILAR_SELECTION_LABELS.get(asset.get("similar_selection"), asset.get("similar_selection")),
    ]
    tags.extend(asset.get("tags") or [])
    return sorted({str(tag) for tag in tags if tag})


def _segment_summary(asset: dict[str, Any]) -> str:
    segments = asset.get("segments") or []
    if not segments:
        return "无"
    return "；".join(f"{item.get('in')}-{item.get('out')} {item.get('role')}：{item.get('reason')}" for item in segments[:3])


def _eagle_base_url(data: dict[str, Any]) -> str:
    sync_config = (data.get("project") or {}).get("eagle_sync") or {}
    return str(os.environ.get("EAGLE_API_URL") or sync_config.get("base_url") or "http://127.0.0.1:41595/api").rstrip("/")


def _eagle_available(base_url: str) -> bool:
    try:
        _eagle_get(base_url, "/application/info")
        return True
    except Exception:
        return False


def _ensure_folder(base_url: str, folder_path: str) -> str | None:
    parent_id: str | None = None
    for part in [piece for piece in folder_path.split("/") if piece]:
        response = _eagle_post(base_url, "/folder/create", {"folderName": part, "parent": parent_id})
        parent_id = _extract_eagle_item_id(response) or parent_id
    return parent_id


def _add_or_update_item(base_url: str, planned: dict[str, Any], folder_id: str | None) -> dict[str, Any]:
    payload = {
        "path": planned["path"],
        "name": planned["file"],
        "tags": planned["tags_to_add"],
        "star": planned.get("rating"),
        "annotation": planned["note_preview"],
    }
    if folder_id:
        payload["folderId"] = folder_id
    return _eagle_post(base_url, "/item/addFromPath", payload)


def _eagle_get(base_url: str, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    query = f"?{urllib.parse.urlencode(params)}" if params else ""
    request = urllib.request.Request(f"{base_url}{endpoint}{query}", method="GET")
    return _read_eagle_response(request)


def _eagle_post(base_url: str, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{base_url}{endpoint}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "TripClipper/0.1"},
    )
    return _read_eagle_response(request)


def _read_eagle_response(request: urllib.request.Request) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Eagle API HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')[:300]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Eagle API 连接失败：{exc.reason}") from exc
    data = json.loads(body or "{}")
    if isinstance(data, dict) and data.get("status") == "error":
        raise RuntimeError(str(data.get("message") or "Eagle API 返回错误。"))
    return data


def _extract_eagle_item_id(response: dict[str, Any]) -> str | None:
    if not isinstance(response, dict):
        return None
    data = response.get("data")
    if isinstance(data, dict):
        return str(data.get("id") or data.get("_id") or "") or None
    return str(response.get("id") or response.get("_id") or "") or None
