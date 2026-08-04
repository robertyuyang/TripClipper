"""首次选片任务的成功路径编排。"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tripclipper.cut_index import read_cut_index
from tripclipper.paths import (
    cut_index_path,
    selection_shared_frames_dir,
    selection_task_dir,
)

from .agent import build_codex_model, ensure_codex_authenticated, run_agent
from .asset_tools import AssetBrowser
from .frames import FrameSampler
from .models import SelectionState
from .review import SelectionReviewError, render_selection_review
from .selection_tools import SelectionTools
from .store import SelectionStore
from .validator import SelectionValidator


class SelectionError(RuntimeError):
    pass


@dataclass(frozen=True)
class SelectionResult:
    state: SelectionState
    task_dir: Path
    brief_path: Path
    state_path: Path
    events_path: Path
    review_html_path: Path | None
    review_error: str | None


def parse_target_duration(brief: str) -> float:
    """解析常见秒/分钟表达；无法识别时使用 60 秒。"""
    minute_match = re.search(
        r"(?<![\d.])(\d+(?:\.\d+)?)\s*(?:分钟|分|min(?:ute)?s?)",
        brief,
        flags=re.IGNORECASE,
    )
    if minute_match:
        return float(minute_match.group(1)) * 60
    second_match = re.search(
        r"(?<![\d.])(\d+(?:\.\d+)?)\s*(?:秒|s(?:ec(?:ond)?s?)?)",
        brief,
        flags=re.IGNORECASE,
    )
    if second_match:
        return float(second_match.group(1))
    return 60.0


def _load_runtime_instructions() -> str:
    package_dir = Path(__file__).parent
    system_prompt = (package_dir / "prompts" / "system.md").read_text(
        encoding="utf-8"
    )
    skill_dir = (
        package_dir
        / "skills"
        / "custom"
        / "clip_selection"
    )
    skill = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    references = "\n\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((skill_dir / "references").glob("*.md"))
    )
    return (
        f"{system_prompt}\n\n<clip_selection_skill>\n{skill}\n\n"
        f"{references}\n</clip_selection_skill>"
    )


def run_selection(
    slug: str,
    brief_path: str | Path,
    *,
    base_dir: str | Path | None = None,
    model: Any | None = None,
    asset_page_size: int = 20,
) -> SelectionResult:
    source_brief = Path(brief_path)
    if not source_brief.is_file():
        raise SelectionError(f"Brief 不存在：{source_brief}")
    if source_brief.suffix.lower() != ".md":
        raise SelectionError("Brief 必须是 Markdown 文件（.md）")
    task_name = source_brief.stem
    if not task_name or any(separator in task_name for separator in ("/", "\\")):
        raise SelectionError("任务名称不能为空或包含路径分隔符")
    if task_name == "shared_frames":
        raise SelectionError("任务名称不能使用保留名称 shared_frames")

    index_path = cut_index_path(slug, base_dir)
    if not index_path.is_file():
        raise SelectionError(f"素材索引不存在：{index_path}")
    task_dir = selection_task_dir(slug, task_name, base_dir)
    store = SelectionStore(task_dir)
    if store.state_path.exists():
        raise SelectionError(
            "选片任务已存在；票据 01 只支持从空任务首次运行。恢复与重走由后续票据提供。"
        )

    brief = source_brief.read_text(encoding="utf-8")
    state = SelectionState(
        task_name=task_name,
        target_duration_sec=parse_target_duration(brief),
    )
    task_dir.mkdir(parents=True, exist_ok=True)
    task_brief_path = task_dir / "brief.md"
    shutil.copyfile(source_brief, task_brief_path)
    store.save(state)
    store.append_event(
        "selection_started",
        data={"task_name": task_name, "target_duration_sec": state.target_duration_sec},
    )

    cut = read_cut_index(index_path)
    browser = AssetBrowser(
        cut.assets,
        state,
        store,
        page_size=asset_page_size,
    )
    validator = SelectionValidator(
        browser.asset_durations,
        asset_ids=set(browser.by_id),
        total_pages=browser.total_pages,
    )
    frame_sampler = FrameSampler(
        browser.by_id,
        state,
        store,
        selection_shared_frames_dir(slug, base_dir),
        source_folder=cut.project.source_folder,
    )
    selection_tools = SelectionTools(
        browser,
        state,
        store,
        validator,
        frame_sampler=frame_sampler,
    )

    if model is None:
        ensure_codex_authenticated()
        model = build_codex_model()
    user_prompt = (
        f"项目：{slug}\n"
        f"素材数量：{len(cut.assets)}\n"
        f"素材分页总数：{browser.total_pages}\n"
        f"目标时长：{state.target_duration_sec:g} 秒\n\n"
        "以下是完整 Brief：\n\n"
        f"{brief}"
    )
    run_agent(
        model=model,
        tools=selection_tools.as_langchain_tools(),
        system_prompt=_load_runtime_instructions(),
        user_prompt=user_prompt,
    )
    if state.status != "completed":
        raise SelectionError("Agent 已结束，但选片任务尚未通过完成校验。")
    review_html_path: Path | None = None
    review_error: str | None = None
    try:
        review_html_path = render_selection_review(
            slug,
            task_name,
            base_dir=base_dir,
        )
    except SelectionReviewError as exc:
        # 审阅页是完成结果的只读派生产物；生成失败不能回滚已完成状态。
        review_error = str(exc)
    return SelectionResult(
        state=state,
        task_dir=task_dir,
        brief_path=task_brief_path,
        state_path=store.state_path,
        events_path=store.events_path,
        review_html_path=review_html_path,
        review_error=review_error,
    )


__all__ = [
    "SelectionError",
    "SelectionResult",
    "parse_target_duration",
    "run_selection",
]
