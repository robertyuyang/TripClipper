from hashlib import sha256
from pathlib import Path

from tripclipper.cut_index import write_cut_index
from tripclipper.models import Asset, AssetType, CutIndex, ProjectInfo

from experiments.clip_selection.contracts import (
    AgentAction,
    AgentDecision,
    ProjectSnapshot,
    RunBudget,
    SelectionBrief,
    SelectionRequest,
)
from experiments.clip_selection.production_agent_owned.harness import AgentOwnedSelectionHarness
from experiments.clip_selection.testing import FakeFrameSource, FakeModelClient


class FrameReturningSource(FakeFrameSource):
    def __init__(self, frame: Path) -> None:
        super().__init__()
        self.frame = frame

    def inspect(self, asset_id: str, start_sec: float, end_sec: float):
        observation = super().inspect(asset_id, start_sec, end_sec)
        observation.frame_paths = [str(self.frame)]
        return observation


def _cut_index(path: Path) -> Path:
    cut = CutIndex(
        project=ProjectInfo(project_slug="demo", source_folder=str(path.parent)),
        assets=[
            Asset(
                asset_id="asset-1",
                type=AssetType.video,
                relative_path="a.mp4",
                metadata={"duration": 12.0},
                summary="漂流人物反应",
            )
        ],
    )
    write_cut_index(path, cut)
    return path


def test_project_snapshot_is_stable_and_read_only(tmp_path: Path) -> None:
    path = _cut_index(tmp_path / "cut_index.json")
    before = sha256(path.read_bytes()).hexdigest()

    snapshot = ProjectSnapshot.from_cut_index(path)

    assert snapshot.sha256 == before
    assert snapshot.assets[0].duration_sec == 12.0
    assert sha256(path.read_bytes()).hexdigest() == before


def test_production_agent_owned_runs_tools_and_checkpoints(tmp_path: Path) -> None:
    cut_path = _cut_index(tmp_path / "cut_index.json")
    output = tmp_path / "selections" / "agent.json"
    decisions = [
        AgentDecision(
            action=AgentAction(
                name="inspect_range",
                arguments={"asset_id": "asset-1", "start_sec": 0, "end_sec": 5},
            )
        ),
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
            )
        ),
        AgentDecision(action=AgentAction(name="request_finish")),
    ]
    frame_source = FakeFrameSource()
    harness = AgentOwnedSelectionHarness(
        model_client=FakeModelClient(decisions),
        frame_source=frame_source,
    )
    request = SelectionRequest(
        selection_id="agent-prod",
        project_slug="demo",
        cut_index_path=cut_path,
        output_path=output,
        brief=SelectionBrief(target_duration_sec=5, style="快节奏", max_review_clips=2),
        budget=RunBudget(max_rounds=6, max_frame_requests=2),
    )

    result = harness.run(request)

    assert result.run_status == "completed"
    assert result.checkpoint_count >= 3
    assert result.action_trace.count("request_finish") == 2
    assert frame_source.calls == [("asset-1", 0.0, 5.0)]
    assert output.is_file()
    assert sha256(cut_path.read_bytes()).hexdigest() == result.source_cut_index_sha256


def test_production_agent_owned_budget_exhaustion_is_incomplete(tmp_path: Path) -> None:
    cut_path = _cut_index(tmp_path / "cut_index.json")
    inspect = AgentDecision(
        action=AgentAction(
            name="inspect_range",
            arguments={"asset_id": "asset-1", "start_sec": 0, "end_sec": 2},
        )
    )
    harness = AgentOwnedSelectionHarness(
        model_client=FakeModelClient([inspect, inspect]),
        frame_source=FakeFrameSource(),
    )
    request = SelectionRequest(
        selection_id="budget",
        project_slug="demo",
        cut_index_path=cut_path,
        output_path=tmp_path / "budget.json",
        brief=SelectionBrief(target_duration_sec=5, style="快节奏", max_review_clips=1),
        budget=RunBudget(max_rounds=3, max_frame_requests=1),
    )

    result = harness.run(request)

    assert result.run_status == "incomplete"
    assert any("帧查看预算" in item for item in result.unresolved)


def test_inspected_frames_are_sent_to_next_model_turn(tmp_path: Path) -> None:
    cut_path = _cut_index(tmp_path / "cut_index.json")
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"jpeg")
    model = FakeModelClient(
        [
            AgentDecision(
                action=AgentAction(
                    name="inspect_range",
                    arguments={"asset_id": "asset-1", "start_sec": 0, "end_sec": 2},
                )
            ),
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
                )
            ),
            AgentDecision(action=AgentAction(name="request_finish")),
        ]
    )
    harness = AgentOwnedSelectionHarness(
        model_client=model,
        frame_source=FrameReturningSource(frame),
    )
    request = SelectionRequest(
        selection_id="images",
        project_slug="demo",
        cut_index_path=cut_path,
        output_path=tmp_path / "images.json",
        brief=SelectionBrief(target_duration_sec=5, style="快节奏", max_review_clips=1),
    )

    harness.run(request)

    assert model.image_batches[1] == [frame]
