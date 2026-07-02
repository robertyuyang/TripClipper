# Check List — Eagle Smart Folder 预设

> 阶段：实施前的验收清单。所有项必须在本 change 标「已完成」前逐项勾选。
> 验收纪律：与 M6 一致——单测白盒断言 + Eagle V2 smart folder API 用 `httpx.MockTransport` 打桩 + demo-scan 端到端 + CLI stdout/stderr 断言；真实 Eagle 联调（Task 12）由用户主导。

## A. 文档与决策一致性

- [ ] [spec.md](spec.md) 明确本 change 兑现 [ADR-004 §退出条件 · 第二条](../../adr/ADR-004-eagle-sync-as-thin-mapping-layer.md#退出条件)
- [ ] [spec.md](spec.md) 明确 Smart Folder 是"保存的查询规则"、非物理 folder，不违反 ADR-004 §一 flat 布局决策
- [ ] [task_list.md](task_list.md) 12 个 Task 与 spec.md 中所有 Requirement 逐条覆盖
- [ ] [docs/specs/README.md](file:///Users/bytedance/Documents/TripClipper_Trae/docs/specs/README.md) 模块索引追加 本 change 行
- [ ] [docs/adr/ADR-004-eagle-sync-as-thin-mapping-layer.md](file:///Users/bytedance/Documents/TripClipper_Trae/docs/adr/ADR-004-eagle-sync-as-thin-mapping-layer.md) 加 §"Smart Folder as user-facing view layer"（或 §关联文档追加 本 change 链接）
- [ ] [docs/specs/M6-eagle-sync/spec.md](file:///Users/bytedance/Documents/TripClipper_Trae/docs/specs/M6-eagle-sync/spec.md) §"与未来模块的边界" 追加 本 change 交叉引用

## B. 数据契约不动

- [ ] 本 change **不修改** [models.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/models.py) 任何字段
- [ ] `Asset.eagle_item_id` / `Asset.eagle_sync_status` 语义不变
- [ ] M0~M6 既有 pytest 用例无回归

## C. `EagleV2Client` smart folder 方法

- [ ] `smart_folder_list()` 存在于 [src/tripclipper/eagle_sync.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/eagle_sync.py) `EagleV2Client` 中
- [ ] `smart_folder_create(payload)` 存在，返回新建 folder id
- [ ] `smart_folder_update(folder_id, payload)` 存在，body 中含 `id` 字段
- [ ] 网络异常处理与既有方法一致（ConnectError → EagleUnavailableError；5xx → EagleClientError）
- [ ] 单测（httpx.MockTransport）：list/create/update/5xx 4 场景全过

## D. `MappingConfig` 与加载器扩展

- [ ] `SmartFolderRule` / `SmartFolderPreset` dataclass 存在且 frozen
- [ ] `MappingConfig.smart_folder_presets: tuple[SmartFolderPreset, ...]` 字段存在，默认值 `()`（保持向后兼容）
- [ ] `load_mapping_config` 从 default yaml 加载 5 条 preset（key: highlights/default_selected/excluded/needs_review/analysis_failed）
- [ ] override 合并按 `key` 全量替换
- [ ] override 中未见过 key 的 preset 追加到末尾
- [ ] icon_color 校验：非 `{red, orange, yellow, green, aqua, blue, purple, pink}` 抛 `ConfigError`
- [ ] `match` 校验：非 AND/OR 抛 `ConfigError`
- [ ] `rules` 空数组抛 `ConfigError`
- [ ] 单测：加载 / override 替换 / override 追加 / icon_color 非法 / match 非法 / rules 空 6 用例全过

## E. default yaml 补齐

- [ ] [src/tripclipper/templates/eagle_mapping.default.yaml](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/templates/eagle_mapping.default.yaml) 末尾含 `smart_folders:` 节
- [ ] 5 条 preset 的 `key` / `name` / `icon_color` / `match` / `rules` 与 [spec.md §What Changes 第 1 条](spec.md) 一致
- [ ] 每条 preset 都含 `tc:project:{project_slug}` 作为首条 rule（保证项目命名空间隔离）
- [ ] yaml 语法 `python -c "import yaml; yaml.safe_load(open('...'))"` 无报错

## F. `SmartFolderPlanner` 组件

- [ ] `SmartFolderWarning` / `SmartFolderReconcileResult` dataclass 存在
- [ ] `SmartFolderPlanner.__init__(client, presets, project_slug)` 签名正确
- [ ] `render_payload(preset)` 完成 `{project_slug}` 替换 + rules[].value wrap 成 array
- [ ] `render_conditions(preset)` 单独可用（供对账）
- [ ] `_conditions_equal` 忽略 rule 顺序，避免 unchanged→update 抖动
- [ ] `reconcile()` 只操作 name 以 `TC · ` 起头的 smart folder（不动用户手建）
- [ ] `reconcile()` 单条失败记 warning 不抛
- [ ] 单测 8 用例全过：render_payload_slug / render_payload_wrap / all_new / unchanged / update / ignore_user_smart_folders / single_failure_warning / conditions_equal_semantic

## G. `EagleApplyResult` schema 增量

- [ ] `SyncOptions.no_smart_folders: bool = False` 字段存在
- [ ] `EagleApplyResult.smart_folders: SmartFolderReconcileResult | None` 字段存在
- [ ] 序列化时 `smart_folders is None` → 输出 dict 不含此 key
- [ ] 序列化时非 None → 含 `created` / `updated` / `unchanged` / `warnings` 四个键
- [ ] 单测：None 时省略 / 非 None 时序列化 warning

## H. `EagleSyncRunner` 集成

- [ ] Runner 在 tag group 维护后、构造 result 前追加 smart folder 阶段
- [ ] `apply` 且未 aborted 且未 `--no-smart-folders` → 调 `SmartFolderPlanner.reconcile()`
- [ ] `apply` 且 aborted → 跳过 reconcile，写 `warnings=[{key:"_all", error:"skipped due to aborted sync"}]`
- [ ] `apply` + `--no-smart-folders` → 完全跳过；`result.smart_folders is None`
- [ ] `dry-run` → 不调 planner，`result.smart_folders is None`（CLI 层单独打印计划）
- [ ] `EagleUnavailable` 兜底：planner 阶段抛 EagleUnavailableError → 记 warning 不阻断
- [ ] 单测 4 用例全过：apply_runs_reconcile / dry_run_skips / no_smart_folders_skips / aborted_records_skip_warning

## I. CLI `sync-eagle` flag 与 stdout

- [ ] `--no-smart-folders` flag 存在，默认 `False`
- [ ] 该 flag 传入 `SyncOptions.no_smart_folders`
- [ ] `--dry-run` stdout 含 `Smart Folder 计划: 将建/更新 N 个（...）`
- [ ] `--apply`（无 warning）stdout 含 `✅ Smart Folder: N 个已就绪（新建 X / 更新 Y / 保持 Z）`
- [ ] `--apply`（有 warning）stdout 含 `⚠️ Smart Folder: N 个已就绪，M 个失败`
- [ ] `--apply --no-smart-folders` stdout 无 Smart Folder 相关行
- [ ] 单测 4 用例全过：apply_prints_summary / apply_with_warnings / no_smart_folders_omits / dry_run_prints_plan

## J. Eagle 版本要求提升

- [ ] `EagleV2Client.health_check()` 错误文案（若含 build 号）改为 "≥ 4.0 Build 22"
- [ ] [docs/specs/M6-eagle-sync/spec.md](file:///Users/bytedance/Documents/TripClipper_Trae/docs/specs/M6-eagle-sync/spec.md) header + Requirement 中版本号 Build 21 → Build 22（4 处以内）
- [ ] [docs/specs/M6-eagle-sync/check_list.md](file:///Users/bytedance/Documents/TripClipper_Trae/docs/specs/M6-eagle-sync/check_list.md) K 段版本号 Build 21 → Build 22（不改 L126 的 "Build 23" 用户机声明）
- [ ] 既有单测（如 test_health_check_v1_only 或类似）文案断言更新到 Build 22

## K. 项目级 override 契约

- [ ] `tripclipper.yaml` 中 `eagle_sync.mapping_overrides.smart_folders` 节可读
- [ ] override preset 按 `key` 全量替换 default 版本（字段级不做浅合并）
- [ ] override 中未在 default 声明的 key 追加到 preset 列表末尾
- [ ] 单测覆盖 replace / append 两种情况

## L. 幂等 reconcile 行为

- [ ] 首次 apply → 5 条 create
- [ ] 立刻重跑 apply → 5 条 unchanged，无 create/update
- [ ] 修改 override 后 apply → 对应 preset 走 update；其他 preset 保持 unchanged
- [ ] 用户手建的 smart folder（name 不以 `TC · ` 起头）不受影响
- [ ] 单条 create/update 失败 → warning 化，不阻断其他 preset

## M. dry-run 行为

- [ ] `--dry-run` 不调 `smart_folder_list` / `smart_folder_create` / `smart_folder_update` 中任何一个
- [ ] cut_index.json 与 Eagle 库均无变化
- [ ] stdout 打印计划行（除非 `--no-smart-folders`）

## N. 依赖

- [ ] 无新增第三方依赖（复用 M6 已引入的 httpx）
- [ ] `.venv/bin/python -c "import httpx"` 无异常（M6 已保证）

## O. demo-scan 端到端

- [ ] `test_apply_creates_five_default_smart_folders`：apply 后至少 5 次 smart_folder_create 调用；参数含 `TC · demo-scan · *` 5 个 name
- [ ] `test_reapply_smart_folder_reconcile_all_unchanged`：第二次 apply 无 create/update；unchanged 长度 5
- [ ] `test_project_override_triggers_update`：加 override 后第二次 apply 触发 update

## P. 错误处理

- [ ] Eagle 未启动：主同步已阻断，smart folder 阶段不会执行
- [ ] Eagle 版本 < Build 22：主同步已阻断，smart folder 阶段不会执行
- [ ] 主同步 aborted：smart folder 阶段跳过，warning 记 `_all`
- [ ] 单条 smart folder 失败：warning + 继续其他 preset

## Q. 人工视觉验收（用户主导 / Task 12，待用户）

- [ ] Eagle 版本 ≥ 4.0 Build 22 已确认
- [ ] `sync-eagle demo-scan --apply` 后：
  - [ ] stdout 含 `✅ Smart Folder: 5 个已就绪（新建 5 / 更新 0 / 保持 0）`
  - [ ] Eagle 侧栏"智能文件夹"分组下出现 5 个 name = `TC · demo-scan · *` 的 smart folder
  - [ ] 每个 smart folder 图标颜色与 default yaml 声明一致（highlights=green / excluded=red / needs_review=yellow / analysis_failed=orange / default_selected=blue）
  - [ ] 点击 `TC · demo-scan · 精选高光` → 只显示同时含 default_selected + highlight tag 的 items
  - [ ] 点击 `TC · demo-scan · 建议删除` → 只显示 excluded 的 items
  - [ ] `projects/demo-scan/eagle_apply_result.json.smart_folders.created` 含 5 个 name；`updated` / `unchanged` / `warnings` 均为空
- [ ] 立刻重跑 `--apply`：
  - [ ] stdout 含 `✅ Smart Folder: 5 个已就绪（新建 0 / 更新 0 / 保持 5）`
  - [ ] `smart_folders.unchanged` 含 5 个 name
- [ ] 加 override（highlights 换 name/icon）→ 重跑 `--apply`：
  - [ ] Eagle 中 highlights 对应 smart folder 被重命名 + icon 变色
  - [ ] `smart_folders.updated` 含该 name
- [ ] 手建 "我的收藏" → 重跑 `--apply` → 未被动
- [ ] `--apply --no-smart-folders`：
  - [ ] stdout 无 Smart Folder 相关行
  - [ ] `eagle_apply_result.json` 中无 `smart_folders` 段
- [ ] `--dry-run`：
  - [ ] stdout 含 `Smart Folder 计划: 将建/更新 5 个`
  - [ ] Eagle 侧栏 smart folder 无变化

## R. 验收终判

- [ ] 上述 A-P 全部勾选完成
- [ ] Q 段人工视觉验收签字通过
- [ ] [docs/specs/README.md](file:///Users/bytedance/Documents/TripClipper_Trae/docs/specs/README.md) 本 change 行状态更新为「已完成」
- [ ] [ADR-004](file:///Users/bytedance/Documents/TripClipper_Trae/docs/adr/ADR-004-eagle-sync-as-thin-mapping-layer.md) 与 [spec.md](spec.md) 无互相矛盾
