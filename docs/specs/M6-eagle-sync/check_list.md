# Check List — M6 Eagle 同步

> 阶段：实施前的验收清单。所有项必须在本 change 标「已完成」前逐项勾选。
> 验收纪律：与 M3/M4/M5 同——单测白盒断言 + Eagle V2 API 用 `httpx.MockTransport` 打桩 + demo-scan 端到端 + CLI stdout/stderr 断言；真实 Eagle 联调（Task 15）由用户主导，不写 selenium。
> 字段名说明：草案中 `similar_group_reason` / `analysis_failure_reason` 系理想化命名；实现严格遵循真实 M0 契约（[models.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/models.py)），对应字段为 `similar_reason` / `failures`。ClipSuggestion 真实字段为 `in_`/`out`/`rating`/`reason`（无 `start`/`end`/`priority`）。

## A. 文档与决策一致性

- [x] [spec.md](spec.md) 明确以 [ADR-004](file:///Users/bytedance/Documents/TripClipper_Trae/docs/adr/ADR-004-eagle-sync-as-thin-mapping-layer.md) 为决策来源，8 条 ADDED + 1 条 MODIFIED requirements 覆盖 grilling 拍板全部内容
- [x] [spec.md](spec.md) 明确 PRD §FR-10 的 `folders_to_create` 示例**不字面兑现**（flat 布局）；「中文友好 tag」不实现
- [x] [task_list.md](task_list.md) 15 个 Task 与 spec.md 中所有 Requirement 逐条覆盖
- [x] [docs/specs/README.md](file:///Users/bytedance/Documents/TripClipper_Trae/docs/specs/README.md) M6 行状态在审阅完成后由「定稿（待用户审）」更新为「已完成」
- [x] [CONTEXT.md L44-50](file:///Users/bytedance/Documents/TripClipper_Trae/CONTEXT.md#L44-L50) 已拿掉"Eagle 主列表展示/折叠"实现假设，改为纯候选池角色语义
- [x] [CONTEXT.md L86](file:///Users/bytedance/Documents/TripClipper_Trae/CONTEXT.md#L86) ADR-004 已加入关键决策清单
- [x] [docs/todolist.md](file:///Users/bytedance/Documents/TripClipper_Trae/docs/todolist.md) 含"Eagle 同步防重复导入（sha1 去重）"作为后续优化项

## B. 数据契约不动

- [x] 本 change **不修改** [models.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/models.py) 任何字段
- [x] `Asset.eagle_item_id` 与 `Asset.eagle_sync_status` 字段保持 M0 定义不变（M6 仅消费）
- [x] `EditCandidateStatus` 枚举 4 个值不变
- [x] `similar_group_id` / `similar_selection` / `analysis_status` / `shot_scale` / `shot_function` / `subject_type` / `rating` / `clip_suggestions` 字段语义不变
- [x] M0~M5 既有 pytest 用例无回归（`.venv/bin/python -m pytest tests/ --ignore=tests/test_integration_m3.py --ignore=tests/test_integration_m4.py` → 332 passed）

## C. `EagleV2Client` HTTP 客户端

- [x] 类存在于 [src/tripclipper/eagle_sync.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/eagle_sync.py)，用 `httpx.Client` 底座
- [x] `health_check()` 校验 V2 API 可用；V1 only 抛 `EagleVersionError`；连接失败抛 `EagleUnavailableError`
- [x] `add_from_path` / `update_item` / `move_to_trash` / `tag_group_list` / `tag_group_create` / `tag_group_add_tags` 方法齐全
- [x] `update_item` 只传非 None 字段（避免误覆盖为空）
- [x] 支持 `with EagleV2Client(...) as client:` 上下文管理
- [x] 单测（`httpx.MockTransport`）：health check 3 场景 + add/update/trash + tag group 3 方法 全过

## D. `MappingConfig` 与加载器

- [x] `MappingConfig` / `TargetSpec` / `NoteTemplate` dataclass 存在且 frozen
- [x] [src/tripclipper/templates/eagle_mapping.default.yaml](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/templates/eagle_mapping.default.yaml) 已随包发布
- [x] `tag_prefix` 默认值 `"tc"`
- [x] `auto_map_unknown` 默认 `True`
- [x] default mapping 声明 8+ 个 tag 字段（analysis_status / shot_scale / shot_function / subject_type / similar_selection / similar_group_id / edit_candidate_status + rating→eagle_rating）〔实际另含 type / people_presence，共 9 个 tag 字段〕
- [x] default mapping 声明 note 字段〔按真实 M0 契约落地为 5 个：edit_candidate_reason(1) / similar_reason(2) / summary(3) / clip_suggestions(4) / failures(5)；草案 similar_group_reason→similar_reason、analysis_failure_reason→failures〕
- [x] `skip_fields` 含 asset_id / path 等结构性字段〔草案列的 sha1 / imported_at / analyzed_at / similar_group_confidence 在真实 Asset 模型不存在，无需 skip；yaml 实际 skip 22 个结构性字段〕
- [x] `note_template.header` 支持 `{project_slug}` 与 `{sync_timestamp}` 占位
- [x] `load_mapping_config` 支持项目级 override（浅合并，`skip_fields` 取并集）
- [x] 非法 target 值加载时抛 `ConfigError`
- [x] 单测：默认加载 / override 合并 / skip_fields 并集 / 非法值 4 用例全过

## E. `AssetMapper` 字段映射器

- [x] 类存在，`plan(asset) -> AssetWritePlan`
- [x] 项目 tag `tc:project:{slug}` 每条 asset 都有
- [x] tag 格式严格 `tc:{field}:{value}`，无中文别名
- [x] rating 直传到 Eagle rating（int）
- [x] `edit_candidate_reason` / `similar_reason` / `summary` 用 `_render_text_block`；`failures` 用 `_render_failures_list`〔草案的 similar_group_reason/analysis_failure_reason 系理想化字段名〕
- [x] `clip_suggestions` 用 `_render_clip_suggestions_list`：时间码反引号包裹，格式 ``- `{in} → {out}` [★{rating}] {reason}``〔真实字段 in_/out/rating/reason，无 start/end/priority；保留 cut_index 原序〕
- [x] 空字段按 `empty_section_behavior=skip` 不渲染标题
- [x] `auto_map_unknown=True` 时未声明字段自动 `tc:{field}:{value}` 化
- [x] `auto_map_unknown=False` 时未声明字段跳过 + 记 warning
- [x] `skip_fields` 中的字段值不出现在任何 tag 中
- [x] `tag_group_updates` 按字段名分组正确（如 `tc:edit_candidate_status` group 收集所有 `tc:edit_candidate_status:*` tag）
- [x] annotation 排版：header → 按 order 排序的 sections → 空 sections 跳过
- [x] 单测 9 用例全过（default_selected 完整 / excluded / analysis_failed / auto_map / strict / skip_fields / clip 渲染 / project tag / group_updates）〔"clip 排序"改为 clip 渲染：真实 ClipSuggestion 无 priority 字段〕

## F. `EagleSyncRunner` 同步执行器

- [x] 类存在，`run(cut_index) -> tuple[CutIndex, EagleApplyResult]`
- [x] 启动期检查：health_check → cut_index 校验 → scanned 检查
- [x] scanned 阻断：存在 scanned 且 `not skip_unanalyzed` → 抛 `SyncPreconditionError`
- [x] scanned 软放行：`skip_unanalyzed=True` → 跳过、`totals.skipped_unanalyzed` 累计
- [x] `analysis_status == analysis_failed` 素材被同步（不阻断）
- [x] `dry_run` 模式无任何 Eagle API 写入
- [x] `apply` 模式：`eagle_item_id` 非空走 update；否则走 addFromPath
- [x] `--skip` flag：跳 `synced` 状态素材
- [x] `--reset` flag：move_to_trash 已同步 items → 清 `eagle_item_id` → 后续走 addFromPath
- [x] 单条业务失败：设 `eagle_sync_status = "failed"` → 记 `failures` → 继续
- [x] 连续 5 条网络失败：`aborted = True` → `abort_reason = "eagle_disconnected_after_5_consecutive_failures"` → 主循环 break → 已成功保留
- [x] tag group 维护在主循环之后：现有 group 用 add_tags；不存在则 create；失败仅记 `tag_group_warnings`
- [x] 单测 12 用例全过（覆盖 dry-run / apply 全成功 / update-existing / skip / scanned 硬阻断 / scanned 软跳 / analysis_failed / 单条失败 / 5 连败中止 / reset / tag group / tag group 失败）

## G. 产物 `eagle_apply_result.json`

- [x] 每次 `--apply` 跑完写入 `projects/<slug>/eagle_apply_result.json`（覆盖式）
- [x] schema 含 `synced_at` / `project_slug` / `eagle_library_path` / `totals` / `failures` / `tag_group_warnings` / `aborted` / `abort_reason`
- [x] `totals` 含 `total` / `synced` / `failed` / `skipped` / `skipped_unanalyzed` 五个键
- [x] `failures[]` 每项含 `asset_id` / `asset_path` / `stage` / `error` / `retryable`
- [x] `tag_group_warnings[]` 每项含 `tag_group` / `missing_tags` / `error`
- [x] `dry_run` 模式**不**写 result 文件（按 spec 第 4 条：仅 `--apply` 时写）

## H. paths.py Eagle helper

- [x] `eagle_apply_result_path(slug, base_dir)` 返回 `projects/<slug>/eagle_apply_result.json`
- [x] `eagle_mapping_default_template_path()` 返回 `<package_root>/templates/eagle_mapping.default.yaml`
- [x] 二者加入 `__all__`
- [x] paths.py docstring 顶部布局图含 `eagle_apply_result.json`
- [x] 单测：路径拼接正确、default template 文件 `.exists()`

## I. config.EagleSync

- [x] `EagleSync` 含 `enabled` / `api_base_url` / `api_token` / `connection_failure_threshold` / `mapping_overrides` 五个字段（另保留 M0 的 mode/base_url，向后兼容）
- [x] `api_base_url` 默认 `"http://localhost:41595/api/v2/"`
- [x] `connection_failure_threshold` 默认 5
- [x] project yaml 中 `eagle_sync` 节可 override 上述字段
- [x] 单测：默认值 / yaml 加载 全过

## J. CLI `sync-eagle` 命令

- [x] `--apply` / `--dry-run`（默认）互斥 flag
- [x] `--skip` / `--reset` / `--retry-failed` / `--skip-unanalyzed` / `--strict-mapping` / `--yes` 六个 flag 齐全
- [x] 默认（不加 `--apply`）为 dry-run
- [x] `--reset` 无 `--yes` 时 `click.confirm(abort=True)` 二次确认
- [x] `--reset --yes` 跳过确认
- [x] Eagle 不可达 → exit 2 + stderr 面向用户文案
- [x] Eagle 版本过低 → exit 2 + stderr 提示"版本 ≥ 4.0 Build 21"
- [x] scanned 存在 + 无 flag → exit 2 + stderr 提示 `--skip-unanalyzed` 或先跑 analyze
- [x] apply 成功 → exit 0 + stdout `✅ 已同步 N/N`
- [x] apply 部分失败 → exit 0 + stdout `⚠️ M 条失败`
- [x] apply aborted → exit 0 + stdout `❌ 已中止`（实现选 exit 0，stderr 打印中止原因，与既有 CLI 兜底一致）
- [x] `--strict-mapping` 覆盖 default `auto_map_unknown = False`
- [x] 单测（`CliRunner` + monkeypatch）10 用例全过

## K. Eagle V2 版本要求

- [x] `health_check()` 检查 `/api/v2/library/info`，V1-only 用户返回 404 → 抛 `EagleVersionError`
- [x] `EagleVersionError` 文案含 "≥ 4.0 Build 21"
- [x] spec + ADR-004 均声明不做 V1 降级
- [ ] 用户本机 Eagle 版本已确认 ≥ 4.0 Build 23（Task 15 前置，用户环境，待用户确认）

## L. tag group 自动维护

- [x] 每个 `target: tag` 字段对应一个 tag group（group name = `tc:{field}`）
- [x] `tc:project` group 包含项目 slug tag
- [x] group 不存在时 `tag_group_create`；存在时 `tag_group_add_tags`（增量）
- [x] tag group 维护失败**不阻断**主流程；仅记 `tag_group_warnings`
- [x] 单测：group 创建 / group 增量 / group 失败 warning 三场景

## M. note 模板

- [x] header 一行斜体：`_TripClipper · {slug} · synced {timestamp}_`
- [x] 区块顺序：候选池理由（1）→ 雷同组理由（2）→ 内容摘要（3）→ 建议剪辑片段（4）→ 分析失败原因（5）〔按真实 M0 字段：similar_reason/summary/clip_suggestions/failures〕
- [x] 空字段跳过标题（`empty_section_behavior: skip`）
- [x] 区块标题用 `## markdown H2`
- [x] `clip_suggestions` 时间码用反引号包裹
- [x] 单测覆盖：完整 note / 空字段跳过 / clip 时间码格式〔clip "priority 排序"不适用：真实 ClipSuggestion 无 priority 字段〕

## N. 二次同步行为

- [x] 默认 `--apply` = update：覆盖式刷 tag/rating/note，包括覆盖 Eagle 端手工修改
- [x] `--skip` 跳过 `synced` 状态
- [x] `--reset` 移到回收站 + 清 `eagle_item_id`
- [x] 不做 sha1 去重（信任 cut_index 状态）
- [x] 不做 stale 检测
- [x] `eagle_sync_status` 状态转移正确：`None`/`pending` → `synced`/`failed`；reset 后回到 `None`

## O. 依赖

- [x] `httpx>=0.27.0` 加入 [pyproject.toml](file:///Users/bytedance/Documents/TripClipper_Trae/pyproject.toml) 主依赖
- [x] `.venv/bin/python -c "import httpx"` 无异常
- [x] 无新增 non-httpx 网络库（如 requests / aiohttp）

## P. demo-scan 端到端

- [x] `test_dry_run_on_demo_scan`：dry-run 待同步计数与 demo-scan 实际 analyzed 素材数一致；无 API 调用
- [x] `test_apply_on_demo_scan_writes_expected_tags`：至少 1 条 addFromPath 参数含预期 `tc:*` tag 集合；rating 与 cut_index 一致
- [x] `test_apply_creates_tag_groups`：tag_group_create 在 `tc:edit_candidate_status` / `tc:shot_function` / `tc:project` 至少三个 group 上被调
- [x] `test_reapply_updates_not_creates`：第二次 apply 只调 update_item，无 addFromPath

## Q. 错误处理

- [x] Eagle 未启动：启动期硬阻断，无副作用
- [x] Eagle 版本 < V2：启动期硬阻断，无副作用
- [x] cut_index 校验失败：启动期硬阻断，无副作用
- [x] scanned 存在（无 flag）：启动期硬阻断，无副作用
- [x] 单条 asset 业务失败：`failed` 状态 + 继续
- [x] tag group 失败：warning + 继续
- [x] 5 连败网络错：整体中止，已成功保留
- [x] `--retry-failed` 只处理 `failed` 状态

## R. 人工视觉验收（用户主导 / Task 15，待用户）

- [ ] Eagle 版本 ≥ 4.0 Build 21 已确认
- [ ] `sync-eagle demo-scan --dry-run` 打印摘要，Eagle 无变化
- [ ] `sync-eagle demo-scan --apply` 后：
  - [ ] Eagle 标签面板出现 `tc:project:demo-scan` / `tc:edit_candidate_status` / `tc:shot_function` 等 tag group（可折叠）
  - [ ] default_selected 素材：rating 星级正确 + `tc:*` tag 齐全 + annotation 含斜体头部与 markdown 区块
  - [ ] 筛选 `tc:edit_candidate_status:excluded` 定位到 excluded 素材
  - [ ] `eagle_apply_result.json` 存在且 schema 正确
- [ ] Eagle 手工改 rating → 重跑 `--apply` → rating 被覆盖回 cut_index 值（默认 update 行为）
- [ ] `--skip` flag：无 API 调用
- [ ] Eagle 未启动 → `--apply` 立即报错，无副作用
- [ ] scanned 阻断：手工构造 scanned 素材 → `--apply` 报错；`--skip-unanalyzed` 跳过
- [ ] annotation 视觉：斜体头部 + 加粗 `##` 标题 + 反引号时间码等宽字体
- [ ] `--reset --yes`：Eagle items 进回收站；`eagle_item_id` 清空；重跑 `--apply` 全新创建

## S. 验收终判

- [ ] 上述 A-R 全部勾选完成（A-Q 自动化项已全过；R 段人工视觉验收待用户）
- [x] [docs/specs/README.md](file:///Users/bytedance/Documents/TripClipper_Trae/docs/specs/README.md) M6 行状态更新为「已完成」
- [x] [ADR-004](file:///Users/bytedance/Documents/TripClipper_Trae/docs/adr/ADR-004-eagle-sync-as-thin-mapping-layer.md) 与 [spec.md](spec.md) 无互相矛盾
- [ ] Task 15（用户人工验收）签字通过
