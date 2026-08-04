"""CLI sub-commands.

M0 仅提供占位；M1 接通了 ``init``；M2 接通了 ``analyze --stage scan``；
M3 在本文件接通 ``analyze --stage sample/full`` 与 ``run`` 命令，并在所有
命令启动前用 :mod:`dotenv` 把项目根目录的 ``.env`` 注入 ``os.environ``，
不覆盖已存在的环境变量（spec Q1 / SubTask 5.1）。

错误兜底原则（SubTask 5.5）：业务层异常（``AnalyzerError`` /
``ProviderError`` / ``ScanError`` / ``ConfigError`` / ``ProjectError`` /
``RuntimeError``）一律 ``click.echo(..., err=True)`` + ``sys.exit(非0)``；
不抛裸堆栈给用户。密钥永远不在错误文案中出现——provider/analyzer 已自己
把 ``message`` 写成不含密钥的形态，CLI 层只做透传。
"""

from __future__ import annotations

import dataclasses
import json
import sys
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import click
from dotenv import load_dotenv

from . import __version__
from .analyzer import (
    AnalyzeResult,
    AnalyzerError,
    full_analyze,
    sample_analyze,
)
from .arbiter import ArbiterError
from .cluster_runner import (
    ClusterResult,
    ClusterRunnerError,
    cluster as runner_cluster,
)
from .clip_selection.agent import CodexAuthenticationError
from .clip_selection.review import SelectionReviewError, render_selection_review
from .clip_selection.runner import SelectionError, run_selection
from .config import ConfigError, EagleSync, load_config
from .cut_index import read_cut_index, write_cut_index
from .eagle_sync import (
    AssetMapper,
    EagleSyncRunner,
    EagleUnavailableError,
    EagleV2Client,
    EagleVersionError,
    SyncOptions,
    SyncPreconditionError,
    load_mapping_config,
)
from .exporter import (
    ExportError,
    _summarise_for_stdout,
    copy_cut_index,
    render_assets_csv,
    render_review_html,
)
from .models import AnalysisStatus
from .paths import cut_index_path, eagle_apply_result_path
from .progress import PeriodicProgressReporter
from .project import (
    ProjectError,
    ProjectSummary,
    init_project,
    scaffold_config_file,
)
from .provider import ProviderError
from .runner import RunResult, run as runner_run
from .scan import ScanError, ScanResult, scan_project

_PLACEHOLDER = (
    "该能力将由后续模块提供（M5/M6）。当前为 M3 阶段。"
)

# 与 analyzer._ELIGIBLE_STATUSES 保持一致：scanned / analyzing / analyzed /
# analysis_failed 都可以再次进入 sample/full 分析。CLI 层硬卡用相同集合。
_ELIGIBLE_STATUS_VALUES = {
    AnalysisStatus.scanned.value,
    AnalysisStatus.analyzing.value,
    AnalysisStatus.analyzed.value,
    AnalysisStatus.analysis_failed.value,
}


def _bootstrap_env() -> None:
    """在所有命令真正执行业务前把 ``<cwd>/.env`` 注入 ``os.environ``。

    使用 ``override=False`` —— 已经在外部 shell 里 ``export`` 的变量优先。
    缺 ``.env`` 不报错（开发者可能直接 export 了）。
    """
    env_path = Path.cwd() / ".env"
    if env_path.is_file():
        load_dotenv(dotenv_path=env_path, override=False)


@click.group()
@click.version_option(__version__, prog_name="tripclipper")
def main() -> None:
    """TripClipper — local-first media triage and rough-cut planning tool."""
    _bootstrap_env()


@main.command("select")
@click.argument("slug")
@click.argument("brief_path", type=click.Path(path_type=Path))
@click.option("--base-dir", default=None, type=click.Path(path_type=Path), help="项目根目录基准。")
def select_command(slug: str, brief_path: Path, base_dir: Path | None) -> None:
    """用真实 Codex Agent 从 Markdown Brief 建立任务级主选候选池。"""
    try:
        result = run_selection(slug, brief_path, base_dir=base_dir)
    except (SelectionError, CodexAuthenticationError, OSError, ValueError) as exc:
        click.echo(f"选片失败：{exc}", err=True)
        raise click.exceptions.Exit(1) from exc
    click.echo("选片完成：")
    click.echo(f"  状态           : {result.state.status}")
    click.echo(f"  候选数         : {len(result.state.candidates)}")
    click.echo(f"  任务目录       : {result.task_dir}")
    if result.review_html_path is not None:
        click.echo(f"  审阅页面       : {result.review_html_path}")
    else:
        click.echo(
            "警告：选片已成功，但审阅页生成失败："
            f"{result.review_error or '未知错误'}",
            err=True,
        )


@main.command("select-review")
@click.argument("slug")
@click.argument("task_name")
@click.option(
    "--base-dir",
    default=None,
    type=click.Path(path_type=Path),
    help="项目根目录基准。",
)
@click.option("--open", "open_browser", is_flag=True, help="生成后用默认浏览器打开。")
def select_review_command(
    slug: str,
    task_name: str,
    base_dir: Path | None,
    open_browser: bool,
) -> None:
    """只读重建已有选片任务的离线验收页。"""
    try:
        output = render_selection_review(slug, task_name, base_dir=base_dir)
    except (SelectionReviewError, OSError, ValueError) as exc:
        click.echo(f"生成选片验收页失败：{exc}", err=True)
        raise click.exceptions.Exit(1) from exc
    click.echo(f"审阅页面: {output}")
    if open_browser:
        try:
            opened = webbrowser.open(output.as_uri())
        except OSError as exc:
            click.echo(f"审阅页已生成，但浏览器打开失败：{exc}", err=True)
            raise click.exceptions.Exit(1) from exc
        if not opened:
            click.echo("审阅页已生成，但浏览器未能打开。", err=True)
            raise click.exceptions.Exit(1)


def _print_summary(summary: ProjectSummary) -> None:
    """打印不含密钥的项目配置摘要（只展示 api_key_env 名称，绝不打印密钥）。"""
    model = summary.model_config_summary or {}
    click.echo("项目初始化完成：")
    click.echo(f"  项目名         : {summary.project_name}")
    click.echo(f"  slug          : {summary.project_slug}")
    click.echo(f"  素材目录       : {summary.source_folder}")
    click.echo(f"  素材目录存在    : {summary.source_folder_exists}")
    click.echo(f"  模型可用       : {summary.model_usable}")
    click.echo(f"  project_dir    : {summary.project_dir}")
    click.echo(f"  cut_index_path : {summary.cut_index_path}")
    click.echo(f"  provider       : {model.get('provider')}")
    click.echo(f"  vision_model   : {model.get('vision_model')}")
    click.echo(f"  api_key_env    : {model.get('api_key_env')}")
    if summary.warnings:
        click.echo("警告：")
        for warning in summary.warnings:
            click.echo(f"  - {warning}")


@main.command()
@click.option("--config", "config", default=None, help="Path to project.yaml.")
@click.option(
    "--scaffold",
    "scaffold",
    default=None,
    help="生成 project.yaml 模板的目标路径。",
)
@click.option("--project-name", "project_name", default=None, help="项目名（scaffold 模式必填）。")
@click.option("--source-folder", "source_folder", default=None, help="素材目录（scaffold 模式必填）。")
@click.option("--base-dir", "base_dir", default=None, help="项目根目录基准（透传给 init_project）。")
@click.option(
    "--force/--no-force",
    "force",
    default=False,
    help="已存在时是否覆盖。",
)
def init(
    config: str,
    scaffold: str,
    project_name: str,
    source_folder: str,
    base_dir: str,
    force: bool,
) -> None:
    """创建/初始化项目，或生成 project.yaml 模板（M1 / FR-1）。"""
    if scaffold is not None:
        if not project_name or not source_folder:
            click.echo(
                "scaffold 模式需同时提供 --project-name 与 --source-folder。",
                err=True,
            )
            sys.exit(2)
        try:
            written = scaffold_config_file(
                scaffold,
                project_name=project_name,
                source_folder=source_folder,
                force=force,
            )
        except ProjectError as exc:
            click.echo(f"生成模板失败：{exc}", err=True)
            sys.exit(1)
        click.echo(f"已生成 project.yaml 模板：{written}")
        return

    if config is not None:
        try:
            summary = init_project(config, base_dir=base_dir, force=force)
        except (ProjectError, ConfigError) as exc:
            click.echo(f"初始化项目失败：{exc}", err=True)
            sys.exit(1)
        _print_summary(summary)
        return

    click.echo(
        "用法：tripclipper init --config <project.yaml> [--base-dir <dir>] [--force]\n"
        "      tripclipper init --scaffold <目标路径> --project-name \"X\" "
        "--source-folder <dir> [--force]",
        err=True,
    )
    sys.exit(2)


@main.command()
@click.option("--host", default="127.0.0.1", show_default=True, help="Bind host.")
@click.option("--port", default=8765, show_default=True, type=int, help="Bind port.")
def serve(host: str, port: int) -> None:
    """Start the local FastAPI launcher page (placeholder)."""
    click.echo(f"serve (host={host}, port={port}): {_PLACEHOLDER}")


def _print_scan_result(result: ScanResult) -> None:
    """打印 Stage 1 扫描摘要（总数/各类型/跳过/失败/能力）。"""
    cap = result.capabilities
    click.echo("扫描完成（Stage 1）：")
    click.echo(f"  发现媒体总数   : {result.total}")
    click.echo(f"    视频         : {result.by_type.get('video', 0)}")
    click.echo(f"    图片         : {result.by_type.get('image', 0)}")
    click.echo(f"    音频         : {result.by_type.get('audio', 0)}")
    click.echo(f"  跳过非媒体     : {result.skipped}")
    click.echo(f"  单文件失败     : {result.failures}")
    click.echo(f"  ffmpeg 可用    : {cap.ffmpeg}")
    click.echo(f"  ffprobe 可用   : {cap.ffprobe}")
    click.echo(f"  切分 session   : {result.session_count} 个（gap=1h）")
    click.echo(f"  cut_index      : {result.cut_index_path}")
    if result.is_empty:
        click.echo("  提示：未发现可处理媒体。")


def _format_session_preview_line(session) -> str:
    """One ``Sessions preview`` row: id + time range + count."""
    label = session.session_id.ljust(20)
    count = f"n={session.asset_count}"
    if session.started_at is not None and session.ended_at is not None:
        # started_at/ended_at are stored in UTC; show local wall-clock time.
        start_dt = session.started_at
        end_dt = session.ended_at
        if start_dt.tzinfo is not None:
            start_dt = start_dt.astimezone()
        if end_dt.tzinfo is not None:
            end_dt = end_dt.astimezone()
        start = start_dt.strftime("%Y-%m-%d %H:%M")
        end = end_dt.strftime("%H:%M")
        return f"  {label}  {start} → {end}  {count}"
    return f"  {label}  {'':<24}{count}"


def _render_sessions_preview(sessions) -> list[str]:
    """Build the ``Sessions preview (gap=1h)`` block for dry-run output.

    When there are more than 12 sessions, show the first 5 and last 5 with a
    ``... (N sessions omitted) ...`` marker in between.
    """
    if not sessions:
        return []
    lines = ["Sessions preview (gap=1h):"]
    if len(sessions) > 12:
        head = sessions[:5]
        tail = sessions[-5:]
        omitted = len(sessions) - 10
        for s in head:
            lines.append(_format_session_preview_line(s))
        lines.append(f"  ... ({omitted} sessions omitted) ...")
        for s in tail:
            lines.append(_format_session_preview_line(s))
    else:
        for s in sessions:
            lines.append(_format_session_preview_line(s))
    return lines


def _render_tag_group_warning_lines(warnings) -> list[str]:
    if not warnings:
        return []
    lines = [f"⚠️ {len(warnings)} 个 tag group 维护警告："]
    for warning in warnings:
        lines.append(
            f"  - {warning.tag_group}: {warning.missing_tags} 个 tags；"
            f"{warning.error}"
        )
    return lines


def _print_analyze_result(result: AnalyzeResult) -> None:
    """打印 Stage 2 分析摘要（成功 / 失败 / 跳过 / 错误简要）。"""
    click.echo(f"分析完成（Stage 2 / {result.stage}）：")
    click.echo(f"  总计           : {result.total}")
    click.echo(f"  成功 N         : {result.succeeded}")
    click.echo(f"  失败 M         : {result.failed}")
    click.echo(f"  跳过 K         : {result.skipped}")
    if result.cut_index_path:
        click.echo(f"  cut_index      : {result.cut_index_path}")
    if result.log_path:
        click.echo(f"  日志           : {result.log_path}")
    if result.errors:
        click.echo("  失败素材（最多列出 5 条）：")
        for asset_id, reason in result.errors[:5]:
            # reason 可能包含 HTTP 状态码 + 截断后的响应体，不会包含密钥
            # （provider 已在构造异常时避开）。
            click.echo(f"    - {asset_id}: {reason}")


def _print_cluster_result(result: ClusterResult) -> None:
    click.echo("聚类完成（cluster）：")
    click.echo(f"  组总数         : {result.total_groups}")
    click.echo(f"  主选已决定     : {result.primary_decided}")
    click.echo(f"  待人工确认组   : {result.needs_review_groups}")
    click.echo(f"  仲裁失败       : {result.arbitration_failures}")
    click.echo(f"  候选池规模     : {result.pool_size}")
    click.echo(f"  备选数         : {result.alternate_count}")
    click.echo(f"  needs_review N : {result.needs_review_count}")
    click.echo(f"  被排除         : {result.excluded_count}")
    click.echo(f"  cut_index      : {result.cut_index_path}")
    click.echo(f"  日志           : {result.log_path}")


def _make_progress_reporter(stage: str) -> PeriodicProgressReporter:
    return PeriodicProgressReporter(stage, emit=click.echo)


def _eligible_assets_or_exit(slug: str, base_dir: str) -> None:
    """SubTask 5.2：sample 阶段硬卡——不存在或无可处理素材即退出。"""
    index_path = cut_index_path(slug, base_dir)
    if not index_path.exists():
        click.echo(
            f"项目 `{slug}` 尚未初始化或扫描。请先运行 "
            f"`tripclipper init --config <project.yaml>` 与 "
            f"`tripclipper analyze --stage scan --config <project.yaml>`。",
            err=True,
        )
        sys.exit(2)
    cut = read_cut_index(index_path)
    if not cut.assets or not any(
        (a.analysis_status.value if a.analysis_status else "")
        in _ELIGIBLE_STATUS_VALUES
        for a in cut.assets
    ):
        click.echo(
            "cut_index.json 中没有可分析的 asset。请先运行 "
            "`tripclipper analyze --stage scan --config <project.yaml>`。",
            err=True,
        )
        sys.exit(2)


def _maybe_warn_full_without_sample(slug: str, base_dir: str) -> None:
    """SubTask 5.3：full 阶段软警告（spec Q15）。"""
    index_path = cut_index_path(slug, base_dir)
    if not index_path.exists():
        # full 也需要先 scan，硬卡同 sample。
        click.echo(
            f"项目 `{slug}` 尚未初始化或扫描。请先运行 "
            f"`tripclipper init` 与 `tripclipper analyze --stage scan`。",
            err=True,
        )
        sys.exit(2)
    cut = read_cut_index(index_path)
    analysis = cut.analysis
    if not analysis or analysis.stage != "sample" or analysis.status != "completed":
        click.echo(
            "警告：未检测到已完成的 sample 阶段；建议先跑 "
            "`tripclipper analyze --stage sample` 评估抽样效果再进 full。",
            err=True,
        )


@main.command()
@click.argument("slug", required=False)
@click.option("--config", "config", default=None, help="Path to project.yaml.")
@click.option("--base-dir", "base_dir", default=None, help="项目根目录基准。")
@click.option(
    "--stage",
    type=click.Choice(["scan", "sample", "full", "cluster"]),
    default=None,
    help="Analysis stage.",
)
@click.option(
    "--no-extract-media/--extract-media",
    "no_extract_media",
    default=False,
    help="跳过缩略图/关键帧抽取（仅写基础信息与媒体元数据）。",
)
@click.option(
    "--force/--no-force",
    "force",
    default=False,
    help="(stage=full) 强制重分析已 analyzed 的素材。",
)
@click.option(
    "--concurrency",
    type=int,
    default=5,
    show_default=True,
    help="(stage=sample/full) 并发线程数。",
)
def analyze(
    slug: str,
    config: str,
    base_dir: str,
    stage: str,
    no_extract_media: bool,
    force: bool,
    concurrency: int,
) -> None:
    """Run Stage 1 scan or Stage 2 sample/full analysis."""
    # ---------- stage=scan：保留 M2 行为（用 --config 推导 slug） ----------
    if stage == "scan":
        if not config and not slug:
            click.echo(
                "用法：tripclipper analyze --stage scan --config <project.yaml> "
                "[--base-dir <dir>]",
                err=True,
            )
            sys.exit(2)
        try:
            if slug:
                effective_slug = slug
            else:
                project_config = load_config(config)
                effective_slug = project_config.project_slug or ""
            result = scan_project(
                effective_slug,
                base_dir=base_dir,
                extract_media=not no_extract_media,
                progress=_make_progress_reporter("scan"),
            )
        except (ScanError, ConfigError) as exc:
            click.echo(f"扫描失败：{exc}", err=True)
            sys.exit(1)
        _print_scan_result(result)
        return

    # ---------- stage=sample/full：M3 新接线 ----------
    if stage in ("sample", "full"):
        if not slug:
            click.echo(
                f"用法：tripclipper analyze <slug> --stage {stage} "
                f"[--concurrency N]"
                + (" [--force]" if stage == "full" else ""),
                err=True,
            )
            sys.exit(2)

        if stage == "sample":
            _eligible_assets_or_exit(slug, base_dir)
            try:
                result = sample_analyze(
                    slug,
                    base_dir=base_dir,
                    concurrency=concurrency,
                    progress=_make_progress_reporter("sample"),
                )
            except AnalyzerError as exc:
                click.echo(f"分析失败：{exc}", err=True)
                sys.exit(1)
            except ProviderError as exc:
                click.echo(f"分析失败（Provider）：{exc}", err=True)
                sys.exit(1)
            _print_analyze_result(result)
            return

        # stage == "full"
        _maybe_warn_full_without_sample(slug, base_dir)
        try:
            result = full_analyze(
                slug,
                base_dir=base_dir,
                force=force,
                concurrency=concurrency,
                progress=_make_progress_reporter("full"),
            )
        except AnalyzerError as exc:
            click.echo(f"分析失败：{exc}", err=True)
            sys.exit(1)
        except ProviderError as exc:
            click.echo(f"分析失败（Provider）：{exc}", err=True)
            sys.exit(1)
        _print_analyze_result(result)
        if result.skipped > 0 and not force:
            click.echo(f"跳过 {result.skipped} 个已完成素材（用 --force 重新分析）。")
        if result.failed > 0:
            click.echo(f"失败 {result.failed} 个素材；下一次 full 会重试。")
        return

    # ---------- stage=cluster：M4 新接线 ----------
    if stage == "cluster":
        if not slug:
            click.echo(
                "用法：tripclipper analyze <slug> --stage cluster [--base-dir <dir>]",
                err=True,
            )
            sys.exit(2)
        try:
            cluster_result = runner_cluster(slug, base_dir=base_dir)
        except ClusterRunnerError as exc:
            click.echo(f"聚类失败：{exc}", err=True)
            sys.exit(1)
        except ArbiterError as exc:
            click.echo(f"聚类失败（Arbiter）：{exc}", err=True)
            sys.exit(1)
        _print_cluster_result(cluster_result)
        return

    # 无 stage：保留旧的占位提示。
    click.echo(f"analyze (config={config}, stage={stage}): {_PLACEHOLDER}")


@main.command()
@click.argument("slug")
@click.option("--base-dir", "base_dir", default=None, help="项目根目录基准。")
@click.option(
    "--pause-after",
    "pause_after",
    type=click.Choice(["sample"]),
    default=None,
    help="在指定阶段后阻塞等用户回车再继续（仅支持 sample）。",
)
@click.option(
    "--concurrency",
    type=int,
    default=5,
    show_default=True,
    help="sample/full 阶段并发线程数。",
)
def run(slug: str, base_dir: str, pause_after: str, concurrency: int) -> None:
    """一键编排：scan → sample → full（绕过 analyze 的分步硬卡，Q15）。"""
    try:
        result: RunResult = runner_run(
            slug,
            base_dir=base_dir,
            pause_after_sample=(pause_after == "sample"),
            concurrency=concurrency,
            progress_factory=_make_progress_reporter,
        )
    except KeyboardInterrupt:
        click.echo("\n已收到 Ctrl-C，已落盘的进度保留；下次重跑会从中断处续接。", err=True)
        sys.exit(130)
    except (AnalyzerError, ScanError, ClusterRunnerError) as exc:
        click.echo(f"run 失败：{exc}", err=True)
        sys.exit(1)
    except ProviderError as exc:
        click.echo(f"run 失败（Provider）：{exc}", err=True)
        sys.exit(1)
    except (ConfigError, ProjectError) as exc:
        click.echo(f"run 失败（配置）：{exc}", err=True)
        sys.exit(1)

    click.echo("run 完成（scan → sample → full → cluster → export）：")
    if result.scan is not None:
        click.echo(f"  [scan]   total={result.scan.total} failures={result.scan.failures}")
    if result.sample is not None:
        click.echo(
            f"  [sample] succeeded={result.sample.succeeded} "
            f"failed={result.sample.failed} skipped={result.sample.skipped}"
        )
    if result.full is not None:
        click.echo(
            f"  [full]   succeeded={result.full.succeeded} "
            f"failed={result.full.failed} skipped={result.full.skipped}"
        )
    if result.cluster is not None:
        cr = result.cluster
        click.echo(
            f"  [cluster] groups={cr.total_groups} pool_size={cr.pool_size} "
            f"arbitration_failures={cr.arbitration_failures}"
        )
    if result.export_cut_index_path is not None:
        click.echo(f"  [export] cut_index 副本: {result.export_cut_index_path}")
    if result.export_review_html_path is not None:
        click.echo(f"  [export] review.html:   {result.export_review_html_path}")
    if result.export_assets_csv_path is not None:
        click.echo(f"  [export] assets.csv:   {result.export_assets_csv_path}")
    for note in result.notes:
        click.echo(f"  · {note}")

    if result.export_review_html_path is not None:
        webbrowser.open(f"file://{result.export_review_html_path}")


@main.command()
@click.argument("slug")
@click.option("--base-dir", "base_dir", default=None, help="项目根目录基准。")
@click.option(
    "--cut-index-only/--no-cut-index-only",
    "cut_index_only",
    default=False,
    show_default=True,
    help="仅生成 cut_index 副本，跳过 review.html。",
)
def export(slug: str, base_dir: str, cut_index_only: bool) -> None:
    """生成派生产物（cut_index 副本 + review.html）。默认自动打开 review.html。"""
    try:
        cut_index_copy_path = copy_cut_index(slug, base_dir=base_dir)
        click.echo(f"已生成 cut_index 副本: {cut_index_copy_path}")
        csv_path = render_assets_csv(slug, base_dir=base_dir)
        click.echo(f"已生成 assets.csv: {csv_path}")
        html_path: Optional[Path] = None
        if not cut_index_only:
            html_path = render_review_html(slug, base_dir=base_dir)
            click.echo(f"已生成 review.html: {html_path}")
        cut = read_cut_index(cut_index_path(slug, base_dir=base_dir))
        click.echo("")
        click.echo(_summarise_for_stdout(cut))
        if html_path is not None:
            webbrowser.open(f"file://{html_path}")
    except ExportError as exc:
        click.echo(f"导出失败：{exc}", err=True)
        sys.exit(1)


@main.command(name="sync-eagle")
@click.argument("slug")
@click.option("--base-dir", "base_dir", default=None, help="项目根目录基准。")
@click.option(
    "--apply/--dry-run",
    "apply_flag",
    default=False,
    help="写入 Eagle（--apply）或仅预览（--dry-run，默认）。",
)
@click.option(
    "--skip",
    "skip_synced",
    is_flag=True,
    default=False,
    help="跳过已同步(synced)素材。",
)
@click.option(
    "--reset",
    "reset",
    is_flag=True,
    default=False,
    help="把已同步 items 移到回收站并清除 eagle_item_id 后重建（默认需二次确认）。",
)
@click.option(
    "--retry-failed",
    "retry_failed",
    is_flag=True,
    default=False,
    help="仅处理上次失败(failed)的素材。",
)
@click.option(
    "--skip-unanalyzed",
    "skip_unanalyzed",
    is_flag=True,
    default=False,
    help="跳过未分析(scanned)素材而非启动期阻断。",
)
@click.option(
    "--strict-mapping",
    "strict_mapping",
    is_flag=True,
    default=False,
    help="禁用 auto_map_unknown：未声明字段不产 tag。",
)
@click.option(
    "--no-smart-folders",
    "no_smart_folders",
    is_flag=True,
    default=False,
    help="跳过 smart folder 维护阶段。",
)
@click.option(
    "--library-path",
    "library_path",
    default=None,
    help="预期的 Eagle 库路径（.library 结尾）。若与 Eagle 当前打开的库不一致则中止。"
    "未传时回落到 project.yaml 的 eagle_sync.library_path。",
)
@click.option(
    "--yes",
    "yes",
    is_flag=True,
    default=False,
    help="跳过 --reset 的二次确认（用于 CI）。",
)
def sync_eagle(
    slug,
    base_dir,
    apply_flag,
    skip_synced,
    reset,
    retry_failed,
    skip_unanalyzed,
    strict_mapping,
    no_smart_folders,
    library_path,
    yes,
):
    """把项目分析结果同步到 Eagle（dry-run 预览 / apply 写入）。"""
    index_path = cut_index_path(slug, base_dir)
    if not index_path.exists():
        click.echo(f"项目 `{slug}` 不存在或尚未扫描/分析。", err=True)
        sys.exit(2)

    cut = read_cut_index(index_path)

    config = load_mapping_config()
    if strict_mapping:
        config = dataclasses.replace(config, auto_map_unknown=False)

    # Eagle client 连接参数：优先读项目 project.yaml.eagle_sync；缺失则默认。
    project_config_path = cut.project.config_path
    eagle_settings = EagleSync()
    if project_config_path and Path(project_config_path).is_file():
        try:
            eagle_settings = load_config(project_config_path).eagle_sync
        except ConfigError:
            # 配置损坏时不影响 sync-eagle，仍用默认值。
            eagle_settings = EagleSync()

    # 库路径门禁：命令行 --library-path 优先；未传则回落到 project.yaml。
    effective_library_path = library_path or eagle_settings.library_path

    # --reset 二次确认（仅 apply 时 reset 生效）
    if reset and apply_flag and not yes:
        count = sum(1 for a in cut.assets if a.eagle_item_id)
        click.confirm(
            f"将把 {count} 条 Eagle items 移到回收站，是否继续?", abort=True
        )

    sync_timestamp = datetime.now(timezone.utc).isoformat()

    options = SyncOptions(
        apply=apply_flag,
        skip_synced=skip_synced,
        reset=reset,
        retry_failed=retry_failed,
        skip_unanalyzed=skip_unanalyzed,
        strict_mapping=strict_mapping,
        no_smart_folders=no_smart_folders,
    )

    project_slug = cut.project.project_slug or slug

    try:
        with EagleV2Client(
            base_url=eagle_settings.api_base_url,
            api_token=eagle_settings.api_token,
        ) as client:
            # 启动期库路径校验：如指定 --library-path（或 project.yaml 里配置了
            # library_path），必须与 Eagle 当前打开的库一致，避免误把素材写进
            # 另一个库。M6 不主动 switch，只做门禁。
            if effective_library_path:
                try:
                    live_library = client.fetch_library()
                except EagleUnavailableError as exc:
                    click.echo(
                        f"无法连接到 Eagle：{exc}\n"
                        "请确认 Eagle 应用已启动，且版本 ≥ 4.0 Build 22。",
                        err=True,
                    )
                    sys.exit(2)
                except EagleVersionError as exc:
                    click.echo(
                        f"Eagle 版本过低：{exc}\n"
                        "需要 Eagle V2 Web API（版本 ≥ 4.0 Build 22）。",
                        err=True,
                    )
                    sys.exit(2)
                live_path = (live_library or {}).get("path") or ""
                if Path(live_path).resolve() != Path(effective_library_path).resolve():
                    source = (
                        "--library-path"
                        if library_path
                        else "project.yaml 的 eagle_sync.library_path"
                    )
                    click.echo(
                        f"Eagle 当前打开的库与期望不一致（期望值来自 {source}）：\n"
                        f"  期望: {effective_library_path}\n"
                        f"  当前: {live_path or '(未知)'}\n"
                        "请在 Eagle 中切换到目标库后重试。",
                        err=True,
                    )
                    sys.exit(2)

            mapper = AssetMapper(
                config,
                project_slug=project_slug,
                sync_timestamp=sync_timestamp,
                project_dir=cut_index_path(project_slug).parent,
            )
            runner = EagleSyncRunner(
                client,
                mapper,
                config,
                options,
                eagle_library_path=effective_library_path,
            )
            updated_cut, result = runner.run(cut)
    except EagleUnavailableError as exc:
        click.echo(
            f"无法连接到 Eagle：{exc}\n"
            "请确认 Eagle 应用已启动，且版本 ≥ 4.0 Build 22。",
            err=True,
        )
        sys.exit(2)
    except EagleVersionError as exc:
        click.echo(
            f"Eagle 版本过低：{exc}\n"
            "需要 Eagle V2 Web API（版本 ≥ 4.0 Build 22）。",
            err=True,
        )
        sys.exit(2)
    except SyncPreconditionError as exc:
        click.echo(f"无法开始同步：{exc}", err=True)
        sys.exit(2)

    if apply_flag:
        # 持久化成功项（即使中途中止也保留已成功的写回）。
        write_cut_index(index_path, updated_cut)
        result_path = eagle_apply_result_path(slug, base_dir)
        result_path.write_text(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    totals = result.totals
    if not apply_flag:
        click.echo(
            f"[dry-run] 待同步 {totals['synced']} 条素材"
            f"（总计 {totals['total']}，跳过 {totals['skipped']}）。未写入 Eagle。"
        )
        if not no_smart_folders:
            click.echo(
                "Smart Folder 计划: 将建/更新 "
                f"{len(config.smart_folder_presets)} 个"
                "（干跑不连库对账，实际执行时按 name 幂等 reconcile）"
            )
        for line in _render_sessions_preview(cut.sessions):
            click.echo(line)
    else:
        if result.aborted:
            click.echo(f"❌ 已中止：{result.abort_reason}", err=True)
        else:
            click.echo(
                f"✅ 已同步 {totals['synced']}/{totals['total']} 条素材到 Eagle。"
            )
        if totals["failed"] > 0:
            click.echo(
                f"⚠️ {totals['failed']} 条失败，详见 eagle_apply_result.json。"
            )
        if result.smart_folders is not None:
            ready = (
                len(result.smart_folders.created)
                + len(result.smart_folders.updated)
                + len(result.smart_folders.unchanged)
            )
            failed = len(result.smart_folders.warnings)
            if failed == 0:
                click.echo(
                    "✅ Smart Folder: "
                    f"{ready} 个已就绪（新建 {len(result.smart_folders.created)} / "
                    f"更新 {len(result.smart_folders.updated)} / "
                    f"保持 {len(result.smart_folders.unchanged)}）"
                )
            else:
                click.echo(
                    f"⚠️ Smart Folder: {ready} 个已就绪，{failed} 个失败"
                    "（详见 eagle_apply_result.json）"
                )

    if result.tag_group_warnings:
        for line in _render_tag_group_warning_lines(result.tag_group_warnings):
            click.echo(line)
    if getattr(result, "folder_warnings", None):
        click.echo(f"⚠️ {len(result.folder_warnings)} 个 session folder 归属警告。")


if __name__ == "__main__":  # pragma: no cover
    main()
