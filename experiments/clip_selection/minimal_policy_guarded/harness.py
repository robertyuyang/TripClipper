from __future__ import annotations

from copy import deepcopy
from typing import Any

from experiments.clip_selection.contracts import RunStatus, SelectionRun

from .policy import SelectionPolicy
from .tools import apply_action


class MinimalPolicyGuardedHarness:
    def __init__(self, *, max_rounds: int = 20, policy: SelectionPolicy | None = None) -> None:
        self.max_rounds = max_rounds
        self.policy = policy or SelectionPolicy()

    def run(self, agent: Any, initial_run: SelectionRun) -> SelectionRun:
        run = deepcopy(initial_run)
        for _ in range(self.max_rounds):
            decision = agent.decide(run.model_dump(mode="json"))
            run.rounds += 1
            run.action_trace.append(decision.action.name)
            should_finish, errors = apply_action(run, decision.action, self.policy)
            if errors:
                run.rejected_actions += 1
                run.observations.extend(errors)
                continue
            if should_finish:
                run.run_status = RunStatus.completed
                return run
        run.run_status = RunStatus.incomplete
        run.unresolved.append("达到最大轮数")
        return run

