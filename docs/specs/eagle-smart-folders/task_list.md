# Tasks — Eagle Smart Folder 预设

> 阶段：实施前的有序工作清单。每项任务对应 [spec.md](spec.md) 中的一个或一组 Requirement。
> 实施纪律：与 M6 一致——纯函数单测 + Eagle V2 smart folder API 用 `httpx.MockTransport` 打桩 + CLI stdout 用 `CliRunner` 捕获断言；真实 Eagle 联调由用户主导（Task 12）。

## Task 列表

- [ ] Task 1：`EagleV2Client` 新增 3 个 smart folder 方法（spec §What Changes 第 4 条；ADDED §"sync-eagle --apply SHALL 在同步末尾..."的底层能力）
  - [ ] SubTask 1.1：在 [src/tripclipper/eagle_sync.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/eagle_sync.py) `EagleV2Client` 类中新增：
        - `smart_folder_list() -> list[dict]`：GET `/api/v2/smartFolder/get`；返回 `data` 字段（若 API 分页则拼接全部）
        - `smart_folder_create(payload: dict) -> str`：POST `/api/v2/smartFolder/create`；返回响应中 `data.id`
        - `smart_folder_update(folder_id: str, payload: dict) -> None`：POST `/api/v2/smartFolder/update`；payload 内含 `id` 字段（folder_id 参数与 payload["id"] 由方法内部合并，避免调用方误传）
        - 网络异常捕获与既有方法一致（`httpx.ConnectError` → `EagleUnavailableError`；HTTP 5xx → `EagleClientError`）
  - [ ] SubTask 1.2：单测 [tests/test_eagle_smart_folder.py](file:///Users/bytedance/Documents/TripClipper_Trae/tests/test_eagle_smart_folder.py)（httpx.MockTransport）：
        - `test_smart_folder_list_returns_data_array` → mock 返回标准 JSend 格式，断言解析出 dict 列表
        - `test_smart_folder_list_empty` → mock 返回 `data: []`，断言返回空列表
        - `test_smart_folder_create_returns_id` → mock 返回 `{"status":"success","data":{"id":"SF_UUID"}}`，断言返回 `"SF_UUID"`
        - `test_smart_folder_create_5xx_raises` → mock 返回 500，断言抛 `EagleClientError`
        - `test_smart_folder_update_sends_id_in_body` → 传 folder_id="XX", payload={"name":"..."}；断言 request body 含 `"id": "XX"`
        - `test_smart_folder_update_no_return` → mock 返回 200 无 data，断言方法无异常返回

- [ ] Task 2：`MappingConfig` 扩展 `smart_folder_presets`（spec §What Changes 第 2、3 条；ADDED §"Smart Folder 预设 SHALL 支持项目级 override"）
  - [ ] SubTask 2.1：在 [eagle_sync.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/eagle_sync.py) 定义：
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
            icon_color: str | None
            match: Literal["AND", "OR"]
            rules: tuple[SmartFolderRule, ...]
        ```
  - [ ] SubTask 2.2：在既有 `MappingConfig` 中新增字段：
        ```python
        smart_folder_presets: tuple[SmartFolderPreset, ...] = ()
        ```
        （放在类末尾，加默认值 `()` 保持向后兼容——现有 M6 单测构造 MappingConfig 不写此字段仍可跑）
  - [ ] SubTask 2.3：修改 `load_mapping_config` 加载 `smart_folders:` 节：
        - 从 default yaml 读 `smart_folders`，逐条构造 `SmartFolderPreset`
        - `rules[].value` 若为标量 str，直接用；若为 list（用户显式写数组），取首元素并 warning "本 change 阶段仅支持标量 value"
        - 校验 `match ∈ {"AND", "OR"}`；`rules` 非空；`icon_color` 若非 None 需 ∈ 官方枚举 `{red, orange, yellow, green, aqua, blue, purple, pink}`；违反抛 `ConfigError`
  - [ ] SubTask 2.4：override 合并逻辑：
        ```python
        # in load_mapping_config
        default_presets = [...]  # from default yaml
        override_presets = project_overrides.get("smart_folders", []) if project_overrides else []
        by_key = {p["key"]: SmartFolderPreset(...) for p in default_presets}
        for op in override_presets:
            by_key[op["key"]] = SmartFolderPreset(...)  # 全量替换
        # 保持顺序：先 default 声明顺序 → 再 override 中 default 里没有的 key
        merged = [by_key[p["key"]] for p in default_presets] + \
                 [by_key[op["key"]] for op in override_presets if op["key"] not in {p["key"] for p in default_presets}]
        ```
  - [ ] SubTask 2.5：补测 [tests/test_eagle_mapping.py](file:///Users/bytedance/Documents/TripClipper_Trae/tests/test_eagle_mapping.py)：
        - `test_load_default_smart_folders` → 断言默认加载 5 条 preset，key 分别为 highlights/default_selected/excluded/needs_review/analysis_failed
        - `test_smart_folder_override_replaces_by_key` → override highlights 的 icon_color=purple → 断言 key=highlights 的 preset.icon_color==purple，其他 4 条不变
        - `test_smart_folder_override_appends_new_key` → override 声明 key=extreme_wide → 断言合并后有 6 条，末尾是 extreme_wide
        - `test_smart_folder_invalid_icon_color_rejected` → yaml 里 icon_color=magenta → 抛 `ConfigError`
        - `test_smart_folder_invalid_match_rejected` → match=XOR → 抛 `ConfigError`
        - `test_smart_folder_empty_rules_rejected` → rules=[] → 抛 `ConfigError`

- [ ] Task 3：更新 default yaml（spec §What Changes 第 1 条）
  - [ ] SubTask 3.1：在 [src/tripclipper/templates/eagle_mapping.default.yaml](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/templates/eagle_mapping.default.yaml) 末尾追加 `smart_folders:` 节，5 条完整 preset（内容见 spec §What Changes 第 1 条）
  - [ ] SubTask 3.2：yaml 加载后 `python -c "import yaml; ..."` 冒烟检查——确保 yaml 语法正确、5 条 preset 都能加载

- [ ] Task 4：`SmartFolderPlanner` 组件（spec §What Changes 第 5 条；ADDED §"sync-eagle --apply SHALL..."/§"Smart folder 阶段失败..."/§"用户手建的 smart folder 不动"）
  - [ ] SubTask 4.1：在 [eagle_sync.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/eagle_sync.py) 定义：
        ```python
        @dataclass
        class SmartFolderWarning:
            key: str
            name: str
            error: str

        @dataclass
        class SmartFolderReconcileResult:
            created: list[str] = field(default_factory=list)
            updated: list[str] = field(default_factory=list)
            unchanged: list[str] = field(default_factory=list)
            warnings: list[SmartFolderWarning] = field(default_factory=list)
        ```
  - [ ] SubTask 4.2：实现 `class SmartFolderPlanner`：
        - `__init__(client: EagleV2Client, presets: tuple[SmartFolderPreset, ...], project_slug: str)`
        - `render_payload(preset: SmartFolderPreset) -> dict`：
          - 把 preset.name 中 `{project_slug}` 替换为实际 slug
          - 把每条 rule.value 中 `{project_slug}` 替换为实际 slug
          - 返回 Eagle API payload（rules[].value wrap 成 `[value]`）
        - `render_conditions(preset: SmartFolderPreset) -> list[dict]`：仅返回 `conditions` 段（供对账用）
        - `_conditions_equal(existing: list[dict], target: list[dict]) -> bool`：语义相等判断
          - 忽略字段顺序：把每条 rule 转成 `(property, method, tuple(value))` 后排序比较
          - `match` 字段直接比较
        - `reconcile() -> SmartFolderReconcileResult`：
          1. `existing = client.smart_folder_list()`
          2. 建 `existing_by_name = {sf["name"]: sf for sf in existing if sf["name"].startswith("TC · ")}`
          3. 遍历 presets：
             - `target_name = preset.name.format(project_slug=self.project_slug)`
             - `target_conditions = self.render_conditions(preset)`
             - 若 target_name in existing_by_name:
               - 若 conditions 语义相等 → result.unchanged.append(target_name)
               - 否则 → 调 `smart_folder_update`；成功 → result.updated.append(target_name)；失败 → result.warnings.append(...)
             - 否则 → 调 `smart_folder_create`；成功 → result.created.append(target_name)；失败 → result.warnings.append(...)
  - [ ] SubTask 4.3：单测（追加到 [tests/test_eagle_smart_folder.py](file:///Users/bytedance/Documents/TripClipper_Trae/tests/test_eagle_smart_folder.py)）：
        - `test_render_payload_substitutes_slug` → preset name/rules 含 `{project_slug}` → 断言 payload 中已替换
        - `test_render_payload_wraps_value_as_array` → 断言 rules[].value 是 `["tc:project:demo-scan"]`
        - `test_reconcile_all_new_creates` → mock existing=[]（或全非 TC·）→ 断言全部走 create；result.created 长度==preset 数
        - `test_reconcile_unchanged_when_conditions_match` → mock existing 中含同名同 conditions → 断言不调 update；result.unchanged 含该 name
        - `test_reconcile_update_when_conditions_differ` → mock existing 同名但 rules 少一条 → 断言调 update；result.updated 含该 name
        - `test_reconcile_ignores_user_smart_folders` → mock existing 含 name="我的收藏" → 断言 planner 不动它；result 中不含该 name
        - `test_reconcile_single_failure_becomes_warning` → mock create 对第 2 条抛错 → 断言其他 4 条继续；warnings 含 1 条
        - `test_conditions_equal_semantic_ignores_order` → 两组 rules 顺序不同 → 断言判定相等（避免 unchanged → update 的抖动）

- [ ] Task 5：`EagleApplyResult` schema 增量与 `SyncOptions.no_smart_folders`（spec §What Changes 第 6、7 条）
  - [ ] SubTask 5.1：修改 `SyncOptions`（在 [eagle_sync.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/eagle_sync.py)）：
        ```python
        @dataclass
        class SyncOptions:
            # ... 既有字段 ...
            no_smart_folders: bool = False
        ```
  - [ ] SubTask 5.2：修改 `EagleApplyResult`：
        ```python
        @dataclass
        class EagleApplyResult:
            # ... 既有字段 ...
            smart_folders: SmartFolderReconcileResult | None = None  # None 表示跳过（--no-smart-folders）
        ```
  - [ ] SubTask 5.3：`EagleApplyResult` 序列化时（若既有 `to_dict()` / `.model_dump()` / json.dumps default）：
        - `smart_folders is None` → 输出 dict 中不含此 key
        - 否则 → 输出 `{"created": [...], "updated": [...], "unchanged": [...], "warnings": [{...}, ...]}`
  - [ ] SubTask 5.4：单测：`test_result_omits_smart_folders_when_none` / `test_result_serializes_smart_folder_warnings`

- [ ] Task 6：`EagleSyncRunner` 集成 smart folder 阶段（spec §What Changes 第 6 条；ADDED §"主同步 aborted 时跳过 smart folder 阶段"）
  - [ ] SubTask 6.1：`EagleSyncRunner.__init__` 参数扩展：接受 `mapper` 时同时能拿到 `MappingConfig.smart_folder_presets`（若既有构造已传 config，无需改 signature）
  - [ ] SubTask 6.2：`run()` 方法在 tag group 维护之后、构造 `EagleApplyResult` 之前追加：
        ```python
        smart_folders_result = None
        if self.options.apply and not aborted and not self.options.no_smart_folders:
            planner = SmartFolderPlanner(self.client, self.config.smart_folder_presets, self.project_slug)
            try:
                smart_folders_result = planner.reconcile()
            except EagleUnavailableError:
                # planner 内部已 warning 化的失败不会抛到这里；这里只兜底 EagleUnavailable
                smart_folders_result = SmartFolderReconcileResult(
                    warnings=[SmartFolderWarning(key="_all", name="", error="Eagle unavailable during smart folder stage")]
                )
        elif self.options.apply and aborted and not self.options.no_smart_folders:
            smart_folders_result = SmartFolderReconcileResult(
                warnings=[SmartFolderWarning(key="_all", name="", error="skipped due to aborted sync")]
            )
        # dry-run: 不填 smart_folders_result（保持 None）；CLI 层单独打印计划
        ```
  - [ ] SubTask 6.3：把 `smart_folders_result` 塞入 `EagleApplyResult`
  - [ ] SubTask 6.4：`EagleSyncRunner` 需要知道 `project_slug`——若既有构造已传，复用；否则从 `AssetMapper` 或参数拿
  - [ ] SubTask 6.5：补测 [tests/test_eagle_sync_runner.py](file:///Users/bytedance/Documents/TripClipper_Trae/tests/test_eagle_sync_runner.py)：
        - `test_apply_runs_smart_folder_reconcile` → mock client 全成功 → 断言 planner 被调用；result.smart_folders 非 None
        - `test_dry_run_skips_smart_folder_reconcile` → apply=False → 断言 planner 未被调用；result.smart_folders is None
        - `test_no_smart_folders_flag_skips_stage` → SyncOptions.no_smart_folders=True → 断言 planner 未被调用；result.smart_folders is None（序列化后无 smart_folders 字段）
        - `test_aborted_sync_records_smart_folder_skip_warning` → 5 连败 aborted=True → 断言 result.smart_folders.warnings 含 `key="_all", error="skipped due to aborted sync"`；planner 未被调 create/update

- [ ] Task 7：CLI `sync-eagle` 加 `--no-smart-folders` flag + stdout 摘要（spec §What Changes 第 8、9 条；ADDED §"--no-smart-folders SHALL 完全跳过..."/§"dry-run SHALL 打印计划..."）
  - [ ] SubTask 7.1：在 [src/tripclipper/cli.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/cli.py) `sync-eagle` 命令加 `@click.option("--no-smart-folders", is_flag=True, default=False, help="跳过 smart folder 维护阶段")`
  - [ ] SubTask 7.2：把 flag 传入 `SyncOptions.no_smart_folders`
  - [ ] SubTask 7.3：`--dry-run` 分支在既有摘要行之后打印：
        ```
        Smart Folder 计划: 将建/更新 {N} 个（干跑不连库对账，实际执行时按 name 幂等 reconcile）
        ```
        （N = 已加载的 preset 数量）
        `--no-smart-folders` + `--dry-run` 组合时不打印此行
  - [ ] SubTask 7.4：`--apply` 分支（未 aborted）在既有摘要行之后打印：
        ```
        ✅ Smart Folder: {ready} 个已就绪（新建 {created} / 更新 {updated} / 保持 {unchanged}）
        ```
        若 `warnings` 非空：
        ```
        ⚠️ Smart Folder: {ready} 个已就绪，{failed} 个失败（详见 eagle_apply_result.json）
        ```
        `--no-smart-folders` 时不打印任何 smart folder 相关行
  - [ ] SubTask 7.5：补测 [tests/test_cli_sync_eagle.py](file:///Users/bytedance/Documents/TripClipper_Trae/tests/test_cli_sync_eagle.py)：
        - `test_apply_prints_smart_folder_summary` → 断言 stdout 含 "Smart Folder: 5 个已就绪"
        - `test_apply_with_warnings_prints_warning_line` → mock 1 条 warning → 断言 stdout 含 "1 个失败"
        - `test_no_smart_folders_flag_omits_summary` → --no-smart-folders → stdout 不含 "Smart Folder"
        - `test_dry_run_prints_plan_line` → --dry-run → stdout 含 "Smart Folder 计划: 将建/更新 5 个"

- [ ] Task 8：Eagle 版本要求提升到 Build 22（spec §What Changes 第 10 条；MODIFIED §"M6 SHALL 仅支持 Eagle V2 Web API"）
  - [ ] SubTask 8.1：修改 [eagle_sync.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/eagle_sync.py) 中 `EagleV2Client.health_check()` 版本判定文案：所有 "≥ 4.0 Build 21" → "≥ 4.0 Build 22"（若 health_check 未实际检 build number 只检 V2 endpoint 存在，仅改文案；若检了 build number，把阈值从 21 改到 22）
  - [ ] SubTask 8.2：修改 [docs/specs/M6-eagle-sync/spec.md](file:///Users/bytedance/Documents/TripClipper_Trae/docs/specs/M6-eagle-sync/spec.md) 中 4 处版本文案：header L6、Requirement §"M6 SHALL 仅支持 Eagle V2 Web API"（Build 21 → Build 22）
  - [ ] SubTask 8.3：修改 [docs/specs/M6-eagle-sync/check_list.md](file:///Users/bytedance/Documents/TripClipper_Trae/docs/specs/M6-eagle-sync/check_list.md) K 段：3 处 "≥ 4.0 Build 21" → "≥ 4.0 Build 22"（不改 L126 的"≥ 4.0 Build 23"用户机声明）
  - [ ] SubTask 8.4：更新既有单测 `test_health_check_v1_only` 及类似 → 断言错误文案含 "Build 22"

- [ ] Task 9：demo-scan E2E 测试（spec §验收口径 步骤 2、3）
  - [ ] SubTask 9.1：补测 [tests/test_eagle_sync_demo_scan.py](file:///Users/bytedance/Documents/TripClipper_Trae/tests/test_eagle_sync_demo_scan.py)：
        - `test_apply_creates_five_default_smart_folders` → apply on demo-scan → 断言 mock client 收到 5 次 smart_folder_create 调用；调用参数含 `TC · demo-scan · *` 5 个 name
        - `test_reapply_smart_folder_reconcile_all_unchanged` → 先 apply 一次，把 create 请求录成 fixture，第二次 apply 时 mock smart_folder_list 返回该 fixture → 断言无 create/update 调用；result.smart_folders.unchanged 长度==5
        - `test_project_override_triggers_update` → 加载 override（highlights 的 icon_color=purple）→ 第二次 apply → 断言 smart_folder_update 被调 1 次

- [ ] Task 10：文档 & ADR 更新（spec §What Changes 影响的代码 · 文档段）
  - [ ] SubTask 10.1：更新 [docs/specs/README.md](file:///Users/bytedance/Documents/TripClipper_Trae/docs/specs/README.md) 模块索引：在 M6 行下方追加 本 change 行：
        ```
        | eagle-smart-folders | Eagle Smart Folder 预设 | FR-9/FR-10 视图层增强 | M6 | 定稿（待用户审）|
        ```
  - [ ] SubTask 10.2：更新 [docs/adr/ADR-004-eagle-sync-as-thin-mapping-layer.md](file:///Users/bytedance/Documents/TripClipper_Trae/docs/adr/ADR-004-eagle-sync-as-thin-mapping-layer.md)：
        - 在 §决策 · 二 (Eagle 版本与布局) 之后新增一小节 §"Smart Folder as user-facing view layer"：
          - 声明 Smart Folder 是"保存的查询规则"，不是物理 folder，不与 §一 flat 布局决策冲突
          - 声明 本 change 兑现 §退出条件第二条（"用户反馈打开 Eagle 后总要花时间筛/配 smart folder"）
          - 引用 本 change spec
        - 或在 §关联文档追加 本 change spec 链接（选一种即可，避免文档过长）
  - [ ] SubTask 10.3：更新 [docs/specs/M6-eagle-sync/spec.md](file:///Users/bytedance/Documents/TripClipper_Trae/docs/specs/M6-eagle-sync/spec.md) §"与未来模块的边界" 追加：
        ```
        - **Eagle Smart Folder 预设**：M6 --apply 结束后自动维护一批 smart folder 作为"用户友好视图层"，不改 tag 命名与字段映射。详见 [eagle-smart-folders spec](../eagle-smart-folders/spec.md)。
        ```
  - [ ] SubTask 10.4：确认 [CONTEXT.md](file:///Users/bytedance/Documents/TripClipper_Trae/CONTEXT.md) 是否需要新增术语（"Smart Folder Preset"）；本 change 尽量不动，若需要仅加一行

- [ ] Task 11：回归验证
  - [ ] SubTask 11.1：`.venv/bin/python -m pytest tests/ --ignore=tests/test_integration_m3.py --ignore=tests/test_integration_m4.py -x` 全通过
  - [ ] SubTask 11.2：M0~M6 既有单测无回归（重点关注：`test_health_check_v1_only` 文案改动 / `MappingConfig` 构造是否被上游用例破坏）
  - [ ] SubTask 11.3：`.venv/bin/python -c "from tripclipper.eagle_sync import SmartFolderPlanner, SmartFolderPreset, SmartFolderReconcileResult"` 无 import 错

- [ ] Task 12：人工端到端验收（用户主导）
  - [ ] SubTask 12.1：确认 Eagle 版本 ≥ 4.0 Build 22
  - [ ] SubTask 12.2：跑 `.venv/bin/tripclipper sync-eagle demo-scan --apply`：
        - stdout 含 `✅ Smart Folder: 5 个已就绪（新建 5 / 更新 0 / 保持 0）`
        - Eagle 侧栏"智能文件夹"分组下出现 5 个 name = `TC · demo-scan · *` 的 smart folder
        - 每个 smart folder 点开后，右侧素材区能看到符合 rule 的 items
        - `projects/demo-scan/eagle_apply_result.json.smart_folders.created` 含 5 个 name
  - [ ] SubTask 12.3：立刻重跑 `--apply`：
        - stdout 含 `✅ Smart Folder: 5 个已就绪（新建 0 / 更新 0 / 保持 5）`
        - `smart_folders.unchanged` 含 5 个 name
  - [ ] SubTask 12.4：在 `projects/demo-scan/tripclipper.yaml` 加 override（highlights 换 name/icon）→ 重跑 `--apply`：
        - Eagle 中 highlights 对应 smart folder 被更新
        - `smart_folders.updated` 含该 name
  - [ ] SubTask 12.5：在 Eagle 手工建 name="我的收藏" smart folder → 重跑 `--apply` → 该 folder 未被动
  - [ ] SubTask 12.6：跑 `--apply --no-smart-folders`：
        - stdout 无 Smart Folder 摘要行
        - `eagle_apply_result.json` 中无 `smart_folders` 段
  - [ ] SubTask 12.7：跑 `--dry-run`：
        - stdout 含 `Smart Folder 计划: 将建/更新 5 个`
        - Eagle 侧栏 smart folder 无变化

## Task Dependencies

- Task 1（EagleV2Client 底层）在最前
- Task 2（MappingConfig）依赖 Task 1？→ 不依赖，dataclass 层可独立；但 Task 2 的单测最好在 Task 1 之后
- Task 3（default yaml）与 Task 2 强耦合，一起做
- Task 4（Planner）依赖 Task 1、2、3
- Task 5（Result/Options 扩展）与 Task 6 一起做，Task 6 依赖 Task 4、5
- Task 7（CLI）依赖 Task 6
- Task 8（版本文案）与 Task 1-7 独立，可并行
- Task 9（E2E）依赖 Task 1-7 全部完成
- Task 10（文档）在 Task 1-9 之后
- Task 11（回归）在 Task 1-10 之后
- Task 12（人工验收）在 Task 1-11 全部完成 + 用户 Eagle 环境就绪

## 实施建议顺序

1. **底座**：Task 1（Client）→ Task 2（Config）→ Task 3（yaml）→ 各自单测
2. **核心**：Task 4（Planner）→ Task 5（Result 扩展）→ Task 6（Runner 集成）→ 各自单测
3. **CLI 与 E2E**：Task 7（CLI）→ Task 9（demo-scan E2E）
4. **配套**：Task 8（版本文案）
5. **收尾**：Task 10（文档）→ Task 11（回归）
6. **验收**：Task 12（用户主导）
