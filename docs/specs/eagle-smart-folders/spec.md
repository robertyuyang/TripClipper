# Eagle Smart Folder 预设 Spec

> 状态：**待用户审**。本 change 由 2026-07-01 用户反馈 "顶层 tag 面板视觉炸、日常筛选靠打 tag 太累" 触发（正是 [ADR-004 §退出条件 · 第二条](../../adr/ADR-004-eagle-sync-as-thin-mapping-layer.md#退出条件) 预留的重估触发点）。
> 覆盖：M6 主 spec 未覆盖的 "用户友好视图层"；不动 M6 tag 命名与字段映射语义。
> 依赖：[M6](../M6-eagle-sync/spec.md)（sync-eagle 命令、EagleV2Client、MappingConfig、EagleSyncRunner）；Eagle 4.0 Build 22+（Smart Folder V2 API）。

## Why

M6 已把 cut_index 字段全部映射为 `tc:{field}:{value}` 格式的 Eagle tag，并通过 tag group 把它们折叠在 Eagle 标签面板下。用户在实际使用中反馈：

1. **顶层 tag 面板视觉炸**：9 个 tag group × 每组 2-6 个值 tag，加上 `tc:edit_candidate_status:default_selected` 这类 40+ 字符的长命名，展开后视觉密度很高，日常浏览时视线定位成本高。
2. **常用筛选场景需要手打组合**：例如"看本项目所有精选高光"，用户要在 tag 面板里同时点亮 `tc:project:demo-scan` + `tc:edit_candidate_status:default_selected` + `tc:shot_function:highlight` 三个 tag，交互繁琐。
3. **Eagle 内置的 Smart Folder 侧栏被闲置**：Smart Folder 本是 Eagle 官方推荐的"保存的查询"承载点，但 M6 没有主动生成任何 smart folder，用户如果想用需要在 Eagle 里逐条手动配置规则，学习成本高。

[ADR-004](../../adr/ADR-004-eagle-sync-as-thin-mapping-layer.md) 明确 M6 不做业务过滤 / 不做 folder 结构，其 §理由 4 也点明"Eagle 的 smart folder / starred tags / tag group 折叠这些客户端能力足以让用户基于 tc:* 这类机器可读 tag 自定义视图"——但**这份"自定义"依然需要用户手工完成**。本 change 把这份自定义工作**下沉为 M6 sync 流水线里的一个自动化步骤**：sync-eagle --apply 结束前，本 change 按 default mapping yaml 里声明的 preset 表，在 Eagle 库里幂等地建/更新一批 smart folder，rule 全部由 `tc:*` tag 组合构成——数据层零变化，只加视图层。

**与 ADR-004 的兼容性**：Smart Folder 是 Eagle 侧的"保存的查询规则"，本身不是数据、不新造字段、不发明命名，等价于把用户"打开 Eagle 后手工建 smart folder"这一步由代码代做。ADR-004 §一 (M6 不建 folder) 特指**物理 Folder**，Smart Folder 是查询规则不是物理归类桶，两者不冲突。

## What Changes

### 1. `eagle_mapping.default.yaml` 新增 `smart_folders:` 节

在 [src/tripclipper/templates/eagle_mapping.default.yaml](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/templates/eagle_mapping.default.yaml) 末尾追加：

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

字段语义：

- `key`（必填）：预设唯一标识，用于项目级 override 按 key 匹配（不出现在 Eagle UI 里）。
- `name`（必填）：Eagle 中的 smart folder 显示名，支持 `{project_slug}` 占位。前缀统一为 `TC · `，天然带命名空间避免与用户手建 smart folder 撞名。
- `icon_color`（可选）：Eagle 支持的枚举 `red / orange / yellow / green / aqua / blue / purple / pink`；缺省时不设 icon color。
- `match`（必填）：`AND` / `OR`，对应 Eagle rule 的 `match` 字段。
- `rules[]`（必填）：条件列表，每条 `{property, method, value}` 对应 Eagle rule schema。本 change 阶段仅用 `property: tag, method: equal`；未来可扩展。

### 2. `MappingConfig` 新增 `smart_folder_presets` 字段

在 [src/tripclipper/eagle_sync.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/eagle_sync.py) 中新增 dataclass，扩展 `MappingConfig`：

```python
@dataclass(frozen=True)
class SmartFolderRule:
    property: str          # 目前恒 "tag"
    method: str            # 目前恒 "equal"
    value: str             # 支持 {project_slug} 占位

@dataclass(frozen=True)
class SmartFolderPreset:
    key: str
    name: str              # 支持 {project_slug} 占位
    icon_color: str | None
    match: Literal["AND", "OR"]
    rules: tuple[SmartFolderRule, ...]

@dataclass(frozen=True)
class MappingConfig:
    # ... 既有字段 ...
    smart_folder_presets: tuple[SmartFolderPreset, ...]
```

`load_mapping_config` 加载 `smart_folders:` 节；每条 preset 的 `rules[].value` 若省略 `[...]` 而写标量（yaml 惯用），加载器统一 wrap 为单元素 str（Eagle API payload 组装阶段再 wrap 成 array）。

### 3. 项目级 override 合并策略：按 `key` 匹配

`load_mapping_config(project_overrides)` 处理 `project_overrides["smart_folders"]`：

- 每条 override preset 按 `key` 与 default 匹配
- 匹配到 → 该 preset **完全替换** default 版本（不做字段级浅合并；如需只改 name，用户在 override 里也要写完整 preset）
- 未匹配 → 追加为新 preset
- 顺序：先默认（按 default yaml 声明顺序）再追加（按 override 声明顺序），以保证 Eagle 侧栏排序稳定

**为什么按 key 全量替换而非字段级合并**：字段级合并会诱发"我只想改 name 却不小心保留了旧 rules"这种坑，而且 preset 是一个整体决策（rule 逻辑与 name 强相关），全量替换心智更简单。

### 4. `EagleV2Client` 新增 3 个 smart folder 方法

- `smart_folder_list() -> list[dict]`：GET `/api/v2/smartFolder/get`，返回全部 smart folder（含 pagination 处理，若有）
- `smart_folder_create(payload: dict) -> str`：POST `/api/v2/smartFolder/create`，返回新建 folder 的 id
- `smart_folder_update(folder_id: str, payload: dict) -> None`：POST `/api/v2/smartFolder/update`，覆盖 conditions/name/iconColor

payload 组装规则（本 change 内部约定）：

```json
{
  "name": "TC · demo-scan · 精选高光",
  "iconColor": "green",
  "conditions": [
    {
      "match": "AND",
      "rules": [
        { "property": "tag", "method": "equal", "value": ["tc:project:demo-scan"] },
        { "property": "tag", "method": "equal", "value": ["tc:edit_candidate_status:default_selected"] },
        { "property": "tag", "method": "equal", "value": ["tc:shot_function:highlight"] }
      ]
    }
  ]
}
```

（yaml 侧 rule.value 写标量、payload 侧统一转成 array 由 client wrapper 完成。）

### 5. 新增 `SmartFolderPlanner` 组件

在 [eagle_sync.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/eagle_sync.py) 新增：

```python
@dataclass
class SmartFolderReconcileResult:
    created: list[str]        # names
    updated: list[str]        # names
    unchanged: list[str]      # names
    warnings: list[SmartFolderWarning]

@dataclass
class SmartFolderWarning:
    key: str
    name: str
    error: str

class SmartFolderPlanner:
    def __init__(self, client: EagleV2Client, presets: tuple[SmartFolderPreset, ...], project_slug: str):
        ...

    def render_payload(self, preset: SmartFolderPreset) -> dict:
        """把 preset 渲染为 Eagle API payload（占位替换 + rule.value 转 array）"""

    def reconcile(self) -> SmartFolderReconcileResult:
        """
        1. client.smart_folder_list() 拿库里现存 smart folder
        2. 按 name 精确匹配 preset（name 已带 TC· 前缀 + slug，天然带命名空间）
        3. 存在 && conditions 与 preset 渲染值等价 → unchanged
        4. 存在 && conditions 有差异 → smart_folder_update
        5. 不存在 → smart_folder_create
        6. 单条失败 → 记 SmartFolderWarning，continue
        """
```

**非侵入原则**：Planner 只操作 `name` 以 `TC · ` 起头的 smart folder；用户手工建的 smart folder 不动。

### 6. `EagleSyncRunner` 集成 smart folder 阶段

在 [EagleSyncRunner.run()](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/eagle_sync.py) 主循环 + tag group 维护之后、写 result 之前追加：

```
1. health_check                            # 已有
2. cut_index / scanned 检查                 # 已有
3. reset 分支（可选）                       # 已有
4. 主循环: addFromPath / update_item        # 已有
5. tag group 维护                           # 已有
6. smart folder 维护   ★ 本 change 新增
7. 生成 EagleApplyResult（含 smart_folders 段）
```

行为分支：

- `dry_run` 模式：不调 API；SmartFolderPlanner 输出 "计划" 到 stdout（不改 Eagle 库；因为无法拿到 `smart_folder_list`，将 5 条预设全部计入 `created`，加脚注说明"实际执行时按当前库对账"）
- `apply` 模式且未 aborted：调 `SmartFolderPlanner.reconcile()`；结果并入 result
- `apply` 模式且 aborted（连续 5 条网络失败中止）：**跳过** smart folder 阶段（Eagle 已疑似断开，重试无意义）；result 中 `smart_folders` 段仍写入但四个 list 为空，`warnings` 里写一条 `{"key":"_all", "name":"", "error":"skipped due to aborted sync"}`
- `--no-smart-folders` flag：全阶段跳过；result 中不写 `smart_folders` 段

### 7. `EagleApplyResult` schema 增量

`projects/<slug>/eagle_apply_result.json` 新增顶层字段 `smart_folders`：

```json
{
  "synced_at": "...",
  "totals": {...},
  "failures": [...],
  "tag_group_warnings": [...],
  "smart_folders": {
    "created": ["TC · demo-scan · 精选高光", "TC · demo-scan · 建议删除"],
    "updated": ["TC · demo-scan · 待复核"],
    "unchanged": ["TC · demo-scan · 候选主选"],
    "warnings": [
      {"key": "analysis_failed", "name": "TC · demo-scan · 分析失败", "error": "HTTP 500: ..."}
    ]
  },
  "aborted": false
}
```

`smart_folders` 段是可选的：`--no-smart-folders` 时不写，向后兼容 M7 消费方（M7 遇到无该段时视作空）。

### 8. CLI `sync-eagle` 新增 `--no-smart-folders` flag

在 [sync-eagle 命令](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/cli.py) 新增：

```python
@click.option("--no-smart-folders", is_flag=True, default=False,
              help="跳过 smart folder 维护阶段")
```

默认关（即默认执行 smart folder 维护）。

### 9. CLI 输出增量

- `--dry-run` 结尾追加：`Smart Folder 计划: 将建/更新 5 个（干跑不连库对账，实际执行时按 name 幂等 reconcile）`
- `--apply` 结尾追加（正常）：`✅ Smart Folder: 5 个已就绪（新建 5 / 更新 0 / 保持 0）`
- `--apply` 结尾追加（有 warning）：`⚠️ Smart Folder: 4 个已就绪，1 个失败（详见 eagle_apply_result.json）`
- `--apply --no-smart-folders`：不打印相关行

### 10. Eagle 版本要求：从 Build 21 提到 Build 22

Smart Folder V2 API（`/api/v2/smartFolder/*`）自 Eagle 4.0 Build 22 起可用。本 change 把 M6 主 spec 中的 "≥ 4.0 Build 21" 全局改为 "≥ 4.0 Build 22"，`EagleV2Client.health_check()` 阻断阈值从 Build 21 提到 Build 22（用户已确认本机 ≥ Build 23，无实际影响）。

### 11. 不变项

- 数据契约（[models.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/models.py)）不变
- M6 tag 命名（`tc:{field}:{value}`）不变
- M6 tag group 维护逻辑不变
- ADR-004 §一 (flat 布局，不建 folder) 不改；smart folder 是查询规则不是物理 folder
- M5 exports schema 不变
- CLI `sync-eagle` 既有 flag 全部保留

## Impact

- **影响的能力**：
  - `sync-eagle --apply` 结束后，Eagle 侧栏"智能文件夹"分组下自动出现 `TC · <slug> · *` 一批预设，日常筛选一键完成
  - 用户配置项目 override 可自定义预设集合
  - `eagle_apply_result.json` 多一段 `smart_folders` 供 M7 状态面板消费
- **影响的代码**：
  - 修改 [src/tripclipper/eagle_sync.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/eagle_sync.py)：新增 `SmartFolderRule` / `SmartFolderPreset` / `SmartFolderReconcileResult` / `SmartFolderWarning` / `SmartFolderPlanner`，扩展 `EagleV2Client` 3 个方法、`MappingConfig.smart_folder_presets`、`EagleApplyResult.smart_folders`、`SyncOptions.no_smart_folders`、`EagleSyncRunner.run()` 追加 stage
  - 修改 [src/tripclipper/templates/eagle_mapping.default.yaml](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/templates/eagle_mapping.default.yaml)：追加 `smart_folders:` 节（5 条）
  - 修改 [src/tripclipper/cli.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/cli.py)：`sync-eagle` 加 `--no-smart-folders` flag + stdout 摘要
  - 修改 [docs/specs/M6-eagle-sync/spec.md](file:///Users/bytedance/Documents/TripClipper_Trae/docs/specs/M6-eagle-sync/spec.md)：Eagle 版本要求 Build 21 → Build 22（一处 Requirement 文案 + 一处 header）；末尾"与未来模块的边界"加交叉引用指向本 spec
  - 修改 [docs/specs/M6-eagle-sync/check_list.md](file:///Users/bytedance/Documents/TripClipper_Trae/docs/specs/M6-eagle-sync/check_list.md)：K 段 "≥ 4.0 Build 21" → "≥ 4.0 Build 22"
  - 修改 [docs/adr/ADR-004-eagle-sync-as-thin-mapping-layer.md](file:///Users/bytedance/Documents/TripClipper_Trae/docs/adr/ADR-004-eagle-sync-as-thin-mapping-layer.md)：新增一段 §"Smart Folder as user-facing view layer"，声明视图层与数据层分工，声明 本 change 是 §退出条件第二条的兑现
  - 修改 [docs/specs/README.md](file:///Users/bytedance/Documents/TripClipper_Trae/docs/specs/README.md)：模块索引追加 本 change 行
  - 新增 [tests/test_eagle_smart_folder.py](file:///Users/bytedance/Documents/TripClipper_Trae/tests/test_eagle_smart_folder.py)（Client + Planner 单测）
  - 补测 [tests/test_eagle_mapping.py](file:///Users/bytedance/Documents/TripClipper_Trae/tests/test_eagle_mapping.py)：`smart_folders` 加载 / override / 缺省
  - 补测 [tests/test_eagle_sync_runner.py](file:///Users/bytedance/Documents/TripClipper_Trae/tests/test_eagle_sync_runner.py)：runner 集成 smart folder 阶段
  - 补测 [tests/test_cli_sync_eagle.py](file:///Users/bytedance/Documents/TripClipper_Trae/tests/test_cli_sync_eagle.py)：`--no-smart-folders`
  - 补测 [tests/test_eagle_sync_demo_scan.py](file:///Users/bytedance/Documents/TripClipper_Trae/tests/test_eagle_sync_demo_scan.py)：apply 后 5 条 smart folder 就绪
- **依赖更新**：无新增第三方依赖（复用 httpx）
- 不改 M0 数据契约。无 BREAKING（`smart_folders` 段是 result 文件的新增字段，M7 未来消费方按可选处理）

## ADDED Requirements

### Requirement: sync-eagle --apply SHALL 在同步末尾维护默认 Smart Folder 预设

系统 SHALL 在 `sync-eagle <slug> --apply` 主循环 + tag group 维护完成后，按 default mapping 中 `smart_folders` 声明，在 Eagle 库中幂等地建/更新一批 smart folder。

#### Scenario: 首次 apply 建立预设
- **WHEN** 用户首次执行 `tripclipper sync-eagle demo-scan --apply`（Eagle 库中无同名 smart folder）
- **THEN** Eagle 库 SHALL 出现 5 个 name 以 `TC · demo-scan · ` 起头的 smart folder
- **AND** 每个 smart folder 的 conditions SHALL 与 default yaml 中 preset 的 rules 语义等价
- **AND** `eagle_apply_result.json.smart_folders.created` SHALL 含 5 个 name

#### Scenario: 再次 apply 幂等
- **WHEN** 用户已跑过一次 --apply，第二次执行 `tripclipper sync-eagle demo-scan --apply`（cut_index 与 mapping 均无变化）
- **THEN** Eagle 库 SHALL NOT 出现同名重复 smart folder
- **AND** 5 个 smart folder 的 conditions 保持不变
- **AND** `eagle_apply_result.json.smart_folders.unchanged` SHALL 含 5 个 name（`created` / `updated` 均为空数组）

#### Scenario: 修改 default mapping 后 apply 触发 update
- **WHEN** 用户在 `tripclipper.yaml` 里 override 一条 preset 的 rules（key 匹配、rules 变化）
- **AND** 重跑 `--apply`
- **THEN** 该 preset 对应的 smart folder SHALL 被 `smart_folder_update` 覆盖 conditions
- **AND** `eagle_apply_result.json.smart_folders.updated` SHALL 含该 name

#### Scenario: 用户手建的 smart folder 不动
- **GIVEN** 用户在 Eagle 中手工建过一个 name = "我的高光集" 的 smart folder
- **WHEN** 用户跑 `--apply`
- **THEN** 本 change SHALL NOT 修改或删除 "我的高光集"
- **AND** 只操作 name 以 `TC · ` 起头的 smart folder

### Requirement: Smart folder 阶段失败 SHALL NOT 阻断整体同步

单条 smart folder 的 create/update 失败 SHALL 仅记 warning，不影响主同步已完成的成果。

#### Scenario: 单条 smart folder create 失败
- **WHEN** 主循环成功同步全部 asset 后，某条 smart folder 的 `smartFolder/create` 返回 5xx
- **THEN** 该失败 SHALL 记入 `eagle_apply_result.json.smart_folders.warnings`（含 key / name / error）
- **AND** 其他 smart folder 的 create/update SHALL 继续尝试
- **AND** 已成功同步的 asset 的 `eagle_sync_status == "synced"` SHALL 保留

#### Scenario: 主同步 aborted 时跳过 smart folder 阶段
- **WHEN** 主循环因连续 5 条网络失败触发 `aborted = True`
- **THEN** 本 change SHALL NOT 尝试 smart folder create/update（Eagle 疑似已断开）
- **AND** `eagle_apply_result.json.smart_folders.warnings` SHALL 含 1 条 `{"key": "_all", "error": "skipped due to aborted sync"}`

### Requirement: Smart Folder 预设 SHALL 支持项目级 override（按 key 全量替换）

系统 SHALL 允许用户在项目 `tripclipper.yaml` 的 `eagle_sync.mapping_overrides.smart_folders` 中声明 override preset。

#### Scenario: 按 key 匹配的 preset 被完全替换
- **GIVEN** default yaml 中 preset `key: highlights` 的 name 为 "TC · {slug} · 精选高光"、icon_color 为 green
- **WHEN** 用户 override `{key: highlights, name: "TC · {slug} · Hero", icon_color: purple, match: AND, rules: [...]}`
- **THEN** 加载后 `MappingConfig.smart_folder_presets` 中 `key == "highlights"` 的 preset SHALL 完全等于 override 声明
- **AND** default 版本 SHALL 被替换（不做字段级合并）

#### Scenario: 未见过 key 的 preset 追加
- **WHEN** 用户 override 声明 `{key: extreme_wide, name: "TC · {slug} · 大远景", ...}`（default 中无此 key）
- **THEN** 加载后 `MappingConfig.smart_folder_presets` SHALL 在末尾追加该 preset
- **AND** 已有 5 条 default preset 保留

### Requirement: --no-smart-folders SHALL 完全跳过 smart folder 阶段

系统 SHALL 提供 `--no-smart-folders` flag，让用户在必要时禁用 smart folder 维护。

#### Scenario: 加 flag 后不动 Eagle smart folder
- **WHEN** 用户执行 `tripclipper sync-eagle demo-scan --apply --no-smart-folders`
- **THEN** 主同步 + tag group 维护正常执行
- **AND** SHALL NOT 调用任何 `smartFolder/*` API
- **AND** `eagle_apply_result.json` 中 SHALL NOT 出现 `smart_folders` 顶层字段（保持向后兼容）

### Requirement: dry-run SHALL 打印 smart folder 计划但不调 API

`sync-eagle --dry-run`（默认）SHALL 输出 smart folder 计划摘要，且 SHALL NOT 调用任何 smart folder 写入 API。

#### Scenario: dry-run 打印计划
- **WHEN** 用户执行 `tripclipper sync-eagle demo-scan --dry-run`
- **THEN** stdout SHALL 含一行 "Smart Folder 计划: 将建/更新 5 个（干跑不连库对账）"
- **AND** SHALL NOT 调用 `smart_folder_list` / `smart_folder_create` / `smart_folder_update`
- **AND** cut_index.json 与 Eagle 库均无变化

## MODIFIED Requirements

### Requirement: M6 SHALL 仅支持 Eagle V2 Web API

原 M6 spec 声明 "Eagle ≥ 4.0 Build 21"。本 change 因引入 Smart Folder V2 API（Build 22 起可用），SHALL 把最低版本要求提高到 **Eagle 4.0 Build 22**。

#### Scenario: Eagle 版本 < Build 22
- **WHEN** 用户执行 `sync-eagle` 时 Eagle 已启动但版本 < 4.0 Build 22
- **THEN** `EagleV2Client.health_check()` SHALL 抛 `EagleVersionError`，文案含 "≥ 4.0 Build 22"
- **AND** SHALL NOT 写入任何东西

（用户已确认本机 Eagle ≥ Build 23，此提升无实际影响。）

## REMOVED Requirements

无。

## 与未来模块的边界

- **M7 启动页与状态面板** SHALL 消费 `eagle_apply_result.json.smart_folders` 段：展示"最近一次同步在 Eagle 中新建/更新了 N 个 smart folder"作为直达链接。
- **未来"更多 rule property 支持"**（如按 rating 范围、按导入时间）SHALL 通过在 `SmartFolderRule` 支持更多 `property` / `method` 值扩展；yaml schema 与 payload 组装保持向前兼容。
- **未来"Smart Folder 层级/嵌套"**（Eagle API 支持 `parent` 字段）SHALL 通过 preset 加 `parent_key` 字段实现，本 change 不做。

## 验收口径（人类可执行）

1. 前置：demo-scan 项目已跑过 `sync-eagle demo-scan --apply`（M6 已完成）。
2. 本 change 落地后重跑 `sync-eagle demo-scan --apply`：
   - stdout 含 `✅ Smart Folder: 5 个已就绪（新建 5 / 更新 0 / 保持 0）`
   - Eagle 侧栏"智能文件夹"分组下出现 5 个 name 为 `TC · demo-scan · *` 的 smart folder
   - 点击 `TC · demo-scan · 精选高光` → 只显示 `edit_candidate_status:default_selected` + `shot_function:highlight` 的素材
   - 点击 `TC · demo-scan · 建议删除` → 只显示 `edit_candidate_status:excluded` 的素材
   - `eagle_apply_result.json.smart_folders.created` 含 5 个 name；`updated` / `unchanged` 为空；`warnings` 为空
3. 再跑一次 `--apply`（无变化）：
   - stdout 含 `✅ Smart Folder: 5 个已就绪（新建 0 / 更新 0 / 保持 5）`
   - `eagle_apply_result.json.smart_folders.unchanged` 含 5 个 name
4. 在 `projects/demo-scan/tripclipper.yaml` 中加 override：
   ```yaml
   eagle_sync:
     mapping_overrides:
       smart_folders:
         - key: highlights
           name: "TC · {project_slug} · Hero"
           icon_color: purple
           match: AND
           rules:
             - { property: tag, method: equal, value: "tc:project:{project_slug}" }
             - { property: tag, method: equal, value: "tc:shot_function:highlight" }
   ```
   重跑 `--apply`：Eagle 中 `TC · demo-scan · 精选高光` 被重命名为 `TC · demo-scan · Hero`，rules 变化，icon 变紫；`updated` 含此 name。
5. 在 Eagle 中手工建 smart folder "我的收藏"，重跑 `--apply` → "我的收藏" 不受影响。
6. `sync-eagle demo-scan --apply --no-smart-folders`：Eagle 侧栏无变化；`eagle_apply_result.json` 中无 `smart_folders` 段。
7. `sync-eagle demo-scan --dry-run`：stdout 含"Smart Folder 计划: 将建/更新 5 个"；Eagle 库无变化。
