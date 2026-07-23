"""v5 三版结果汇总与筛选测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _record(asset_id: str, rating: int) -> dict[str, object]:
    return {
        "asset_id": asset_id,
        "relative_path": f"{asset_id}.mp4",
        "candidate_rating": rating,
        "summary": f"{asset_id} 摘要",
        "clip_suggestions": [],
        "error": None,
    }


def test_load_variant_results_combines_two_batches_without_duplicates(
    tmp_path: Path,
) -> None:
    from rating_lab.variants import load_variant_results

    for batch, records in (
        ("initial-30", [_record("a", 4)]),
        ("extension-15", [_record("b", 3)]),
    ):
        path = tmp_path / batch
        path.mkdir()
        (path / "results.json").write_text(json.dumps(records), encoding="utf-8")

    assert [row["asset_id"] for row in load_variant_results(tmp_path)] == ["a", "b"]


def test_load_variant_results_rejects_duplicate_assets(tmp_path: Path) -> None:
    from rating_lab.variants import load_variant_results

    for batch in ("initial-30", "extension-15"):
        path = tmp_path / batch
        path.mkdir()
        (path / "results.json").write_text(
            json.dumps([_record("same", 4)]), encoding="utf-8"
        )

    with pytest.raises(ValueError, match="重复素材"):
        load_variant_results(tmp_path)


def test_build_variant_comparison_selects_key_review_assets() -> None:
    from rating_lab.variants import build_variant_comparison

    results = {
        "v5-balanced": [
            _record("annotated", 4),
            _record("split", 5),
            _record("same", 3),
        ],
        "v5-conservative": [
            _record("annotated", 3),
            _record("split", 2),
            _record("same", 3),
        ],
        "v5-recall": [
            _record("annotated", 4),
            _record("split", 4),
            _record("same", 3),
        ],
    }
    labels = [
        {"asset_id": "annotated", "expected_rating": "4"},
        {"asset_id": "split", "expected_rating": "4"},
        {"asset_id": "same", "expected_rating": "3"},
    ]
    annotations = [
        {
            "asset_id": "annotated",
            "expected_rating": "2",
            "human_rating_reason": "人工意见",
            "model_error_type": "none",
        },
        {
            "asset_id": "split",
            "expected_rating": "4",
            "human_rating_reason": "",
            "model_error_type": "",
        },
        {
            "asset_id": "same",
            "expected_rating": "3",
            "human_rating_reason": "",
            "model_error_type": "",
        },
    ]

    comparison = build_variant_comparison(results, labels, annotations)

    assert comparison["key_asset_ids"] == ["annotated", "split"]
    assert (
        comparison["variants"]["v5-balanced"]["metrics"]["sample_count"] == 3
    )
    assert comparison["assets"][0]["has_human_reason"] is True
    assert comparison["assets"][0]["original_expected_rating"] == 2
