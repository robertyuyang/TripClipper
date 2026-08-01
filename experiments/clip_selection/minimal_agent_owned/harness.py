from __future__ import annotations

from copy import deepcopy
from typing import Any

from experiments.clip_selection.contracts import RunStatus, SelectionRun

from .tools import apply_action


class MinimalAgentOwnedHarness:
    def __init__(self, *, max_rounds: int = 20) -> None:
        self.max_rounds = max_rounds

    def run(self, agent: Any, initial_run: SelectionRun) -> SelectionRun:
        run = deepcopy(initial_run)
        for _ in range(self.max_rounds):
            decision = agent.decide(run.model_dump(mode="json"))
            run.rounds += 1
            run.action_trace.append(decision.action.name)
            if apply_action(run, decision.action):
                run.run_status = RunStatus.completed
                return run
        run.run_status = RunStatus.incomplete
        run.unresolved.append("达到最大轮数")
        return run

