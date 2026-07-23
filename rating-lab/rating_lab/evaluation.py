"""评分实验的指标计算。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence


def compare_ratings(
    records: Sequence[Mapping[str, object]],
    labels: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """将候选评分与固定人工基准对齐并计算校准指标。"""
    labels_by_id: dict[str, int] = {}
    for row in labels:
        asset_id = str(row.get("asset_id") or "")
        if asset_id in labels_by_id:
            raise ValueError(f"重复的人工标签：{asset_id}")
        try:
            expected = int(str(row.get("expected_rating")))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"人工评分必须是 1-5：{asset_id}") from exc
        if expected not in range(1, 6):
            raise ValueError(f"人工评分必须是 1-5：{asset_id}")
        labels_by_id[asset_id] = expected

    for record in records:
        asset_id = str(record.get("asset_id") or "")
        if asset_id not in labels_by_id:
            raise ValueError(f"缺少人工标签：{asset_id}")

    pairs: list[tuple[int, int]] = []
    failed_count = 0
    for record in records:
        candidate = record.get("candidate_rating")
        if candidate is None or record.get("error"):
            failed_count += 1
            continue
        expected = labels_by_id[str(record.get("asset_id"))]
        pairs.append((int(candidate), expected))

    scored_count = len(pairs)
    exact_match_count = sum(candidate == expected for candidate, expected in pairs)
    within_one_count = sum(
        abs(candidate - expected) <= 1 for candidate, expected in pairs
    )
    severe_mismatch_count = sum(
        abs(candidate - expected) >= 2 for candidate, expected in pairs
    )
    total_absolute_error = sum(
        abs(candidate - expected) for candidate, expected in pairs
    )

    predicted_high = sum(candidate >= 4 for candidate, _ in pairs)
    actual_high = sum(expected >= 4 for _, expected in pairs)
    true_high = sum(
        candidate >= 4 and expected >= 4 for candidate, expected in pairs
    )

    confusion_matrix = {
        str(expected): {str(candidate): 0 for candidate in range(1, 6)}
        for expected in range(1, 6)
    }
    for candidate, expected in pairs:
        confusion_matrix[str(expected)][str(candidate)] += 1

    high_precision = true_high / predicted_high if predicted_high else None
    return {
        "sample_count": len(records),
        "scored_count": scored_count,
        "failed_count": failed_count,
        "exact_match_count": exact_match_count,
        "exact_match_rate": exact_match_count / scored_count if scored_count else None,
        "mean_absolute_error": (
            total_absolute_error / scored_count if scored_count else None
        ),
        "within_one_rate": within_one_count / scored_count if scored_count else None,
        "severe_mismatch_count": severe_mismatch_count,
        "high_rating_precision": high_precision,
        "high_rating_false_positive_rate": (
            1 - high_precision if high_precision is not None else None
        ),
        "high_rating_recall": true_high / actual_high if actual_high else None,
        "confusion_matrix": confusion_matrix,
    }

__all__ = ["compare_ratings"]
