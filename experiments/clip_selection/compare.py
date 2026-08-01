"""比较多次选片运行的结构化指标。"""

from __future__ import annotations

import json
from pathlib import Path

import click

from .contracts import ClipStatus, SelectionRun


def summarize(run: SelectionRun) -> dict[str, object]:
    return {
        "selection_id": run.selection_id,
        "run_status": run.run_status.value,
        "rounds": run.rounds,
        "frame_requests": run.frame_requests,
        "rejected_actions": run.rejected_actions,
        "checkpoint_count": run.checkpoint_count,
        "clip_count": len(run.clips),
        "primary_count": sum(clip.status is ClipStatus.primary for clip in run.clips),
        "needs_review_count": sum(
            clip.status is ClipStatus.needs_review for clip in run.clips
        ),
    }


@click.command()
@click.argument("results", nargs=-1, type=click.Path(exists=True, path_type=Path))
def main(results: tuple[Path, ...]) -> None:
    """输出一个或多个选片结果的可比指标。"""
    if not results:
        raise click.ClickException("至少提供一个选片结果 JSON")
    report = {
        str(path): summarize(
            SelectionRun.model_validate_json(path.read_text(encoding="utf-8"))
        )
        for path in results
    }
    click.echo(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
