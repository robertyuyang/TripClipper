"""评分实验室命令入口测试。"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from tripclipper.models import AssetType, CutIndex, ProjectInfo
from tripclipper.cut_index import write_cut_index

from helpers import make_assets

def test_prepare_script_generates_manifest_from_cut_index(tmp_path: Path) -> None:
    index_path = tmp_path / "cut_index.json"
    manifest_path = tmp_path / "sample_manifest.json"
    write_cut_index(
        index_path,
        CutIndex(
            project=ProjectInfo(project_slug="demo"),
            assets=make_assets(),
        ),
    )

    completed = subprocess.run(
        [
            sys.executable,
            "rating-lab/cli.py",
            "prepare",
            "--cut-index",
            str(index_path),
            "--manifest",
            str(manifest_path),
            "--quotas",
            "1:1,2:2,3:3,4:4,5:1",
            "--seed",
            "9",
        ],
        cwd=Path(__file__).parents[2],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["project_slug"] == "demo"
    assert manifest["seed"] == 9
    assert len(manifest["assets"]) == 11
    assert {row["type"] for row in manifest["assets"]} == {"video"}


def test_prepare_script_default_generates_thirty_and_blind_review_files(
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "cut_index.json"
    output_dir = tmp_path / "rating-calibration"
    manifest_path = output_dir / "sample_manifest.json"
    write_cut_index(
        index_path,
        CutIndex(
            project=ProjectInfo(project_slug="demo", source_folder=str(tmp_path)),
            assets=make_assets(),
        ),
    )

    completed = subprocess.run(
        [
            sys.executable,
            "rating-lab/cli.py",
            "prepare",
            "--cut-index",
            str(index_path),
            "--manifest",
            str(manifest_path),
        ],
        cwd=Path(__file__).parents[2],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert len(manifest["assets"]) == 30
    labels_text = (output_dir / "manual_labels.csv").read_text(encoding="utf-8")
    review_text = (output_dir / "manual-review.html").read_text(encoding="utf-8")
    assert "baseline_rating" not in labels_text
    assert "baseline_rating" not in review_text
    assert "导出 CSV" in review_text


def test_prepare_script_excludes_assets_from_existing_manifest(
    tmp_path: Path,
) -> None:
    from rating_lab.sampling import build_manifest

    assets = make_assets()
    source_folder = str(tmp_path)
    quotas = {1: 1, 2: 2, 3: 3, 4: 4, 5: 1}
    index_path = tmp_path / "cut_index.json"
    excluded_path = tmp_path / "calibration-sample.json"
    output_dir = tmp_path / "rating-validation"
    manifest_path = output_dir / "sample_manifest.json"
    write_cut_index(
        index_path,
        CutIndex(
            project=ProjectInfo(project_slug="demo", source_folder=source_folder),
            assets=assets,
        ),
    )
    video_assets = [asset for asset in assets if asset.type == AssetType.video]
    excluded = build_manifest(
        project_slug="demo",
        source_folder=source_folder,
        assets=video_assets,
        quotas=quotas,
        seed=7,
    )
    excluded_path.write_text(json.dumps(excluded), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "rating-lab/cli.py",
            "prepare",
            "--cut-index",
            str(index_path),
            "--manifest",
            str(manifest_path),
            "--exclude-manifest",
            str(excluded_path),
            "--quotas",
            "1:1,2:2,3:3,4:4,5:1",
            "--seed",
            "7",
        ],
        cwd=Path(__file__).parents[2],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    selected_ids = {row["asset_id"] for row in manifest["assets"]}
    excluded_ids = {row["asset_id"] for row in excluded["assets"]}
    assert len(selected_ids) == 11
    assert selected_ids.isdisjoint(excluded_ids)
    assert manifest["excluded_asset_count"] == len(excluded_ids)


def test_prepare_script_does_not_partially_write_when_output_exists(
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "cut_index.json"
    output_dir = tmp_path / "rating-calibration"
    manifest_path = output_dir / "sample_manifest.json"
    labels_path = output_dir / "manual_labels.csv"
    output_dir.mkdir()
    labels_path.write_text("保留现有标注\n", encoding="utf-8")
    write_cut_index(
        index_path,
        CutIndex(project=ProjectInfo(project_slug="demo"), assets=make_assets()),
    )

    completed = subprocess.run(
        [
            sys.executable,
            "rating-lab/cli.py",
            "prepare",
            "--cut-index",
            str(index_path),
            "--manifest",
            str(manifest_path),
        ],
        cwd=Path(__file__).parents[2],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert labels_path.read_text(encoding="utf-8") == "保留现有标注\n"
    assert not manifest_path.exists()
    assert not (output_dir / "manual-review.html").exists()


def test_run_script_help_exposes_read_only_calibration_inputs() -> None:
    completed = subprocess.run(
        [sys.executable, "rating-lab/cli.py", "run", "--help"],
        cwd=Path(__file__).parents[2],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "--cut-index" in completed.stdout
    assert "--manifest" in completed.stdout
    assert "--rating-guide" in completed.stdout
    assert "--output-dir" in completed.stdout
    assert "--concurrency" in completed.stdout


def test_compare_script_writes_metrics_without_overwriting(tmp_path: Path) -> None:
    results_path = tmp_path / "results.json"
    labels_path = tmp_path / "manual_labels.completed.csv"
    output_path = tmp_path / "comparison.json"
    results_path.write_text(
        json.dumps(
            [
                {"asset_id": "asset-1", "candidate_rating": 4, "error": None},
                {"asset_id": "asset-2", "candidate_rating": 5, "error": None},
            ]
        ),
        encoding="utf-8",
    )
    labels_path.write_text(
        "asset_id,expected_rating\nasset-1,4\nasset-2,3\n",
        encoding="utf-8",
    )
    command = [
        sys.executable,
        "rating-lab/cli.py",
        "compare",
        "--results",
        str(results_path),
        "--labels",
        str(labels_path),
        "--output",
        str(output_path),
    ]

    completed = subprocess.run(
        command,
        cwd=Path(__file__).parents[2],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    metrics = json.loads(output_path.read_text(encoding="utf-8"))
    assert metrics["exact_match_rate"] == 0.5
    assert metrics["mean_absolute_error"] == 1.0
    assert metrics["high_rating_false_positive_rate"] == 0.5
    original = output_path.read_bytes()

    repeated = subprocess.run(
        command,
        cwd=Path(__file__).parents[2],
        capture_output=True,
        text=True,
        check=False,
    )

    assert repeated.returncode != 0
    assert output_path.read_bytes() == original


def test_run_script_rejects_manifest_from_another_project(tmp_path: Path) -> None:
    index_path = tmp_path / "cut_index.json"
    manifest_path = tmp_path / "sample_manifest.json"
    guide_path = tmp_path / "rating-guide.txt"
    output_dir = tmp_path / "run-001"
    write_cut_index(
        index_path,
        CutIndex(project=ProjectInfo(project_slug="project-a"), assets=[]),
    )
    original_index = index_path.read_bytes()
    manifest_path.write_text(
        json.dumps({"project_slug": "project-b", "assets": []}),
        encoding="utf-8",
    )
    guide_path.write_text("- 5：特别高光。", encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "rating-lab/cli.py",
            "run",
            "--cut-index",
            str(index_path),
            "--manifest",
            str(manifest_path),
            "--rating-guide",
            str(guide_path),
            "--output-dir",
            str(output_dir),
        ],
        cwd=Path(__file__).parents[2],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "manifest 属于 project-b" in completed.stderr
    assert index_path.read_bytes() == original_index
    assert not output_dir.exists()


def test_run_script_rejects_same_slug_with_different_source_folder(tmp_path: Path) -> None:
    from rating_lab.sampling import project_fingerprint

    index_path = tmp_path / "cut_index.json"
    manifest_path = tmp_path / "sample_manifest.json"
    guide_path = tmp_path / "rating-guide.txt"
    output_dir = tmp_path / "run-001"
    write_cut_index(
        index_path,
        CutIndex(
            project=ProjectInfo(
                project_slug="same-slug",
                source_folder="/source/project-a",
            ),
            assets=[],
        ),
    )
    manifest_path.write_text(
        json.dumps(
            {
                "project_slug": "same-slug",
                "project_fingerprint": project_fingerprint(
                    "same-slug", "/source/project-b"
                ),
                "assets": [],
            }
        ),
        encoding="utf-8",
    )
    guide_path.write_text("- 5：特别高光。", encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "rating-lab/cli.py",
            "run",
            "--cut-index",
            str(index_path),
            "--manifest",
            str(manifest_path),
            "--rating-guide",
            str(guide_path),
            "--output-dir",
            str(output_dir),
        ],
        cwd=Path(__file__).parents[2],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "项目指纹不匹配" in completed.stderr
    assert not output_dir.exists()
