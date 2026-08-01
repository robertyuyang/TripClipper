from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import click

from tripclipper.config import load_software_config

from experiments.clip_selection.contracts import ProjectSnapshot, RunBudget, SelectionBrief, SelectionRequest
from experiments.clip_selection.frame_source import ProjectFrameSource
from experiments.clip_selection.openai_model import OpenAISelectionModel, SelectionModelError

from .harness import PolicyGuardedSelectionHarness


@click.command()
@click.argument("slug")
@click.option("--base-dir", type=click.Path(path_type=Path), default=Path("projects"))
@click.option("--target-duration-sec", type=float, required=True)
@click.option("--style", required=True)
@click.option("--max-review-clips", type=int, default=5, show_default=True)
@click.option("--max-rounds", type=int, default=20, show_default=True)
@click.option("--max-frame-requests", type=int, default=8, show_default=True)
@click.option("--selection-id", default=None)
@click.option("--output", type=click.Path(path_type=Path), default=None)
@click.option("--resume", is_flag=True)
def main(
    slug: str,
    base_dir: Path,
    target_duration_sec: float,
    style: str,
    max_review_clips: int,
    max_rounds: int,
    max_frame_requests: int,
    selection_id: str | None,
    output: Path | None,
    resume: bool,
) -> None:
    """运行 Policy 保护状态的生产选片 Harness。"""
    identifier = selection_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    cut_path = base_dir / slug / "cut_index.json"
    output_path = output or base_dir / slug / "selections" / f"policy-guarded-{identifier}.json"
    try:
        snapshot = ProjectSnapshot.from_cut_index(cut_path)
        model = OpenAISelectionModel(load_software_config().llm)
        frames = ProjectFrameSource(snapshot, base_dir / slug / "cache" / "selection-frames")
        harness = PolicyGuardedSelectionHarness(model_client=model, frame_source=frames)
        request = SelectionRequest(
            selection_id=identifier,
            project_slug=slug,
            cut_index_path=cut_path,
            output_path=output_path,
            brief=SelectionBrief(
                target_duration_sec=target_duration_sec,
                style=style,
                max_review_clips=max_review_clips,
            ),
            budget=RunBudget(max_rounds=max_rounds, max_frame_requests=max_frame_requests),
        )
        result = harness.resume(request) if resume else harness.run(request)
    except (OSError, ValueError, SelectionModelError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(str(output_path))
    click.echo(result.run_status.value)


if __name__ == "__main__":
    main()
