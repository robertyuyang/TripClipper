from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from click.testing import CliRunner
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool
from pydantic import PrivateAttr
import pytest

from tripclipper.clip_selection.agent import (
    CodexAuthenticationError,
    ensure_codex_authenticated,
)
from tripclipper.clip_selection.asset_tools import AssetBrowser
from tripclipper.clip_selection.models import (
    AssetInspection,
    SelectionCandidate,
    SelectionCategory,
    SelectionState,
)
from tripclipper.clip_selection.runner import run_selection
from tripclipper.clip_selection.runner import parse_target_duration
from tripclipper.clip_selection.selection_tools import SelectionTools
from tripclipper.clip_selection.store import SelectionStore
from tripclipper.clip_selection.validator import (
    SelectionValidationError,
    SelectionValidator,
)
from tripclipper.cli import main
from tripclipper.models import Asset


class ScriptedSelectionModel(FakeMessagesListChatModel):
    """按固定 Tool Call 脚本驱动真实 DeerFlow Harness。"""

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


def _write_cut_index(path: Path) -> None:
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": "0.4",
                "project": {
                    "project_slug": "demo",
                    "project_name": "演示项目",
                    "source_folder": str(path.parent / "media"),
                },
                "assets": [
                    {
                        "asset_id": "asset-people",
                        "filename": "people.mp4",
                        "type": "video",
                        "metadata": {"duration": 20.0},
                        "analysis_status": "analyzed",
                        "summary": "朋友们挥手欢呼，情绪高涨。",
                        "rating": 5,
                        "subject_type": "people",
                        "shot_scale": "medium",
                        "clip_suggestions": [
                            {
                                "in": "00:00:00",
                                "out": "00:00:15",
                                "reason": "欢呼动作完整",
                            }
                        ],
                    },
                    {
                        "asset_id": "asset-landscape",
                        "filename": "landscape.mp4",
                        "type": "video",
                        "metadata": {"duration": 20.0},
                        "analysis_status": "analyzed",
                        "summary": "开阔山谷空镜，构图干净。",
                        "rating": 5,
                        "subject_type": "landscape",
                        "shot_scale": "wide",
                        "clip_suggestions": [
                            {
                                "in": "00:00:00",
                                "out": "00:00:15",
                                "reason": "环境层次清楚",
                            }
                        ],
                    },
                    {
                        "asset_id": "asset-activity-1",
                        "filename": "activity-1.mp4",
                        "type": "video",
                        "metadata": {"duration": 20.0},
                        "analysis_status": "analyzed",
                        "summary": "人物参与户外活动，动作强烈，环境开阔。",
                        "rating": 4,
                        "subject_type": "activity",
                        "shot_scale": "wide",
                        "clip_suggestions": [
                            {
                                "in": "00:00:00",
                                "out": "00:00:15",
                                "reason": "动作完整",
                            }
                        ],
                    },
                    {
                        "asset_id": "asset-activity-2",
                        "filename": "activity-2.mp4",
                        "type": "video",
                        "metadata": {"duration": 20.0},
                        "analysis_status": "analyzed",
                        "summary": "人物与山谷环境同框，节奏轻快。",
                        "rating": 4,
                        "subject_type": "people_landscape",
                        "shot_scale": "full",
                        "clip_suggestions": [
                            {
                                "in": "00:00:00",
                                "out": "00:00:15",
                                "reason": "人物环境兼具",
                            }
                        ],
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_scripted_model_completes_depth_checked_selection_without_changing_index(
    tmp_path: Path,
) -> None:
    projects_dir = tmp_path / "projects"
    cut_index_path = projects_dir / "demo" / "cut_index.json"
    _write_cut_index(cut_index_path)
    brief_path = tmp_path / "30秒欢快快剪.md"
    brief_text = "# 30秒欢快快剪\n\n剪一个约 30 秒、特别欢快的旅行快剪。"
    brief_path.write_text(brief_text, encoding="utf-8")
    before_hash = hashlib.sha256(cut_index_path.read_bytes()).hexdigest()

    model = ScriptedSelectionModel(
        responses=[
            _tool_call("asset_list", {"page": 1}, "call-list-1"),
            _tool_call("asset_list", {"page": 2}, "call-list-2"),
            _tool_call("asset_list", {"page": 3}, "call-list-3"),
            _tool_call("asset_list", {"page": 4}, "call-list-4"),
            _tool_call(
                "selection_categories_save",
                {
                    "categories": [
                        {
                            "name": "人物高能",
                            "required": True,
                            "purpose": "提供感染力强的开头",
                        },
                        {
                            "name": "环境空镜",
                            "required": True,
                            "purpose": "补足无人物环境画面",
                        },
                    ]
                },
                "call-categories",
            ),
            _tool_call(
                "asset_get_batch",
                {
                    "inspections": [
                        {
                            "asset_id": asset_id,
                            "category_ids": ["category-001", "category-002"],
                            "shortlist_reason": "两个分类的同类比较素材",
                        }
                        for asset_id in [
                            "asset-people",
                            "asset-landscape",
                            "asset-activity-1",
                            "asset-activity-2",
                        ]
                    ]
                },
                "call-inspect",
            ),
            _tool_call(
                "selection_candidate_add",
                {
                    "asset_id": "asset-people",
                    "start_sec": 0.0,
                    "end_sec": 15.0,
                    "category_ids": ["category-001"],
                    "recommended_use": "片头",
                    "reason": "人物表情强，优于三个同类比较素材。",
                },
                "call-candidate-1",
            ),
            _tool_call(
                "selection_candidate_add",
                {
                    "asset_id": "asset-landscape",
                    "start_sec": 0.0,
                    "end_sec": 15.0,
                    "category_ids": ["category-002"],
                    "recommended_use": "环境过场",
                    "reason": "环境层次清楚，优于三个同类比较素材。",
                },
                "call-candidate-2",
            ),
            _tool_call(
                "selection_candidate_add",
                {
                    "asset_id": "asset-activity-1",
                    "start_sec": 0.0,
                    "end_sec": 15.0,
                    "category_ids": ["category-001", "category-002"],
                    "recommended_use": "中段高光",
                    "reason": "内容与景别形成变化，优于三个同类比较素材。",
                },
                "call-candidate-3",
            ),
            _tool_call("selection_finish_request", {}, "call-finish"),
            AIMessage(content="选片候选池已完成。"),
        ]
    )

    result = run_selection(
        "demo",
        brief_path,
        base_dir=projects_dir,
        model=model,
        asset_page_size=1,
    )

    assert result.state.status == "completed"
    assert result.state.target_duration_sec == 30.0
    assert len(result.state.categories) == 2
    assert len(result.state.candidates) == 3
    assert [category.category_id for category in result.state.categories] == [
        "category-001",
        "category-002",
    ]
    assert [candidate.candidate_id for candidate in result.state.candidates] == [
        "candidate-001",
        "candidate-002",
        "candidate-003",
    ]
    assert result.brief_path.read_text(encoding="utf-8") == brief_text
    assert any(
        brief_text in str(message.content)
        for invocation in model._seen_messages
        for message in invocation
    )
    assert hashlib.sha256(cut_index_path.read_bytes()).hexdigest() == before_hash
    assert json.loads(result.state_path.read_text(encoding="utf-8"))["status"] == "completed"
    assert not result.state_path.with_name("state.json.tmp").exists()
    event_types = [
        json.loads(line)["event_type"]
        for line in result.events_path.read_text(encoding="utf-8").splitlines()
    ]
    assert event_types == [
        "selection_started",
        "asset_listed",
        "asset_listed",
        "asset_listed",
        "asset_listed",
        "change_validated",
        "categories_saved",
        "change_validated",
        "asset_opened",
        "asset_opened",
        "asset_opened",
        "asset_opened",
        "asset_batch_opened",
        "change_validated",
        "candidate_added",
        "change_validated",
        "candidate_added",
        "change_validated",
        "candidate_added",
        "completion_validated",
        "selection_completed",
    ]
    assert result.state.asset_progress.opened_asset_ids == [
        "asset-people",
        "asset-landscape",
        "asset-activity-1",
        "asset-activity-2",
    ]
    assert len(result.state.asset_progress.inspections) == 4


def test_select_cli_reports_completed_task(monkeypatch, tmp_path: Path) -> None:
    brief_path = tmp_path / "brief.md"
    brief_path.write_text("剪一个 30 秒视频。", encoding="utf-8")
    task_dir = tmp_path / "projects" / "demo" / "selections" / "brief"

    def fake_run_selection(slug, brief, *, base_dir=None):
        assert slug == "demo"
        assert Path(brief) == brief_path
        assert Path(base_dir) == tmp_path / "projects"
        return SimpleNamespace(
            state=SimpleNamespace(status="completed", candidates=[1, 2]),
            task_dir=task_dir,
        )

    monkeypatch.setattr("tripclipper.cli.run_selection", fake_run_selection)
    result = CliRunner().invoke(
        main,
        [
            "select",
            "demo",
            str(brief_path),
            "--base-dir",
            str(tmp_path / "projects"),
        ],
    )

    assert result.exit_code == 0
    assert "completed" in result.output
    assert "候选数" in result.output
    assert str(task_dir) in result.output


@pytest.mark.parametrize(
    ("candidate", "message"),
    [
        (
            SelectionCandidate(
                candidate_id="candidate-001",
                asset_id="missing",
                start_sec=0,
                end_sec=5,
                category_ids=["category-001"],
                reason="有理由",
            ),
            "素材不存在",
        ),
        (
            SelectionCandidate(
                candidate_id="candidate-001",
                asset_id="asset-1",
                start_sec=0,
                end_sec=5,
                category_ids=["category-missing"],
                reason="有理由",
            ),
            "分类引用不存在",
        ),
        (
            SelectionCandidate(
                candidate_id="candidate-001",
                asset_id="asset-1",
                start_sec=0,
                end_sec=5,
                category_ids=["category-001"],
                reason=" ",
            ),
            "候选理由不能为空",
        ),
    ],
)
def test_validator_rejects_invalid_candidate_references_and_reason(
    candidate: SelectionCandidate,
    message: str,
) -> None:
    state = SelectionState(
        task_name="demo",
        target_duration_sec=30,
        categories=[
            SelectionCategory(
                category_id="category-001",
                name="人物高能",
                purpose="用于开头",
            )
        ],
    )
    validator = SelectionValidator({"asset-1": 20}, total_pages=1)

    with pytest.raises(SelectionValidationError, match=message):
        validator.validate_candidate(candidate, state)


@pytest.mark.parametrize(
    ("asset_count", "required_category_count", "expected"),
    [
        (1, 0, 1),
        (2, 0, 2),
        (3, 0, 3),
        (4, 0, 4),
        (20, 1, 20),
        (100, 1, 30),
        (100, 10, 80),
        (260, 4, 52),
        (500, 4, 100),
    ],
)
def test_required_inspection_count_covers_scale_boundaries(
    asset_count: int,
    required_category_count: int,
    expected: int,
) -> None:
    categories = [
        SelectionCategory(
            category_id=f"category-{index:03d}",
            name=f"分类 {index}",
            purpose="比较素材",
        )
        for index in range(1, required_category_count + 1)
    ]
    state = SelectionState(
        task_name="demo",
        target_duration_sec=30,
        categories=categories,
    )
    validator = SelectionValidator(
        {},
        asset_ids={f"asset-{index}" for index in range(asset_count)},
        total_pages=13,
    )

    assert validator.required_inspection_count(state) == expected


def test_old_state_defaults_to_empty_inspections() -> None:
    state = SelectionState.model_validate(
        {"task_name": "demo", "target_duration_sec": 30}
    )

    assert state.asset_progress.inspections == []


def _build_inspection_batch_tool(
    tmp_path: Path,
    asset_count: int = 4,
) -> tuple[SelectionState, StructuredTool]:
    assets = [
        Asset(asset_id=f"asset-{index}", metadata={"duration": 20})
        for index in range(1, asset_count + 1)
    ]
    state = SelectionState(
        task_name="demo",
        target_duration_sec=30,
        categories=[
            SelectionCategory(
                category_id="category-001",
                name="人物",
                purpose="人物比较",
            ),
            SelectionCategory(
                category_id="category-002",
                name="环境",
                purpose="环境比较",
            ),
        ],
    )
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
    batch = next(tool for tool in tools if tool.name == "asset_get_batch")
    return state, batch


def test_asset_get_batch_records_inspections_atomically(tmp_path: Path) -> None:
    state, batch = _build_inspection_batch_tool(tmp_path)

    result = batch.invoke(
        {
            "inspections": [
                {
                    "asset_id": f"asset-{index}",
                    "category_ids": ["category-001"],
                    "shortlist_reason": f"比较对象 {index}",
                }
                for index in range(1, 5)
            ]
        }
    )

    assert result["accepted"] is True
    assert len(result["assets"]) == 4
    assert result["required_inspection_count"] == 4
    assert result["inspection_count"] == 4
    assert result["remaining_inspection_count"] == 0
    assert result["category_progress"] == {
        "category-001": {
            "inspection_count": 4,
            "required_inspection_count": 4,
            "remaining_inspection_count": 0,
        },
        "category-002": {
            "inspection_count": 0,
            "required_inspection_count": 4,
            "remaining_inspection_count": 4,
        },
    }
    assert len(state.asset_progress.inspections) == 4
    assert state.asset_progress.opened_asset_ids == [
        "asset-1",
        "asset-2",
        "asset-3",
        "asset-4",
    ]
    events = [
        json.loads(line)
        for line in (tmp_path / "task" / "events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [
        event["data"]
        for event in events
        if event["event_type"] == "asset_opened"
    ] == [
        {
            "asset_id": f"asset-{index}",
            "category_ids": ["category-001"],
            "shortlist_reason": f"比较对象 {index}",
        }
        for index in range(1, 5)
    ]
    assert next(
        event["data"]
        for event in events
        if event["event_type"] == "asset_batch_opened"
    ) == {
        "asset_ids": ["asset-1", "asset-2", "asset-3", "asset-4"],
        "count": 4,
    }


def test_asset_get_batch_rejects_whole_batch_on_invalid_category(
    tmp_path: Path,
) -> None:
    state, batch = _build_inspection_batch_tool(tmp_path)

    result = batch.invoke(
        {
            "inspections": [
                {
                    "asset_id": "asset-1",
                    "category_ids": ["category-001"],
                    "shortlist_reason": "合法",
                },
                {
                    "asset_id": "asset-2",
                    "category_ids": ["category-missing"],
                    "shortlist_reason": "非法分类",
                },
            ]
        }
    )

    assert result["accepted"] is False
    assert state.asset_progress.inspections == []
    assert state.asset_progress.opened_asset_ids == []
    events = [
        json.loads(line)
        for line in (tmp_path / "task" / "events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert not any(
        event["event_type"] in {"asset_opened", "asset_batch_opened"}
        for event in events
    )


@pytest.mark.parametrize(
    ("asset_count", "inspections"),
    [
        (4, []),
        (
            11,
            [
                {
                    "asset_id": f"asset-{index}",
                    "category_ids": ["category-001"],
                    "shortlist_reason": "超过批量上限",
                }
                for index in range(1, 12)
            ],
        ),
        (
            4,
            [
                {
                    "asset_id": "asset-1",
                    "category_ids": ["category-001"],
                    "shortlist_reason": "重复素材",
                },
                {
                    "asset_id": "asset-1",
                    "category_ids": ["category-001"],
                    "shortlist_reason": "重复素材",
                },
            ],
        ),
        (
            4,
            [
                {
                    "asset_id": "asset-missing",
                    "category_ids": ["category-001"],
                    "shortlist_reason": "不存在的素材",
                }
            ],
        ),
    ],
)
def test_asset_get_batch_rejects_invalid_batch_without_state_change(
    tmp_path: Path,
    asset_count: int,
    inspections: list[dict[str, object]],
) -> None:
    state, batch = _build_inspection_batch_tool(tmp_path, asset_count)

    result = batch.invoke({"inspections": inspections})

    assert result["accepted"] is False
    assert state.asset_progress.inspections == []
    assert state.asset_progress.opened_asset_ids == []


def test_asset_get_batch_merges_categories_and_latest_reason(tmp_path: Path) -> None:
    state, batch = _build_inspection_batch_tool(tmp_path)
    first = {
        "asset_id": "asset-1",
        "category_ids": ["category-001"],
        "shortlist_reason": "先比较人物",
    }
    second = {
        "asset_id": "asset-1",
        "category_ids": ["category-002"],
        "shortlist_reason": "再比较环境",
    }

    assert batch.invoke({"inspections": [first]})["accepted"] is True
    assert batch.invoke({"inspections": [second]})["accepted"] is True

    assert len(state.asset_progress.inspections) == 1
    inspection = state.asset_progress.inspections[0]
    assert inspection.category_ids == ["category-001", "category-002"]
    assert inspection.shortlist_reason == "再比较环境"


def test_asset_get_records_single_inspection(tmp_path: Path) -> None:
    state, _ = _build_inspection_batch_tool(tmp_path)
    assets = [Asset(asset_id="asset-1", metadata={"duration": 20})]
    store = SelectionStore(tmp_path / "single")
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
    get = next(tool for tool in tools if tool.name == "asset_get")

    result = get.invoke(
        {
            "asset_id": "asset-1",
            "category_ids": ["category-001"],
            "shortlist_reason": "单条比较",
        }
    )

    assert result["accepted"] is True
    assert result["required_inspection_count"] == 1
    assert result["inspection_count"] == 1
    assert result["remaining_inspection_count"] == 0
    assert result["category_progress"] == {
        "category-001": {
            "inspection_count": 1,
            "required_inspection_count": 1,
            "remaining_inspection_count": 0,
        },
        "category-002": {
            "inspection_count": 0,
            "required_inspection_count": 1,
            "remaining_inspection_count": 1,
        },
    }
    assert state.asset_progress.inspections == [
        AssetInspection(
            asset_id="asset-1",
            category_ids=["category-001"],
            shortlist_reason="单条比较",
        )
    ]
    events = [
        json.loads(line)
        for line in (tmp_path / "single" / "events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert any(event["event_type"] == "asset_opened" for event in events)
    assert not any(event["event_type"] == "asset_batch_opened" for event in events)


@pytest.mark.parametrize(
    ("brief", "expected"),
    [
        ("剪一个 45 秒视频", 45.0),
        ("剪一个 1.5 分钟视频", 90.0),
        ("Make a 30s clip", 30.0),
        ("做一条轻松旅行视频", 60.0),
    ],
)
def test_target_duration_parser_uses_common_units_or_default(
    brief: str,
    expected: float,
) -> None:
    assert parse_target_duration(brief) == expected


def test_codex_authentication_fails_before_model_start(tmp_path: Path) -> None:
    with pytest.raises(CodexAuthenticationError, match="请先登录 Codex"):
        ensure_codex_authenticated(tmp_path / "missing-auth.json")


def test_completion_counts_overlapping_primary_ranges_by_union() -> None:
    state = SelectionState(
        task_name="demo",
        target_duration_sec=30,
        categories=[
            SelectionCategory(
                category_id="category-001",
                name="人物高能",
                purpose="用于开头",
            )
        ],
        candidates=[
            SelectionCandidate(
                candidate_id="candidate-001",
                asset_id="asset-1",
                start_sec=0,
                end_sec=30,
                category_ids=["category-001"],
                reason="前半段动作完整",
            ),
            SelectionCandidate(
                candidate_id="candidate-002",
                asset_id="asset-1",
                start_sec=10,
                end_sec=45,
                category_ids=["category-001"],
                reason="后半段反应自然",
            ),
        ],
    )
    state.asset_progress.listed_pages = [1]
    state.asset_progress.inspections = [
        AssetInspection(
            asset_id=f"asset-{index}",
            category_ids=["category-001"],
            shortlist_reason="同类比较",
        )
        for index in range(1, 5)
    ]

    SelectionValidator(
        {f"asset-{index}": 60 for index in range(1, 5)},
        total_pages=1,
    ).validate_completion(state)


def _state_with_four_required_categories() -> SelectionState:
    return SelectionState(
        task_name="demo",
        target_duration_sec=30,
        categories=[
            SelectionCategory(
                category_id=f"category-{index:03d}",
                name=f"分类 {index}",
                purpose="比较素材",
            )
            for index in range(1, 5)
        ],
    )


def test_search_depth_requires_52_inspections_for_260_assets() -> None:
    state = _state_with_four_required_categories()
    state.asset_progress.inspections = [
        AssetInspection(
            asset_id=f"asset-{index}",
            category_ids=[category.category_id for category in state.categories],
            shortlist_reason="同类比较",
        )
        for index in range(51)
    ]
    validator = SelectionValidator(
        {},
        asset_ids={f"asset-{index}" for index in range(260)},
        total_pages=13,
    )

    with pytest.raises(SelectionValidationError, match="至少需要完整检查 52 个素材"):
        validator.validate_search_depth(state)


def _fully_inspected_four_category_state() -> tuple[SelectionState, SelectionValidator]:
    state = _state_with_four_required_categories()
    asset_ids = {f"asset-{index}" for index in range(30)}
    state.asset_progress.inspections = [
        AssetInspection(
            asset_id=asset_id,
            category_ids=[category.category_id for category in state.categories],
            shortlist_reason="同类比较",
        )
        for asset_id in sorted(asset_ids)
    ]
    return state, SelectionValidator({}, asset_ids=asset_ids, total_pages=2)


@pytest.mark.parametrize(
    ("replacement", "message"),
    [
        (
            AssetInspection(
                asset_id="asset-missing",
                category_ids=[
                    "category-001",
                    "category-002",
                    "category-003",
                    "category-004",
                ],
                shortlist_reason="伪造检查",
            ),
            "素材不存在：asset-missing",
        ),
        (
            AssetInspection(
                asset_id="asset-0",
                category_ids=["category-missing"],
                shortlist_reason="伪造检查",
            ),
            "分类引用不存在：category-missing",
        ),
        (
            AssetInspection(
                asset_id="asset-0",
                category_ids=[],
                shortlist_reason="伪造检查",
            ),
            "asset-0 缺少比较分类",
        ),
        (
            AssetInspection(
                asset_id="asset-0",
                category_ids=[
                    "category-001",
                    "category-002",
                    "category-003",
                    "category-004",
                ],
                shortlist_reason=" ",
            ),
            "asset-0 缺少入围理由",
        ),
    ],
)
def test_search_depth_rejects_invalid_existing_inspection(
    replacement: AssetInspection,
    message: str,
) -> None:
    state, validator = _fully_inspected_four_category_state()
    state.asset_progress.inspections[0] = replacement

    with pytest.raises(SelectionValidationError, match=message):
        validator.validate_search_depth(state)


def test_search_depth_rejects_duplicate_existing_inspections() -> None:
    state, validator = _fully_inspected_four_category_state()
    state.asset_progress.inspections[-1] = AssetInspection(
        asset_id="asset-0",
        category_ids=[
            "category-001",
            "category-002",
            "category-003",
            "category-004",
        ],
        shortlist_reason="重复检查",
    )

    with pytest.raises(SelectionValidationError, match="素材检查记录重复：asset-0"):
        validator.validate_search_depth(state)


def test_search_depth_requires_eight_assets_for_each_required_category() -> None:
    state, validator = _fully_inspected_four_category_state()
    for index, inspection in enumerate(state.asset_progress.inspections):
        inspection.category_ids = (
            ["category-001", "category-002", "category-003", "category-004"]
            if index < 7
            else ["category-002", "category-003", "category-004"]
        )

    with pytest.raises(SelectionValidationError, match="必要分类 分类 1 至少需要 8 个比较素材"):
        validator.validate_search_depth(state)


def _completed_search_state(
    duration: float,
) -> tuple[SelectionState, SelectionValidator]:
    category = SelectionCategory(
        category_id="category-001",
        name="人物高能",
        purpose="用于开头",
    )
    asset_ids = {f"asset-{index}" for index in range(4)}
    state = SelectionState(
        task_name="demo",
        target_duration_sec=30,
        categories=[category],
        candidates=[
            SelectionCandidate(
                candidate_id="candidate-001",
                asset_id="asset-0",
                start_sec=0,
                end_sec=duration,
                category_ids=[category.category_id],
                reason="比较三个同类素材后保留",
            )
        ],
    )
    state.asset_progress.listed_pages = [1]
    state.asset_progress.opened_asset_ids = sorted(asset_ids)
    state.asset_progress.inspections = [
        AssetInspection(
            asset_id=asset_id,
            category_ids=[category.category_id],
            shortlist_reason="同类比较",
        )
        for asset_id in sorted(asset_ids)
    ]
    validator = SelectionValidator(
        {"asset-0": 100},
        asset_ids=asset_ids,
        total_pages=1,
    )
    return state, validator


@pytest.mark.parametrize(
    ("duration", "accepted"),
    [(29.9, False), (30.0, True), (45.0, True), (45.1, False)],
)
def test_completion_requires_100_to_150_percent_capacity(
    duration: float,
    accepted: bool,
) -> None:
    state, validator = _completed_search_state(duration)

    if accepted:
        validator.validate_completion(state)
    else:
        with pytest.raises(SelectionValidationError, match="30～45"):
            validator.validate_completion(state)


def test_candidate_requires_inspection_and_three_same_category_comparisons() -> None:
    state = SelectionState(
        task_name="demo",
        target_duration_sec=30,
        categories=[
            SelectionCategory(
                category_id="category-001",
                name="人物高能",
                purpose="用于开头",
            )
        ],
    )
    candidate = SelectionCandidate(
        candidate_id="candidate-001",
        asset_id="asset-0",
        start_sec=0,
        end_sec=15,
        category_ids=["category-001"],
        reason="动作完整",
    )
    validator = SelectionValidator(
        {"asset-0": 20},
        asset_ids={f"asset-{index}" for index in range(4)},
        total_pages=1,
    )

    with pytest.raises(SelectionValidationError, match="尚未完整检查"):
        validator.validate_candidate(candidate, state)

    state.asset_progress.inspections = [
        AssetInspection(
            asset_id="asset-0",
            category_ids=["category-001"],
            shortlist_reason="候选素材",
        ),
        AssetInspection(
            asset_id="asset-1",
            category_ids=["category-001"],
            shortlist_reason="比较素材 1",
        ),
        AssetInspection(
            asset_id="asset-2",
            category_ids=["category-001"],
            shortlist_reason="比较素材 2",
        ),
    ]

    with pytest.raises(SelectionValidationError, match="至少需要 3 个其他比较素材"):
        validator.validate_candidate(candidate, state)


def test_candidate_add_requires_completed_search_depth() -> None:
    state = SelectionState(
        task_name="demo",
        target_duration_sec=30,
        categories=[
            SelectionCategory(
                category_id="category-001",
                name="人物高能",
                purpose="用于开头",
            )
        ],
    )
    state.asset_progress.inspections = [
        AssetInspection(
            asset_id="asset-0",
            category_ids=["category-001"],
            shortlist_reason="候选素材",
        )
    ] + [
        AssetInspection(
            asset_id=f"asset-{index}",
            category_ids=["category-001"],
            shortlist_reason="比较素材",
        )
        for index in range(1, 4)
    ]
    validator = SelectionValidator(
        {"asset-0": 20},
        asset_ids={f"asset-{index}" for index in range(30)},
        total_pages=2,
    )
    candidate = SelectionCandidate(
        candidate_id="candidate-001",
        asset_id="asset-0",
        start_sec=0,
        end_sec=15,
        category_ids=["category-001"],
        reason="动作完整",
    )

    with pytest.raises(SelectionValidationError, match="至少需要完整检查 30 个素材"):
        validator.validate_candidate_add(candidate, state)


def test_candidate_add_rejects_pool_that_would_exceed_capacity() -> None:
    state = SelectionState(
        task_name="demo",
        target_duration_sec=30,
        categories=[
            SelectionCategory(
                category_id="category-001",
                name="人物高能",
                purpose="用于开头",
            )
        ],
        candidates=[
            SelectionCandidate(
                candidate_id="candidate-001",
                asset_id="asset-1",
                start_sec=0,
                end_sec=40,
                category_ids=["category-001"],
                reason="已有 40 秒主选",
            )
        ],
    )
    extra = SelectionCandidate(
        candidate_id="candidate-002",
        asset_id="asset-2",
        start_sec=0,
        end_sec=10,
        category_ids=["category-001"],
        reason="加入后会超过 45 秒上限",
    )
    validator = SelectionValidator(
        {"asset-1": 60, "asset-2": 20},
        total_pages=1,
    )
    state.asset_progress.inspections = [
        AssetInspection(
            asset_id=asset_id,
            category_ids=["category-001"],
            shortlist_reason="同类比较",
        )
        for asset_id in ("asset-1", "asset-2")
    ]
    state.asset_progress.opened_asset_ids = ["asset-1", "asset-2"]

    with pytest.raises(SelectionValidationError, match="超过主选容量上限"):
        validator.validate_candidate_add(extra, state)


def test_selection_completed_event_records_search_metrics(tmp_path: Path) -> None:
    state, validator = _completed_search_state(45)
    store = SelectionStore(tmp_path / "task")
    finish = next(
        tool
        for tool in SelectionTools(
            AssetBrowser([], state, store),
            state,
            store,
            validator,
        ).as_langchain_tools()
        if tool.name == "selection_finish_request"
    )

    assert finish.invoke({}) == {"accepted": True, "status": "completed"}

    completed = json.loads(
        store.events_path.read_text(encoding="utf-8").splitlines()[-1]
    )
    assert completed["event_type"] == "selection_completed"
    assert completed["data"] == {
        "candidate_count": 1,
        "inspection_count": 4,
        "required_inspection_count": 4,
        "primary_union_duration_sec": 45.0,
    }


def test_completion_requires_dynamic_categories() -> None:
    state = SelectionState(
        task_name="demo",
        target_duration_sec=30,
        candidates=[
            SelectionCandidate(
                candidate_id="candidate-001",
                asset_id="asset-1",
                start_sec=0,
                end_sec=30,
                category_ids=[],
                reason="虽然时长达标，但没有分类",
            )
        ],
    )
    state.asset_progress.listed_pages = [1]

    with pytest.raises(SelectionValidationError, match="尚未建立内容分类"):
        SelectionValidator({"asset-1": 40}, total_pages=1).validate_completion(
            state
        )


def test_old_state_without_inspections_cannot_complete() -> None:
    state, validator = _completed_search_state(45)
    state.asset_progress.inspections = []

    with pytest.raises(SelectionValidationError, match="至少需要完整检查 4 个素材"):
        validator.validate_completion(state)


def test_category_resave_preserves_ids_across_rename_and_reorder(
    tmp_path: Path,
) -> None:
    state = SelectionState(task_name="demo", target_duration_sec=30)
    store = SelectionStore(tmp_path / "task")
    browser = AssetBrowser([], state, store)
    tools = SelectionTools(
        browser,
        state,
        store,
        SelectionValidator({}, total_pages=1),
    ).as_langchain_tools()
    save = next(tool for tool in tools if tool.name == "selection_categories_save")

    first = save.invoke(
        {
            "categories": [
                {"name": "人物高能", "purpose": "用于开头"},
                {"name": "环境空镜", "purpose": "用于穿插"},
            ]
        }
    )
    assert [item["category_id"] for item in first["categories"]] == [
        "category-001",
        "category-002",
    ]
    assert first["required_inspection_count"] == 0
    assert first["inspection_count"] == 0
    assert first["remaining_inspection_count"] == 0
    assert first["category_progress"] == {
        "category-001": {
            "inspection_count": 0,
            "required_inspection_count": 0,
            "remaining_inspection_count": 0,
        },
        "category-002": {
            "inspection_count": 0,
            "required_inspection_count": 0,
            "remaining_inspection_count": 0,
        },
    }

    second = save.invoke(
        {
            "categories": [
                {
                    "category_id": "category-002",
                    "name": "无人物环境空镜",
                    "purpose": "用于穿插",
                },
                {
                    "category_id": "category-001",
                    "name": "开头人物高能",
                    "purpose": "用于开头",
                },
            ]
        }
    )

    assert [
        (item["category_id"], item["name"]) for item in second["categories"]
    ] == [
        ("category-002", "无人物环境空镜"),
        ("category-001", "开头人物高能"),
    ]


def test_category_resave_rejects_omitting_an_existing_category(
    tmp_path: Path,
) -> None:
    state = SelectionState(
        task_name="demo",
        target_duration_sec=30,
        categories=[
            SelectionCategory(
                category_id="category-001",
                name="人物高能",
                purpose="用于开头",
            ),
            SelectionCategory(
                category_id="category-002",
                name="环境空镜",
                purpose="用于穿插",
            ),
        ],
        candidates=[
            SelectionCandidate(
                candidate_id="candidate-001",
                asset_id="asset-1",
                start_sec=0,
                end_sec=15,
                category_ids=["category-002"],
                reason="需要保留环境分类引用",
            )
        ],
    )
    store = SelectionStore(tmp_path / "task")
    save = next(
        tool
        for tool in SelectionTools(
            AssetBrowser([], state, store),
            state,
            store,
            SelectionValidator({}, total_pages=1),
        ).as_langchain_tools()
        if tool.name == "selection_categories_save"
    )

    result = save.invoke(
        {
            "categories": [
                {
                    "category_id": "category-001",
                    "name": "人物高能",
                    "purpose": "用于开头",
                }
            ]
        }
    )

    assert result["accepted"] is False
    assert "必须提交完整分类列表" in "；".join(result["blockers"])
    assert [category.category_id for category in state.categories] == [
        "category-001",
        "category-002",
    ]


def test_category_resave_cannot_downgrade_required_categories_and_reduce_k(
    tmp_path: Path,
) -> None:
    state = SelectionState(
        task_name="demo",
        target_duration_sec=30,
        categories=[
            SelectionCategory(
                category_id=f"category-{index:03d}",
                name=f"分类 {index}",
                purpose="完整比较",
            )
            for index in range(1, 11)
        ],
    )
    validator = SelectionValidator(
        {},
        asset_ids={f"asset-{index}" for index in range(100)},
        total_pages=1,
    )
    store = SelectionStore(tmp_path / "task")
    save = next(
        tool
        for tool in SelectionTools(
            AssetBrowser([], state, store), state, store, validator
        ).as_langchain_tools()
        if tool.name == "selection_categories_save"
    )

    assert validator.required_inspection_count(state) == 80
    result = save.invoke(
        {
            "categories": [
                {
                    "category_id": category.category_id,
                    "name": category.name,
                    "purpose": category.purpose,
                    "required": False,
                }
                for category in state.categories
            ]
        }
    )

    assert result["accepted"] is False
    assert "不得将必要分类降级" in "；".join(result["blockers"])
    assert all(category.required for category in state.categories)
    assert validator.required_inspection_count(state) == 80


def test_asset_list_returns_compact_suggestion_overview(tmp_path: Path) -> None:
    asset = Asset.model_validate(
        {
            "asset_id": "asset-1",
            "filename": "demo.mp4",
            "metadata": {"duration": 20.0},
            "summary": "朋友们挥手欢呼。",
            "clip_suggestions": [
                {
                    "in": "00:00:01",
                    "out": "00:00:05",
                    "role": "highlight",
                    "rating": 5,
                    "reason": "动作完整且表情自然",
                    "audio_strategy": "music_only",
                    "tags": ["欢快", "人物"],
                }
            ],
        }
    )
    state = SelectionState(task_name="demo", target_duration_sec=30)
    summary = AssetBrowser(
        [asset],
        state,
        SelectionStore(tmp_path / "task"),
    ).list_page()["assets"][0]

    assert summary["suggestion_count"] == 1
    assert summary["suggestion_overview"] == [
        {
            "in": "00:00:01",
            "out": "00:00:05",
            "role": "highlight",
            "rating": 5,
        }
    ]
    assert "clip_suggestions" not in summary
