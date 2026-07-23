"""评分实验的确定性抽样与数据清单。"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path

from tripclipper.models import Asset


DEFAULT_RATING_QUOTAS: dict[int, int] = {1: 1, 2: 3, 3: 9, 4: 15, 5: 2}


def project_fingerprint(project_slug: str, source_folder: str | None) -> str:
    """生成数据来源项目和素材根目录的稳定本地指纹。"""
    normalized_source = ""
    if source_folder:
        normalized_source = str(Path(source_folder).expanduser().resolve(strict=False))
    material = f"{project_slug}\0{normalized_source}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def _asset_identity(asset: Asset) -> str:
    return asset.asset_id or asset.relative_path or asset.filename or ""


def _sample_order(asset: Asset, seed: int) -> str:
    identity = _asset_identity(asset)
    material = f"{seed}|{asset.rating}|{identity}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def _secondary_balance_key(asset: Asset) -> tuple[str, str]:
    asset_type = asset.type.value if asset.type is not None else "unknown"
    subject = asset.subject_type.value if asset.subject_type is not None else "unknown"
    return (asset_type, subject)


def _balanced_pick(candidates: Sequence[Asset], count: int, seed: int) -> list[Asset]:
    session_buckets: dict[str, list[Asset]] = defaultdict(list)
    for asset in candidates:
        session_buckets[asset.session_id or "unknown"].append(asset)
    ordered_sessions = sorted(
        session_buckets,
        key=lambda session: hashlib.sha256(
            f"{seed}|{session}".encode("utf-8")
        ).hexdigest(),
    )
    selected: list[Asset] = []
    secondary_counts: dict[tuple[str, str], int] = defaultdict(int)
    while len(selected) < count:
        added = False
        for session in ordered_sessions:
            bucket = session_buckets[session]
            if not bucket:
                continue
            chosen = min(
                bucket,
                key=lambda asset: (
                    secondary_counts[_secondary_balance_key(asset)],
                    _sample_order(asset, seed),
                ),
            )
            bucket.remove(chosen)
            selected.append(chosen)
            secondary_counts[_secondary_balance_key(chosen)] += 1
            added = True
            if len(selected) == count:
                break
        if not added:
            break
    return selected


def select_fixed_sample(
    assets: Sequence[Asset],
    *,
    quotas: Mapping[int, int],
    seed: int,
) -> list[Asset]:
    """按现有星级配额确定性抽样，返回顺序不依赖输入排列。"""
    selected: list[Asset] = []
    for rating in sorted(quotas):
        candidates = [asset for asset in assets if asset.rating == rating]
        selected.extend(_balanced_pick(candidates, max(0, quotas[rating]), seed))
    target = min(sum(max(0, count) for count in quotas.values()), len(assets))
    if len(selected) < target:
        selected_ids = {_asset_identity(asset) for asset in selected}
        remaining = [
            asset for asset in assets if _asset_identity(asset) not in selected_ids
        ]
        selected.extend(_balanced_pick(remaining, target - len(selected), seed))
    return selected


def _enum_value(value: object) -> object:
    return getattr(value, "value", value)


def build_manifest(
    *,
    project_slug: str,
    assets: Sequence[Asset],
    source_folder: str | None = None,
    quotas: Mapping[int, int] = DEFAULT_RATING_QUOTAS,
    seed: int = 42,
) -> dict[str, object]:
    """生成固定样本清单；清单写入后，后续运行只使用其中的 asset_id。"""
    selected = select_fixed_sample(assets, quotas=quotas, seed=seed)
    rows = [
        {
            "asset_id": asset.asset_id,
            "relative_path": asset.relative_path,
            "baseline_rating": asset.rating,
            "type": _enum_value(asset.type),
            "session_id": asset.session_id,
            "subject_type": _enum_value(asset.subject_type),
            "shot_scale": _enum_value(asset.shot_scale),
        }
        for asset in selected
    ]
    actual_counts: dict[str, int] = {}
    for asset in selected:
        key = str(asset.rating) if asset.rating is not None else "unrated"
        actual_counts[key] = actual_counts.get(key, 0) + 1
    return {
        "schema_version": 1,
        "project_slug": project_slug,
        "project_fingerprint": project_fingerprint(project_slug, source_folder),
        "seed": seed,
        "rating_quotas": {
            str(rating): count for rating, count in sorted(quotas.items())
        },
        "actual_rating_counts": dict(sorted(actual_counts.items())),
        "assets": rows,
    }

__all__ = [
    "DEFAULT_RATING_QUOTAS",
    "build_manifest",
    "project_fingerprint",
    "select_fixed_sample",
]
