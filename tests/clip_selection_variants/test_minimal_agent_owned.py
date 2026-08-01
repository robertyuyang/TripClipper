from experiments.clip_selection.contracts import (
    AgentAction,
    AgentDecision,
    SelectionBrief,
    SelectionRun,
)
from experiments.clip_selection.minimal_agent_owned.harness import MinimalAgentOwnedHarness
from experiments.clip_selection.testing import ScriptedAgent


def test_agent_owned_harness_commits_schema_valid_state_without_business_gate() -> None:
    run = SelectionRun(
        selection_id="sel-agent",
        project_slug="demo",
        brief=SelectionBrief(target_duration_sec=10, style="快节奏", max_review_clips=2),
    )
    agent = ScriptedAgent(
        [
            AgentDecision(
                action=AgentAction(
                    name="upsert_candidate",
                    arguments={
                        "clip_id": "clip-1",
                        "asset_id": "asset-1",
                        "start_sec": 0,
                        "end_sec": 5,
                        "source": "selection_agent",
                        "status": "primary",
                    },
                ),
                rationale="Agent 自主主选",
            ),
            AgentDecision(action=AgentAction(name="request_finish", arguments={}), rationale="结束"),
        ]
    )

    result = MinimalAgentOwnedHarness(max_rounds=4).run(agent, run)

    assert [clip.clip_id for clip in result.clips] == ["clip-1"]
    assert result.rejected_actions == 0
    assert result.run_status == "completed"

