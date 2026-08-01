"""四套实现共用的确定性计算，不拥有 Agent 状态。"""

from __future__ import annotations

from hashlib import sha256
import json

from experiments.clip_selection.contracts import CandidateClip, ClipStatus, ProjectSnapshot, SelectionRun


def validate_clip_reference(clip: CandidateClip, snapshot: ProjectSnapshot) -> None:
    asset = snapshot.asset(clip.asset_id)
    if asset.duration_sec is not None and clip.end_sec > asset.duration_sec:
        raise ValueError(
            f"片段越界: {clip.end_sec:g} > {asset.duration_sec:g}"
        )


def primary_duration_sec(run: SelectionRun) -> float:
    by_asset: dict[str, list[tuple[float, float]]] = {}
    for clip in run.clips:
        if clip.status is ClipStatus.primary:
            by_asset.setdefault(clip.asset_id, []).append((clip.start_sec, clip.end_sec))
    total = 0.0
    for ranges in by_asset.values():
        merged: list[list[float]] = []
        for start, end in sorted(ranges):
            if not merged or start > merged[-1][1]:
                merged.append([start, end])
            else:
                merged[-1][1] = max(merged[-1][1], end)
        total += sum(end - start for start, end in merged)
    return total


def finish_errors(run: SelectionRun) -> list[str]:
    errors: list[str] = []
    duration = primary_duration_sec(run)
    target = run.brief.target_duration_sec
    if duration < target:
        errors.append(f"主选时长不足: {duration:g} < {target:g}")
    if duration > target * 1.5:
        errors.append(f"主选时长过多: {duration:g} > {target * 1.5:g}")
    review_count = sum(clip.status is ClipStatus.needs_review for clip in run.clips)
    if review_count > run.brief.max_review_clips:
        errors.append("needs_review 超过 max_review_clips")
    clip_ids = {clip.clip_id for clip in run.clips}
    for clip in run.clips:
        if clip.alternate_for and clip.alternate_for not in clip_ids:
            errors.append(f"片段 {clip.clip_id} 的替代引用不存在")
    primary_categories = {
        category
        for clip in run.clips
        if clip.status is ClipStatus.primary
        for category in clip.categories
    }
    for category in run.categories:
        if category.required and category.category_id not in primary_categories:
            errors.append(f"必要分类 {category.category_id} 没有主选覆盖")
    return errors


def structure_fingerprint(run: SelectionRun) -> str:
    payload = {
        "clips": sorted(
            (clip.model_dump(mode="json") for clip in run.clips),
            key=lambda item: item["clip_id"],
        ),
        "categories": sorted(
            (category.model_dump(mode="json") for category in run.categories),
            key=lambda item: item["category_id"],
        ),
        "unresolved": sorted(run.unresolved),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return sha256(encoded).hexdigest()


def model_context(run: SelectionRun, snapshot: ProjectSnapshot) -> dict[str, object]:
    return {
        "run": run.model_dump(mode="json"),
        "assets": [asset.model_dump(mode="json") for asset in snapshot.assets],
    }
