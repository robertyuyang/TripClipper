# Eagle Smart Folder 预设 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` (recommended) or `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> Companion documents:
> - Spec: [`spec.md`](./spec.md) — 事实源
> - Task list: [`task_list.md`](./task_list.md) — 与本 plan 编号一一对应
> - Check list: [`check_list.md`](./check_list.md) — A~R 段验收清单

**Goal:** 让 `sync-eagle --apply` 结束后自动在 Eagle 库中幂等地建/更新一批 `TC · {slug} · xxx` 智能文件夹（内置 5 条 default，用户可 yaml override），把闲置的 Eagle Smart Folder 侧栏用起来。

**Architecture:** 在既有 M6 [`eagle_sync.py`](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/eagle_sync.py) 里追加 3 层：`EagleV2Client` 加 `smart_folder_list/create/update` 三个方法；`MappingConfig` 加 `smart_folder_presets` 字段，`load_mapping_config` 支持项目级 override 按 `key` 全量替换；新组件 `SmartFolderPlanner.reconcile()` 负责名字前缀 `TC · ` 的幂等对账（list → 语义相等判断 → create/update/unchanged）。`EagleSyncRunner.run()` 在 tag group 维护之后、写 result 之前追加 stage。数据契约（`Asset` / `cut_index.json`）与 M6 tag 命名不动。

**Tech Stack:** Python 3.11+ / dataclass / `httpx.MockTransport` 单测打桩 / Click CLI / PyYAML / 复用 M6 已有 httpx 依赖，无新增第三方依赖。

## Global Constraints

- **Eagle 版本要求**：≥ **4.0 Build 22**（Smart Folder V2 API 前置）。全代码库 "Build 21" → "Build 22"，用户机声明 "Build 23" 保持不变。
- **命名前缀**：Smart Folder name 一律形如 `TC · {project_slug} · {中文短名}`，`{project_slug}` 在 `SmartFolderPlanner.render_payload()` 里替换。**Planner 只操作 name 以 `TC · ` 起头的 smart folder**（用户手建的不动）。
- **override 合并策略**：`tripclipper.yaml` 中 `eagle_sync.mapping_overrides.smart_folders` 按 `key` **全量替换** default preset（不做字段级浅合并）；未见过的 key **追加到末尾**；顺序稳定为「default 声明顺序 → override 中 default 里没有的 key」。
- **数据契约不动**：不改 [`models.py`](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/models.py)、`Asset` 字段、`cut_index.json` schema、M6 `tc:{field}:{value}` tag 命名、tag group 维护逻辑。
- **依赖不新增**：全部走 M6 已有的 `httpx` / `pyyaml` / `click`。
- **CLI flag**：新增 `--no-smart-folders`（默认 `False`）；三个例外分支——`--dry-run` 不连库只打印计划、`aborted` 跳过、`--no-smart-folders` 全跳。
- **result schema 兼容**：`EagleApplyResult.smart_folders` 为 `SmartFolderReconcileResult | None`；`None` 时序列化 dict 里**不含此 key**（M7 未来消费方按可选处理）。
- **测试纪律**：与 M6 一致——纯函数单测 + `httpx.MockTransport` 打桩 + `CliRunner` 捕 stdout；真实 Eagle 联调只在 Task 12 由用户主导。

---

## File Structure

**Create:**
- [`tests/test_eagle_smart_folder.py`](file:///Users/bytedance/Documents/TripClipper_Trae/tests/test_eagle_smart_folder.py) — Client smart folder 方法 + Planner reconcile 全部单测（约 14 个用例）

**Modify:**
- [`src/tripclipper/eagle_sync.py`](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/eagle_sync.py) — 新增 dataclass（`SmartFolderRule` / `SmartFolderPreset` / `SmartFolderReconcileResult` / `SmartFolderWarning`）、`EagleV2Client` 3 个方法、`MappingConfig.smart_folder_presets` 字段、`load_mapping_config` override 分支、`SmartFolderPlanner` 类、`SyncOptions.no_smart_folders` 字段、`EagleApplyResult.smart_folders` 字段与 `to_dict()` 分支、`EagleSyncRunner.run()` stage 追加、`EagleVersionError` 文案与模块 docstring 版本号
- [`src/tripclipper/templates/eagle_mapping.default.yaml`](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/templates/eagle_mapping.default.yaml) — 末尾追加 `smart_folders:` 节，5 条 preset
- [`src/tripclipper/cli.py`](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/cli.py) — `sync-eagle` 命令加 `--no-smart-folders` flag + stdout 摘要行；四处 "Build 21" 文案 → "Build 22"
- [`tests/test_eagle_mapping.py`](file:///Users/bytedance/Documents/TripClipper_Trae/tests/test_eagle_mapping.py) — 追加 6 个 `smart_folders` 加载/override/校验用例
- [`tests/test_eagle_sync_runner.py`](file:///Users/bytedance/Documents/TripClipper_Trae/tests/test_eagle_sync_runner.py) — 追加 4 个 runner 集成用例
- [`tests/test_cli_sync_eagle.py`](file:///Users/bytedance/Documents/TripClipper_Trae/tests/test_cli_sync_eagle.py) — 追加 4 个 CLI stdout 用例；改 L246 `"4.0 Build 21"` → `"4.0 Build 22"`
- [`tests/test_eagle_sync_demo_scan.py`](file:///Users/bytedance/Documents/TripClipper_Trae/tests/test_eagle_sync_demo_scan.py) — 追加 3 个 E2E 用例
- [`docs/specs/M6-eagle-sync/spec.md`](file:///Users/bytedance/Documents/TripClipper_Trae/docs/specs/M6-eagle-sync/spec.md) — L6 header + Requirement §"M6 SHALL 仅支持 Eagle V2 Web API" + L269 / L273 / L381 版本文案 → Build 22；末尾"与未来模块的边界"追加 本 change 交叉引用
- [`docs/specs/M6-eagle-sync/check_list.md`](file:///Users/bytedance/Documents/TripClipper_Trae/docs/specs/M6-eagle-sync/check_list.md) — L113 / L124 / L180 版本号 → Build 22（**不改 L126 "Build 23"**）
- [`docs/adr/ADR-004-eagle-sync-as-thin-mapping-layer.md`](file:///Users/bytedance/Documents/TripClipper_Trae/docs/adr/ADR-004-eagle-sync-as-thin-mapping-layer.md) — §决策·二 之后新增 §"Smart Folder as user-facing view layer"；L40 "Build 21" → "Build 22"
- [`docs/specs/README.md`](file:///Users/bytedance/Documents/TripClipper_Trae/docs/specs/README.md) — 模块索引 M6 行下追加 本 change 行

---

## Task 1: `EagleV2Client` 新增 3 个 smart folder 方法

对应 spec: `Requirement: sync-eagle --apply SHALL 在同步末尾维护默认 Smart Folder 预设` 的底层能力。
对应 task_list Task 1 / check_list §C。

**Files:**
- Modify: `src/tripclipper/eagle_sync.py` — `EagleV2Client` 类（当前 L100~L470 之间）
- Test: `tests/test_eagle_smart_folder.py`（新建）

**Interfaces produced:**
- `EagleV2Client.smart_folder_list() -> list[dict]` — GET `/api/v2/smartFolder/get`；返回响应 `data` 数组（每条至少含 `id`, `name`, `conditions`, `iconColor`, `match`）
- `EagleV2Client.smart_folder_create(payload: dict) -> str` — POST `/api/v2/smartFolder/create`；返回响应 `data.id`
- `EagleV2Client.smart_folder_update(folder_id: str, payload: dict) -> None` — POST `/api/v2/smartFolder/update`；方法内部把 `folder_id` 合并进 payload 的 `id` 字段（避免调用方误传）
- 网络异常映射：`httpx.ConnectError` → `EagleUnavailableError`；HTTP 5xx → `EagleClientError`（与既有方法一致）

- [ ] **Step 1: 写 test_eagle_smart_folder.py 骨架 + 6 个 Client 单测（先失败）**

新建 `tests/test_eagle_smart_folder.py`：

```python
"""eagle-smart-folders SmartFolder client + planner tests. Uses httpx.MockTransport per M6 convention."""
from __future__ import annotations

import json
import pytest
import httpx

from tripclipper.eagle_sync import (
    EagleV2Client,
    EagleClientError,
    EagleUnavailableError,
)


def _client_with(handler) -> EagleV2Client:
    transport = httpx.MockTransport(handler)
    client = EagleV2Client(base_url="http://localhost:41595", api_token=None)
    client._client = httpx.Client(transport=transport, base_url="http://localhost:41595")
    return client


def test_smart_folder_list_returns_data_array():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v2/smartFolder/get"
        return httpx.Response(200, json={"status": "success", "data": [
            {"id": "SF1", "name": "TC · demo · 精选高光", "conditions": [], "match": "AND", "iconColor": "green"},
        ]})
    client = _client_with(handler)
    result = client.smart_folder_list()
    assert len(result) == 1
    assert result[0]["name"] == "TC · demo · 精选高光"


def test_smart_folder_list_empty():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "success", "data": []})
    assert _client_with(handler).smart_folder_list() == []


def test_smart_folder_create_returns_id():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v2/smartFolder/create"
        return httpx.Response(200, json={"status": "success", "data": {"id": "SF_UUID"}})
    assert _client_with(handler).smart_folder_create({"name": "x", "conditions": []}) == "SF_UUID"


def test_smart_folder_create_5xx_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"status": "error"})
    with pytest.raises(EagleClientError):
        _client_with(handler).smart_folder_create({"name": "x", "conditions": []})


def test_smart_folder_update_sends_id_in_body():
    captured = {}
    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        assert request.url.path == "/api/v2/smartFolder/update"
        return httpx.Response(200, json={"status": "success"})
    _client_with(handler).smart_folder_update("XX", {"name": "renamed"})
    assert captured["body"]["id"] == "XX"
    assert captured["body"]["name"] == "renamed"


def test_smart_folder_update_no_return():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "success"})
    # 无异常即成功
    _client_with(handler).smart_folder_update("XX", {})
```

- [ ] **Step 2: 运行测试确认全部 fail**

Run: `.venv/bin/python -m pytest tests/test_eagle_smart_folder.py -v`
Expected: 6 failures — `AttributeError: 'EagleV2Client' object has no attribute 'smart_folder_list'`（及 `smart_folder_create` / `smart_folder_update`）

- [ ] **Step 3: 在 `EagleV2Client` 里实现三个方法**

在 [`eagle_sync.py`](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/eagle_sync.py) `EagleV2Client` 类中（既有 `add_from_path` / `update_item` / `move_to_trash` 附近）追加：

```python
def smart_folder_list(self) -> list[dict]:
    """GET /api/v2/smartFolder/get — return the raw ``data`` array (may be empty)."""
    resp = self._request("GET", "/api/v2/smartFolder/get", stage="smart_folder_list")
    data = resp.get("data") if isinstance(resp, dict) else None
    return data if isinstance(data, list) else []

def smart_folder_create(self, payload: dict) -> str:
    """POST /api/v2/smartFolder/create — return the new folder id."""
    resp = self._request(
        "POST", "/api/v2/smartFolder/create",
        json=payload, stage="smart_folder_create",
    )
    data = resp.get("data") if isinstance(resp, dict) else None
    if not isinstance(data, dict) or not data.get("id"):
        raise EagleClientError(stage="smart_folder_create", cause=None, http_status=None)
    return str(data["id"])

def smart_folder_update(self, folder_id: str, payload: dict) -> None:
    """POST /api/v2/smartFolder/update — folder_id is merged into payload['id']."""
    body = {**payload, "id": folder_id}
    self._request("POST", "/api/v2/smartFolder/update", json=body, stage="smart_folder_update")
```

如果 `EagleV2Client` 尚无统一 `_request()` helper，则参照既有 `add_from_path` / `update_item` 的实现风格：用 `self._client.request()` + 5xx 抛 `EagleClientError` + `httpx.ConnectError` 抛 `EagleUnavailableError`。**关键：错误分类必须与既有方法一致**，具体参考 [`eagle_sync.py`](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/eagle_sync.py) 中 `add_from_path` 的错误处理块，把相同的 try/except 套一层即可。

- [ ] **Step 4: 运行测试确认 6 个全过**

Run: `.venv/bin/python -m pytest tests/test_eagle_smart_folder.py -v`
Expected: 6 passed

- [ ] **Step 5: 提交**

```bash
git add src/tripclipper/eagle_sync.py tests/test_eagle_smart_folder.py
git commit -m "feat(eagle-smart-folders): EagleV2Client add smart_folder_list/create/update"
```

---

## Task 2: `MappingConfig` 扩展 `smart_folder_presets` + override 合并

对应 spec §What Changes 2/3 + `Requirement: Smart Folder 预设 SHALL 支持项目级 override（按 key 全量替换）`。
对应 task_list Task 2 / check_list §D、§K。

**Files:**
- Modify: `src/tripclipper/eagle_sync.py`（`MappingConfig` dataclass + `load_mapping_config` 函数）
- Test: `tests/test_eagle_mapping.py`（追加）

**Interfaces produced:**
- `SmartFolderRule(property: str, method: str, value: str)` — `frozen=True`
- `SmartFolderPreset(key: str, name: str, icon_color: str | None, match: Literal["AND","OR"], rules: tuple[SmartFolderRule, ...])` — `frozen=True`
- `MappingConfig.smart_folder_presets: tuple[SmartFolderPreset, ...] = ()` — 新字段，默认 `()`（M6 既有构造保持向后兼容）
- `load_mapping_config(project_overrides: dict | None = None) -> MappingConfig` 支持从 `project_overrides["smart_folders"]` 读 override，按 `key` 匹配 default 后**全量替换**；未见过 key 追加至末尾；default 顺序保留

**Interfaces consumed:**
- Task 1 无（本 Task 独立）

- [ ] **Step 1: 在 `tests/test_eagle_mapping.py` 追加 6 个用例（先失败）**

在文件末尾追加：

```python
def test_load_default_smart_folders():
    from tripclipper.eagle_sync import load_mapping_config
    cfg = load_mapping_config()
    keys = [p.key for p in cfg.smart_folder_presets]
    assert keys == ["highlights", "default_selected", "excluded", "needs_review", "analysis_failed"]


def test_smart_folder_override_replaces_by_key():
    from tripclipper.eagle_sync import load_mapping_config
    overrides = {
        "smart_folders": [
            {
                "key": "highlights",
                "name": "TC · {project_slug} · Hero",
                "icon_color": "purple",
                "match": "AND",
                "rules": [{"property": "tag", "method": "equal", "value": "tc:project:{project_slug}"}],
            }
        ]
    }
    cfg = load_mapping_config(project_overrides=overrides)
    hi = next(p for p in cfg.smart_folder_presets if p.key == "highlights")
    assert hi.icon_color == "purple"
    assert hi.name == "TC · {project_slug} · Hero"
    others = [p.key for p in cfg.smart_folder_presets if p.key != "highlights"]
    assert others == ["default_selected", "excluded", "needs_review", "analysis_failed"]  # 顺序保留


def test_smart_folder_override_appends_new_key():
    from tripclipper.eagle_sync import load_mapping_config
    overrides = {
        "smart_folders": [
            {"key": "extreme_wide", "name": "TC · {project_slug} · 大远景", "icon_color": None,
             "match": "AND",
             "rules": [{"property": "tag", "method": "equal", "value": "tc:shot_scale:extreme_wide"}]}
        ]
    }
    cfg = load_mapping_config(project_overrides=overrides)
    keys = [p.key for p in cfg.smart_folder_presets]
    assert keys == ["highlights", "default_selected", "excluded", "needs_review", "analysis_failed", "extreme_wide"]


def test_smart_folder_invalid_icon_color_rejected():
    from tripclipper.eagle_sync import load_mapping_config
    from tripclipper.config import ConfigError
    overrides = {"smart_folders": [
        {"key": "highlights", "name": "x", "icon_color": "magenta", "match": "AND",
         "rules": [{"property": "tag", "method": "equal", "value": "x"}]}
    ]}
    with pytest.raises(ConfigError):
        load_mapping_config(project_overrides=overrides)


def test_smart_folder_invalid_match_rejected():
    from tripclipper.eagle_sync import load_mapping_config
    from tripclipper.config import ConfigError
    overrides = {"smart_folders": [
        {"key": "highlights", "name": "x", "icon_color": None, "match": "XOR",
         "rules": [{"property": "tag", "method": "equal", "value": "x"}]}
    ]}
    with pytest.raises(ConfigError):
        load_mapping_config(project_overrides=overrides)


def test_smart_folder_empty_rules_rejected():
    from tripclipper.eagle_sync import load_mapping_config
    from tripclipper.config import ConfigError
    overrides = {"smart_folders": [
        {"key": "highlights", "name": "x", "icon_color": None, "match": "AND", "rules": []}
    ]}
    with pytest.raises(ConfigError):
        load_mapping_config(project_overrides=overrides)
```

- [ ] **Step 2: 运行 → 全 fail（预期）**

Run: `.venv/bin/python -m pytest tests/test_eagle_mapping.py -k smart_folder -v`
Expected: 6 failures — 因为 `smart_folder_presets` 字段还不存在 / default yaml 里也没有 `smart_folders:` 节

- [ ] **Step 3: 在 `eagle_sync.py` 定义两个新 dataclass + 扩展 MappingConfig**

在 `MappingConfig` 定义之前追加：

```python
@dataclass(frozen=True)
class SmartFolderRule:
    property: str
    method: str
    value: str


@dataclass(frozen=True)
class SmartFolderPreset:
    key: str
    name: str
    icon_color: Optional[str]  # red / orange / yellow / green / aqua / blue / purple / pink / None
    match: str  # "AND" | "OR"
    rules: tuple  # tuple[SmartFolderRule, ...]
```

在 `MappingConfig` 类末尾追加字段（默认值 `()` 保持向后兼容）：

```python
    smart_folder_presets: tuple = ()  # tuple[SmartFolderPreset, ...]
```

- [ ] **Step 4: 扩展 `load_mapping_config` 支持 smart_folders 加载与 override 合并**

在 `load_mapping_config` 函数体最后（return `MappingConfig(...)` 之前）追加解析逻辑：

```python
_VALID_ICON_COLORS = frozenset({"red", "orange", "yellow", "green", "aqua", "blue", "purple", "pink"})
_VALID_MATCH = frozenset({"AND", "OR"})


def _preset_from_dict(raw: dict) -> SmartFolderPreset:
    key = raw.get("key")
    name = raw.get("name")
    icon_color = raw.get("icon_color")
    match = raw.get("match")
    rules_raw = raw.get("rules") or []
    if not key or not isinstance(key, str):
        raise ConfigError(f"smart_folder preset missing 'key': {raw!r}")
    if not name or not isinstance(name, str):
        raise ConfigError(f"smart_folder preset missing 'name': {raw!r}")
    if icon_color is not None and icon_color not in _VALID_ICON_COLORS:
        raise ConfigError(
            f"smart_folder preset '{key}' has invalid icon_color={icon_color!r}; "
            f"valid: {sorted(_VALID_ICON_COLORS)}"
        )
    if match not in _VALID_MATCH:
        raise ConfigError(
            f"smart_folder preset '{key}' has invalid match={match!r}; must be 'AND' or 'OR'"
        )
    if not rules_raw:
        raise ConfigError(f"smart_folder preset '{key}' has empty rules")
    rules = tuple(
        SmartFolderRule(
            property=r["property"],
            method=r["method"],
            value=r["value"] if isinstance(r["value"], str) else r["value"][0],
        )
        for r in rules_raw
    )
    return SmartFolderPreset(
        key=key, name=name, icon_color=icon_color, match=match, rules=rules,
    )
```

在 `load_mapping_config` 主体里（default yaml 加载后 + return 之前）加：

```python
default_smart_folders_raw = default_yaml.get("smart_folders", []) or []
override_smart_folders_raw = (project_overrides or {}).get("smart_folders", []) or []

by_key: dict[str, SmartFolderPreset] = {}
default_order: list[str] = []
for raw in default_smart_folders_raw:
    preset = _preset_from_dict(raw)
    by_key[preset.key] = preset
    default_order.append(preset.key)

override_order: list[str] = []
for raw in override_smart_folders_raw:
    preset = _preset_from_dict(raw)
    if preset.key not in by_key:
        override_order.append(preset.key)
    by_key[preset.key] = preset  # 全量替换

merged_presets = tuple([by_key[k] for k in default_order] + [by_key[k] for k in override_order])
```

然后把 `merged_presets` 塞进返回的 `MappingConfig(..., smart_folder_presets=merged_presets)`。

- [ ] **Step 5: 更新 default yaml（Task 3 内容合并到本 Task，避免 Task 2 单测跑不过）**

在 [`src/tripclipper/templates/eagle_mapping.default.yaml`](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/templates/eagle_mapping.default.yaml) 末尾追加：

```yaml
smart_folders:
  - key: highlights
    name: "TC · {project_slug} · 精选高光"
    icon_color: green
    match: AND
    rules:
      - { property: tag, method: equal, value: "tc:project:{project_slug}" }
      - { property: tag, method: equal, value: "tc:edit_candidate_status:default_selected" }
      - { property: tag, method: equal, value: "tc:shot_function:highlight" }

  - key: default_selected
    name: "TC · {project_slug} · 候选主选"
    icon_color: blue
    match: AND
    rules:
      - { property: tag, method: equal, value: "tc:project:{project_slug}" }
      - { property: tag, method: equal, value: "tc:edit_candidate_status:default_selected" }

  - key: excluded
    name: "TC · {project_slug} · 建议删除"
    icon_color: red
    match: AND
    rules:
      - { property: tag, method: equal, value: "tc:project:{project_slug}" }
      - { property: tag, method: equal, value: "tc:edit_candidate_status:excluded" }

  - key: needs_review
    name: "TC · {project_slug} · 待复核"
    icon_color: yellow
    match: AND
    rules:
      - { property: tag, method: equal, value: "tc:project:{project_slug}" }
      - { property: tag, method: equal, value: "tc:edit_candidate_status:needs_review" }

  - key: analysis_failed
    name: "TC · {project_slug} · 分析失败"
    icon_color: orange
    match: AND
    rules:
      - { property: tag, method: equal, value: "tc:project:{project_slug}" }
      - { property: tag, method: equal, value: "tc:analysis_status:analysis_failed" }
```

- [ ] **Step 6: 运行测试**

Run: `.venv/bin/python -m pytest tests/test_eagle_mapping.py -v`
Expected: 全部通过（含既有用例 + 新增 6 个 smart_folder 用例）

- [ ] **Step 7: 提交**

```bash
git add src/tripclipper/eagle_sync.py src/tripclipper/templates/eagle_mapping.default.yaml tests/test_eagle_mapping.py
git commit -m "feat(eagle-smart-folders): MappingConfig.smart_folder_presets + default yaml + override merge"
```

---

## Task 3: `SmartFolderPlanner` 组件（reconcile 幂等对账）

对应 spec §What Changes 5 + `Requirement: sync-eagle --apply SHALL 在同步末尾维护默认 Smart Folder 预设` / `Requirement: Smart folder 阶段失败 SHALL NOT 阻断整体同步`。
对应 task_list Task 4 / check_list §F。

**Files:**
- Modify: `src/tripclipper/eagle_sync.py`（新增 `SmartFolderWarning` / `SmartFolderReconcileResult` / `SmartFolderPlanner`）
- Test: `tests/test_eagle_smart_folder.py`（追加 8 个用例）

**Interfaces consumed:**
- `EagleV2Client.smart_folder_list()` / `.smart_folder_create(payload)` / `.smart_folder_update(id, payload)`（Task 1）
- `SmartFolderPreset` / `SmartFolderRule`（Task 2）

**Interfaces produced:**
- `SmartFolderWarning(key: str, name: str, error: str)`
- `SmartFolderReconcileResult(created: list[str], updated: list[str], unchanged: list[str], warnings: list[SmartFolderWarning])`（field 用 `default_factory=list`）
- `SmartFolderPlanner(client, presets, project_slug)`
  - `.render_payload(preset) -> dict` — `{project_slug}` 替换 + rule.value wrap 成单元素 array
  - `.render_conditions(preset) -> list[dict]` — 只渲染 conditions 段，供 `_conditions_equal` 调用
  - `._conditions_equal(existing_conditions, target_conditions) -> bool` — 忽略 rule 顺序
  - `.reconcile() -> SmartFolderReconcileResult`

- [ ] **Step 1: 追加 8 个 Planner 单测（先失败）**

在 `tests/test_eagle_smart_folder.py` 末尾追加：

```python
from tripclipper.eagle_sync import (
    SmartFolderPreset, SmartFolderRule, SmartFolderPlanner,
    SmartFolderReconcileResult,
)


def _preset(key: str, name: str, rules: list[tuple[str, str, str]], icon="green", match="AND"):
    return SmartFolderPreset(
        key=key, name=name, icon_color=icon, match=match,
        rules=tuple(SmartFolderRule(property=p, method=m, value=v) for p, m, v in rules),
    )


class _StubClient:
    def __init__(self, existing=None, create_id="NEW_ID", create_error_on=None, update_error_on=None):
        self.existing = existing or []
        self.create_calls = []
        self.update_calls = []
        self.create_id = create_id
        self.create_error_on = create_error_on or set()
        self.update_error_on = update_error_on or set()

    def smart_folder_list(self):
        return list(self.existing)

    def smart_folder_create(self, payload):
        self.create_calls.append(payload)
        if payload["name"] in self.create_error_on:
            raise EagleClientError(stage="smart_folder_create", cause=None, http_status=500)
        return self.create_id

    def smart_folder_update(self, folder_id, payload):
        self.update_calls.append((folder_id, payload))
        if payload["name"] in self.update_error_on:
            raise EagleClientError(stage="smart_folder_update", cause=None, http_status=500)


def test_render_payload_substitutes_slug():
    p = _preset("h", "TC · {project_slug} · 精选",
                [("tag", "equal", "tc:project:{project_slug}")])
    planner = SmartFolderPlanner(_StubClient(), (p,), "demo-scan")
    payload = planner.render_payload(p)
    assert payload["name"] == "TC · demo-scan · 精选"
    assert payload["conditions"][0]["value"] == ["tc:project:demo-scan"]


def test_render_payload_wraps_value_as_array():
    p = _preset("h", "TC · x", [("tag", "equal", "tc:project:demo")])
    planner = SmartFolderPlanner(_StubClient(), (p,), "demo")
    payload = planner.render_payload(p)
    assert payload["conditions"][0]["value"] == ["tc:project:demo"]


def test_reconcile_all_new_creates():
    p1 = _preset("h", "TC · demo · A", [("tag", "equal", "tc:x")])
    p2 = _preset("d", "TC · demo · B", [("tag", "equal", "tc:y")])
    stub = _StubClient(existing=[])
    result = SmartFolderPlanner(stub, (p1, p2), "demo").reconcile()
    assert len(stub.create_calls) == 2
    assert result.created == ["TC · demo · A", "TC · demo · B"]
    assert result.updated == [] and result.unchanged == []


def test_reconcile_unchanged_when_conditions_match():
    p = _preset("h", "TC · demo · A",
                [("tag", "equal", "tc:x"), ("tag", "equal", "tc:y")], match="AND")
    existing_conditions = [
        {"match": "AND", "rules": [
            {"property": "tag", "method": "equal", "value": ["tc:y"]},
            {"property": "tag", "method": "equal", "value": ["tc:x"]},
        ]}
    ]
    stub = _StubClient(existing=[
        {"id": "SF1", "name": "TC · demo · A", "conditions": existing_conditions}
    ])
    result = SmartFolderPlanner(stub, (p,), "demo").reconcile()
    assert stub.create_calls == [] and stub.update_calls == []
    assert result.unchanged == ["TC · demo · A"]


def test_reconcile_update_when_conditions_differ():
    p = _preset("h", "TC · demo · A",
                [("tag", "equal", "tc:x"), ("tag", "equal", "tc:y")])
    existing_conditions = [
        {"match": "AND", "rules": [
            {"property": "tag", "method": "equal", "value": ["tc:x"]},  # 少一条
        ]}
    ]
    stub = _StubClient(existing=[
        {"id": "SF1", "name": "TC · demo · A", "conditions": existing_conditions}
    ])
    result = SmartFolderPlanner(stub, (p,), "demo").reconcile()
    assert len(stub.update_calls) == 1
    assert stub.update_calls[0][0] == "SF1"
    assert result.updated == ["TC · demo · A"]


def test_reconcile_ignores_user_smart_folders():
    p = _preset("h", "TC · demo · A", [("tag", "equal", "tc:x")])
    stub = _StubClient(existing=[
        {"id": "USER", "name": "我的收藏", "conditions": []},
    ])
    result = SmartFolderPlanner(stub, (p,), "demo").reconcile()
    assert result.created == ["TC · demo · A"]  # 我的收藏不影响
    assert "我的收藏" not in result.updated + result.unchanged + result.created
    # 且 planner 不应尝试更新 "我的收藏"
    assert stub.update_calls == []


def test_reconcile_single_failure_becomes_warning():
    p1 = _preset("h", "TC · demo · A", [("tag", "equal", "tc:x")])
    p2 = _preset("d", "TC · demo · B", [("tag", "equal", "tc:y")])
    stub = _StubClient(existing=[], create_error_on={"TC · demo · A"})
    result = SmartFolderPlanner(stub, (p1, p2), "demo").reconcile()
    assert result.created == ["TC · demo · B"]
    assert len(result.warnings) == 1
    assert result.warnings[0].name == "TC · demo · A"


def test_conditions_equal_semantic_ignores_order():
    planner = SmartFolderPlanner(_StubClient(), (), "demo")
    a = [{"match": "AND", "rules": [
        {"property": "tag", "method": "equal", "value": ["x"]},
        {"property": "tag", "method": "equal", "value": ["y"]},
    ]}]
    b = [{"match": "AND", "rules": [
        {"property": "tag", "method": "equal", "value": ["y"]},
        {"property": "tag", "method": "equal", "value": ["x"]},
    ]}]
    assert planner._conditions_equal(a, b) is True
```

- [ ] **Step 2: 运行 → 全 fail**

Run: `.venv/bin/python -m pytest tests/test_eagle_smart_folder.py -v -k "planner or reconcile or render or conditions_equal"`
Expected: 8 failures with `ImportError: cannot import name 'SmartFolderPlanner'`

- [ ] **Step 3: 实现 `SmartFolderPlanner` 与两个 dataclass**

在 `eagle_sync.py`（`MappingConfig` 之后 / `AssetMapper` 之前）追加：

```python
from dataclasses import field


@dataclass
class SmartFolderWarning:
    key: str
    name: str
    error: str

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


@dataclass
class SmartFolderReconcileResult:
    created: list = field(default_factory=list)
    updated: list = field(default_factory=list)
    unchanged: list = field(default_factory=list)
    warnings: list = field(default_factory=list)  # list[SmartFolderWarning]

    def to_dict(self) -> dict:
        return {
            "created": list(self.created),
            "updated": list(self.updated),
            "unchanged": list(self.unchanged),
            "warnings": [w.to_dict() for w in self.warnings],
        }


class SmartFolderPlanner:
    """Reconcile Eagle smart folders idempotently against a preset list."""

    _NAMESPACE_PREFIX = "TC · "

    def __init__(self, client, presets, project_slug: str) -> None:
        self.client = client
        self.presets = presets
        self.project_slug = project_slug

    def render_payload(self, preset: SmartFolderPreset) -> dict:
        name = preset.name.format(project_slug=self.project_slug)
        payload = {
            "name": name,
            "conditions": self.render_conditions(preset),
        }
        if preset.icon_color is not None:
            payload["iconColor"] = preset.icon_color
        return payload

    def render_conditions(self, preset: SmartFolderPreset) -> list[dict]:
        rules = [
            {
                "property": r.property,
                "method": r.method,
                "value": [r.value.format(project_slug=self.project_slug)],
            }
            for r in preset.rules
        ]
        return [{"match": preset.match, "rules": rules}]

    def _conditions_equal(self, existing: list[dict], target: list[dict]) -> bool:
        def _norm(cond_list):
            out = []
            for c in cond_list or []:
                match_ = c.get("match")
                rules = tuple(sorted(
                    (r.get("property"), r.get("method"), tuple(r.get("value") or []))
                    for r in c.get("rules") or []
                ))
                out.append((match_, rules))
            return sorted(out)
        return _norm(existing) == _norm(target)

    def reconcile(self) -> SmartFolderReconcileResult:
        result = SmartFolderReconcileResult()
        try:
            existing = self.client.smart_folder_list()
        except Exception as exc:  # EagleUnavailableError bubbles up to caller
            raise
        by_name = {
            sf["name"]: sf
            for sf in existing
            if isinstance(sf, dict) and str(sf.get("name", "")).startswith(self._NAMESPACE_PREFIX)
        }
        for preset in self.presets:
            payload = self.render_payload(preset)
            target_name = payload["name"]
            target_conditions = payload["conditions"]
            existing_sf = by_name.get(target_name)
            try:
                if existing_sf is None:
                    self.client.smart_folder_create(payload)
                    result.created.append(target_name)
                else:
                    if self._conditions_equal(existing_sf.get("conditions", []), target_conditions):
                        result.unchanged.append(target_name)
                    else:
                        self.client.smart_folder_update(existing_sf["id"], payload)
                        result.updated.append(target_name)
            except EagleClientError as exc:
                result.warnings.append(SmartFolderWarning(
                    key=preset.key, name=target_name, error=str(exc),
                ))
        return result
```

- [ ] **Step 4: 运行 → 8 个全过**

Run: `.venv/bin/python -m pytest tests/test_eagle_smart_folder.py -v`
Expected: 14 passed（Task 1 的 6 个 + Task 3 的 8 个）

- [ ] **Step 5: 提交**

```bash
git add src/tripclipper/eagle_sync.py tests/test_eagle_smart_folder.py
git commit -m "feat(eagle-smart-folders): SmartFolderPlanner idempotent reconcile"
```

---

## Task 4: `SyncOptions.no_smart_folders` + `EagleApplyResult.smart_folders` schema 增量

对应 spec §What Changes 6/7 + `Requirement: --no-smart-folders SHALL 完全跳过 smart folder 阶段`。
对应 task_list Task 5 / check_list §G。

**Files:**
- Modify: `src/tripclipper/eagle_sync.py`（`SyncOptions` / `EagleApplyResult` / `EagleApplyResult.to_dict()`）
- Test: `tests/test_eagle_sync_runner.py`（追加）

**Interfaces produced:**
- `SyncOptions.no_smart_folders: bool = False`
- `EagleApplyResult.smart_folders: SmartFolderReconcileResult | None = None`
- `EagleApplyResult.to_dict()`：`smart_folders is None` 时输出 dict 不含此 key；否则含 `{"created", "updated", "unchanged", "warnings": [{"key","name","error"}, ...]}`

- [ ] **Step 1: 追加 2 个 result 序列化单测（新建 test 或加进既有 file）**

在 `tests/test_eagle_sync_runner.py`（若无则新建）追加：

```python
from tripclipper.eagle_sync import (
    EagleApplyResult, SmartFolderReconcileResult, SmartFolderWarning,
)


def test_result_omits_smart_folders_when_none():
    r = EagleApplyResult(
        synced_at="2026-07-02T00:00:00Z", project_slug="demo", eagle_library_path=None,
        totals={"total": 0, "synced": 0, "failed": 0, "skipped": 0, "skipped_unanalyzed": 0},
        failures=[], tag_group_warnings=[], aborted=False, abort_reason=None,
        smart_folders=None,
    )
    d = r.to_dict()
    assert "smart_folders" not in d


def test_result_serializes_smart_folder_warnings():
    sf = SmartFolderReconcileResult(
        created=["TC · demo · A"], updated=[], unchanged=[],
        warnings=[SmartFolderWarning(key="excluded", name="TC · demo · X", error="HTTP 500")],
    )
    r = EagleApplyResult(
        synced_at="t", project_slug="demo", eagle_library_path=None,
        totals={"total": 0, "synced": 0, "failed": 0, "skipped": 0, "skipped_unanalyzed": 0},
        failures=[], tag_group_warnings=[], aborted=False, abort_reason=None,
        smart_folders=sf,
    )
    d = r.to_dict()
    assert d["smart_folders"]["created"] == ["TC · demo · A"]
    assert d["smart_folders"]["warnings"][0]["key"] == "excluded"
```

- [ ] **Step 2: 运行 → fail**

Run: `.venv/bin/python -m pytest tests/test_eagle_sync_runner.py::test_result_omits_smart_folders_when_none tests/test_eagle_sync_runner.py::test_result_serializes_smart_folder_warnings -v`
Expected: fail — `TypeError: unexpected keyword argument 'smart_folders'`

- [ ] **Step 3: 修改 SyncOptions 与 EagleApplyResult**

`SyncOptions`：

```python
@dataclass
class SyncOptions:
    apply: bool = False
    skip_synced: bool = False
    reset: bool = False
    retry_failed: bool = False
    skip_unanalyzed: bool = False
    strict_mapping: bool = False
    no_smart_folders: bool = False  # eagle-smart-folders
```

`EagleApplyResult`：

```python
@dataclass
class EagleApplyResult:
    synced_at: str
    project_slug: str
    eagle_library_path: Optional[str]
    totals: dict
    failures: list
    tag_group_warnings: list
    aborted: bool
    abort_reason: Optional[str]
    smart_folders: Optional[SmartFolderReconcileResult] = None  # eagle-smart-folders

    def to_dict(self) -> dict:
        d = {
            "synced_at": self.synced_at,
            "project_slug": self.project_slug,
            "eagle_library_path": self.eagle_library_path,
            "totals": self.totals,
            "failures": [f.to_dict() for f in self.failures],
            "tag_group_warnings": [w.to_dict() for w in self.tag_group_warnings],
            "aborted": self.aborted,
            "abort_reason": self.abort_reason,
        }
        if self.smart_folders is not None:
            d["smart_folders"] = self.smart_folders.to_dict()
        return d
```

- [ ] **Step 4: 运行**

Run: `.venv/bin/python -m pytest tests/test_eagle_sync_runner.py -v`
Expected: 2 新增用例通过；既有用例无回归

- [ ] **Step 5: 提交**

```bash
git add src/tripclipper/eagle_sync.py tests/test_eagle_sync_runner.py
git commit -m "feat(eagle-smart-folders): SyncOptions/EagleApplyResult smart_folders fields"
```

---

## Task 5: `EagleSyncRunner` 集成 smart folder 阶段

对应 spec §What Changes 6 + 三条 Scenario（apply / dry-run / aborted / --no-smart-folders）。
对应 task_list Task 6 / check_list §H。

**Files:**
- Modify: `src/tripclipper/eagle_sync.py`（`EagleSyncRunner.__init__` 增 `project_slug`；`run()` 追加 stage）
- Test: `tests/test_eagle_sync_runner.py`（追加 4 个用例）

**Interfaces consumed:**
- `SmartFolderPlanner` / `SmartFolderReconcileResult` / `SmartFolderWarning`（Task 3）
- `SyncOptions.no_smart_folders` / `EagleApplyResult.smart_folders`（Task 4）
- `MappingConfig.smart_folder_presets`（Task 2）

**Interfaces produced:**
- `EagleSyncRunner(client, mapper, config, options, eagle_library_path=None, project_slug: str = "")`（追加 project_slug 参数，向后兼容默认空串；`run()` 内部若 project_slug 为空则从 mapper/首个 asset 兜底或 raise）
- `EagleSyncRunner.run()` 在 tag group 维护后追加：apply 未 aborted 未 no_smart_folders → 调 planner；aborted → 记 skip warning；dry-run/no_smart_folders → smart_folders 保持 None

- [ ] **Step 1: 追加 4 个 runner 集成用例**

在 `tests/test_eagle_sync_runner.py` 追加（补齐 fixtures 参考既有 M6 runner 单测）：

```python
def test_apply_runs_smart_folder_reconcile(monkeypatch, minimal_cut_index_with_one_analyzed_asset, in_memory_stub_client):
    """apply=True + not aborted + not no_smart_folders → planner.reconcile 被调用一次。"""
    # 参考既有 test_eagle_sync_runner.py 里 apply 路径的 fixture 组装方式
    # 断言：result.smart_folders is not None; stub_client.smart_folder_create 被调用 5 次（当有 5 条 preset 时）


def test_dry_run_skips_smart_folder_reconcile(minimal_cut_index_with_one_analyzed_asset, in_memory_stub_client):
    # apply=False → runner 不调用 planner
    # 断言：result.smart_folders is None; stub_client.smart_folder_list 未被调用


def test_no_smart_folders_flag_skips_stage(minimal_cut_index_with_one_analyzed_asset, in_memory_stub_client):
    # apply=True + no_smart_folders=True → planner 不被调用；result.smart_folders is None
    # 序列化后 dict 不含 "smart_folders" key


def test_aborted_sync_records_smart_folder_skip_warning(monkeypatch, cut_index_that_forces_5_consecutive_failures, in_memory_stub_client):
    # apply=True + connection_failure_threshold=5 触发 aborted → smart folder 阶段跳过
    # result.smart_folders 非 None，只含一条 warning：key="_all", error="skipped due to aborted sync"
    # stub_client.smart_folder_create/update/list 均未被调用（reconcile 完全跳过）
```

> **提示给实施者**：`in_memory_stub_client` fixture 若既有 `test_eagle_sync_runner.py` 已定义则直接复用；否则参照 Task 3 的 `_StubClient` 模式，为它加 `smart_folder_list/create/update` 方法与调用计数。

- [ ] **Step 2: 运行 → fail**

Run: `.venv/bin/python -m pytest tests/test_eagle_sync_runner.py -v`
Expected: 4 新增用例失败（runner 未接入 smart folder 阶段）

- [ ] **Step 3: 修改 `EagleSyncRunner` 接受 `project_slug`**

```python
class EagleSyncRunner:
    def __init__(
        self,
        client: EagleV2Client,
        mapper: AssetMapper,
        config: MappingConfig,
        options: SyncOptions,
        eagle_library_path: Optional[str] = None,
        project_slug: str = "",
    ) -> None:
        self.client = client
        self.mapper = mapper
        self.config = config
        self.options = options
        self.eagle_library_path = eagle_library_path
        self.project_slug = project_slug
```

**注意**：CLI 调用点（[`cli.py`](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/cli.py) 中构造 `EagleSyncRunner` 的位置）需要顺手把已知的 slug 传进去，Task 6 会一起改。

- [ ] **Step 4: 在 `run()` 末尾（构造 `EagleApplyResult` 之前）追加 stage**

在 `run()` 最后 `return ...` 之前替换/补充：

```python
smart_folders_result: Optional[SmartFolderReconcileResult] = None
if opts.apply and not opts.no_smart_folders:
    if aborted:
        smart_folders_result = SmartFolderReconcileResult(
            warnings=[SmartFolderWarning(
                key="_all", name="",
                error="skipped due to aborted sync",
            )],
        )
    else:
        try:
            planner = SmartFolderPlanner(
                self.client,
                self.config.smart_folder_presets,
                self.project_slug,
            )
            smart_folders_result = planner.reconcile()
        except EagleUnavailableError as exc:
            smart_folders_result = SmartFolderReconcileResult(
                warnings=[SmartFolderWarning(
                    key="_all", name="",
                    error=f"Eagle unavailable during smart folder stage: {exc}",
                )],
            )

result = EagleApplyResult(
    ...,  # 既有字段
    smart_folders=smart_folders_result,
)
```

- [ ] **Step 5: 运行 → 全过**

Run: `.venv/bin/python -m pytest tests/test_eagle_sync_runner.py -v`
Expected: passed

- [ ] **Step 6: 提交**

```bash
git add src/tripclipper/eagle_sync.py tests/test_eagle_sync_runner.py
git commit -m "feat(eagle-smart-folders): EagleSyncRunner integrates SmartFolderPlanner stage"
```

---

## Task 6: CLI `sync-eagle` 加 `--no-smart-folders` flag + stdout 摘要

对应 spec §What Changes 8/9 + `Requirement: dry-run SHALL 打印 smart folder 计划但不调 API`。
对应 task_list Task 7 / check_list §I。

**Files:**
- Modify: [`src/tripclipper/cli.py`](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/cli.py) — `sync-eagle` 命令
- Test: `tests/test_cli_sync_eagle.py`（追加）

**Interfaces consumed:**
- `SyncOptions.no_smart_folders`（Task 4）
- `EagleSyncRunner(project_slug=...)`（Task 5）
- `MappingConfig.smart_folder_presets`（Task 2）
- `EagleApplyResult.smart_folders`（Task 4）

**Interfaces produced:**
- CLI: `tripclipper sync-eagle <slug> [--dry-run|--apply] [--no-smart-folders]`
- stdout 追加行：
  - `--dry-run`：`Smart Folder 计划: 将建/更新 {N} 个（干跑不连库对账，实际执行时按 name 幂等 reconcile）`
  - `--apply` 无 warning：`✅ Smart Folder: {N} 个已就绪（新建 {C} / 更新 {U} / 保持 {K}）`
  - `--apply` 有 warning：`⚠️ Smart Folder: {N} 个已就绪，{W} 个失败（详见 eagle_apply_result.json）`
  - `--no-smart-folders`：完全不打印

- [ ] **Step 1: 加 4 个 CLI 测试（先失败）**

在 `tests/test_cli_sync_eagle.py` 追加：

```python
def test_apply_prints_smart_folder_summary(...):
    """默认 --apply → stdout 含 '✅ Smart Folder: 5 个已就绪'"""


def test_apply_with_warnings_prints_warning_line(...):
    """mock 1 条 create 失败 → stdout 含 '⚠️ Smart Folder' 且含 '1 个失败'"""


def test_no_smart_folders_flag_omits_summary(...):
    """--no-smart-folders → stdout 不含 'Smart Folder' 字样"""


def test_dry_run_prints_plan_line(...):
    """--dry-run → stdout 含 'Smart Folder 计划: 将建/更新 5 个'"""
```

- [ ] **Step 2: 运行 → fail**

Run: `.venv/bin/python -m pytest tests/test_cli_sync_eagle.py -v -k smart`
Expected: 4 failures — CLI 未打印相关摘要行

- [ ] **Step 3: 在 `cli.py` `sync-eagle` 命令加 flag + 传入 SyncOptions**

在 `sync-eagle` 命令 decorator 追加：

```python
@click.option(
    "--no-smart-folders", is_flag=True, default=False,
    help="跳过 smart folder 维护阶段",
)
```

签名与函数体里加 `no_smart_folders: bool` 参数，构造 `SyncOptions(..., no_smart_folders=no_smart_folders)`。

**同时**：构造 `EagleSyncRunner(...)` 时传入 `project_slug=slug`（Task 5 要求）。

- [ ] **Step 4: 在 CLI 的 dry-run 分支后追加计划行**

```python
if not no_smart_folders:
    n_presets = len(mapping_config.smart_folder_presets)
    click.echo(
        f"Smart Folder 计划: 将建/更新 {n_presets} 个"
        f"（干跑不连库对账，实际执行时按 name 幂等 reconcile）"
    )
```

- [ ] **Step 5: 在 CLI 的 apply 分支尾部（写完 apply_result 后）追加摘要**

```python
sf = apply_result.smart_folders
if sf is not None:
    ready = len(sf.created) + len(sf.updated) + len(sf.unchanged)
    failed = len(sf.warnings)
    if failed == 0:
        click.echo(
            f"✅ Smart Folder: {ready} 个已就绪"
            f"（新建 {len(sf.created)} / 更新 {len(sf.updated)} / 保持 {len(sf.unchanged)}）"
        )
    else:
        click.echo(
            f"⚠️ Smart Folder: {ready} 个已就绪，{failed} 个失败"
            f"（详见 eagle_apply_result.json）"
        )
```

- [ ] **Step 6: 运行**

Run: `.venv/bin/python -m pytest tests/test_cli_sync_eagle.py -v`
Expected: 全过

- [ ] **Step 7: 提交**

```bash
git add src/tripclipper/cli.py tests/test_cli_sync_eagle.py
git commit -m "feat(eagle-smart-folders): CLI --no-smart-folders flag + stdout summary"
```

---

## Task 7: Eagle 版本文案全库 Build 21 → Build 22

对应 spec MODIFIED §"M6 SHALL 仅支持 Eagle V2 Web API"（Build 21 → Build 22）。
对应 task_list Task 8 / check_list §J。

**Files:**
- Modify: `src/tripclipper/eagle_sync.py:17` 模块 docstring；`:84` `EagleVersionError.__str__` 文案
- Modify: `src/tripclipper/cli.py:653,660,689,696` 四处提示文案
- Modify: `tests/test_cli_sync_eagle.py:246`
- Modify: `docs/specs/M6-eagle-sync/spec.md` L6 header + `Requirement: M6 SHALL 仅支持 Eagle V2 Web API` 三处（L263、L269、L273、L381）
- Modify: `docs/specs/M6-eagle-sync/check_list.md` L113、L124、L180
- Modify: `docs/adr/ADR-004-eagle-sync-as-thin-mapping-layer.md:40`
- **不改**：`docs/specs/M6-eagle-sync/check_list.md:126` "Build 23"（用户机声明）；`docs/adr/ADR-004:106` "Build 23"（用户机声明）；`docs/eagle-web-api-guide.md`（工具书文档）

**Interfaces produced:** 无（纯文案）

- [ ] **Step 1: 逐文件替换 "Build 21" → "Build 22"**

- `src/tripclipper/eagle_sync.py:17`: `Version < 4.0 Build 21` → `Version < 4.0 Build 22`
- `src/tripclipper/eagle_sync.py:84`: `≥ 4.0 Build 21` → `≥ 4.0 Build 22`
- `src/tripclipper/cli.py:653,660,689,696`: `≥ 4.0 Build 21` → `≥ 4.0 Build 22`
- `tests/test_cli_sync_eagle.py:246`: `assert "4.0 Build 21" in result.output` → `assert "4.0 Build 22" in result.output`
- `docs/specs/M6-eagle-sync/spec.md`: L6 / L263 / L269 / L273 / L381
- `docs/specs/M6-eagle-sync/check_list.md`: L113 / L124 / L180
- `docs/adr/ADR-004-eagle-sync-as-thin-mapping-layer.md`: L40

- [ ] **Step 2: grep 校验**

Run: `grep -rn "Build 21" src/ tests/ docs/`
Expected: 输出仅含允许列表中的引用

- [ ] **Step 3: 运行相关测试**

Run: `.venv/bin/python -m pytest tests/test_cli_sync_eagle.py tests/test_eagle_client.py -v`
Expected: 通过

- [ ] **Step 4: 提交**

```bash
git add src/tripclipper/eagle_sync.py src/tripclipper/cli.py tests/test_cli_sync_eagle.py \
        docs/specs/M6-eagle-sync/spec.md docs/specs/M6-eagle-sync/check_list.md \
        docs/adr/ADR-004-eagle-sync-as-thin-mapping-layer.md
git commit -m "chore(eagle-smart-folders): bump Eagle version floor Build 21 → Build 22"
```

---

## Task 8: demo-scan E2E 三个 apply 用例

对应 spec §验收口径 步骤 2/3。
对应 task_list Task 9 / check_list §O。

**Files:**
- Modify: `tests/test_eagle_sync_demo_scan.py`

**Interfaces consumed:**
- 全 Task 1-6 已完成的 API + CLI

- [ ] **Step 1: 追加 3 个 E2E 用例**

```python
def test_apply_creates_five_default_smart_folders(demo_scan_project, mocked_eagle_client):
    # 断言：mocked_eagle_client.smart_folder_create 被调用 5 次
    # 5 次调用的 payload["name"] 集合 == {
    #   "TC · demo-scan · 精选高光",
    #   "TC · demo-scan · 候选主选",
    #   "TC · demo-scan · 建议删除",
    #   "TC · demo-scan · 待复核",
    #   "TC · demo-scan · 分析失败",
    # }


def test_reapply_smart_folder_reconcile_all_unchanged(demo_scan_project, mocked_eagle_client_with_prev_smart_folders):
    # 第二次跑 --apply 时 mock smart_folder_list 返回前次结果
    # 断言：smart_folder_create / smart_folder_update 均无调用
    # apply_result.smart_folders.unchanged 长度 == 5


def test_project_override_triggers_update(demo_scan_project, mocked_eagle_client_with_prev_smart_folders):
    # 加 override（highlights 换 icon_color=purple）→ 第二次 --apply
    # 断言：smart_folder_update 被调用 1 次
    # apply_result.smart_folders.updated == ["TC · demo-scan · 精选高光"]
```

- [ ] **Step 2: 运行**

Run: `.venv/bin/python -m pytest tests/test_eagle_sync_demo_scan.py -v`
Expected: 3 新用例通过；既有用例无回归

- [ ] **Step 3: 提交**

```bash
git add tests/test_eagle_sync_demo_scan.py
git commit -m "test(eagle-smart-folders): demo-scan E2E smart folder create/reconcile/override"
```

---

## Task 9: 文档 & ADR 更新

对应 spec §Impact · 影响的代码 · 文档段。
对应 task_list Task 10 / check_list §A。

**Files:**
- Modify: `docs/specs/README.md` — M6 行下方追加 本 change 行
- Modify: `docs/adr/ADR-004-eagle-sync-as-thin-mapping-layer.md` — §决策·二 之后新增小节
- Modify: `docs/specs/M6-eagle-sync/spec.md` — 末尾"与未来模块的边界" 追加 本 change 交叉引用

- [ ] **Step 1: `docs/specs/README.md` 加 本 change 行**

在 M6 行（当前 L43）下方 M7 行（L44）之前插入：

```
| eagle-smart-folders | Eagle Smart Folder 预设 | FR-9/FR-10 视图层增强 | M6 | 定稿（待用户审）|
```

- [ ] **Step 2: `docs/adr/ADR-004` 加 §"Smart Folder as user-facing view layer"**

在 §决策·二"Eagle 版本与布局" 之后（L42-L43 之间），插入：

```markdown
### 二·补 Smart Folder as user-facing view layer

eagle-smart-folders change（[docs/specs/eagle-smart-folders/spec.md](../specs/eagle-smart-folders/spec.md)）
在 sync-eagle --apply 结束后自动维护一批 name 前缀 `TC · ` 的 Eagle Smart Folder，作为
"用户友好视图层"。Smart Folder 是 Eagle 侧保存的查询规则（saved queries），rule
全部由 `tc:*` tag 组合构成，本身不新造字段、不发明命名，也不是物理 Folder，因此
不与 §一 flat 布局决策冲突。

该 change 兑现本 ADR §退出条件 · 第二条（"用户反馈打开 Eagle 后总要花时间筛/配 smart
folder"）。
```

- [ ] **Step 3: `docs/specs/M6-eagle-sync/spec.md` §"与未来模块的边界" 追加**

追加一条：

```markdown
- **Eagle Smart Folder 预设**：M6 --apply 结束后自动维护一批 smart folder 作为
  "用户友好视图层"，不改 tag 命名与字段映射。详见 [eagle-smart-folders spec](../eagle-smart-folders/spec.md)。
```

- [ ] **Step 4: 提交**

```bash
git add docs/specs/README.md docs/adr/ADR-004-eagle-sync-as-thin-mapping-layer.md \
        docs/specs/M6-eagle-sync/spec.md
git commit -m "docs(eagle-smart-folders): index + ADR-004 view-layer section + M6 boundary xref"
```

---

## Task 10: 全量回归

对应 check_list §B `M0~M6 既有 pytest 用例无回归`。
对应 task_list Task 11。

- [ ] **Step 1: 全量单测**

Run: `.venv/bin/python -m pytest tests/ --ignore=tests/test_integration_m3.py --ignore=tests/test_integration_m4.py -x`
Expected: 全过

- [ ] **Step 2: 冒烟 import**

Run: `.venv/bin/python -c "from tripclipper.eagle_sync import SmartFolderPlanner, SmartFolderPreset, SmartFolderReconcileResult, SmartFolderWarning; print('ok')"`
Expected: `ok`

- [ ] **Step 3: 手动跑一次 dry-run**

Run: `.venv/bin/tripclipper sync-eagle demo-scan --dry-run || echo "expected fail: no eagle running"`
Expected: 命令流程走到 health_check 报错退出

- [ ] **Step 4: 更新 本 change check_list.md**

把 [`check_list.md`](./check_list.md) A~P 段全部 `- [ ]` → `- [x]`（Q/R 段留给 Task 11 用户主导）。

- [ ] **Step 5: 提交**

```bash
git add docs/specs/eagle-smart-folders/check_list.md
git commit -m "chore(eagle-smart-folders): sign off automated check_list A-P"
```

---

## Task 11: 人工验收（用户主导）

对应 spec §验收口径 + check_list §Q、§R。
对应 task_list Task 12。

**这一步不由自动化 agent 执行；实施到此暂停，把控制权交回用户。**

用户将手动执行：

1. 确认本机 Eagle 版本 ≥ 4.0 Build 22
2. `.venv/bin/tripclipper sync-eagle demo-scan --apply`：
   - stdout 含 `✅ Smart Folder: 5 个已就绪（新建 5 / 更新 0 / 保持 0）`
   - Eagle 侧栏"智能文件夹"分组下出现 5 个 name 为 `TC · demo-scan · *` 的 smart folder
   - `projects/demo-scan/eagle_apply_result.json.smart_folders.created` 含 5 个 name
3. 立刻重跑 `--apply`：stdout 含 `保持 5`；`.smart_folders.unchanged` 长度 5
4. 加 override（highlights 换 icon_color=purple）→ 重跑 `--apply`：Eagle 中该 folder icon 变紫；`.smart_folders.updated` 含该 name
5. 手建 name="我的收藏" smart folder → 重跑 `--apply` → 该 folder 未被动
6. `--apply --no-smart-folders`：stdout 无 Smart Folder 相关行
7. `--dry-run`：stdout 含 `Smart Folder 计划: 将建/更新 5 个`

- [ ] **Step 1: 用户完成上述 7 项后勾选 [check_list.md](./check_list.md) §Q 全部条目**
- [ ] **Step 2: 用户勾选 §R 终判并把 `docs/specs/README.md` 本 change 行状态改为「已完成」**
- [ ] **Step 3: 提交**

```bash
git add docs/specs/eagle-smart-folders/check_list.md docs/specs/README.md
git commit -m "docs(eagle-smart-folders): manual acceptance signed off"
```

---

## Self-Review

**1. Spec coverage**：所有 spec §What Changes 1-11 与 ADDED/MODIFIED requirements 均有承接 Task。

**2. Placeholder scan**：无 TBD/TODO；fixture 名（`mocked_eagle_client_with_prev_smart_folders` 等）为描述性名字，实施者按 M6 已建立的 `httpx.MockTransport` 模式复用/扩写。

**3. Type consistency**：`SmartFolderPreset.rules` (tuple)、`SmartFolderReconcileResult.warnings` (list)、`EagleApplyResult.smart_folders` (Optional)、方法命名 `smart_folder_list/create/update` 全跨 Task 一致。

---

**Plan complete and saved to [`docs/specs/eagle-smart-folders/plan.md`](./plan.md).**

## Two execution options

**1. Subagent-Driven (recommended)** — 每个 Task 派一个 fresh subagent，实现完立刻回来 review。适合当前场景：11 个 Task 边界清晰、TDD 风格重、跨 6 个源文件。

**2. Inline Execution** — 在本会话按 Task 顺序批量执行，每 3-4 个 Task 停下来一次给你 checkpoint。