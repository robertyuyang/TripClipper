import json

import pytest
from pydantic import ValidationError

from experiments.clip_selection.contracts import (
    AgentAction,
    AgentDecision,
    CandidateClip,
    ClipStatus,
    SelectionBrief,
    SelectionRun,
)
from experiments.clip_selection.testing import ScriptedAgent
from experiments.clip_selection.production_policy_guarded.agent import SYSTEM_PROMPT as POLICY_PROMPT


def test_contracts_reject_invalid_clip_range_and_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        CandidateClip(
            clip_id="c1",
            asset_id="a1",
            start_sec=5,
            end_sec=4,
            source="cut_index",
            status=ClipStatus.primary,
        )
    with pytest.raises(ValidationError):
        SelectionBrief(target_duration_sec=30, style="旅行", max_review_clips=3, extra=1)
    with pytest.raises(ValidationError):
        CandidateClip(
            clip_id="c1",
            asset_id="a1",
            start_sec=0,
            end_sec=1,
            source="arbitrary",
            status=ClipStatus.primary,
        )


def test_selection_run_round_trips_as_json() -> None:
    run = SelectionRun(
        selection_id="sel-1",
        project_slug="demo",
        brief=SelectionBrief(target_duration_sec=30, style="旅行", max_review_clips=3),
    )
    restored = SelectionRun.model_validate_json(json.dumps(run.model_dump(mode="json")))
    assert restored == run


def test_scripted_agent_returns_finish_when_actions_exhausted() -> None:
    agent = ScriptedAgent(
        [AgentDecision(action=AgentAction(name="list_assets", arguments={}), rationale="先看索引")]
    )
    assert agent.decide({}).action.name == "list_assets"
    assert agent.decide({}).action.name == "request_finish"


def test_production_prompt_publishes_tool_contract() -> None:
    tools = {
        "list_assets",
        "inspect_range",
        "upsert_candidate",
        "set_categories",
        "request_finish",
    }
    for name in tools:
        assert name in POLICY_PROMPT
