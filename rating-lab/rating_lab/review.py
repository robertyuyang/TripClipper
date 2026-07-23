"""评分实验的人工标注与复核产物。"""

from __future__ import annotations

import csv
import json
from collections.abc import Mapping
from pathlib import Path


def write_manifest(path: Path, manifest: Mapping[str, object]) -> None:
    """以独占创建方式写入 manifest，避免意外改变既有固定样本。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def write_manual_labels(path: Path, manifest: Mapping[str, object]) -> None:
    """生成不含旧评分的人工盲评 CSV 模板。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "asset_id",
        "relative_path",
        "expected_rating",
        "expected_action",
        "whole_asset_or_clip",
        "notes",
    ]
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for asset in manifest.get("assets", []):
            writer.writerow(
                {
                    "asset_id": asset.get("asset_id"),
                    "relative_path": asset.get("relative_path"),
                    "expected_rating": "",
                    "expected_action": "",
                    "whole_asset_or_clip": "",
                    "notes": "",
                }
            )


def write_manual_review_html(
    path: Path,
    manifest: Mapping[str, object],
    source_folder: str,
) -> None:
    """生成不含旧评分、可离线保存并导出答案的盲评页面。"""
    source_root = Path(source_folder).expanduser().resolve(strict=False)
    items: list[dict[str, str]] = []
    for row in manifest.get("assets", []):
        relative_path = str(row.get("relative_path") or "")
        media_path = (source_root / relative_path).resolve(strict=False)
        media_uri = media_path.as_uri() if media_path.is_relative_to(source_root) else ""
        items.append(
            {
                "asset_id": str(row.get("asset_id") or ""),
                "relative_path": relative_path,
                "media_uri": media_uri,
            }
        )

    payload = {
        "project_slug": str(manifest.get("project_slug") or "project"),
        "items": items,
    }
    data_json = json.dumps(payload, ensure_ascii=False)
    data_json = (
        data_json.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )
    template_path = (
        Path(__file__).parent / "templates" / "rating_manual_review.html.tmpl"
    )
    rendered = template_path.read_text(encoding="utf-8").replace(
        "__CALIBRATION_DATA__", data_json
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(rendered)


def _safe_json(value: object) -> str:
    return (
        json.dumps(value, ensure_ascii=False)
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )


def write_variant_review_html(
    path: Path,
    comparison: Mapping[str, object],
    source_folder: str,
) -> None:
    """生成三版候选结果并排复核页面。"""
    source_root = Path(source_folder).expanduser().resolve(strict=False)
    payload = json.loads(json.dumps(comparison, ensure_ascii=False))
    for row in payload["assets"]:
        media_path = (source_root / row["relative_path"]).resolve(strict=False)
        row["media_uri"] = (
            media_path.as_uri() if media_path.is_relative_to(source_root) else ""
        )
    template_path = Path(__file__).parent / "templates" / "variant_review.html.tmpl"
    rendered = template_path.read_text(encoding="utf-8").replace(
        "__VARIANT_REVIEW_DATA__", _safe_json(payload)
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(rendered)


__all__ = [
    "write_manifest",
    "write_manual_labels",
    "write_manual_review_html",
    "write_variant_review_html",
]
