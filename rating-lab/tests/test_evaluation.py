"""评分实验室指标计算测试。"""

from __future__ import annotations

import pytest


def test_compare_ratings_reports_calibration_metrics() -> None:
    from rating_lab.evaluation import compare_ratings

    records = [
        {"asset_id": "a", "candidate_rating": 5, "error": None},
        {"asset_id": "b", "candidate_rating": 4, "error": None},
        {"asset_id": "c", "candidate_rating": 3, "error": None},
        {"asset_id": "d", "candidate_rating": 1, "error": None},
        {"asset_id": "e", "candidate_rating": None, "error": "模型失败"},
    ]
    labels = [
        {"asset_id": "a", "expected_rating": "5"},
        {"asset_id": "b", "expected_rating": "3"},
        {"asset_id": "c", "expected_rating": "4"},
        {"asset_id": "d", "expected_rating": "3"},
        {"asset_id": "e", "expected_rating": "2"},
    ]

    metrics = compare_ratings(records, labels)

    assert metrics["sample_count"] == 5
    assert metrics["scored_count"] == 4
    assert metrics["failed_count"] == 1
    assert metrics["exact_match_count"] == 1
    assert metrics["exact_match_rate"] == 0.25
    assert metrics["mean_absolute_error"] == 1.0
    assert metrics["within_one_rate"] == 0.75
    assert metrics["severe_mismatch_count"] == 1
    assert metrics["high_rating_precision"] == 0.5
    assert metrics["high_rating_false_positive_rate"] == 0.5
    assert metrics["high_rating_recall"] == 0.5
    assert metrics["confusion_matrix"] == {
        "1": {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0},
        "2": {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0},
        "3": {"1": 1, "2": 0, "3": 0, "4": 1, "5": 0},
        "4": {"1": 0, "2": 0, "3": 1, "4": 0, "5": 0},
        "5": {"1": 0, "2": 0, "3": 0, "4": 0, "5": 1},
    }


@pytest.mark.parametrize(
    ("labels", "message"),
    [
        (
            [
                {"asset_id": "asset-1", "expected_rating": "4"},
                {"asset_id": "asset-1", "expected_rating": "4"},
            ],
            "重复的人工标签：asset-1",
        ),
        ([], "缺少人工标签：asset-1"),
        (
            [{"asset_id": "asset-1", "expected_rating": "高"}],
            "人工评分必须是 1-5：asset-1",
        ),
    ],
)
def test_compare_ratings_rejects_invalid_labels(
    labels: list[dict[str, str]],
    message: str,
) -> None:
    from rating_lab.evaluation import compare_ratings

    records = [{"asset_id": "asset-1", "candidate_rating": 4, "error": None}]

    with pytest.raises(ValueError, match=message):
        compare_ratings(records, labels)
