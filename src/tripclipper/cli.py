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

import sys
import webbrowser
from pathlib import Path

import click
from dotenv import load_dotenv

from . import __version__
from .analyzer import (
    AnalyzeResult,
    AnalyzerError,
    full_analyze,
    sample_analyze,
)
from .config import ConfigError, load_config
from .cut_index import read_cut_index
from .exporter import ExportError, render_review_html
from .models import AnalysisStatus
from .paths import cut_index_path
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
    click.echo(f"  cut_index      : {result.cut_index_path}")
    if result.is_empty:
        click.echo("  提示：未发现可处理媒体。")


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
    type=click.Choice(["scan", "sample", "full"]),
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
        )
    except KeyboardInterrupt:
        click.echo("\n已收到 Ctrl-C，已落盘的进度保留；下次重跑会从中断处续接。", err=True)
        sys.exit(130)
    except (AnalyzerError, ScanError) as exc:
        click.echo(f"run 失败：{exc}", err=True)
        sys.exit(1)
    except ProviderError as exc:
        click.echo(f"run 失败（Provider）：{exc}", err=True)
        sys.exit(1)
    except (ConfigError, ProjectError) as exc:
        click.echo(f"run 失败（配置）：{exc}", err=True)
        sys.exit(1)

    click.echo("run 完成（scan → sample → full）：")
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
    for note in result.notes:
        click.echo(f"  · {note}")


@main.command()
@click.argument("slug")
@click.option("--base-dir", "base_dir", default=None, help="项目根目录基准。")
@click.option(
    "--html/--no-html",
    "html_flag",
    default=True,
    show_default=True,
    help="是否产出 review.html（M5-early 当前只支持 HTML）。",
)
@click.option(
    "--open/--no-open",
    "open_flag",
    default=False,
    show_default=True,
    help="生成成功后是否用系统浏览器打开。",
)
def export(slug: str, base_dir: str, html_flag: bool, open_flag: bool) -> None:
    """生成派生产物（M5-early：仅 review.html）。"""
    if not html_flag:
        click.echo(
            "M5-early 当前只支持 HTML 导出，CSV/MD 留给 M5 完整版。",
            err=True,
        )
        sys.exit(2)
    try:
        out_path = render_review_html(slug, base_dir=base_dir)
    except ExportError as exc:
        click.echo(f"导出失败：{exc}", err=True)
        sys.exit(1)
    click.echo(f"已生成 review.html: {out_path}")
    if open_flag:
        webbrowser.open(f"file://{out_path}")


@main.command(name="sync-eagle")
@click.option("--project", "project", default=None, help="Project slug.")
@click.option(
    "--dry-run/--apply",
    "dry_run",
    default=True,
    help="Plan only (--dry-run) or write to Eagle (--apply).",
)
def sync_eagle(project: str, dry_run: bool) -> None:
    """Sync the project to Eagle in dry-run or apply mode (placeholder)."""
    mode = "dry-run" if dry_run else "apply"
    click.echo(f"sync-eagle (project={project}, mode={mode}): {_PLACEHOLDER}")


if __name__ == "__main__":  # pragma: no cover
    main()
