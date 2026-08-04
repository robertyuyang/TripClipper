from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from pydantic import PrivateAttr

from tripclipper.clip_selection import runner as selection_runner
from tripclipper.clip_selection.agent import MultimodalCodexChatModel
from tripclipper.clip_selection.frames import FrameSampler
from tripclipper.clip_selection.asset_tools import AssetBrowser
from tripclipper.clip_selection.models import (
    AssetInspection,
    SelectionCandidate,
    SelectionCategory,
    SelectionState,
)
from tripclipper.clip_selection.runner import _load_runtime_instructions, run_selection
from tripclipper.clip_selection.selection_tools import SelectionTools
from tripclipper.clip_selection.store import SelectionStore
from tripclipper.clip_selection.validator import SelectionValidator
from tripclipper.models import Asset


class ScriptedTicket02Model(FakeMessagesListChatModel):
    _seen_messages: list[list] = PrivateAttr(default_factory=list)

    def bind_tools(self, tools, **kwargs):  # type: ignore[override]
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self._seen_messages.append(messages)
        return super()._generate(messages, stop, run_manager, **kwargs)


def _tool_call(name: str, args: dict, call_id: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": call_id}],
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_frame_sampler_reuses_index_and_shared_frames_across_tasks(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    indexed = tmp_path / "indexed.jpg"
    indexed.write_bytes(b"indexed")
    shared_dir = tmp_path / "selections" / "shared_frames"
    asset = Asset(
        asset_id="asset-1",
        path=str(source),
        metadata={"duration": 12.0},
        frame_paths=[str(indexed)],
        frame_timestamps=[6.0],
    )
    extracted: list[float] = []

    def extract(_source: Path, timestamp: float, target: Path) -> Path:
        extracted.append(timestamp)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(f"frame-{timestamp}".encode())
        return target

    first_state = SelectionState(task_name="first", target_duration_sec=30)
    first = FrameSampler(
        {"asset-1": asset},
        first_state,
        SelectionStore(tmp_path / "first"),
        shared_dir,
        extractor=extract,
    )

    first_result = first.sample("asset-1", 3, 9, 3)

    assert len(first_result["frames"]) == 3
    assert {frame["source"] for frame in first_result["frames"]} == {
        "cut_index",
        "shared_extracted",
    }
    assert len(extracted) == 2
    assert len(list(shared_dir.glob("*.jpg"))) == 2
    assert first_state.asset_progress.sampled_ranges[0].asset_id == "asset-1"

    second_state = SelectionState(task_name="second", target_duration_sec=30)
    second = FrameSampler(
        {"asset-1": asset},
        second_state,
        SelectionStore(tmp_path / "second"),
        shared_dir,
        extractor=extract,
    )

    second_result = second.sample("asset-1", 3, 9, 3)

    assert len(extracted) == 2
    assert {frame["source"] for frame in second_result["frames"]} == {
        "cut_index",
        "shared_reused",
    }


def test_frame_sampler_keeps_cut_index_read_only(tmp_path: Path) -> None:
    index = tmp_path / "cut_index.json"
    index.write_text(json.dumps({"schema_version": "0.4"}), encoding="utf-8")
    before = _sha256(index)
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    asset = Asset(
        asset_id="asset-1",
        path=str(source),
        metadata={"duration": 10.0},
    )

    def extract(_source: Path, timestamp: float, target: Path) -> Path:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(f"frame-{timestamp}".encode())
        return target

    sampler = FrameSampler(
        {"asset-1": asset},
        SelectionState(task_name="task", target_duration_sec=30),
        SelectionStore(tmp_path / "task"),
        tmp_path / "shared",
        extractor=extract,
    )

    sampler.sample("asset-1", 0, 10, 2)

    assert _sha256(index) == before


def test_asset_frames_sample_tool_returns_visual_content(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    asset = Asset(
        asset_id="asset-1",
        path=str(source),
        metadata={"duration": 10.0},
    )
    state = SelectionState(task_name="task", target_duration_sec=30)
    store = SelectionStore(tmp_path / "task")
    browser = AssetBrowser([asset], state, store)

    def extract(_source: Path, timestamp: float, target: Path) -> Path:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(f"frame-{timestamp}".encode())
        return target

    sampler = FrameSampler(
        browser.by_id,
        state,
        store,
        tmp_path / "shared",
        extractor=extract,
    )
    tools = SelectionTools(
        browser,
        state,
        store,
        SelectionValidator(
            browser.asset_durations,
            asset_ids=set(browser.by_id),
            total_pages=1,
        ),
        frame_sampler=sampler,
    ).as_langchain_tools()
    sample = next(tool for tool in tools if tool.name == "asset_frames_sample")

    content = sample.invoke(
        {"asset_id": "asset-1", "start_sec": 0, "end_sec": 10, "count": 2}
    )

    assert content[0]["type"] == "input_text"
    assert [item["type"] for item in content[1:]] == [
        "input_image",
        "input_image",
    ]
    assert all(item["image_url"].startswith("data:image/jpeg;base64,") for item in content[1:])


def test_codex_model_preserves_multimodal_function_output() -> None:
    content = [
        {"type": "input_text", "text": "采样帧"},
        {
            "type": "input_image",
            "image_url": "data:image/jpeg;base64,ZmFrZQ==",
            "detail": "high",
        },
    ]

    assert MultimodalCodexChatModel._normalize_content(content) == content


def test_runtime_instructions_require_targeted_new_visual_evidence() -> None:
    instructions = _load_runtime_instructions()

    assert "150%～200%" in instructions
    assert "至少选择一个会影响主备或候选修订的争议片段" in instructions
    assert "至少追加一张新帧" in instructions
    assert "不得只依赖索引文字完成任务" in instructions


def _candidate_tools(tmp_path: Path) -> tuple[SelectionState, dict[str, object]]:
    assets = [
        Asset(asset_id=f"asset-{index}", metadata={"duration": 100.0})
        for index in range(4)
    ]
    category = SelectionCategory(
        category_id="category-001",
        name="人物高能",
        purpose="提供有感染力的开头",
    )
    state = SelectionState(
        task_name="task",
        target_duration_sec=30,
        categories=[category],
    )
    state.asset_progress.listed_pages = [1]
    state.asset_progress.inspections = [
        AssetInspection(
            asset_id=asset.asset_id or "",
            category_ids=[category.category_id],
            shortlist_reason="同类比较",
        )
        for asset in assets
    ]
    store = SelectionStore(tmp_path / "task")
    browser = AssetBrowser(assets, state, store)
    tools = SelectionTools(
        browser,
        state,
        store,
        SelectionValidator(
            browser.asset_durations,
            asset_ids=set(browser.by_id),
            total_pages=1,
        ),
    ).as_langchain_tools()
    return state, {tool.name: tool for tool in tools}


def test_candidate_update_enforces_200_percent_primary_capacity(
    tmp_path: Path,
) -> None:
    _, tools = _candidate_tools(tmp_path)
    added = tools["selection_candidate_add"].invoke(
        {
            "asset_id": "asset-0",
            "start_sec": 0,
            "end_sec": 55,
            "status": "primary",
            "category_ids": ["category-001"],
            "reason": "先保留 55 秒主选范围。",
        }
    )
    candidate_id = added["candidate"]["candidate_id"]

    accepted = tools["selection_candidate_update"].invoke(
        {
            "candidate_id": candidate_id,
            "start_sec": 0,
            "end_sec": 60,
            "status": "primary",
            "category_ids": ["category-001"],
            "reason": "补足到 60 秒上限。",
        }
    )
    assert accepted["accepted"] is True

    rejected = tools["selection_candidate_update"].invoke(
        {
            "candidate_id": candidate_id,
            "start_sec": 0,
            "end_sec": 60.1,
            "status": "primary",
            "category_ids": ["category-001"],
            "reason": "超过 60 秒上限。",
        }
    )
    assert rejected["accepted"] is False
    assert "超过主选容量上限 60 秒" in "；".join(rejected["blockers"])


def test_candidate_tools_add_update_remove_and_protect_references(
    tmp_path: Path,
) -> None:
    state, tools = _candidate_tools(tmp_path)
    add = tools["selection_candidate_add"]
    update = tools["selection_candidate_update"]
    remove = tools["selection_candidate_remove"]

    primary = add.invoke(
        {
            "asset_id": "asset-0",
            "start_sec": 0,
            "end_sec": 45,
            "status": "primary",
            "category_ids": ["category-001"],
            "reason": "人物动作清楚，同类中感染力最强。",
        }
    )
    alternate = add.invoke(
        {
            "asset_id": "asset-1",
            "start_sec": 2,
            "end_sec": 12,
            "status": "alternate",
            "category_ids": ["category-001"],
            "reason": "同类动作完整，可替代主选。",
            "alternative_to_ids": [primary["candidate"]["candidate_id"]],
        }
    )

    blocked = remove.invoke(
        {
            "candidate_id": primary["candidate"]["candidate_id"],
            "reason": "尝试移除被引用主选",
        }
    )
    assert blocked["accepted"] is False
    assert "仍被其他候选引用" in "；".join(blocked["blockers"])

    revised = update.invoke(
        {
            "candidate_id": alternate["candidate"]["candidate_id"],
            "start_sec": 3,
            "end_sec": 11,
            "status": "needs_review",
            "category_ids": ["category-001"],
            "reason": "表情稀有，值得保留。",
            "alternative_to_ids": [],
            "review_reason": "快速动作中有轻微遮挡，人工重点确认表情是否完整。",
        }
    )
    assert revised["accepted"] is True
    assert revised["candidate"]["status"] == "needs_review"

    removed = remove.invoke(
        {
            "candidate_id": primary["candidate"]["candidate_id"],
            "reason": "深入看帧后发现动作与另一主选重复",
        }
    )
    assert removed == {"accepted": True, "candidate_id": "candidate-001"}
    assert [candidate.candidate_id for candidate in state.candidates] == [
        "candidate-002"
    ]
    events = [
        json.loads(line)
        for line in (tmp_path / "task" / "events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert any(
        event["event_type"] == "candidate_removed"
        and event["data"]["reason"] == "深入看帧后发现动作与另一主选重复"
        for event in events
    )


def test_completion_validates_roles_relations_review_reason_and_high_priority(
    tmp_path: Path,
) -> None:
    state, tools = _candidate_tools(tmp_path)
    add = tools["selection_candidate_add"]
    finish = tools["selection_finish_request"]

    primary = add.invoke(
        {
            "asset_id": "asset-0",
            "start_sec": 0,
            "end_sec": 45,
            "status": "primary",
            "category_ids": ["category-001"],
            "reason": "人物动作清楚，同类中感染力最强。",
        }
    )["candidate"]
    invalid_review = add.invoke(
        {
            "asset_id": "asset-1",
            "start_sec": 2,
            "end_sec": 8,
            "status": "needs_review",
            "category_ids": ["category-001"],
            "reason": "内容稀有，值得保留。",
            "review_reason": " ",
        }
    )
    assert invalid_review["accepted"] is False
    assert "待人工复核理由不能为空" in "；".join(invalid_review["blockers"])

    invalid_review_relation = add.invoke(
        {
            "asset_id": "asset-1",
            "start_sec": 2,
            "end_sec": 8,
            "status": "needs_review",
            "category_ids": ["category-001"],
            "reason": "内容稀有，值得保留。",
            "alternative_to_ids": [primary["candidate_id"]],
            "review_reason": "动作很快，人工重点确认表情是否完整。",
        }
    )
    assert invalid_review_relation["accepted"] is False
    assert "只有备选候选可以设置替代关系" in "；".join(
        invalid_review_relation["blockers"]
    )

    add.invoke(
        {
            "asset_id": "asset-2",
            "start_sec": 1,
            "end_sec": 6,
            "status": "alternate",
            "category_ids": ["category-001"],
            "reason": "动作相似，可作为备选。",
            "alternative_to_ids": [primary["candidate_id"]],
        }
    )
    state.unresolved = [
        {"priority": "low", "reason": "可选的进一步比较"},
        {"priority": "high", "reason": "开头遮挡尚未确认"},
    ]

    blocked = finish.invoke({})
    assert blocked["accepted"] is False
    assert "仍存在未解决的高优先级问题" in blocked["blockers"]

    state.unresolved = [{"priority": "urgent", "reason": "未知优先级"}]
    assert finish.invoke({})["accepted"] is False

    state.unresolved = [{"priority": "low", "reason": "可选的进一步比较"}]
    accepted = finish.invoke({})
    assert accepted == {"accepted": True, "status": "completed"}


@pytest.mark.parametrize(
    ("duration", "accepted"),
    [(44.9, False), (45.0, True), (60.0, True), (60.1, False)],
)
def test_finish_tool_enforces_150_to_200_percent_primary_capacity(
    tmp_path: Path,
    duration: float,
    accepted: bool,
) -> None:
    state, tools = _candidate_tools(tmp_path / str(duration))
    state.candidates = [
        SelectionCandidate(
            candidate_id="candidate-001",
            asset_id="asset-0",
            start_sec=0,
            end_sec=duration,
            status="primary",
            category_ids=["category-001"],
            reason="边界容量候选。",
        )
    ]

    result = tools["selection_finish_request"].invoke({})

    assert result["accepted"] is accepted
    if not accepted:
        assert "45～60" in "；".join(result["blockers"])


def test_alternate_and_needs_review_do_not_increase_primary_union(
    tmp_path: Path,
) -> None:
    state, tools = _candidate_tools(tmp_path)
    state.candidates = [
        SelectionCandidate(
            candidate_id="candidate-001",
            asset_id="asset-0",
            start_sec=0,
            end_sec=45,
            status="primary",
            category_ids=["category-001"],
            reason="45 秒主选。",
        ),
        SelectionCandidate(
            candidate_id="candidate-002",
            asset_id="asset-1",
            start_sec=0,
            end_sec=100,
            status="alternate",
            category_ids=["category-001"],
            reason="不计入容量的备选。",
            alternative_to_ids=["candidate-001"],
        ),
        SelectionCandidate(
            candidate_id="candidate-003",
            asset_id="asset-2",
            start_sec=0,
            end_sec=100,
            status="needs_review",
            category_ids=["category-001"],
            reason="不计入容量的待复核候选。",
            review_reason="内容稀有但存在遮挡，人工重点确认主体清晰度。",
        ),
    ]

    assert SelectionValidator.primary_union_duration(state.candidates) == 45
    assert tools["selection_finish_request"].invoke({}) == {
        "accepted": True,
        "status": "completed",
    }


def test_scripted_model_samples_frames_and_revises_candidates_without_network(
    tmp_path: Path,
    monkeypatch,
) -> None:
    projects = tmp_path / "projects"
    project = projects / "demo"
    media = project / "media"
    frames = project / "cache" / "frames"
    media.mkdir(parents=True)
    frames.mkdir(parents=True)
    assets = []
    for index in range(4):
        video = media / f"asset-{index}.mp4"
        video.write_bytes(b"video")
        frame = frames / f"asset-{index}.jpg"
        frame.write_bytes(b"jpeg")
        assets.append(
            {
                "asset_id": f"asset-{index}",
                "filename": video.name,
                "path": str(video),
                "relative_path": video.name,
                "type": "video",
                "metadata": {"duration": 30.0},
                "analysis_status": "analyzed",
                "summary": f"素材 {index}，人物与环境画面。",
                "frame_paths": [str(frame)],
                "frame_timestamps": [5.0],
                "clip_suggestions": [
                    {
                        "in": "00:00:00",
                        "out": "00:00:15",
                        "reason": "动作完整",
                    }
                ],
            }
        )
    index_path = project / "cut_index.json"
    index_path.write_text(
        json.dumps(
            {
                "schema_version": "0.4",
                "project": {
                    "project_slug": "demo",
                    "source_folder": str(media),
                },
                "assets": assets,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    brief = tmp_path / "10秒快剪.md"
    brief.write_text("剪一个 10 秒欢快视频。", encoding="utf-8")
    before_hash = _sha256(index_path)

    def extract(_source: Path, timestamp: float, target: Path) -> Path:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(f"new-frame-{timestamp}".encode())
        return target

    class ScriptedFrameSampler(FrameSampler):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs, extractor=extract)

    monkeypatch.setattr(selection_runner, "FrameSampler", ScriptedFrameSampler)
    inspections = [
        {
            "asset_id": f"asset-{index}",
            "category_ids": ["category-001"],
            "shortlist_reason": "同类比较",
        }
        for index in range(4)
    ]
    model = ScriptedTicket02Model(
        responses=[
            _tool_call("asset_list", {"page": 1}, "list"),
            _tool_call(
                "selection_categories_save",
                {
                    "categories": [
                        {
                            "name": "人物高能",
                            "required": True,
                            "purpose": "提供欢快开头",
                        }
                    ]
                },
                "categories",
            ),
            _tool_call("asset_get_batch", {"inspections": inspections}, "inspect"),
            _tool_call(
                "asset_frames_sample",
                {"asset_id": "asset-0", "start_sec": 0, "end_sec": 10, "count": 2},
                "frames",
            ),
            _tool_call(
                "selection_candidate_add",
                {
                    "asset_id": "asset-1",
                    "start_sec": 0,
                    "end_sec": 5,
                    "status": "primary",
                    "category_ids": ["category-001"],
                    "reason": "早期候选，动作可见。",
                },
                "temporary",
            ),
            _tool_call(
                "selection_candidate_remove",
                {
                    "candidate_id": "candidate-001",
                    "reason": "深入查看后与更强人物镜头重复",
                },
                "remove",
            ),
            _tool_call(
                "selection_candidate_add",
                {
                    "asset_id": "asset-0",
                    "start_sec": 0,
                    "end_sec": 15,
                    "status": "primary",
                    "category_ids": ["category-001"],
                    "recommended_use": "片头",
                    "reason": "新增 3.33 秒帧显示表情清楚，同类中感染力更强。",
                },
                "primary",
            ),
            _tool_call(
                "selection_candidate_add",
                {
                    "asset_id": "asset-2",
                    "start_sec": 0,
                    "end_sec": 8,
                    "status": "alternate",
                    "category_ids": ["category-001"],
                    "reason": "动作完整，可替代主选。",
                    "alternative_to_ids": ["candidate-002"],
                },
                "alternate",
            ),
            _tool_call(
                "selection_candidate_add",
                {
                    "asset_id": "asset-3",
                    "start_sec": 1,
                    "end_sec": 6,
                    "status": "needs_review",
                    "category_ids": ["category-001"],
                    "reason": "反应稀有，值得保留。",
                    "review_reason": "动作末尾略有遮挡，人工重点确认表情是否完整。",
                },
                "review",
            ),
            _tool_call("selection_finish_request", {}, "finish"),
            AIMessage(content="完成。"),
        ]
    )

    result = run_selection(
        "demo",
        brief,
        base_dir=projects,
        model=model,
        asset_page_size=20,
    )

    assert result.state.status == "completed"
    assert [candidate.status for candidate in result.state.candidates] == [
        "primary",
        "alternate",
        "needs_review",
    ]
    assert result.state.asset_progress.sampled_ranges
    assert _sha256(index_path) == before_hash
    events = [
        json.loads(line)
        for line in result.events_path.read_text(encoding="utf-8").splitlines()
    ]
    assert any(event["event_type"] == "asset_frames_sampled" for event in events)
    frame_event = next(
        event for event in events if event["event_type"] == "asset_frames_sampled"
    )
    assert any(
        frame["source"] == "shared_extracted"
        for frame in frame_event["data"]["frames"]
    )
    assert any(
        "新增" in candidate.reason and "帧" in candidate.reason
        for candidate in result.state.candidates
    )
    event_types = [event["event_type"] for event in events]
    assert event_types.index("asset_opened") < event_types.index("asset_frames_sampled")
    assert any(event["event_type"] == "candidate_removed" for event in events)
