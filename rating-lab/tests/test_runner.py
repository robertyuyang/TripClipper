"""评分实验室模型执行测试。"""

from __future__ import annotations

import csv
import json
import time
from pathlib import Path

import pytest

from tripclipper.models import Asset, AssetType
from tripclipper.provider import AnalysisResult


def test_run_calibration_records_visual_result_without_mutating_asset() -> None:
    from rating_lab.runner import run_calibration

    asset = Asset(
        asset_id="asset-1",
        relative_path="day-1/a.mp4",
        rating=4,
        summary="旧摘要",
        type=AssetType.video,
    )
    manifest = {
        "project_slug": "demo",
        "assets": [
            {
                "asset_id": "asset-1",
                "relative_path": "day-1/a.mp4",
                "baseline_rating": 4,
            }
        ],
    }

    def analyze_visual(selected: Asset) -> AnalysisResult:
        assert selected is asset
        return AnalysisResult(
            content_title="新标题",
            summary="新摘要",
            rating=3,
            tags=["活动", "中景"],
        )

    records = run_calibration([asset], manifest, analyze_visual=analyze_visual)

    assert records == [
        {
            "asset_id": "asset-1",
            "relative_path": "day-1/a.mp4",
            "baseline_rating": 4,
            "candidate_rating": 3,
            "content_title": "新标题",
            "summary": "新摘要",
            "tags": ["活动", "中景"],
            "clip_suggestions": [],
            "error": None,
        }
    ]
    assert asset.rating == 4
    assert asset.summary == "旧摘要"


def test_run_calibration_isolates_single_asset_failure() -> None:
    from rating_lab.runner import run_calibration

    assets = [Asset(asset_id="good", rating=4), Asset(asset_id="bad", rating=3)]
    manifest = {
        "assets": [
            {"asset_id": "good", "baseline_rating": 4},
            {"asset_id": "bad", "baseline_rating": 3},
        ]
    }

    def analyze_visual(asset: Asset) -> AnalysisResult:
        if asset.asset_id == "bad":
            raise RuntimeError("模型失败")
        return AnalysisResult(rating=3)

    records = run_calibration(assets, manifest, analyze_visual=analyze_visual)

    assert records[0]["candidate_rating"] == 3
    assert records[0]["error"] is None
    assert records[1]["candidate_rating"] is None
    assert records[1]["error"] == "RuntimeError: 模型失败"


def test_write_results_creates_json_and_annotation_csv(tmp_path: Path) -> None:
    from rating_lab.runner import write_results

    records = [
        {
            "asset_id": "asset-1",
            "relative_path": "day/a.mp4",
            "baseline_rating": 4,
            "candidate_rating": 3,
            "content_title": "漂流者经过激流",
            "summary": "画面可用但整体普通。",
            "tags": ["漂流", "激流"],
            "clip_suggestions": [],
            "error": None,
        }
    ]

    json_path, csv_path = write_results(tmp_path / "run-001", records)

    assert json.loads(json_path.read_text(encoding="utf-8")) == records
    with csv_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["asset_id"] == "asset-1"
    assert rows[0]["candidate_rating"] == "3"
    assert rows[0]["expected_rating"] == ""
    assert rows[0]["expected_action"] == ""
    with pytest.raises(FileExistsError):
        write_results(tmp_path / "run-001", records)


def test_reserve_run_dir_fails_before_work_when_target_exists(tmp_path: Path) -> None:
    from rating_lab.runner import reserve_run_dir

    run_dir = tmp_path / "run-001"

    reserve_run_dir(run_dir)

    assert run_dir.is_dir()
    with pytest.raises(FileExistsError):
        reserve_run_dir(run_dir)


def test_run_calibration_concurrency_preserves_manifest_order() -> None:
    from rating_lab.runner import run_calibration

    assets = [Asset(asset_id=f"asset-{index}", rating=4) for index in range(3)]
    manifest = {
        "assets": [
            {"asset_id": f"asset-{index}", "baseline_rating": 4}
            for index in range(3)
        ]
    }

    def analyze_visual(asset: Asset) -> AnalysisResult:
        time.sleep({"asset-0": 0.03, "asset-1": 0.02, "asset-2": 0.01}[asset.asset_id])
        return AnalysisResult(rating=3)

    records = run_calibration(
        assets,
        manifest,
        analyze_visual=analyze_visual,
        concurrency=3,
    )

    assert [record["asset_id"] for record in records] == [
        "asset-0",
        "asset-1",
        "asset-2",
    ]
