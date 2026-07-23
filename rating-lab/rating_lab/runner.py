"""评分实验的模型执行与结果写入。"""

from __future__ import annotations

import concurrent.futures
import csv
import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from tripclipper.models import Asset
from tripclipper.provider import AnalysisResult


def reserve_run_dir(run_dir: Path) -> None:
    """在模型调用前原子预留一次运行目录。"""
    run_dir.mkdir(parents=True, exist_ok=False)


def write_results(
    run_dir: Path,
    records: Sequence[Mapping[str, object]],
) -> tuple[Path, Path]:
    """把一次评分实验写成 JSON 与可人工标注的 CSV。"""
    if not run_dir.exists():
        reserve_run_dir(run_dir)
    json_path = run_dir / "results.json"
    with json_path.open("x", encoding="utf-8") as handle:
        json.dump(list(records), handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    csv_path = run_dir / "review.csv"
    fieldnames = [
        "asset_id",
        "relative_path",
        "baseline_rating",
        "candidate_rating",
        "expected_rating",
        "expected_action",
        "whole_asset_or_clip",
        "content_title",
        "summary",
        "tags",
        "clip_suggestions",
        "error",
    ]
    with csv_path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            writer.writerow(
                {
                    **record,
                    "expected_rating": "",
                    "expected_action": "",
                    "whole_asset_or_clip": "",
                    "tags": "、".join(record.get("tags", [])),
                    "clip_suggestions": json.dumps(
                        record.get("clip_suggestions", []), ensure_ascii=False
                    ),
                }
            )
    return json_path, csv_path


def run_calibration(
    assets: Sequence[Asset],
    manifest: Mapping[str, object],
    *,
    analyze_visual: Callable[[Asset], AnalysisResult],
    concurrency: int = 1,
) -> list[dict[str, object]]:
    """只读运行固定样本的视觉分析并返回独立结果记录。"""
    assets_by_id = {asset.asset_id: asset for asset in assets}
    manifest_rows = [dict(row) for row in manifest.get("assets", [])]

    def analyze_row(manifest_row: Mapping[str, object]) -> dict[str, object]:
        row = dict(manifest_row)
        asset_id = row.get("asset_id")
        asset = assets_by_id.get(asset_id)
        if asset is None:
            return {
                "asset_id": asset_id,
                "relative_path": row.get("relative_path"),
                "baseline_rating": row.get("baseline_rating"),
                "candidate_rating": None,
                "content_title": None,
                "summary": None,
                "tags": [],
                "clip_suggestions": [],
                "error": "manifest 中的素材不存在于当前 cut_index",
            }
        try:
            result = analyze_visual(asset)
        except Exception as exc:
            return {
                "asset_id": asset_id,
                "relative_path": row.get("relative_path") or asset.relative_path,
                "baseline_rating": row.get("baseline_rating"),
                "candidate_rating": None,
                "content_title": None,
                "summary": None,
                "tags": [],
                "clip_suggestions": [],
                "error": f"{type(exc).__name__}: {exc}",
            }
        return {
            "asset_id": asset_id,
            "relative_path": row.get("relative_path") or asset.relative_path,
            "baseline_rating": row.get("baseline_rating"),
            "candidate_rating": result.rating,
            "content_title": result.content_title,
            "summary": result.summary,
            "tags": result.tags,
            "clip_suggestions": [
                clip.model_dump(by_alias=True) for clip in result.clip_suggestions
            ],
            "error": None,
        }

    if concurrency <= 1:
        return [analyze_row(row) for row in manifest_rows]
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
        return list(pool.map(analyze_row, manifest_rows))

__all__ = ["reserve_run_dir", "run_calibration", "write_results"]
