import json

from experiments.clip_selection.contracts import AgentAction, AgentDecision, SelectionBrief, SelectionRun
from experiments.clip_selection.testing import ScriptedAgent

from .harness import MinimalAgentOwnedHarness


def main() -> None:
    run = SelectionRun(
        selection_id="minimal-agent-owned",
        project_slug="demo",
        brief=SelectionBrief(target_duration_sec=10, style="旅行", max_review_clips=2),
    )
    agent = ScriptedAgent([AgentDecision(action=AgentAction(name="request_finish"))])
    result = MinimalAgentOwnedHarness().run(agent, run)
    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

