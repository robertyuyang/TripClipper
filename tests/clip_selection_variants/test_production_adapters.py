import json
from pathlib import Path

import httpx

from tripclipper.config import ModelConfig

from experiments.clip_selection.contracts import AssetSnapshot, ProjectSnapshot
from experiments.clip_selection.frame_source import ProjectFrameSource
from experiments.clip_selection.openai_model import OpenAISelectionModel


def test_openai_selection_model_parses_structured_action(monkeypatch) -> None:
    monkeypatch.setenv("SELECTION_TEST_KEY", "secret")

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["model"] == "vision-test"
        assert payload["messages"][0]["role"] == "system"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "action": {"name": "list_assets", "arguments": {}},
                                    "rationale": "先看索引",
                                }
                            )
                        }
                    }
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    model = OpenAISelectionModel(
        ModelConfig(
            provider="openai_compatible",
            base_url="https://example.test",
            api_key_env="SELECTION_TEST_KEY",
            vision_model="vision-test",
        ),
        client=client,
    )

    decision = model.decide("选片 Prompt", {"run": {}})

    assert decision.action.name == "list_assets"
    assert decision.rationale == "先看索引"


def test_project_frame_source_prefers_existing_frames(tmp_path: Path) -> None:
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"jpeg")
    snapshot = ProjectSnapshot(
        project_slug="demo",
        cut_index_path=tmp_path / "cut_index.json",
        sha256="abc",
        assets=[
            AssetSnapshot(
                asset_id="asset-1",
                duration_sec=10,
                frame_paths=[str(frame)],
                frame_timestamps=[4.0],
            )
        ],
    )

    observation = ProjectFrameSource(snapshot, tmp_path / "cache").inspect("asset-1", 3, 5)

    assert observation.frame_paths == [str(frame)]
    assert "已有帧" in observation.description

