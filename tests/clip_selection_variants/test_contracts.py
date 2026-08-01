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

