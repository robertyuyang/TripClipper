"""候选 Prompt 多版本结果的合并与比较。"""

from __future__ import annotations

import csv
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from .evaluation import compare_ratings


def load_variant_results(variant_dir: Path) -> list[dict[str, object]]:
    """按固定批次顺序加载一个候选版本的全部结果。"""
    records: list[dict[str, object]] = []
    for batch in ("initial-30", "extension-15"):
        path = variant_dir / batch / "results.json"
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(loaded, list):
            raise ValueError(f"结果文件必须是列表：{path}")
        records.extend(dict(row) for row in loaded)
    asset_ids = [str(row.get("asset_id") or "") for row in records]
    if len(asset_ids) != len(set(asset_ids)):
        raise ValueError(f"候选版本中存在重复素材：{variant_dir}")
    return records


def load_labels(path: Path) -> list[dict[str, str]]:
    """读取统一人工评分。"""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def load_annotations(path: Path) -> list[dict[str, str]]:
    """读取人工评语导出。"""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _rows_by_id(
    rows: Sequence[Mapping[str, object]],
    *,
    source_name: str,
) -> dict[str, Mapping[str, object]]:
    indexed: dict[str, Mapping[str, object]] = {}
    for row in rows:
        asset_id = str(row.get("asset_id") or "")
        if asset_id in indexed:
            raise ValueError(f"{source_name} 中存在重复素材：{asset_id}")
        indexed[asset_id] = row
    return indexed


def build_variant_comparison(
    variant_results: Mapping[str, Sequence[Mapping[str, object]]],
    labels: Sequence[Mapping[str, object]],
    annotations: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """计算三版指标并筛选需要人工复核的素材。"""
    if len(variant_results) != 3:
        raise ValueError("必须提供三个候选版本")

    labels_by_id = _rows_by_id(labels, source_name="人工评分")
    annotations_by_id = _rows_by_id(annotations, source_name="人工评语")
    result_maps = {
        name: _rows_by_id(records, source_name=f"候选版本 {name}")
        for name, records in variant_results.items()
    }
    ordered_names = list(variant_results)
    first_name = ordered_names[0]
    asset_order = [
        str(record.get("asset_id") or "") for record in variant_results[first_name]
    ]
    expected_ids = set(asset_order)
    if set(labels_by_id) != expected_ids:
        raise ValueError("统一人工评分与候选版本的素材集合不一致")
    for name, rows_by_id in result_maps.items():
        if set(rows_by_id) != expected_ids:
            raise ValueError(f"候选版本 {name} 的素材集合不一致")

    variant_summaries = {
        name: {"metrics": compare_ratings(records, labels)}
        for name, records in variant_results.items()
    }
    assets: list[dict[str, object]] = []
    for original_index, asset_id in enumerate(asset_order):
        label = labels_by_id[asset_id]
        annotation = annotations_by_id.get(asset_id, {})
        expected_rating = int(str(label.get("expected_rating")))
        ratings = {
            name: int(result_maps[name][asset_id].get("candidate_rating"))
            for name in ordered_names
        }
        rating_values = list(ratings.values())
        spread = max(rating_values) - min(rating_values)
        errors = {
            name: abs(rating - expected_rating) for name, rating in ratings.items()
        }
        exact_values = [error == 0 for error in errors.values()]
        has_human_reason = bool(
            str(annotation.get("human_rating_reason") or "").strip()
        )
        is_key_review = (
            has_human_reason
            or spread >= 2
            or max(errors.values()) >= 2
            or (any(exact_values) and not all(exact_values))
        )
        original_rating_text = str(annotation.get("expected_rating") or "").strip()
        assets.append(
            {
                "asset_id": asset_id,
                "relative_path": str(label.get("relative_path") or ""),
                "expected_rating": expected_rating,
                "original_expected_rating": (
                    int(original_rating_text) if original_rating_text else None
                ),
                "human_rating_reason": str(
                    annotation.get("human_rating_reason") or ""
                ),
                "model_error_type": str(annotation.get("model_error_type") or ""),
                "has_human_reason": has_human_reason,
                "is_key_review": is_key_review,
                "variant_spread": spread,
                "max_error": max(errors.values()),
                "variant_results": {
                    name: dict(result_maps[name][asset_id]) for name in ordered_names
                },
                "_original_index": original_index,
            }
        )

    assets.sort(
        key=lambda row: (
            not bool(row["has_human_reason"]),
            -int(row["variant_spread"]),
            -int(row["max_error"]),
            int(row["_original_index"]),
        )
    )
    for row in assets:
        row.pop("_original_index")

    return {
        "schema_version": 1,
        "variants": variant_summaries,
        "key_asset_ids": [
            str(row["asset_id"]) for row in assets if row["is_key_review"]
        ],
        "assets": assets,
    }


__all__ = [
    "build_variant_comparison",
    "load_annotations",
    "load_labels",
    "load_variant_results",
]
