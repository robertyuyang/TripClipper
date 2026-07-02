"""M3 一键编排：scan → sample → (pause?) → full → cluster → export 串行执行。

CLI 入口为 ``tripclipper run <slug> [--pause-after sample] [--concurrency N]``，
对应 spec Q15：``run`` 命令绕过 ``analyze`` 的分步硬卡，由编排自身保证
前置 stage 已完成（先调 M2 ``scan_project`` 把 ``cut_index.json``
建出来）。

设计要点（参见 ``docs/specs/M3-real-llm-analysis/spec.md``）：

- Q15：runner 顺序 ``scan → sample → full``；不复用 CLI 层的"必须先 scan"
  硬卡，而是真把 scan 跑一遍（已扫描过的项目会幂等合并）。
- Q12：``analyzer._run`` 内部每 5 个素材落一次 ``cut_index.json``，所以
  ``KeyboardInterrupt`` 中断时磁盘上始终是一致状态。runner 只负责把
  ``KeyboardInterrupt`` 翻译成清晰的退出语义，不做"清场"动作。
- ``pause_after_sample=True``：sample 完成后用 ``input()`` 阻塞等回车；
  收到 Ctrl-C 同样优雅退出。
- export 是最后一步派生产物，只写盘、不改 cut_index；单点失败按 note 记录、
  不让整条 run 变成非零退出（cut_index 已经在 cluster 阶段落好了盘）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, Union

from .analyzer import AnalyzeResult, full_analyze, sample_analyze
from .arbiter import ArbiterError
from .cluster_runner import (
    ClusterResult,
    ClusterRunnerError,
    cluster as cluster_runner_cluster,
)
from .exporter import ExportError, copy_cut_index, render_review_html
from .scan import ScanResult, scan_project

_PathLike = Union[str, Path]


@dataclass
class RunResult:
    """一次 ``run`` 调用的结果摘要，供 CLI 直接展示。"""

    slug: str
    scan: Optional[ScanResult] = None
    sample: Optional[AnalyzeResult] = None
    full: Optional[AnalyzeResult] = None
    cluster: Optional[ClusterResult] = None
    export_cut_index_path: Optional[Path] = None
    export_review_html_path: Optional[Path] = None
    interrupted: bool = False
    interrupted_stage: Optional[str] = None
    notes: list[str] = field(default_factory=list)


def run(
    slug: str,
    *,
    base_dir: Optional[_PathLike] = None,
    pause_after_sample: bool = False,
    concurrency: int = 5,
    _input: Callable[[str], str] = input,
) -> RunResult:
    """按 scan → sample → full 顺序串起 M2/M3。

    ``_input`` 是测试钩子：默认使用内置 :func:`input`，单元 / CLI 测试可注入
    一个返回固定字符串的可调用对象，避免真起 stdin 阻塞。``pause_after_sample``
    为 False 时此参数无效。

    退出语义：

    - 正常完成：返回 :class:`RunResult`，``scan``/``sample``/``full`` 三字段
      均有值，``interrupted=False``。
    - 用户 Ctrl-C：捕获 :class:`KeyboardInterrupt`，把 ``interrupted=True`` /
      ``interrupted_stage`` 记入结果后再次抛出，由 CLI 层翻译成退出码（已落
      盘的进度由 :func:`analyzer._run` 的 5+5+... 增量落盘自然保留）。
    """
    result = RunResult(slug=slug)

    # ---------- Stage 1: scan ----------
    try:
        result.scan = scan_project(slug, base_dir=base_dir)
    except KeyboardInterrupt:
        result.interrupted = True
        result.interrupted_stage = "scan"
        raise

    # ---------- Stage 2: sample ----------
    try:
        result.sample = sample_analyze(
            slug,
            base_dir=base_dir,
            concurrency=concurrency,
        )
    except KeyboardInterrupt:
        result.interrupted = True
        result.interrupted_stage = "sample"
        raise

    # ---------- 可选暂停 ----------
    if pause_after_sample:
        try:
            _input("\nSample 阶段已完成。按回车继续 full 分析，按 Ctrl-C 中止。\n")
        except KeyboardInterrupt:
            result.interrupted = True
            result.interrupted_stage = "pause"
            raise
        except EOFError:
            # 非交互式 stdin（如 CliRunner 没注入 input）等价于继续。
            result.notes.append("pause_after_sample: stdin EOF，自动继续 full")

    # ---------- Stage 3: full ----------
    try:
        result.full = full_analyze(
            slug,
            base_dir=base_dir,
            force=False,
            concurrency=concurrency,
        )
    except KeyboardInterrupt:
        result.interrupted = True
        result.interrupted_stage = "full"
        raise

    # ---------- Stage 4: cluster ----------
    try:
        result.cluster = cluster_runner_cluster(slug, base_dir=base_dir)
    except KeyboardInterrupt:
        result.interrupted = True
        result.interrupted_stage = "cluster"
        raise
    except (ClusterRunnerError, ArbiterError) as exc:
        result.notes.append(f"cluster 跳过：{exc}")

    # ---------- Stage 5: export ----------
    # 派生产物（cut_index 副本 + review.html）失败不影响 run 的整体退出码：
    # cut_index.json 已经在前面几步里增量落盘，用户可以事后单独重跑
    # `tripclipper export <slug>`。KeyboardInterrupt 仍然按中断上抛。
    try:
        result.export_cut_index_path = copy_cut_index(slug, base_dir=base_dir)
    except KeyboardInterrupt:
        result.interrupted = True
        result.interrupted_stage = "export"
        raise
    except ExportError as exc:
        result.notes.append(f"export cut_index 跳过：{exc}")

    try:
        result.export_review_html_path = render_review_html(slug, base_dir=base_dir)
    except KeyboardInterrupt:
        result.interrupted = True
        result.interrupted_stage = "export"
        raise
    except ExportError as exc:
        result.notes.append(f"export review.html 跳过：{exc}")

    return result


__all__ = ["RunResult", "run"]
