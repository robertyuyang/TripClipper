#!/usr/bin/env python3
"""只读的评分 Prompt 调优实验室命令入口。"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import threading
from pathlib import Path

from dotenv import load_dotenv

LAB_ROOT = Path(__file__).resolve().parent
REPO_ROOT = LAB_ROOT.parent
TRIPCLIPPER_SRC = REPO_ROOT / "src"
for path in (LAB_ROOT, TRIPCLIPPER_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from tripclipper.config import EditingIntent, load_software_config
from tripclipper.cut_index import read_cut_index
from tripclipper.provider import Provider
from rating_lab.evaluation import compare_ratings
from rating_lab.review import (
    write_manual_labels,
    write_manual_review_html,
    write_manifest,
    write_variant_review_html,
)
from rating_lab.runner import reserve_run_dir, run_calibration, write_results
from rating_lab.sampling import (
    DEFAULT_RATING_QUOTAS,
    build_manifest,
    project_fingerprint,
)
from rating_lab.variants import (
    build_variant_comparison,
    load_annotations,
    load_labels,
    load_variant_results,
)


def _parse_quotas(value: str) -> dict[int, int]:
    quotas: dict[int, int] = {}
    try:
        for item in value.split(","):
            rating_text, count_text = item.split(":", 1)
            rating = int(rating_text)
            count = int(count_text)
            if rating not in range(1, 6) or count < 0:
                raise ValueError
            quotas[rating] = count
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "配额格式应为 1:1,2:3,3:9,4:15,5:2，且数量不能为负数"
        ) from exc
    return quotas


def _format_default_quotas() -> str:
    return ",".join(
        f"{rating}:{count}" for rating, count in DEFAULT_RATING_QUOTAS.items()
    )


def _parse_asset_types(value: str) -> set[str]:
    asset_types = {item.strip() for item in value.split(",") if item.strip()}
    if not asset_types or not asset_types.issubset({"video", "image"}):
        raise argparse.ArgumentTypeError("素材类型只支持 video 或 video,image")
    return asset_types


def _parse_variant(value: str) -> tuple[str, Path]:
    try:
        name, raw_path = value.split("=", 1)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("候选版本格式应为 NAME=DIR") from exc
    if not name or not raw_path:
        raise argparse.ArgumentTypeError("候选版本格式应为 NAME=DIR")
    return name, Path(raw_path)


def _write_json_exclusive(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare", help="生成一次后固定不变的样本清单")
    prepare.add_argument("--cut-index", type=Path, required=True)
    prepare.add_argument("--manifest", type=Path, required=True)
    prepare.add_argument(
        "--exclude-manifest",
        type=Path,
        help="抽样前排除另一个同项目 manifest 中的素材",
    )
    prepare.add_argument("--seed", type=int, default=42)
    prepare.add_argument(
        "--asset-types",
        type=_parse_asset_types,
        default={"video"},
        help="参与校准的素材类型，默认只抽视频；可传 video,image",
    )
    prepare.add_argument(
        "--quotas",
        type=_parse_quotas,
        default=_parse_quotas(_format_default_quotas()),
        help="各旧星级抽样数，默认 1:1,2:3,3:9,4:15,5:2",
    )

    run = subparsers.add_parser("run", help="只读运行固定样本的视觉评分校准")
    run.add_argument("--cut-index", type=Path, required=True)
    run.add_argument("--manifest", type=Path, required=True)
    run.add_argument("--rating-guide", type=Path, required=True)
    run.add_argument("--output-dir", type=Path, required=True)
    run.add_argument("--concurrency", type=int, default=3)

    compare = subparsers.add_parser("compare", help="对比模型评分与固定人工基准")
    compare.add_argument("--results", type=Path, required=True)
    compare.add_argument("--labels", type=Path, required=True)
    compare.add_argument("--output", type=Path, required=True)

    compare_variants = subparsers.add_parser(
        "compare-variants",
        help="合并三个候选版本的两批结果并生成复核页面",
    )
    compare_variants.add_argument(
        "--variant",
        type=_parse_variant,
        action="append",
        required=True,
        help="候选版本及目录，格式 NAME=DIR，必须提供三次",
    )
    compare_variants.add_argument("--labels", type=Path, required=True)
    compare_variants.add_argument("--annotations", type=Path, required=True)
    compare_variants.add_argument("--source-folder", type=Path, required=True)
    compare_variants.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "prepare":
        cut = read_cut_index(args.cut_index)
        slug = cut.project.project_slug or args.cut_index.parent.name
        excluded_ids: set[str] = set()
        if args.exclude_manifest is not None:
            with args.exclude_manifest.open(encoding="utf-8") as handle:
                excluded_manifest = json.load(handle)
            if excluded_manifest.get("project_slug") != slug:
                raise SystemExit("排除 manifest 与当前项目的 project_slug 不一致")
            expected_fingerprint = project_fingerprint(
                slug,
                cut.project.source_folder,
            )
            if excluded_manifest.get("project_fingerprint") != expected_fingerprint:
                raise SystemExit("排除 manifest 与当前项目的素材根目录不一致")
            excluded_ids = {
                str(row.get("asset_id"))
                for row in excluded_manifest.get("assets", [])
                if row.get("asset_id")
            }
        manifest = build_manifest(
            project_slug=slug,
            source_folder=cut.project.source_folder,
            assets=[
                asset
                for asset in cut.assets
                if asset.type is not None and asset.type.value in args.asset_types
                and asset.asset_id not in excluded_ids
            ],
            quotas=args.quotas,
            seed=args.seed,
        )
        manifest["asset_types"] = sorted(args.asset_types)
        if args.exclude_manifest is not None:
            manifest["excluded_asset_count"] = len(excluded_ids)
        labels_path = args.manifest.parent / "manual_labels.csv"
        review_path = args.manifest.parent / "manual-review.html"
        existing = [
            path for path in (args.manifest, labels_path, review_path) if path.exists()
        ]
        if existing:
            joined = "、".join(str(path) for path in existing)
            raise SystemExit(f"输出文件已存在，不会覆盖：{joined}")
        write_manifest(args.manifest, manifest)
        write_manual_labels(labels_path, manifest)
        write_manual_review_html(
            review_path,
            manifest,
            cut.project.source_folder or ".",
        )
        print(f"固定样本已生成：{args.manifest}")
        print(f"样本数量：{len(manifest['assets'])}")
        print(f"人工标注表：{labels_path}")
        print(f"盲评页面：{review_path}")
        return 0
    if args.command == "compare":
        with args.results.open(encoding="utf-8") as handle:
            records = json.load(handle)
        with args.labels.open(encoding="utf-8-sig", newline="") as handle:
            labels = list(csv.DictReader(handle))
        try:
            metrics = compare_ratings(records, labels)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc

        args.output.parent.mkdir(parents=True, exist_ok=True)
        try:
            with args.output.open("x", encoding="utf-8") as handle:
                json.dump(metrics, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
        except FileExistsError as exc:
            raise SystemExit(f"对比结果已存在，不会覆盖：{args.output}") from exc

        def percentage(value: object) -> str:
            return "无可用样本" if value is None else f"{float(value):.1%}"

        print(f"对比结果：{args.output}")
        print(f"成功评分：{metrics['scored_count']} / {metrics['sample_count']}")
        print(f"完全一致率：{percentage(metrics['exact_match_rate'])}")
        print(f"平均绝对误差：{metrics['mean_absolute_error']}")
        print(
            "4/5 星误判率："
            f"{percentage(metrics['high_rating_false_positive_rate'])}"
        )
        print(f"4/5 星召回率：{percentage(metrics['high_rating_recall'])}")
        return 0
    if args.command == "compare-variants":
        if len(args.variant) != 3:
            raise SystemExit("--variant 必须恰好提供三次")
        variant_dirs = dict(args.variant)
        if len(variant_dirs) != 3:
            raise SystemExit("三个候选版本名称必须唯一")
        variant_results = {
            name: load_variant_results(path) for name, path in variant_dirs.items()
        }
        for name, records in variant_results.items():
            if len(records) != 45:
                raise SystemExit(f"候选版本 {name} 不是 45 条结果")
            failures = [record for record in records if record.get("error")]
            if failures:
                raise SystemExit(f"候选版本 {name} 存在 {len(failures)} 条失败结果")

        labels = load_labels(args.labels)
        annotations = load_annotations(args.annotations)
        try:
            comparison = build_variant_comparison(
                variant_results,
                labels,
                annotations,
            )
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc

        output_json = args.output_dir / "comparison.json"
        output_html = args.output_dir / "v5-variant-review.html"
        target_paths = [output_json, output_html]
        for name, variant_dir in variant_dirs.items():
            target_paths.extend(
                [
                    variant_dir / "combined-results.json",
                    variant_dir / "metrics.json",
                ]
            )
        existing = [path for path in target_paths if path.exists()]
        if args.output_dir.exists() or existing:
            joined = "、".join(str(path) for path in existing or [args.output_dir])
            raise SystemExit(f"输出已存在，不会覆盖：{joined}")

        args.output_dir.mkdir(parents=True, exist_ok=False)
        for name, variant_dir in variant_dirs.items():
            _write_json_exclusive(
                variant_dir / "combined-results.json",
                variant_results[name],
            )
            _write_json_exclusive(
                variant_dir / "metrics.json",
                comparison["variants"][name]["metrics"],
            )
        _write_json_exclusive(output_json, comparison)
        write_variant_review_html(
            output_html,
            comparison,
            str(args.source_folder),
        )
        print(f"三版比较结果：{output_json}")
        print(f"三版复核页面：{output_html}")
        print(f"关键复核素材：{len(comparison['key_asset_ids'])}")
        return 0
    if args.command == "run":
        if args.concurrency < 1:
            raise SystemExit("--concurrency 必须大于等于 1")
        cut = read_cut_index(args.cut_index)
        with args.manifest.open(encoding="utf-8") as handle:
            manifest = json.load(handle)
        project_slug = cut.project.project_slug or args.cut_index.parent.name
        manifest_slug = manifest.get("project_slug")
        if manifest_slug != project_slug:
            raise SystemExit(
                f"manifest 属于 {manifest_slug}，当前 cut_index 属于 {project_slug}"
            )
        expected_fingerprint = project_fingerprint(
            project_slug,
            cut.project.source_folder,
        )
        if manifest.get("project_fingerprint") != expected_fingerprint:
            raise SystemExit("项目指纹不匹配：manifest 与当前素材根目录不属于同一项目")
        rating_guide = args.rating_guide.read_text(encoding="utf-8").strip()
        if not rating_guide:
            raise SystemExit("评分标准文件不能为空")

        load_dotenv(REPO_ROOT / ".env")
        config_path = cut.project.config_path
        software = load_software_config(legacy_project_path=config_path)
        editing_intent = EditingIntent.model_validate(cut.project.editing_intent or {})
        thread_local = threading.local()

        try:
            reserve_run_dir(args.output_dir)
        except FileExistsError as exc:
            raise SystemExit(f"输出目录已存在，请为本轮指定新目录：{args.output_dir}") from exc

        def analyze_visual(asset):
            provider = getattr(thread_local, "provider", None)
            if provider is None:
                provider = Provider(
                    software.llm,
                    editing_intent,
                    rating_guide=rating_guide,
                )
                thread_local.provider = provider
            return provider.analyze(asset)

        records = run_calibration(
            cut.assets,
            manifest,
            analyze_visual=analyze_visual,
            concurrency=args.concurrency,
        )
        json_path, csv_path = write_results(args.output_dir, records)
        failures = sum(1 for record in records if record["error"] is not None)
        print(f"评分校准完成：成功 {len(records) - failures}，失败 {failures}")
        print(f"JSON：{json_path}")
        print(f"人工复核 CSV：{csv_path}")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
