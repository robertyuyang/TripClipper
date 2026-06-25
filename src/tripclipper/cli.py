"""CLI sub-command skeleton (TD 3).

In M0 every sub-command prints a clear placeholder message and exits with code
0. No business logic is implemented here.
"""

from __future__ import annotations

import sys

import click

from . import __version__
from .config import ConfigError, load_config
from .project import (
    ProjectError,
    ProjectSummary,
    init_project,
    scaffold_config_file,
)
from .scan import ScanError, ScanResult, scan_project

_PLACEHOLDER = (
    "该能力将由后续模块提供（M2/M3/M5/M6）。当前为 M0 阶段。"
)


@click.group()
@click.version_option(__version__, prog_name="tripclipper")
def main() -> None:
    """TripClipper — local-first media triage and rough-cut planning tool."""


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


@main.command()
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
def analyze(
    config: str, base_dir: str, stage: str, no_extract_media: bool
) -> None:
    """Run Stage 1 scan or Stage 2 sample/full analysis."""
    if stage == "scan":
        if not config:
            click.echo(
                "用法：tripclipper analyze --stage scan --config <project.yaml> "
                "[--base-dir <dir>]",
                err=True,
            )
            sys.exit(2)
        try:
            project_config = load_config(config)
            slug = project_config.project_slug or ""
            result = scan_project(
                slug,
                base_dir=base_dir,
                extract_media=not no_extract_media,
            )
        except (ScanError, ConfigError) as exc:
            click.echo(f"扫描失败：{exc}", err=True)
            sys.exit(1)
        _print_scan_result(result)
        return

    click.echo(f"analyze (config={config}, stage={stage}): {_PLACEHOLDER}")


@main.command()
@click.option("--project", "project", default=None, help="Project slug.")
def export(project: str) -> None:
    """Generate derived artefacts from cut_index.json (placeholder)."""
    click.echo(f"export (project={project}): {_PLACEHOLDER}")


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
