"""生成任务级、离线且只读的选片验收页。"""

from __future__ import annotations

import html
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

from tripclipper.cut_index import read_cut_index
from tripclipper.models import Asset, AssetType, CutIndex
from tripclipper.paths import (
    cut_index_path,
    project_dir,
    selection_review_html_path,
    selection_task_dir,
)

from .models import SelectionCandidate, SelectionState


class SelectionReviewError(RuntimeError):
    """审阅页输入缺失、损坏或模板不可用。"""


def _required_file(path: Path, label: str) -> Path:
    if not path.is_file():
        raise SelectionReviewError(f"{label}不存在：{path}")
    return path


def _read_text(path: Path, label: str) -> str:
    try:
        return _required_file(path, label).read_text(encoding="utf-8")
    except OSError as exc:
        raise SelectionReviewError(f"{label}无法读取：{path}（{exc}）") from exc


def _first_heading(brief: str, fallback: str) -> str:
    for line in brief.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            heading = stripped.lstrip("#").strip()
            if heading:
                return heading
    return fallback


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _format_seconds(value: float) -> str:
    if value.is_integer():
        return f"{value:g} 秒"
    return f"{value:.2f}".rstrip("0").rstrip(".") + " 秒"


def _union_duration(candidates: list[SelectionCandidate]) -> float:
    by_asset: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for candidate in candidates:
        if candidate.status == "primary":
            by_asset[candidate.asset_id].append(
                (candidate.start_sec, candidate.end_sec)
            )

    total = 0.0
    for intervals in by_asset.values():
        ordered = sorted(intervals)
        if not ordered:
            continue
        start, end = ordered[0]
        for next_start, next_end in ordered[1:]:
            if next_start <= end:
                end = max(end, next_end)
            else:
                total += end - start
                start, end = next_start, next_end
        total += end - start
    return total


def _resolve_source_path(asset: Asset, source_folder: str | None) -> Path | None:
    source_root = Path(source_folder).expanduser() if source_folder else None
    for value in (asset.path, asset.relative_path, asset.file, asset.filename):
        if not value:
            continue
        path = Path(value).expanduser()
        if path.is_absolute():
            return path.resolve()
        if source_root is not None:
            return (source_root / path).resolve()
    return None


def _resolve_preview_path(asset: Asset, current_project_dir: Path) -> Path | None:
    if not asset.thumbnail_path:
        return None
    path = Path(asset.thumbnail_path).expanduser()
    if path.is_absolute():
        return path.resolve()
    project_relative = (current_project_dir / path).resolve()
    if project_relative.is_file():
        return project_relative
    return path.resolve()


def _candidate_context(
    candidate: SelectionCandidate,
    *,
    asset: Asset | None,
    categories_by_id: dict[str, dict[str, Any]],
    source_folder: str | None,
    current_project_dir: Path,
    index: int,
) -> dict[str, Any]:
    categories = [
        categories_by_id[category_id]
        for category_id in candidate.category_ids
        if category_id in categories_by_id
    ]
    duration = _number(asset.metadata.get("duration")) if asset else None
    source_path = _resolve_source_path(asset, source_folder) if asset else None
    source_exists = bool(source_path and source_path.is_file())
    media_type = asset.type.value if asset and asset.type else None
    valid_range = (
        0 <= candidate.start_sec < candidate.end_sec
        and (duration is None or candidate.end_sec <= duration)
    )

    if asset is None:
        issue = "素材索引不存在"
    elif media_type != AssetType.video.value:
        issue = "非视频素材"
    elif not valid_range:
        issue = "时间范围错误"
    elif not source_exists:
        issue = "源文件不可访问"
    else:
        issue = None

    thumbnail_path = (
        _resolve_preview_path(asset, current_project_dir) if asset else None
    )
    return {
        "index": index,
        "candidateId": candidate.candidate_id,
        "assetId": candidate.asset_id,
        "filename": asset.filename if asset and asset.filename else candidate.asset_id,
        "filePath": str(source_path) if source_path else None,
        "fileUri": source_path.as_uri() if source_path else None,
        "mediaUri": source_path.as_uri() if source_exists else None,
        "thumbnailUri": (
            thumbnail_path.as_uri()
            if thumbnail_path and thumbnail_path.is_file()
            else None
        ),
        "mediaType": media_type,
        "startSec": candidate.start_sec,
        "endSec": candidate.end_sec,
        "rangeText": (
            f"{candidate.start_sec:g}–{candidate.end_sec:g} 秒"
        ),
        "durationText": _format_seconds(candidate.end_sec - candidate.start_sec),
        "categoryIds": candidate.category_ids,
        "categories": categories,
        "recommendedUse": candidate.recommended_use,
        "reason": candidate.reason,
        "canPlay": issue is None,
        "issue": issue,
    }


def _escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _render_categories(categories: list[dict[str, Any]]) -> str:
    items: list[str] = []
    for category in categories:
        classes = "category-card"
        if category["required"] and not category["covered"]:
            classes += " warning"
        status = "已覆盖" if category["covered"] else "未覆盖"
        detail = category["missingReason"] or category["purpose"]
        items.append(
            f'<article class="{classes}">'
            f"<strong>{_escape(category['name'])}</strong>"
            f'<span class="coverage">{status}</span>'
            f"<p>{_escape(detail)}</p>"
            "</article>"
        )
    return "\n".join(items)


def _render_candidates(candidates: list[dict[str, Any]]) -> str:
    items: list[str] = []
    for candidate in candidates:
        category_badges = "".join(
            f'<span class="tag">{_escape(category["name"])}</span>'
            for category in candidate["categories"]
        )
        issue = (
            f'<span class="candidate-issue">{_escape(candidate["issue"])}</span>'
            if candidate["issue"]
            else ""
        )
        items.append(
            f'<button class="candidate-card" type="button" data-index="{candidate["index"]}" '
            f'data-categories="{_escape(" ".join(candidate["categoryIds"]))}">'
            f'<span class="candidate-number">#{candidate["index"] + 1}</span>'
            f'<span class="candidate-copy"><strong>{_escape(candidate["filename"])}</strong>'
            f'<span>{_escape(candidate["candidateId"])} · {_escape(candidate["rangeText"])} · '
            f'{_escape(candidate["durationText"])}</span>'
            f'<span class="tags">{category_badges}</span>{issue}</span>'
            "</button>"
        )
    return "\n".join(items)


def _render_filters(categories: list[dict[str, Any]]) -> str:
    buttons = [
        '<button type="button" class="filter-chip active" data-category="all">全部</button>'
    ]
    buttons.extend(
        f'<button type="button" class="filter-chip" data-category="{_escape(category["categoryId"])}">'
        f'{_escape(category["name"])}</button>'
        for category in categories
    )
    return "\n".join(buttons)


def _render_unresolved(unresolved: list[dict[str, Any]]) -> str:
    if not unresolved:
        return '<p class="muted">无高优先级未解决问题</p>'
    return "<ul>" + "".join(
        f"<li>{_escape(item.get('message') or json.dumps(item, ensure_ascii=False))}</li>"
        for item in unresolved
    ) + "</ul>"


def _safe_json(value: Any) -> str:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        .replace("</", "<\\/")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def _render_html(context: dict[str, Any]) -> str:
    template_path = Path(__file__).parent / "templates" / "select-review.html.tmpl"
    template = _read_text(template_path, "审阅页模板")
    replacements = {
        "{{PAGE_TITLE}}": _escape(context["title"]),
        "{{TASK_NAME}}": _escape(context["taskName"]),
        "{{BRIEF}}": _escape(context["brief"]),
        "{{STATUS}}": _escape(context["status"]),
        "{{TARGET_DURATION}}": _escape(context["targetDurationText"]),
        "{{PRIMARY_DURATION}}": _escape(context["primaryDurationText"]),
        "{{CANDIDATE_COUNT}}": str(context["candidateCount"]),
        "{{CATEGORY_COUNT}}": str(context["categoryCount"]),
        "{{PAGE_PROGRESS}}": _escape(context["pageProgress"]),
        "{{OPENED_PROGRESS}}": _escape(context["openedProgress"]),
        "{{CATEGORY_CARDS}}": _render_categories(context["categories"]),
        "{{CATEGORY_FILTERS}}": _render_filters(context["categories"]),
        "{{CANDIDATE_CARDS}}": _render_candidates(context["candidates"]),
        "{{UNRESOLVED}}": _render_unresolved(context["unresolved"]),
        "{{UNRESOLVED_CLASS}}": (
            "panel warning" if context["unresolved"] else "panel"
        ),
        "{{REVIEW_DATA}}": _safe_json(
            {
                "taskName": context["taskName"],
                "categories": context["categories"],
                "candidates": context["candidates"],
            }
        ),
    }
    for marker, value in replacements.items():
        template = template.replace(marker, value)
    return template


def _build_context(
    brief: str,
    state: SelectionState,
    cut: CutIndex,
    *,
    current_project_dir: Path,
) -> dict[str, Any]:
    candidate_category_ids = {
        category_id
        for candidate in state.candidates
        for category_id in candidate.category_ids
    }
    categories = [
        {
            "categoryId": category.category_id,
            "name": category.name,
            "required": category.required,
            "purpose": category.purpose,
            "missingReason": category.missing_reason,
            "covered": category.category_id in candidate_category_ids,
        }
        for category in state.categories
    ]
    categories_by_id = {
        category["categoryId"]: category for category in categories
    }
    assets_by_id = {
        asset.asset_id: asset for asset in cut.assets if asset.asset_id is not None
    }
    candidates = [
        _candidate_context(
            candidate,
            asset=assets_by_id.get(candidate.asset_id),
            categories_by_id=categories_by_id,
            source_folder=cut.project.source_folder,
            current_project_dir=current_project_dir,
            index=index,
        )
        for index, candidate in enumerate(state.candidates)
    ]
    total_pages = max(
        math.ceil(len(cut.assets) / 20),
        max(state.asset_progress.listed_pages, default=0),
        1,
    )
    return {
        "title": _first_heading(brief, state.task_name),
        "taskName": state.task_name,
        "brief": brief,
        "status": state.status,
        "targetDurationText": _format_seconds(state.target_duration_sec),
        "primaryDurationText": _format_seconds(_union_duration(state.candidates)),
        "candidateCount": len(state.candidates),
        "categoryCount": len(state.categories),
        "pageProgress": f"{len(set(state.asset_progress.listed_pages))}/{total_pages}",
        "openedProgress": (
            f"{len(set(state.asset_progress.opened_asset_ids))}/{len(cut.assets)}"
        ),
        "categories": categories,
        "candidates": candidates,
        "unresolved": state.unresolved,
    }


def render_selection_review(
    slug: str,
    task_name: str,
    *,
    base_dir: str | Path | None = None,
) -> Path:
    """只读加载任务输入，只覆盖目标 ``select-review.html``。"""
    if not task_name or any(separator in task_name for separator in ("/", "\\")):
        raise SelectionReviewError("任务名称不能为空或包含路径分隔符")

    task_dir = selection_task_dir(slug, task_name, base_dir)
    brief_path = task_dir / "brief.md"
    state_path = task_dir / "state.json"
    index_path = cut_index_path(slug, base_dir)
    brief = _read_text(brief_path, "Brief")
    try:
        state = SelectionState.model_validate_json(_read_text(state_path, "选片状态"))
        cut = read_cut_index(_required_file(index_path, "素材索引"))
    except SelectionReviewError:
        raise
    except (OSError, ValueError) as exc:
        raise SelectionReviewError(f"审阅页输入无效：{exc}") from exc

    context = _build_context(
        brief,
        state,
        cut,
        current_project_dir=project_dir(slug, base_dir),
    )
    target = selection_review_html_path(slug, task_name, base_dir)
    try:
        target.write_text(_render_html(context), encoding="utf-8")
    except OSError as exc:
        raise SelectionReviewError(f"审阅页无法写入：{target}（{exc}）") from exc
    return target.resolve()


__all__ = [
    "SelectionReviewError",
    "render_selection_review",
]
