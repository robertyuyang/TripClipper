from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from .constants import EDIT_CANDIDATE_STATUSES, SIMILAR_SELECTIONS
from .utils import stable_hash


_CONTEXT_SHOT_FUNCTIONS = {"establishing", "transition", "b_roll"}
_MOMENT_SHOT_FUNCTIONS = {"highlight", "reaction", "dialogue"}
_WIDE_SHOT_SCALES = {"extreme_wide", "wide", "full"}
_CLOSE_SHOT_SCALES = {"close_up", "extreme_close_up"}

_SCENE_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("民宿", ("民宿", "度假屋", "客栈", "酒店", "住宿")),
    ("溶洞", ("溶洞", "钟乳石", "石笋")),
    ("atv", ("atv", "全地形车", "越野车")),
    ("溪谷徒步", ("溪谷", "溪流", "徒步")),
    ("团建合影", ("合影", "横幅")),
)

_GENERIC_SCENE_WORDS = {
    "高光",
    "转场",
    "broll",
    "默认候选",
    "团建",
    "户外",
    "户外活动",
    "户外团建",
    "行车记录仪",
    "空镜头",
    "过渡镜头",
    "第一视角",
    "环境",
    "外景",
    "到达",
    "抵达",
}


def apply_postprocessing(data: dict[str, Any]) -> dict[str, Any]:
    _normalize_asset_defaults(data.get("assets", []))
    _build_similar_groups(data)
    _build_default_candidates(data)
    return data


def _normalize_asset_defaults(assets: list[dict[str, Any]]) -> None:
    for asset in assets:
        asset.setdefault("warnings", [])
        asset.setdefault("failures", [])
        asset.setdefault("tags", [])
        asset.setdefault("segments", [])
        if asset.get("analysis_status") == "analyzed":
            asset.setdefault("similar_selection", "none")
            asset.setdefault("eagle_sync_status", "not_synced")


def _build_similar_groups(data: dict[str, Any]) -> None:
    assets = [asset for asset in data.get("assets", []) if asset.get("analysis_status") == "analyzed"]
    for asset in assets:
        asset["similar_group_id"] = None
        asset["similar_selection"] = "none"
        asset["similar_rank"] = None
        asset["similar_reason"] = None

    buckets: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for asset in assets:
        key = (
            str(asset.get("type") or ""),
            str(asset.get("subject_type") or "other"),
            _shot_function_key(asset),
            _shot_scale_key(asset),
            _scene_key(asset),
        )
        if key[-1]:
            buckets[key].append(asset)

    groups: list[dict[str, Any]] = []
    for key, bucket in buckets.items():
        for cluster in _split_by_capture_time(bucket):
            if len(cluster) < 2:
                continue
            group = _make_group(cluster, key)
            groups.append(group)

    data["similar_groups"] = groups


def _make_group(cluster: list[dict[str, Any]], key: tuple[str, str, str, str, str]) -> dict[str, Any]:
    ranked = sorted(
        cluster,
        key=lambda asset: (
            -(asset.get("rating") or 0),
            _has_usable_audio(asset),
            asset.get("file") or "",
        ),
    )
    group_id = f"sim_{stable_hash('|'.join(asset['asset_id'] for asset in ranked), 10)}"
    primary = ranked[0]
    alternates: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for asset in ranked[1:]:
        if (asset.get("rating") or 0) <= 2:
            rejected.append(asset)
        else:
            alternates.append(asset)

    reason = _group_reason(primary, alternates, rejected)
    primary.update(
        {
            "similar_group_id": group_id,
            "similar_selection": "primary",
            "similar_rank": 1,
            "similar_reason": "同组中评分最高，作为默认主选。",
        }
    )
    for rank, asset in enumerate(alternates, start=2):
        asset.update(
            {
                "similar_group_id": group_id,
                "similar_selection": "alternate",
                "similar_rank": rank,
                "similar_reason": "内容接近且质量可用，但同组已有更优主选。",
            }
        )
    for offset, asset in enumerate(rejected, start=2 + len(alternates)):
        asset.update(
            {
                "similar_group_id": group_id,
                "similar_selection": "rejected",
                "similar_rank": offset,
                "similar_reason": "同组内评分较低，不推荐进入默认候选。",
            }
        )

    return {
        "similar_group_id": group_id,
        "asset_ids": [asset["asset_id"] for asset in ranked],
        "basis": _basis(key),
        "primary_asset_id": primary["asset_id"],
        "alternate_asset_ids": [asset["asset_id"] for asset in alternates],
        "rejected_asset_ids": [asset["asset_id"] for asset in rejected],
        "default_candidate_asset_id": primary["asset_id"],
        "confidence": 0.82,
        "needs_review": False,
        "reason": reason,
    }


def _build_default_candidates(data: dict[str, Any]) -> None:
    default_assets: list[dict[str, Any]] = []
    for asset in data.get("assets", []):
        if asset.get("analysis_status") != "analyzed":
            asset["edit_candidate_status"] = None
            asset["edit_candidate_priority"] = None
            asset["edit_candidate_reason"] = None
            continue
        selection = asset.get("similar_selection") or "none"
        rating = asset.get("rating") or 0
        if selection == "primary":
            if rating >= 4:
                _candidate(asset, "default_selected", "高星素材且为雷同组主选，默认进入剪辑候选池。")
                default_assets.append(asset)
            else:
                _candidate(asset, "alternate", "虽为雷同组主选，但星级未达到默认入选阈值。")
        elif selection == "alternate":
            _candidate(asset, "alternate", "同组已有主选，保留为备选，不进入默认主候选列表。")
        elif selection == "rejected":
            _candidate(asset, "excluded", "雷同组内不推荐素材，排除默认候选。")
        elif selection == "needs_review":
            _candidate(asset, "needs_review", "雷同关系或质量判断需要人工确认。")
        elif rating >= 4:
            _candidate(asset, "default_selected", "非雷同高星素材，默认进入剪辑候选池。")
            default_assets.append(asset)
        elif rating == 3:
            _candidate(asset, "alternate", "三星素材可作为备选。")
        else:
            _candidate(asset, "excluded", "评分较低，默认不进入候选池。")

    ordered = _balanced_order(default_assets)
    for priority, asset in enumerate(ordered, start=1):
        asset["edit_candidate_priority"] = priority

    data["default_candidates"] = [
        {
            "asset_id": asset["asset_id"],
            "priority": asset["edit_candidate_priority"],
            "role": asset.get("shot_function") or "other",
            "reason": asset.get("edit_candidate_reason"),
            "similar_group_id": asset.get("similar_group_id"),
            "subject_type": asset.get("subject_type"),
            "shot_scale": asset.get("shot_scale"),
        }
        for asset in ordered
    ]


def _candidate(asset: dict[str, Any], status: str, reason: str) -> None:
    if status not in EDIT_CANDIDATE_STATUSES:
        raise ValueError(f"Unknown edit candidate status: {status}")
    if asset.get("similar_selection") not in SIMILAR_SELECTIONS:
        asset["similar_selection"] = "none"
    asset["edit_candidate_status"] = status
    asset["edit_candidate_priority"] = None
    asset["edit_candidate_reason"] = reason


def _balanced_order(assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for asset in sorted(assets, key=lambda item: (-(item.get("rating") or 0), item.get("file") or "")):
        buckets[str(asset.get("subject_type") or "other")].append(asset)
    ordered: list[dict[str, Any]] = []
    while any(buckets.values()):
        for key in sorted(buckets):
            if buckets[key]:
                ordered.append(buckets[key].pop(0))
    return ordered


def _scene_key(asset: dict[str, Any]) -> str:
    text = _scene_text(asset)
    for canonical, aliases in _SCENE_ALIASES:
        if any(_normalize_scene_text(alias) in text for alias in aliases):
            return canonical

    tokens = _scene_tokens(asset)
    if tokens:
        return "|".join(tokens[:2])

    primary = _normalize_scene_text(asset.get("primary_subject"))
    if primary and primary not in {"other", "未知", "不确定"}:
        return primary[:24]
    return ""


def _shot_function_key(asset: dict[str, Any]) -> str:
    shot_function = str(asset.get("shot_function") or "other")
    if shot_function in _CONTEXT_SHOT_FUNCTIONS:
        return "context"
    if shot_function in _MOMENT_SHOT_FUNCTIONS:
        return "moment"
    return shot_function


def _shot_scale_key(asset: dict[str, Any]) -> str:
    shot_scale = str(asset.get("shot_scale") or "")
    if shot_scale in _WIDE_SHOT_SCALES:
        return "wide"
    if shot_scale in _CLOSE_SHOT_SCALES:
        return "close_up"
    return shot_scale


def _scene_text(asset: dict[str, Any]) -> str:
    parts = [
        str(asset.get("scene") or ""),
        str(asset.get("primary_subject") or ""),
        *[str(tag) for tag in asset.get("tags") or []],
    ]
    return _normalize_scene_text(" ".join(parts))


def _scene_tokens(asset: dict[str, Any]) -> list[str]:
    tokens: list[str] = []
    for value in [asset.get("scene"), *(asset.get("tags") or [])]:
        token = _normalize_scene_text(value)
        if token and token not in _GENERIC_SCENE_WORDS and token not in tokens:
            tokens.append(token)
    return tokens


def _normalize_scene_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    return re.sub(r"[\s,，。！？!?.、:：;；\-_/]+", "", text)


def _split_by_capture_time(bucket: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    enriched = [(asset, _capture_time(asset)) for asset in bucket]
    if all(item[1] is None for item in enriched):
        return [bucket]
    enriched.sort(key=lambda item: item[1] or datetime.max.replace(tzinfo=timezone.utc))
    clusters: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_start: datetime | None = None
    for asset, captured_at in enriched:
        if captured_at is None:
            clusters.append([asset])
            continue
        if current_start is None or (captured_at - current_start).total_seconds() <= 180:
            current.append(asset)
            current_start = current_start or captured_at
        else:
            clusters.append(current)
            current = [asset]
            current_start = captured_at
    if current:
        clusters.append(current)
    return clusters


def _capture_time(asset: dict[str, Any]) -> datetime | None:
    text = str(asset.get("file") or "")
    patterns = [
        r"(?P<date>\d{8})[_-]?(?P<time>\d{6})",
        r"(?P<date>\d{8})-(?P<time>\d{6})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            try:
                return datetime.strptime(match.group("date") + match.group("time"), "%Y%m%d%H%M%S").replace(
                    tzinfo=timezone.utc
                )
            except ValueError:
                return None
    return None


def _basis(key: tuple[str, str, str, str, str]) -> list[str]:
    _, subject_type, shot_function, shot_scale, scene_key = key
    return [
        f"相近场景/主体关键词：{scene_key}",
        f"相同主体类型：{subject_type}",
        f"相近景别：{shot_scale}",
        f"相近镜头功能：{shot_function}",
        "文件拍摄时间或场景摘要接近",
    ]


def _group_reason(primary: dict[str, Any], alternates: list[dict[str, Any]], rejected: list[dict[str, Any]]) -> str:
    parts = [f"{primary.get('file')} 评分最高，作为同组主选。"]
    if alternates:
        parts.append(f"{len(alternates)} 条素材保留为备选。")
    if rejected:
        parts.append(f"{len(rejected)} 条低分素材不推荐。")
    return "".join(parts)


def _has_usable_audio(asset: dict[str, Any]) -> int:
    audio = str(asset.get("audio_strategy") or asset.get("audio_suggestion") or "")
    return 1 if "keep" in audio or "保留" in audio else 0
