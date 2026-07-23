"""评分实验室历史数据完整性测试。"""

from __future__ import annotations

import csv
import json
from pathlib import Path


LAB_ROOT = Path(__file__).resolve().parents[1]
DATASET_ROOT = LAB_ROOT / "datasets" / "development-v1"


def test_development_dataset_contains_two_batches_and_45_unique_assets() -> None:
    dataset = json.loads((DATASET_ROOT / "dataset.json").read_text(encoding="utf-8"))
    rows = dataset["assets"]

    assert dataset["dataset_id"] == "development-v1"
    assert dataset["sample_count"] == 45
    assert len(rows) == 45
    assert len({row["asset_id"] for row in rows}) == 45
    assert sum(row["batch"] == "initial-30" for row in rows) == 30
    assert sum(row["batch"] == "extension-15" for row in rows) == 15


def test_human_labels_and_annotations_cover_expected_rows() -> None:
    with (DATASET_ROOT / "human-labels.csv").open(
        encoding="utf-8-sig", newline=""
    ) as handle:
        labels = list(csv.DictReader(handle))
    with (DATASET_ROOT / "annotations.csv").open(
        encoding="utf-8-sig", newline=""
    ) as handle:
        annotations = list(csv.DictReader(handle))

    assert len(labels) == 45
    assert len({row["asset_id"] for row in labels}) == 45
    assert len(annotations) == 45
    assert sum(
        bool(row["human_rating_reason"].strip()) for row in annotations
    ) == 8


def test_all_seven_historical_runs_are_preserved() -> None:
    runs = LAB_ROOT / "runs" / "development-v1"

    assert sorted(path.name for path in (runs / "initial-30").glob("run-*")) == [
        "run-001",
        "run-002",
        "run-003",
        "run-004",
        "run-005",
    ]
    assert sorted(path.name for path in (runs / "extension-15").glob("run-*")) == [
        "run-001",
        "run-002",
    ]


def test_old_project_owned_lab_directories_are_removed() -> None:
    repo_root = LAB_ROOT.parent

    assert not (repo_root / "projects/26shidu/rating-calibration").exists()
    assert not (repo_root / "projects/26shidu/rating-validation").exists()


def test_authoritative_labels_apply_exactly_five_adjudications() -> None:
    expected_changes = {
        "asset_49ba9c5ba398": ("2", "4"),
        "asset_2dc71a50d977": ("2", "4"),
        "asset_88844cf7f24f": ("1", "3"),
        "asset_08c943eb9686": ("1", "4"),
        "asset_5b691e6d1dbf": ("2", "4"),
    }
    historical: dict[str, str] = {}
    for batch in ("initial-30", "extension-15"):
        path = DATASET_ROOT / "batches" / batch / "human-labels.csv"
        with path.open(encoding="utf-8-sig", newline="") as handle:
            historical.update(
                {
                    row["asset_id"]: row["expected_rating"]
                    for row in csv.DictReader(handle)
                }
            )
    with (DATASET_ROOT / "human-labels.csv").open(
        encoding="utf-8-sig", newline=""
    ) as handle:
        authoritative = {
            row["asset_id"]: row["expected_rating"]
            for row in csv.DictReader(handle)
        }

    changes = {
        asset_id: (historical[asset_id], rating)
        for asset_id, rating in authoritative.items()
        if historical[asset_id] != rating
    }

    assert changes == expected_changes
