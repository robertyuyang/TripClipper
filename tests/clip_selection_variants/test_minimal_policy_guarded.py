from experiments.clip_selection.contracts import (
    AgentAction,
    AgentDecision,
    SelectionBrief,
    SelectionRun,
)
from experiments.clip_selection.minimal_policy_guarded.harness import MinimalPolicyGuardedHarness
from experiments.clip_selection.testing import ScriptedAgent


def test_policy_guarded_harness_rejects_then_accepts_corrected_primary() -> None:
    run = SelectionRun(
        selection_id="sel-policy",
        project_slug="demo",
        brief=SelectionBrief(target_duration_sec=5, style="快节奏", max_review_clips=2),
    )
    invalid = {
        "clip_id": "clip-1",
        "asset_id": "asset-1",
        "start_sec": 0,
        "end_sec": 5,
        "source": "selection_agent",
        "status": "primary",
    }
    valid = {**invalid, "evidence": "人物落水后大笑", "project_role": "漂流高潮"}
    agent = ScriptedAgent(
        [
            AgentDecision(action=AgentAction(name="upsert_candidate", arguments=invalid), rationale="第一次尝试"),
            AgentDecision(action=AgentAction(name="upsert_candidate", arguments=valid), rationale="补齐证据"),
            AgentDecision(action=AgentAction(name="request_finish", arguments={}), rationale="结束"),
        ]
    )

    result = MinimalPolicyGuardedHarness(max_rounds=5).run(agent, run)

    assert [clip.clip_id for clip in result.clips] == ["clip-1"]
    assert result.rejected_actions == 1
    assert any("evidence" in item for item in result.observations)
    assert result.run_status == "completed"
