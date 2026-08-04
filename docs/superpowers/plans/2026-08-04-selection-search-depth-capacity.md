# 动态选片搜索深度与候选容量 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将票据 01 的主选候选容量改为目标时长 150%～200%，并用动态、可审计的完整索引检查规则阻止浅层搜索。

**Architecture:** 在选片状态中记录带分类和理由的 `AssetInspection`；单素材与批量详情 Tool 先确定性校验，再一次性保存检查记录。Validator 根据素材总数和必要分类数计算动态下限，并在候选新增和完成请求时检查搜索深度、同类比较和时间并集。

**Tech Stack:** Python 3.12、Pydantic 2、LangChain `StructuredTool`、DeerFlow Harness、pytest。

## Global Constraints

- `cut_index.json` 始终只读。
- 主选候选时间并集必须满足 `1.5T <= duration <= 2.0T`。
- 完整索引检查下限为 `min(N, max(30, ceil(N * 20%), C * 8))`。
- 每必要分类至少关联 `min(8, N)` 个不同检查素材。
- 每候选所属分类至少有 `min(3, N-1)` 个其他检查素材。
- 批量完整索引 Tool 每次接受 1～10 个不同素材。
- 不实现抽帧、候选更新/删除、`alternate`、`needs_review`、恢复或重走。
- 自动测试不调用网络。
- 只提交本计划涉及文件；保留工作区已有无关修改。

---

### Task 1: 检查状态模型与动态下限

**Files:**
- Modify: `src/tripclipper/clip_selection/models.py`
- Modify: `src/tripclipper/clip_selection/validator.py`
- Modify: `tests/test_clip_selection.py`

**Interfaces:**
- Produces: `AssetInspection`、`AssetProgress.inspections`。
- Produces: `SelectionValidator.required_inspection_count(state) -> int`。
- Changes: `SelectionValidator.__init__(asset_durations, *, asset_ids=None, total_pages)`。

- [ ] **Step 1: 写动态下限和旧状态兼容失败测试**

```python
from tripclipper.clip_selection.models import AssetInspection


def test_required_inspection_count_scales_with_assets_and_categories() -> None:
    categories = [
        SelectionCategory(
            category_id=f"category-{index:03d}",
            name=f"分类 {index}",
            purpose="比较素材",
        )
        for index in range(1, 5)
    ]
    state = SelectionState(
        task_name="demo",
        target_duration_sec=30,
        categories=categories,
    )
    validator = SelectionValidator(
        {},
        asset_ids={f"asset-{index}" for index in range(260)},
        total_pages=13,
    )

    assert validator.required_inspection_count(state) == 52


def test_old_state_defaults_to_empty_inspections() -> None:
    state = SelectionState.model_validate(
        {"task_name": "demo", "target_duration_sec": 30}
    )

    assert state.asset_progress.inspections == []
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `/private/tmp/tripclipper-py312/bin/python -m pytest -q tests/test_clip_selection.py -k 'required_inspection_count or old_state'`

Expected: FAIL，缺少 `AssetInspection` 或 `required_inspection_count`。

- [ ] **Step 3: 实现最小状态模型和公式**

```python
# models.py
class AssetInspection(BaseModel):
    asset_id: str
    category_ids: list[str] = Field(default_factory=list)
    shortlist_reason: str


class AssetProgress(BaseModel):
    listed_pages: list[int] = Field(default_factory=list)
    opened_asset_ids: list[str] = Field(default_factory=list)
    inspections: list[AssetInspection] = Field(default_factory=list)
```

```python
# validator.py
import math

class SelectionValidator:
    def __init__(
        self,
        asset_durations: dict[str, float],
        *,
        asset_ids: set[str] | None = None,
        total_pages: int,
    ) -> None:
        self.asset_durations = asset_durations
        self.asset_ids = set(asset_ids or asset_durations)
        self.total_assets = len(self.asset_ids)
        self.total_pages = total_pages

    def required_inspection_count(self, state: SelectionState) -> int:
        required_categories = sum(category.required for category in state.categories)
        desired = max(
            30,
            math.ceil(self.total_assets * 0.2),
            required_categories * 8,
        )
        return min(self.total_assets, desired)
```

- [ ] **Step 4: 运行目标测试**

Run: `/private/tmp/tripclipper-py312/bin/python -m pytest -q tests/test_clip_selection.py -k 'required_inspection_count or old_state'`

Expected: PASS。

- [ ] **Step 5: 提交 Task 1**

```bash
git add src/tripclipper/clip_selection/models.py src/tripclipper/clip_selection/validator.py tests/test_clip_selection.py
git commit -m "实现动态完整索引检查下限"
```

### Task 2: 原子批量完整索引 Tool

**Files:**
- Modify: `src/tripclipper/clip_selection/asset_tools.py`
- Modify: `src/tripclipper/clip_selection/selection_tools.py`
- Modify: `src/tripclipper/clip_selection/validator.py`
- Modify: `tests/test_clip_selection.py`

**Interfaces:**
- Consumes: `AssetInspection`、`SelectionValidator.asset_ids`。
- Produces: `AssetBrowser.get_many(asset_ids: list[str]) -> list[dict[str, Any]]`，纯读取。
- Produces: LangChain Tool `asset_get_batch(inspections: list[AssetInspection])`。
- Changes: `asset_get(asset_id, category_ids, shortlist_reason)`。

- [ ] **Step 1: 写批量成功、整批拒绝、合并检查测试**

```python
from langchain_core.tools import StructuredTool


def _build_inspection_batch_tool(
    tmp_path: Path,
) -> tuple[SelectionState, StructuredTool]:
    assets = [
        Asset(asset_id=f"asset-{index}", metadata={"duration": 20})
        for index in range(1, 5)
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
    assert len(state.asset_progress.inspections) == 4
    assert state.asset_progress.opened_asset_ids == [
        "asset-1", "asset-2", "asset-3", "asset-4"
    ]


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


def test_asset_get_batch_merges_categories_and_latest_reason(
    tmp_path: Path,
) -> None:
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
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `/private/tmp/tripclipper-py312/bin/python -m pytest -q tests/test_clip_selection.py -k 'asset_get_batch'`

Expected: FAIL，缺少 `asset_get_batch`。

- [ ] **Step 3: 实现批量参数校验**

```python
# validator.py
def validate_inspection_batch(
    self,
    inspections: list[AssetInspection],
    state: SelectionState,
) -> None:
    blockers: list[str] = []
    if not 1 <= len(inspections) <= 10:
        blockers.append("每批必须包含 1～10 个素材")
    asset_ids = [inspection.asset_id for inspection in inspections]
    if len(set(asset_ids)) != len(asset_ids):
        blockers.append("批内素材 ID 不得重复")
    category_ids = {category.category_id for category in state.categories}
    if not category_ids:
        blockers.append("必须先保存分类")
    for inspection in inspections:
        if inspection.asset_id not in self.asset_ids:
            blockers.append(f"素材不存在：{inspection.asset_id}")
        missing = sorted(set(inspection.category_ids) - category_ids)
        if missing:
            blockers.append(f"分类引用不存在：{', '.join(missing)}")
        if not inspection.category_ids:
            blockers.append(f"{inspection.asset_id} 缺少比较分类")
        if not inspection.shortlist_reason.strip():
            blockers.append(f"{inspection.asset_id} 缺少入围理由")
    if blockers:
        raise SelectionValidationError(blockers)
```

- [ ] **Step 4: 实现纯读取与一次保存**

```python
# asset_tools.py
def get_many(self, asset_ids: list[str]) -> list[dict[str, Any]]:
    missing = [asset_id for asset_id in asset_ids if asset_id not in self.by_id]
    if missing:
        raise ValueError("素材不存在：" + ", ".join(missing))
    return [
        self.by_id[asset_id].model_dump(mode="json", by_alias=True)
        for asset_id in asset_ids
    ]
```

```python
# selection_tools.py 内部辅助函数
def save_inspections(inspections: list[AssetInspection]) -> list[dict[str, Any]]:
    validator.validate_inspection_batch(inspections, state)
    details = browser.get_many([item.asset_id for item in inspections])
    merged = {item.asset_id: item for item in state.asset_progress.inspections}
    for item in inspections:
        previous = merged.get(item.asset_id)
        if previous is not None:
            item = item.model_copy(
                update={
                    "category_ids": sorted(
                        set(previous.category_ids) | set(item.category_ids)
                    )
                }
            )
        merged[item.asset_id] = item
        if item.asset_id not in state.asset_progress.opened_asset_ids:
            state.asset_progress.opened_asset_ids.append(item.asset_id)
    state.asset_progress.inspections = list(merged.values())
    store.save(state)
    return details
```

Tool 必须在拒绝和接受时写 `change_validated`；成功后逐素材写 `asset_opened`，再写一条 `asset_batch_opened`。事件不包含完整索引。

- [ ] **Step 5: 运行批量 Tool 测试**

Run: `/private/tmp/tripclipper-py312/bin/python -m pytest -q tests/test_clip_selection.py -k 'asset_get_batch'`

Expected: PASS。

- [ ] **Step 6: 提交 Task 2**

```bash
git add src/tripclipper/clip_selection/asset_tools.py src/tripclipper/clip_selection/selection_tools.py src/tripclipper/clip_selection/validator.py tests/test_clip_selection.py
git commit -m "增加批量完整索引检查工具"
```

### Task 3: 搜索深度与 150%～200% 容量硬校验

**Files:**
- Modify: `src/tripclipper/clip_selection/validator.py`
- Modify: `src/tripclipper/clip_selection/selection_tools.py`
- Modify: `tests/test_clip_selection.py`

**Interfaces:**
- Produces: `SelectionValidator.validate_search_depth(state)`。
- Changes: `validate_candidate` 要求候选来自检查集合并具有同类比较对象。
- Changes: `validate_candidate_add` 在搜索深度达标后才允许新增，并把容量上限改为 `2T`。
- Changes: `validate_completion` 把容量范围改为 `1.5T～2T`。

- [ ] **Step 1: 写搜索深度和容量失败测试**

```python
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
    [(44.9, False), (45.0, True), (60.0, True), (60.1, False)],
)
def test_completion_requires_150_to_200_percent_capacity(
    duration: float,
    accepted: bool,
) -> None:
    state, validator = _completed_search_state(duration)
    if accepted:
        validator.validate_completion(state)
    else:
        with pytest.raises(SelectionValidationError, match="45～60"):
            validator.validate_completion(state)
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `/private/tmp/tripclipper-py312/bin/python -m pytest -q tests/test_clip_selection.py -k 'search_depth or 150_to_200'`

Expected: FAIL，当前仍接受 30～45 秒且无搜索深度检查。

- [ ] **Step 3: 实现搜索深度校验**

```python
def validate_search_depth(self, state: SelectionState) -> None:
    blockers: list[str] = []
    inspections = state.asset_progress.inspections
    inspected_ids = {item.asset_id for item in inspections}
    required_count = self.required_inspection_count(state)
    if len(inspected_ids) < required_count:
        blockers.append(
            f"至少需要完整检查 {required_count} 个素材，当前 {len(inspected_ids)} 个"
        )
    by_category = {
        category.category_id: {
            item.asset_id
            for item in inspections
            if category.category_id in item.category_ids
        }
        for category in state.categories
    }
    category_minimum = min(8, self.total_assets)
    for category in state.categories:
        if category.required and len(by_category[category.category_id]) < category_minimum:
            blockers.append(
                f"必要分类 {category.name} 至少需要 {category_minimum} 个比较素材"
            )
    if blockers:
        raise SelectionValidationError(blockers)
```

在 `validate_candidate` 中检查候选素材已检查，并对每个分类计算其他检查素材数，最低值为 `min(3, max(0, self.total_assets - 1))`。

- [ ] **Step 4: 修改容量边界**

```python
# validate_candidate_add
minimum = state.target_duration_sec * 1.5
maximum = state.target_duration_sec * 2.0

# validate_completion
minimum = state.target_duration_sec * 1.5
maximum = state.target_duration_sec * 2.0
```

`validate_candidate_add` 先调用 `validate_search_depth`，再校验候选和 `2T` 上限。错误文案显示实际秒数。

- [ ] **Step 5: 扩展完成事件指标**

把 `_primary_union_duration` 改为公开静态方法 `primary_union_duration`，所有 Validator 内部调用同步改名。`selection_completed` 事件改为：

```python
self.store.append_event(
    "selection_completed",
    tool="selection_finish_request",
    data={
        "candidate_count": len(self.state.candidates),
        "inspection_count": len(
            {item.asset_id for item in self.state.asset_progress.inspections}
        ),
        "required_inspection_count": (
            self.validator.required_inspection_count(self.state)
        ),
        "primary_union_duration_sec": self.validator.primary_union_duration(
            self.state.candidates
        ),
    },
)
```

- [ ] **Step 6: 给既有容量测试补齐合法搜索前置**

在 `test_candidate_add_rejects_pool_that_would_exceed_capacity` 的状态中加入：

```python
state.asset_progress.inspections = [
    AssetInspection(
        asset_id=asset_id,
        category_ids=["category-001"],
        shortlist_reason="同类比较",
    )
    for asset_id in ("asset-1", "asset-2")
]
state.asset_progress.opened_asset_ids = ["asset-1", "asset-2"]
```

并把该测试已有 40 秒候选改为 55 秒，新增候选 10 秒；加入后 65 秒超过新上限 60 秒。

- [ ] **Step 7: 运行票据测试**

Run: `/private/tmp/tripclipper-py312/bin/python -m pytest -q tests/test_clip_selection.py`

Expected: PASS。

- [ ] **Step 8: 提交 Task 3**

```bash
git add src/tripclipper/clip_selection/validator.py src/tripclipper/clip_selection/selection_tools.py tests/test_clip_selection.py
git commit -m "强制搜索深度和候选容量余量"
```

### Task 4: Agent 指令与脚本化完整路径

**Files:**
- Modify: `src/tripclipper/clip_selection/prompts/system.md`
- Modify: `src/tripclipper/clip_selection/skills/custom/clip_selection/SKILL.md`
- Modify: `src/tripclipper/clip_selection/runner.py`
- Modify: `tests/test_clip_selection.py`

**Interfaces:**
- Consumes: `asset_get_batch`、动态搜索 Validator。
- Produces: Runner 向 Validator 传入全部 `asset_ids`。
- Produces: 脚本化假模型完整走完分页、分类、批量检查、45 秒候选和完成。

- [ ] **Step 1: 扩展脚本化 fixture 到四个素材**

在 `_write_cut_index` 的 `assets` 数组增加两个 20 秒素材：

```python
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
        {"in": "00:00:00", "out": "00:00:15", "reason": "动作完整"}
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
        {"in": "00:00:00", "out": "00:00:15", "reason": "人物环境兼具"}
    ],
},
```

脚本响应顺序改为：

```python
responses=[
    _tool_call("asset_list", {"page": 1}, "list-1"),
    _tool_call("asset_list", {"page": 2}, "list-2"),
    _tool_call("asset_list", {"page": 3}, "list-3"),
    _tool_call("asset_list", {"page": 4}, "list-4"),
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
                    "purpose": "提供无人物环境画面",
                },
            ]
        },
        "categories",
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
        "inspect",
    ),
    # 三个不同素材各 15 秒，总计 45 秒。
    _tool_call(
        "selection_candidate_add",
        {
            "asset_id": "asset-people",
            "start_sec": 0,
            "end_sec": 15,
            "category_ids": ["category-001"],
            "recommended_use": "片头",
            "reason": "人物表情强，优于三个同类比较素材。",
        },
        "candidate-1",
    ),
    _tool_call(
        "selection_candidate_add",
        {
            "asset_id": "asset-landscape",
            "start_sec": 0,
            "end_sec": 15,
            "category_ids": ["category-002"],
            "recommended_use": "环境过场",
            "reason": "环境层次清楚，优于三个同类比较素材。",
        },
        "candidate-2",
    ),
    _tool_call(
        "selection_candidate_add",
        {
            "asset_id": "asset-activity-1",
            "start_sec": 0,
            "end_sec": 15,
            "category_ids": ["category-001", "category-002"],
            "recommended_use": "中段高光",
            "reason": "内容与景别形成变化，优于三个同类比较素材。",
        },
        "candidate-3",
    ),
    _tool_call("selection_finish_request", {}, "finish"),
    AIMessage(content="选片候选池已完成。"),
]
```

- [ ] **Step 2: 运行脚本化测试，确认失败**

Run: `/private/tmp/tripclipper-py312/bin/python -m pytest -q tests/test_clip_selection.py::test_scripted_model_completes_minimal_selection_without_changing_index`

Expected: FAIL，Runner 未注册批量 Tool 或 Validator 缺少全部素材 ID。

- [ ] **Step 3: 修改 Runner 构造 Validator**

```python
validator = SelectionValidator(
    browser.asset_durations,
    asset_ids=set(browser.by_id),
    total_pages=browser.total_pages,
)
```

初始用户消息保留素材总数和分页数。分类保存、单素材检查和批量检查的成功返回值增加：

```json
{
  "required_inspection_count": 52,
  "inspection_count": 20,
  "remaining_inspection_count": 32,
  "category_progress": {"category-001": 8}
}
```

- [ ] **Step 4: 改写 system prompt 和 Skill**

必须包含以下明确规则：

```markdown
- 摘要浏览用于全量召回，不能代替完整索引比较。
- 先保存动态分类，再用 `asset_get_batch` 分批检查 shortlist。
- Tool 返回的动态检查下限和分类缺口全部归零前，不得添加候选。
- 达到下限后若候选判断仍变化，每批追加 10 个素材继续比较。
- 每个候选理由写明可见索引证据和同类比较依据。
- 主选时间并集必须达到目标时长的 150%～200%。
```

删除“最小候选池”“达到 100% 立即完成”“不要添加锦上添花候选”。

- [ ] **Step 5: 运行全部选片测试**

Run: `/private/tmp/tripclipper-py312/bin/python -m pytest -q tests/test_clip_selection.py`

Expected: PASS。

- [ ] **Step 6: 提交 Task 4**

```bash
git add src/tripclipper/clip_selection/prompts/system.md src/tripclipper/clip_selection/skills/custom/clip_selection/SKILL.md src/tripclipper/clip_selection/runner.py tests/test_clip_selection.py
git commit -m "引导 Agent 执行动态深度搜索"
```

### Task 5: 文档、全量验证与真实验收

**Files:**
- Modify: `README.md`
- Test: `tests/test_clip_selection.py`

**Interfaces:**
- Documents: README 使用方式；正式规则保留在已提交的 `docs/superpowers/specs/2026-08-04-selection-search-depth-capacity-design.md`，不触碰已有未提交修改的主设计文档。
- Verifies: 新行为不修改 `cut_index.json`。

- [ ] **Step 1: 更新 README**

README 增加新容量公式：

```text
1.5T <= 主选片段可用总时长 <= 2.0T
```

README 说明动态完整索引检查、`asset_get_batch` 和 30 秒任务形成 45～60 秒主选池。不要修改已有未提交变化的 `docs/clip_selection/2026-08-01-agentic-clip-selection-design.md`。

- [ ] **Step 2: 运行格式和目标测试**

Run: `git diff --check`

Expected: 无输出，退出码 0。

Run: `/private/tmp/tripclipper-py312/bin/python -m compileall -q src/tripclipper/clip_selection`

Expected: 无输出，退出码 0。

Run: `/private/tmp/tripclipper-py312/bin/python -m pytest -q tests/test_clip_selection.py`

Expected: PASS。

- [ ] **Step 3: 运行全仓测试**

Run: `/private/tmp/tripclipper-py312/bin/python -m pytest -q`

Expected: 新增选片测试全部通过；既有联网、缺失媒体 fixture 失败单独列出，不修改无关测试。

- [ ] **Step 4: 准备隔离真实验收目录**

使用 `/private/tmp/tripclipper-search-depth-acceptance/projects/26shidu/`。仅复制：

```text
projects/26shidu/cut_index.json
projects/26shidu/30秒欢快快剪.md
```

不复制现有 `selections/30秒欢快快剪`，保证从空任务开始。记录临时副本 `cut_index.json` 哈希。

- [ ] **Step 5: 运行真实 LLM 验收**

Run:

```bash
PYTHONPATH=src /private/tmp/tripclipper-py312/bin/python -m tripclipper.cli select \
  26shidu \
  /private/tmp/tripclipper-search-depth-acceptance/projects/26shidu/30秒欢快快剪.md \
  --base-dir /private/tmp/tripclipper-search-depth-acceptance/projects
```

Expected:

- `status=completed`；
- 260 个摘要全部浏览；
- `inspections` 不少于 52 个不同素材；
- 每必要分类不少于 8 个检查素材；
- 每候选有至少 3 个同类比较对象；
- 主选时间并集 45～60 秒；
- 临时 `cut_index.json` 哈希不变。

- [ ] **Step 6: 代码审查**

审查固定基线 `2843b9d` 至当前工作树。检查规格符合性、批量原子性、旧状态兼容、错误事件、票据 02/03 范围泄漏。修复确认问题后重新运行 Task 5 Step 2～5。

- [ ] **Step 7: 精确提交**

```bash
git add README.md \
  src/tripclipper/clip_selection/models.py \
  src/tripclipper/clip_selection/asset_tools.py \
  src/tripclipper/clip_selection/selection_tools.py \
  src/tripclipper/clip_selection/validator.py \
  src/tripclipper/clip_selection/runner.py \
  src/tripclipper/clip_selection/prompts/system.md \
  src/tripclipper/clip_selection/skills/custom/clip_selection/SKILL.md \
  tests/test_clip_selection.py \
  docs/superpowers/plans/2026-08-04-selection-search-depth-capacity.md
git diff --cached --check
git commit -m "增强选片搜索深度与候选余量"
```

提交前确认暂存区不含工作区已有无关删除、文档或未跟踪文件。
