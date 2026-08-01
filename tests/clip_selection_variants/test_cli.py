import json
import os
import subprocess
import sys

from experiments.clip_selection.compare import summarize
from experiments.clip_selection.contracts import SelectionBrief, SelectionRun


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
ENV = {**os.environ, "PYTHONPATH": f"{ROOT}/src:{ROOT}"}


def test_minimal_module_runs_offline() -> None:
    module = "experiments.clip_selection.minimal_policy_guarded"
    completed = subprocess.run(
        [sys.executable, "-m", module],
        cwd=ROOT,
        env=ENV,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["run_status"] == "completed"


def test_production_module_has_help() -> None:
    module = "experiments.clip_selection.production_policy_guarded"
    completed = subprocess.run(
        [sys.executable, "-m", module, "--help"],
        cwd=ROOT,
        env=ENV,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "--target-duration-sec" in completed.stdout
    assert "--max-frame-requests" in completed.stdout


def test_compare_summary_exposes_architecture_metrics() -> None:
    run = SelectionRun(
        selection_id="sel",
        project_slug="demo",
        brief=SelectionBrief(target_duration_sec=10, style="旅行", max_review_clips=2),
        rounds=4,
        rejected_actions=2,
        checkpoint_count=3,
    )

    result = summarize(run)

    assert result == {
        "selection_id": "sel",
        "run_status": "running",
        "rounds": 4,
        "frame_requests": 0,
        "rejected_actions": 2,
        "checkpoint_count": 3,
        "clip_count": 0,
        "primary_count": 0,
        "needs_review_count": 0,
    }
