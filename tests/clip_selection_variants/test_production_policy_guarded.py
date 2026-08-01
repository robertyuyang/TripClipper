from pathlib import Path

from tripclipper.cut_index import write_cut_index
from tripclipper.models import Asset, AssetType, CutIndex, ProjectInfo

from experiments.clip_selection.contracts import (
    AgentAction,
    AgentDecision,
    RunBudget,
    SelectionBrief,
    SelectionRequest,
)
from experiments.clip_selection.production_policy_guarded.harness import PolicyGuardedSelectionHarness
from experiments.clip_selection.testing import FakeFrameSource, FakeModelClient


def _request(tmp_path: Path) -> SelectionRequest:
    cut_path = tmp_path / "cut_index.json"
    write_cut_index(
        cut_path,
        CutIndex(
            project=ProjectInfo(project_slug="demo"),
            assets=[
                Asset(
                    asset_id="asset-1",
                    type=AssetType.video,
                    relative_path="a.mp4",
                    metadata={"duration": 10.0},
                )
            ],
        ),
    )
    return SelectionRequest(
        selection_id="policy-prod",
        project_slug="demo",
        cut_index_path=cut_path,
        output_path=tmp_path / "policy.json",
        brief=SelectionBrief(target_duration_sec=5, style="叙事", max_review_clips=1),
        budget=RunBudget(max_rounds=6, max_frame_requests=2),
    )


def test_production_policy_guarded_rejects_transition_then_accepts_fix(tmp_path: Path) -> None:
    invalid = {
        "clip_id": "clip-1",
        "asset_id": "asset-1",
        "start_sec": 0,
        "end_sec": 5,
        "source": "selection_agent",
        "status": "primary",
    }
    valid = {**invalid, "evidence": "人物反应清晰", "project_role": "高潮"}
    model = FakeModelClient(
        [
            AgentDecision(action=AgentAction(name="upsert_candidate", arguments=invalid)),
            AgentDecision(action=AgentAction(name="upsert_candidate", arguments=valid)),
            AgentDecision(action=AgentAction(name="request_finish")),
        ]
    )
    harness = PolicyGuardedSelectionHarness(
        model_client=model,
        frame_source=FakeFrameSource(),
    )

    result = harness.run(_request(tmp_path))

    assert result.run_status == "completed"
    assert result.rejected_actions == 1
    assert result.action_trace.count("request_finish") == 2
    assert result.clips[0].evidence == "人物反应清晰"
    assert any("evidence" in item for item in result.observations)


def test_policy_counts_overlapping_primary_ranges_once(tmp_path: Path) -> None:
    base = {
        "asset_id": "asset-1",
        "source": "selection_agent",
        "status": "primary",
        "evidence": "清晰动作",
        "project_role": "高潮",
    }
    model = FakeModelClient(
        [
            AgentDecision(action=AgentAction(name="upsert_candidate", arguments={**base, "clip_id": "a", "start_sec": 0, "end_sec": 4})),
            AgentDecision(action=AgentAction(name="upsert_candidate", arguments={**base, "clip_id": "b", "start_sec": 2, "end_sec": 6})),
            AgentDecision(action=AgentAction(name="request_finish")),
        ]
    )
    harness = PolicyGuardedSelectionHarness(model_client=model, frame_source=FakeFrameSource())

    result = harness.run(_request(tmp_path))

    assert result.run_status == "completed"
    assert result.unresolved == []


def test_required_category_must_be_covered_before_finish(tmp_path: Path) -> None:
    base = {
        "clip_id": "clip-1",
        "asset_id": "asset-1",
        "start_sec": 0,
        "end_sec": 5,
        "source": "selection_agent",
        "status": "primary",
        "evidence": "抵达景区标志清晰",
        "project_role": "叙事交代",
    }
    model = FakeModelClient(
        [
            AgentDecision(
                action=AgentAction(
                    name="set_categories",
                    arguments={
                        "categories": [
                            {"category_id": "arrival", "label": "抵达", "required": True}
                        ]
                    },
                )
            ),
            AgentDecision(action=AgentAction(name="upsert_candidate", arguments=base)),
            AgentDecision(action=AgentAction(name="request_finish")),
            AgentDecision(
                action=AgentAction(
                    name="upsert_candidate",
                    arguments={**base, "categories": ["arrival"]},
                )
            ),
            AgentDecision(action=AgentAction(name="request_finish")),
            AgentDecision(action=AgentAction(name="request_finish")),
        ]
    )
    harness = PolicyGuardedSelectionHarness(model_client=model, frame_source=FakeFrameSource())

    result = harness.run(_request(tmp_path))

    assert result.run_status == "completed"
    assert any("必要分类 arrival" in item for item in result.observations)
