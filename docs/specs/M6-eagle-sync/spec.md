# M6 Eagle 同步 Spec

> 状态：**待用户审**。本文件由 2026-06-30 grilling 会话讨论定稿，配套 [ADR-004](../../adr/ADR-004-eagle-sync-as-thin-mapping-layer.md)。
> 覆盖：PRD §FR-9（dry-run 预览）/§FR-10（apply 写入）；TD §10。
> 依赖：[M5](../M5-data-export/spec.md)（消费 `exports/cut_index.json` 作为同步基线）、[M4](../M4-similar-clustering/spec.md)（候选池字段事实源）、[M0](../M0-data-contract/spec.md)（数据契约）。
> Eagle 版本要求：≥ 4.0 Build 21（V2 Web API）。

## Why

PRD §FR-9/§FR-10 要求 TripClipper 把分析结果同步到 Eagle，让用户基于 cut_index 的 rating/tag/status/reason 在 Eagle 里完成最终人工裁决（保留 / 删除 / 切换主备选 / 进剪辑流程）。

Grilling 阶段对 M6 形态做了密集推敲，关键张力是：**M6 是"业务呈现层"还是"通用映射层"**？

- 业务呈现层：M6 内置中文友好 tag 翻译（`tc:edit_candidate_status:excluded` → 「建议删除」）、按候选池状态过滤、按 shot_function 创建子 folder。这接近 PRD §FR-10 示例 JSON 的字面理解。
- 通用映射层：M6 仅做"字段值 → Eagle 写入维度"的字面映射，由上游 cut_index 字段决定语义，不翻译、不过滤、不建 folder。

[ADR-004](../../adr/ADR-004-eagle-sync-as-thin-mapping-layer.md) 已拍板取**通用映射层**。本 spec 是该决策的工程兑现。

PRD §FR-10 的 JSON 示例（`folders_to_create: ["项目/高光"]`）在本 spec 中**不被字面兑现**，按 ADR-004 的解读：示例为数据形状演示，验收文字仅要求"成功素材在 Eagle 中具备 ... 标签、星级、状态和备注"，本 spec 通过 tag + Eagle V2 tag group 的组合完整覆盖该验收口径，未实现 folder 维度。

> **后续扩展**：[session-splitting](../session-splitting/spec.md) 在本模块产出之上补齐了 folder 维度——按 `Asset.session_id` 一级平铺创建 Eagle folder 并归属素材（详见该 spec §Eagle 同步扩展）。本 spec 的 tag/rating/status 映射口径保持不变，folder 归属是叠加能力。

## What Changes

### 1. CLI：`tripclipper sync-eagle` 升级为完整命令

当前 [cli.py sync-eagle](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/cli.py#L516-L527) 是占位（仅打印 stub 信息）。本模块替换为完整实现：

- 命令形式：`tripclipper sync-eagle <slug> [--apply | --dry-run] [--skip] [--reset] [--retry-failed] [--skip-unanalyzed] [--strict-mapping]`
- **`--dry-run`**（默认）：仅检查 Eagle 连通性 / 版本 / cut_index 校验 / 待同步素材计数，不写入 Eagle，不修改 cut_index。stdout 打印计划摘要。
- **`--apply`**：执行写入。
- **`--skip`**：跳过 `eagle_sync_status == synced` 的 asset，仅处理 `pending` / `failed`（默认是覆盖刷新）。
- **`--reset`**：把已同步 Eagle item 移到回收站、清 cut_index 的 `eagle_item_id`，下次 `--apply` 重建。**带交互式二次确认**（"将删除 N 条 Eagle items, 是否继续? [y/N]"），CI 场景可加 `--yes` 跳过确认。
- **`--retry-failed`**：仅处理 `eagle_sync_status == failed` 的 asset。
- **`--skip-unanalyzed`**：跳过 `analysis_status == scanned` 的 asset；不加此 flag 时存在 scanned 素材会启动期阻断报错。
- **`--strict-mapping`**：禁用 default mapping 的 `auto_map_unknown`，未在 mapping 声明的字段不产 tag（仅打 warning）。

### 2. 新增模块：`tripclipper.eagle_sync`

新文件 `src/tripclipper/eagle_sync.py`，职责拆为四层：

- **Eagle V2 客户端**（`EagleV2Client`）：
  - 包装 `httpx`；base URL `http://localhost:41595/api/v2/`；超时 30s；retry 1 次（仅幂等 GET）
  - 方法：`health_check()` / `find_item_by_path(path)` / `add_from_path(path, name, tags, rating, annotation)` / `update_item(item_id, ...)` / `move_to_trash(item_id)` / `tag_group_get_all()` / `tag_group_create(name, tags)` / `tag_group_add_tags(group_id, tags)`
  - **不做去重**：`add_from_path` 直接调用 V2，不预检 sha1（按 ADR-004 决策；记 todolist）
- **Mapping 加载器**（`MappingLoader`）：
  - 从 `src/tripclipper/templates/eagle_mapping.default.yaml` 读默认配置，与项目级 `tripclipper.yaml` 中可选的 `eagle_mapping` 节做浅合并
  - 输出 `MappingConfig` dataclass：`{tag_prefix, project_tag_field, auto_map_unknown, mappings: {field_name: TargetSpec}, skip_fields: set[str], note_template: NoteTemplate}`
- **字段映射器**（`AssetMapper`）：
  - 输入：单条 `Asset` + `MappingConfig` + 项目 slug + sync 时间戳
  - 输出：`AssetWritePlan` dataclass：`{tags: list[str], rating: int | None, annotation: str, item_name: str, source_path: str}`
  - 内置渲染器：`clip_suggestions_list`（按 priority 排序，输出 markdown bullet 列表，时间码反引号包裹）；`text_block`（默认渲染器，原样保留多行）
- **同步执行器**（`EagleSyncRunner`）：
  - 遍历 cut_index → 对每条 asset 走 `AssetMapper` → 调用 `EagleV2Client` 写入 → 回写 `eagle_item_id` / `eagle_sync_status` 到 cut_index → 累积 `EagleApplyResult`
  - 处理连续失败阈值（默认 5 条网络层失败 → 整体退出）
  - 处理 tag group 维护（在所有 asset 写完后批量调 `tag_group_add_tags`）

### 3. 新增配置文件：`src/tripclipper/templates/eagle_mapping.default.yaml`

随包发布的默认 mapping。项目级 `tripclipper.yaml` 可通过 `eagle_mapping` 节点 override。

骨架（最终值在实现阶段定稿）：

```yaml
tag_prefix: "tc"
project_tag_field: "project"
auto_map_unknown: true

mappings:
  rating:
    target: eagle_rating

  analysis_status:        { target: tag }
  shot_scale:             { target: tag }
  shot_function:          { target: tag }
  subject_type:           { target: tag }
  similar_selection:      { target: tag }
  similar_group_id:       { target: tag }
  edit_candidate_status:  { target: tag }

  edit_candidate_reason:
    target: note_section
    title: 候选池理由
    order: 1
  similar_group_reason:
    target: note_section
    title: 雷同组理由
    order: 2
  clip_suggestions:
    target: note_section
    title: 建议剪辑片段
    order: 3
    renderer: clip_suggestions_list
  analysis_failure_reason:
    target: note_section
    title: 分析失败原因
    order: 4

skip_fields:
  - asset_id
  - path
  - sha1
  - imported_at
  - analyzed_at
  - similar_group_confidence
  - clip_suggestions  # （已显式在 mappings 中处理，避免 auto-map 重复 tag 化）

note_template:
  header: "_TripClipper · {project_slug} · synced {sync_timestamp}_"
  empty_section_behavior: skip
  section_format: markdown_h2

connection_failure_threshold: 5
```

### 4. 新增产物：`projects/<slug>/eagle_apply_result.json`

每次 `sync-eagle --apply` 跑完写一份（覆盖式，不保留历史）。schema：

```json
{
  "synced_at": "2026-06-30T14:23:11+09:00",
  "project_slug": "2026-japan-trip",
  "eagle_library_path": "/Users/.../Eagle Library.library",
  "totals": {
    "total": 250,
    "synced": 247,
    "failed": 3,
    "skipped": 0,
    "skipped_unanalyzed": 0
  },
  "failures": [
    {
      "asset_id": "IMG_1078",
      "asset_path": "/abs/path/to/IMG_1078.MOV",
      "stage": "addFromPath",
      "error": "Eagle returned 500: file not accessible",
      "retryable": true
    }
  ],
  "tag_group_warnings": [
    {"tag_group": "tc:similar_group_id", "missing_tags": 5, "error": "..."}
  ],
  "aborted": false,
  "abort_reason": null
}
```

`aborted: true` 时 `abort_reason` 填 `"eagle_disconnected_after_5_consecutive_failures"` 等枚举。

### 5. 数据契约修改：`Asset` 模型已有字段补齐

[`Asset`](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/models.py#L165-L166) 中 `eagle_item_id` 与 `eagle_sync_status` 字段已存在（M0 阶段保留），本模块**不新增字段**，仅消费它们：

- `eagle_item_id: str | None`：Eagle 端 item ID（V2 API 返回的 UUID 字符串）
- `eagle_sync_status: Literal["pending", "synced", "failed", "stale"] | None`
  - `pending`：未同步过；首次同步时所有 analyzed 素材的初始状态（实际 cut_index 中默认为 `None`，等价 pending）
  - `synced`：上一次 `--apply` 成功
  - `failed`：上一次 `--apply` 失败，详情见 `eagle_apply_result.json`
  - `stale`：本 spec **不实现** stale 检测，该枚举值保留备用

`Asset.tags` 字段（如 cut_index 中已存在 `tags: list[str]`）由 M3 写入。M6 在 `apply` 时把 `tags` 字段值原样作为 `tag` target 处理（在 default mapping 中不显式声明，走 auto_map_unknown 路径，每个 tag 字符串前缀化为 `tc:tags:{value}`）。具体 tag 字段名以 cut_index schema 实际为准。

### 6. paths.py 补齐

[paths.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/paths.py#L63-L68) 中已有 `eagle_*` 占位 helper，本模块兑现：

- `eagle_apply_result_path(slug, base_dir) -> Path`：`projects/<slug>/eagle_apply_result.json`
- `eagle_mapping_default_template_path() -> Path`：`<package_root>/templates/eagle_mapping.default.yaml`

### 7. 配置补齐：`config.EagleSync`

[`EagleSync`](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/config.py#L56-L63) 当前是占位 dataclass。补充字段：

- `enabled: bool = True`
- `api_base_url: str = "http://localhost:41595/api/v2/"`
- `api_token: str | None = None`（本机使用通常不需要；远程 Eagle 时填）
- `connection_failure_threshold: int = 5`
- `mapping_overrides: dict | None = None`（项目级 mapping override，浅合并到 default）

### 8. 不变项（明确锁定）

- 数据契约 `cut_index.json` schema 不变（已有 eagle_* 字段足够）
- `Asset.tags` / `Asset.rating` / `Asset.edit_candidate_*` / `Asset.similar_*` / `Asset.clip_suggestions` 字段语义不变
- M5 `exports/cut_index.json` 副本作为 M6 同步基线，**M6 读副本不读活动文件**（已在 [M5 spec §与未来模块的边界](../M5-data-export/spec.md) 锁定）
- ADR-002 候选池规则不变（M6 仅消费状态值，不改变它）
- review.html / CSV / 其他导出物与 M6 无依赖

## Impact

- **影响的能力**：
  - `tripclipper sync-eagle <slug>` 从占位升级为可用命令
  - 用户跑完 `export` 后即可执行 `sync-eagle --dry-run` 预览，再 `--apply` 写入 Eagle
  - Eagle 库自动获得按字段分组的 tag group 结构（如 `tc:edit_candidate_status` 包含 4 个值 tag）
- **影响的代码**：
  - 新增 [src/tripclipper/eagle_sync.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/eagle_sync.py)（核心模块）
  - 新增 [src/tripclipper/templates/eagle_mapping.default.yaml](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/templates/eagle_mapping.default.yaml)
  - 修改 [src/tripclipper/cli.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/cli.py#L516-L527) 的 `sync-eagle` 命令
  - 修改 [src/tripclipper/paths.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/paths.py#L63-L68) 兑现 eagle 路径 helper
  - 修改 [src/tripclipper/config.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/config.py#L56-L63) 的 `EagleSync` 配置
  - 新增 [tests/test_eagle_sync.py](file:///Users/bytedance/Documents/TripClipper_Trae/tests/test_eagle_sync.py)（核心单测，含 V2 API stub）
  - 新增 [tests/test_cli_sync_eagle.py](file:///Users/bytedance/Documents/TripClipper_Trae/tests/test_cli_sync_eagle.py)（CLI 行为测试）
  - 修改 [docs/specs/README.md](file:///Users/bytedance/Documents/TripClipper_Trae/docs/specs/README.md) 模块索引：M6 状态 → "定稿（待用户审）/ 开发中"
- **依赖更新**：
  - 新增运行时依赖 `httpx`（Eagle V2 API 调用），加入 [pyproject.toml](file:///Users/bytedance/Documents/TripClipper_Trae/pyproject.toml)
- 不改 M0 数据契约。无 BREAKING（占位命令升级，无外部消费者）。

## ADDED Requirements

### Requirement: `tripclipper sync-eagle <slug>` SHALL 提供 dry-run 与 apply 两种模式

系统 SHALL 提供 `tripclipper sync-eagle <slug>` 命令，默认 `--dry-run` 不写入 Eagle，`--apply` 执行写入。

#### Scenario: dry-run 默认行为
- **WHEN** 用户执行 `tripclipper sync-eagle <slug>` 或 `tripclipper sync-eagle <slug> --dry-run`
- **THEN** 系统 SHALL 检查 Eagle 连通性、版本、cut_index 校验
- **AND** stdout 打印将要同步的素材计数 + 分类摘要
- **AND** SHALL NOT 调用任何 Eagle 写入 API
- **AND** SHALL NOT 修改 cut_index.json

#### Scenario: apply 写入
- **WHEN** 用户执行 `tripclipper sync-eagle <slug> --apply`
- **THEN** 系统 SHALL 把每条 analyzed 素材按 mapping 规则写入 Eagle
- **AND** SHALL 回写每条素材的 `eagle_item_id` 和 `eagle_sync_status` 到 cut_index.json
- **AND** SHALL 在 `projects/<slug>/eagle_apply_result.json` 写入本次执行结果

### Requirement: M6 SHALL 仅做字段映射，不创造业务语义

M6 SHALL NOT 在 mapping 之外发明 tag 命名、过滤素材、或建立 folder 结构。所有"什么状态进 Eagle""tag 叫什么"完全由 cut_index 字段值与 default mapping 配置决定。

#### Scenario: 上游加新枚举字段
- **WHEN** cut_index 中新增字段 `recommend_action` 取值 `"delete" | "keep" | "review"`
- **AND** default mapping 中未显式声明 `recommend_action`
- **AND** `auto_map_unknown: true`（默认）
- **THEN** M6 SHALL 自动产生 tag `tc:recommend_action:delete` / `tc:recommend_action:keep` / `tc:recommend_action:review`
- **AND** SHALL NOT 需要修改 M6 代码

#### Scenario: tag 命名严格 `tc:{field}:{value}` 格式
- **WHEN** 一条 asset 的 `edit_candidate_status == "excluded"`
- **THEN** Eagle 中该 item 的 tag 列表 SHALL 包含 `tc:edit_candidate_status:excluded`
- **AND** SHALL NOT 包含中文友好别名（如「建议删除」「排除」）

### Requirement: M6 SHALL 同步所有 analyzed 素材，不做业务过滤

同步范围 SHALL 包含 `analysis_status == analyzed` 的全部素材，无论其 `edit_candidate_status` 值为 default_selected / alternate / excluded / needs_review 中的哪一个。

#### Scenario: excluded 素材也同步
- **WHEN** 项目中存在 `edit_candidate_status == "excluded"` 的素材
- **AND** 用户执行 `tripclipper sync-eagle <slug> --apply`
- **THEN** 该素材 SHALL 被同步到 Eagle，带 tag `tc:edit_candidate_status:excluded`
- **AND** 用户在 Eagle 中筛选该 tag 即可定位所有"应删"素材

#### Scenario: scanned 素材启动期阻断
- **WHEN** 项目中存在 `analysis_status == "scanned"` 的素材
- **AND** 用户未加 `--skip-unanalyzed`
- **THEN** sync-eagle SHALL 启动期报错退出，提示先跑 `analyze --stage full <slug>` 或加 `--skip-unanalyzed` 逃生
- **AND** SHALL NOT 写入任何 Eagle item
- **AND** SHALL NOT 修改 cut_index.json

#### Scenario: analysis_failed 软放行
- **WHEN** 项目中存在 `analysis_status == "analysis_failed"` 的素材
- **THEN** 该素材 SHALL 被同步，带 tag `tc:analysis_status:analysis_failed`
- **AND** note 中 SHALL 包含「## 分析失败原因」区块

### Requirement: M6 SHALL 仅支持 Eagle V2 Web API（≥ 4.0 Build 21）

启动期 SHALL 验证 Eagle 已运行且 V2 API 可用，不满足时硬阻断。

#### Scenario: Eagle 未启动
- **WHEN** 用户执行 sync-eagle 时 Eagle 应用未运行
- **THEN** 命令 SHALL 启动期报错退出，提示「请确认 Eagle 应用已启动，且版本 ≥ 4.0 Build 21」
- **AND** SHALL NOT 写入任何东西

#### Scenario: Eagle 版本过低
- **WHEN** Eagle 已启动但版本 < 4.0 Build 21（V2 API 返回 404）
- **THEN** 命令 SHALL 报错退出，提示需升级 Eagle

### Requirement: M6 SHALL 通过 V2 tagGroup API 自动维护字段分组

每个被 mapping 为 `target: tag` 的 cut_index 字段 SHALL 在 Eagle 中对应一个同名 tag group（去掉值后缀），group 内挂该字段的所有取值 tag。

#### Scenario: edit_candidate_status 字段分组
- **WHEN** 项目同步完成后
- **THEN** Eagle 中 SHALL 存在名为 `tc:edit_candidate_status` 的 tag group
- **AND** 该 group 内 SHALL 包含 `tc:edit_candidate_status:default_selected` / `:alternate` / `:excluded` / `:needs_review` 中实际出现的所有 tag
- **AND** Eagle 标签面板中这些 tag SHALL 折叠在该 group 下，不污染顶层视图

#### Scenario: tag group 维护失败不阻断
- **WHEN** 单个素材 item 写入成功但 tag group 的 `addTags` 调用失败
- **THEN** 该 item 的 tag SHALL 仍然挂在 item 上（仅 group 归类失败）
- **AND** sync-eagle SHALL 继续处理后续素材
- **AND** 失败信息 SHALL 记入 `eagle_apply_result.json` 的 `tag_group_warnings`

### Requirement: 二次同步默认 update，提供 --skip 与 --reset

默认 `--apply` 行为 SHALL 是 update：覆盖式刷新所有同步过 item 的 tag/rating/note。

#### Scenario: 默认覆盖 Eagle 端手工修改
- **WHEN** 用户在 Eagle 中手工修改了某 item 的 rating
- **AND** 用户重跑 `tripclipper sync-eagle <slug> --apply`
- **THEN** 该 item 的 rating SHALL 被 cut_index 中的 rating 覆盖

#### Scenario: --skip 跳过已同步
- **WHEN** 用户执行 `tripclipper sync-eagle <slug> --apply --skip`
- **THEN** `eagle_sync_status == "synced"` 的 asset SHALL 被跳过
- **AND** 仅 `pending` / `failed` / null 状态的 asset 被处理

#### Scenario: --reset 删 item 重建
- **WHEN** 用户执行 `tripclipper sync-eagle <slug> --apply --reset`
- **THEN** 命令 SHALL 弹出二次确认提示（"将把 N 条 Eagle items 移到回收站, 是否继续? [y/N]"）
- **AND** 用户确认后，所有 `eagle_item_id` 非空的 item 被 `moveToTrash`，cut_index 中对应的 `eagle_item_id` 清空
- **AND** 然后按 default 流程重建

### Requirement: M6 SHALL 提供错误容错与硬中止机制

单条 asset 失败 SHALL NOT 阻断整体；连续 5 条网络层失败 SHALL 触发整体退出。

#### Scenario: 单条失败继续
- **WHEN** 第 N 条 asset 调用 `addFromPath` 返回业务层错误（如文件不可访问）
- **THEN** 该 asset 的 `eagle_sync_status` SHALL 设为 `"failed"`
- **AND** 失败原因 SHALL 记入 `eagle_apply_result.json` 的 `failures`
- **AND** sync-eagle SHALL 继续处理第 N+1 条

#### Scenario: 连续网络失败硬中止
- **WHEN** 连续 5 条 asset 的 Eagle API 调用均触发网络层错误（connection refused / timeout）
- **THEN** sync-eagle SHALL 整体退出，stderr 提示"疑似 Eagle 已断开"
- **AND** 已成功 item 的 `eagle_sync_status == "synced"` SHALL 保留
- **AND** 剩余 asset 的 `eagle_sync_status` SHALL 保持原值
- **AND** `eagle_apply_result.json` 中 `aborted: true`，`abort_reason: "eagle_disconnected_after_5_consecutive_failures"`

### Requirement: note 渲染 SHALL 遵循固定模板

note 内容 SHALL 由头部 + 区块组成，区块按固定顺序排列，空字段不渲染标题。

#### Scenario: 完整 note 内容
- **GIVEN** 一条 default_selected 素材，含 `edit_candidate_reason` / `similar_group_reason` / `clip_suggestions`
- **WHEN** 同步到 Eagle
- **THEN** Eagle item 的 annotation SHALL 以斜体头部 `_TripClipper · {project_slug} · synced {timestamp}_` 开始
- **AND** 之后依次包含 `## 候选池理由` / `## 雷同组理由` / `## 建议剪辑片段` 三个区块（按 mapping order 字段）
- **AND** clip_suggestions 区块 SHALL 按 priority 升序输出 markdown bullet 列表，时间码用反引号包裹

#### Scenario: 空字段不渲染
- **GIVEN** 一条素材的 `clip_suggestions` 为空数组
- **WHEN** 同步到 Eagle
- **THEN** annotation 中 SHALL NOT 出现 `## 建议剪辑片段` 标题

### Requirement: M6 SHALL 写出 eagle_apply_result.json 产物

每次 `--apply` 跑完 SHALL 在 `projects/<slug>/eagle_apply_result.json` 写入本次执行结果（覆盖式）。

#### Scenario: 成功 + 部分失败
- **GIVEN** 250 条素材，247 条成功、3 条业务层失败、tag group 1 个 warning
- **WHEN** sync-eagle --apply 完成
- **THEN** `eagle_apply_result.json` SHALL 包含 `totals: {total: 250, synced: 247, failed: 3, ...}`
- **AND** `failures` 数组 SHALL 含 3 条 `{asset_id, asset_path, stage, error, retryable}` 记录
- **AND** `tag_group_warnings` SHALL 含 1 条记录
- **AND** `aborted: false`

## MODIFIED Requirements

### Requirement: PRD §FR-9/§FR-10 Eagle 同步 MVP 兑现方式

PRD §FR-9 「Eagle 同步预览」和 §FR-10 「Eagle 同步执行」SHALL 按以下方式在 MVP 阶段兑现：

- **预览能力（FR-9）**：由 `sync-eagle <slug> --dry-run`（默认）兑现：检查连通性 / 版本 / cut_index 校验 / 计算待同步素材计数与分类摘要，不写入 Eagle。
- **写入能力（FR-10）**：由 `sync-eagle <slug> --apply` 兑现：通过 Eagle V2 Web API 写入 rating/tag/note，并自动维护 tag group 结构。
- **PRD §FR-10 JSON 示例中的 `folders_to_create`** SHALL NOT 在本 MVP 阶段实现：M6 采用 flat layout，不建 folder（详见 [ADR-004](../../adr/ADR-004-eagle-sync-as-thin-mapping-layer.md)）。
- **「中文友好 tag 命名」** SHALL NOT 在本 MVP 阶段实现：tag 命名严格 `tc:{field}:{value}` 格式，由 Eagle 客户端 smart folder 等能力承担用户友好视图（详见 [ADR-004](../../adr/ADR-004-eagle-sync-as-thin-mapping-layer.md)）。

## REMOVED Requirements

无（M6 是首次落地，无既有功能移除）。

## 与未来模块的边界

- **M7 启动页与状态面板** SHALL 消费 `eagle_apply_result.json` 展示最近一次同步结果（成功/失败计数、待重试列表）。
- **未来"sha1 去重"优化**（见 [todolist.md](../../todolist.md)）SHALL 在 `EagleV2Client` 中增加 `find_item_by_sha1` 方法，并在 `EagleSyncRunner` 的 `addFromPath` 之前增加去重短路。该改动向后兼容，不破坏现有 cut_index 与 eagle_apply_result schema。
- **未来"中文友好命名"增强**（如确认有需要）SHALL 通过给 mapping yaml 加 `display_name` 字段 + 渲染器实现，不改动核心字段映射逻辑。

## 验收口径（人类可执行）

1. 准备一个跑过 `tripclipper export <slug>` 的项目（含 ≥10 条 analyzed 素材，至少 1 个雷同组）。
2. 启动 Eagle ≥ 4.0 Build 21；执行 `tripclipper sync-eagle <slug> --dry-run`：
   - stdout 含连通性 OK、Eagle 版本号、待同步 N 条素材的分类摘要
   - cut_index.json 与 Eagle 库均无变化
3. 执行 `tripclipper sync-eagle <slug> --apply`：
   - 命令成功结束，stdout 含 `✅ 已同步 N / N 条素材到 Eagle`
   - 打开 Eagle，左侧标签面板出现 `tc:project:<slug>` / `tc:edit_candidate_status` / `tc:shot_function` 等 tag group
   - 任一 default_selected 素材的 item，rating 与 cut_index 一致；tags 含 `tc:edit_candidate_status:default_selected` 与对应字段 tag；annotation 含斜体头部 + 候选池理由 / 雷同组理由 / 建议剪辑片段（如有）三个区块
   - 任一 excluded 素材的 item，tag 含 `tc:edit_candidate_status:excluded`，可通过 Eagle tag 筛选定位到所有 excluded 素材
4. 在 Eagle 中手工把任一 item 的 rating 改成 1 星，重跑 `tripclipper sync-eagle <slug> --apply`：
   - 该 item 的 rating SHALL 被 cut_index 中的原 rating 覆盖（验证默认 update 行为）
5. 重跑 `tripclipper sync-eagle <slug> --apply --skip`：
   - stdout 含 `跳过已同步 N 条`
   - Eagle 库无变化
6. 验证错误处理：手工关闭 Eagle 后跑 `tripclipper sync-eagle <slug> --apply`：
   - 启动期立即报错"无法连接到 Eagle"，退出码非 0，cut_index 无变化
7. 验证 scanned 阻断：手工把一条 asset 的 `analysis_status` 改成 `"scanned"`，跑 `tripclipper sync-eagle <slug> --apply`：
   - 启动期报错，提示先跑 analyze 或加 `--skip-unanalyzed`
   - 加 `--skip-unanalyzed` 后该条被跳过，其他正常同步
8. 验证产物：检查 `projects/<slug>/eagle_apply_result.json` schema 完整、totals 准确、failures 与 tag_group_warnings（如有）有详细记录
