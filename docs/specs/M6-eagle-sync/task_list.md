# Tasks — M6 Eagle 同步

> 阶段：实施前的有序工作清单。每项任务对应 [spec.md](spec.md) 中的一个或一组 Requirement。
> 实施纪律：与 M3/M4/M5 一致——纯函数单测 + Eagle V2 API 用 `respx`/httpx MockTransport 打桩 + CLI stdout 用 `CliRunner` 捕获断言；真实 Eagle 联调由用户主导（Task 15）。

## Task 列表

- [x] Task 1：新增 `EagleV2Client` HTTP 客户端（spec ADDED §「M6 SHALL 仅支持 Eagle V2 Web API」/§「M6 SHALL 通过 V2 tagGroup API 自动维护字段分组」的底层能力）
  - [x] SubTask 1.1：新增 [src/tripclipper/eagle_sync.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/eagle_sync.py) 文件，顶部 module docstring 说明"M6 通用字段映射层"（引用 [ADR-004](file:///Users/bytedance/Documents/TripClipper_Trae/docs/adr/ADR-004-eagle-sync-as-thin-mapping-layer.md)）。
  - [x] SubTask 1.2：定义 dataclass 与异常：
        - `@dataclass class EagleClientError(Exception)`：`stage: str, cause: Exception | None, http_status: int | None`
        - `class EagleUnavailableError(EagleClientError)`（网络不可达）
        - `class EagleVersionError(EagleClientError)`（V1 only、V2 不可用）
        - `@dataclass(frozen=True) class EagleItem`：`item_id: str, name: str, path: str, tags: list[str], rating: int | None, annotation: str`
  - [x] SubTask 1.3：实现 `class EagleV2Client`：
        - `__init__(base_url: str, api_token: str | None, timeout: float = 30.0)`；内部持 `httpx.Client`
        - `health_check() -> dict`：GET `/api/v2/library/info`；成功返回 dict，V1 only 返回 404 时抛 `EagleVersionError("Eagle V1 API only, V2 required")`；连接失败抛 `EagleUnavailableError`
        - `add_from_path(path: str, name: str, tags: list[str], rating: int | None, annotation: str) -> str`：POST `/api/v2/item/addFromPath`；返回新建 item 的 `id`
        - `update_item(item_id: str, *, tags: list[str] | None, rating: int | None, annotation: str | None) -> None`：PATCH `/api/v2/item/update`（只传非 None 字段）
        - `move_to_trash(item_ids: list[str]) -> None`：POST `/api/v2/item/moveToTrash`
        - `tag_group_list() -> list[dict]`：GET `/api/v2/tagGroup/list`；返回现有 tag group
        - `tag_group_create(name: str, tags: list[str]) -> str`：POST `/api/v2/tagGroup/create`；返回 group id
        - `tag_group_add_tags(group_id: str, tags: list[str]) -> None`：POST `/api/v2/tagGroup/update`（增量 add）
        - close/`__enter__`/`__exit__` 管理 httpx.Client 生命周期
  - [x] SubTask 1.4：单测 [tests/test_eagle_client.py](file:///Users/bytedance/Documents/TripClipper_Trae/tests/test_eagle_client.py)（用 `httpx.MockTransport`）：
        - `test_health_check_ok` → 返回 dict，无异常
        - `test_health_check_v1_only` → V2 endpoint 返回 404，抛 `EagleVersionError`
        - `test_health_check_connection_refused` → transport 抛 `httpx.ConnectError`，捕获后抛 `EagleUnavailableError`
        - `test_add_from_path_returns_id` → mock 返回 `{"status":"success","data":{"id":"UUID"}}`；断言返回值 `"UUID"`
        - `test_update_item_omits_none_fields` → 传 `tags=["a"], rating=None`；断言 request body 不含 `rating` 键
        - `test_move_to_trash_batch` → 传 `["id1","id2"]`；断言 request body 是 `{"itemIds":["id1","id2"]}`（或按实际 V2 schema）
        - `test_tag_group_add_tags_increment` → 断言 body 只含新增 tag 数组，不含全量替换语义

- [x] Task 2：新增 `MappingConfig` 与 `MappingLoader`（spec §What Changes 第 3 条 default mapping yaml；spec ADDED §「M6 SHALL 仅做字段映射」的配置基础）
  - [x] SubTask 2.1：新增 [src/tripclipper/templates/eagle_mapping.default.yaml](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/templates/eagle_mapping.default.yaml)，内容按 spec §What Changes 第 3 条骨架完整落地：
        ```yaml
        tag_prefix: "tc"
        project_tag_field: "project"
        auto_map_unknown: true

        mappings:
          rating: { target: eagle_rating }
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

        note_template:
          header: "_TripClipper · {project_slug} · synced {sync_timestamp}_"
          empty_section_behavior: skip
          section_format: markdown_h2

        connection_failure_threshold: 5
        ```
  - [x] SubTask 2.2：在 [eagle_sync.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/eagle_sync.py) 定义配置 dataclass：
        - `@dataclass(frozen=True) class TargetSpec`：`target: Literal["tag","eagle_rating","note_section"], title: str | None, order: int | None, renderer: str | None`
        - `@dataclass(frozen=True) class NoteTemplate`：`header: str, empty_section_behavior: Literal["skip","render_empty"], section_format: str`
        - `@dataclass(frozen=True) class MappingConfig`：`tag_prefix: str, project_tag_field: str, auto_map_unknown: bool, mappings: dict[str, TargetSpec], skip_fields: frozenset[str], note_template: NoteTemplate, connection_failure_threshold: int`
  - [x] SubTask 2.3：实现 `load_mapping_config(project_overrides: dict | None = None) -> MappingConfig`：
        - 从 [eagle_mapping_default_template_path()](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/paths.py)（Task 5 提供）读默认 yaml
        - 若 `project_overrides` 非空，做**浅合并**（顶层 key 覆盖；`mappings` 合并至字段级；`skip_fields` 取并集）
        - 校验：`tag_prefix` 为非空 str；每个 `TargetSpec.target` ∈ 三个合法值
        - 返回 `MappingConfig`
  - [x] SubTask 2.4：单测 [tests/test_eagle_mapping.py](file:///Users/bytedance/Documents/TripClipper_Trae/tests/test_eagle_mapping.py)：
        - `test_load_default_mapping` → 断言 `tag_prefix == "tc"`, `mappings["edit_candidate_status"].target == "tag"`, `"asset_id" in skip_fields`
        - `test_project_overrides_shallow_merge` → 传 `{"tag_prefix": "custom"}` → 断言其他字段保留默认，`tag_prefix == "custom"`
        - `test_project_overrides_extends_skip_fields` → 传 `{"skip_fields": ["extra_field"]}` → 断言 `skip_fields` 是原集合 ∪ `{"extra_field"}`
        - `test_invalid_target_rejected` → 构造 `mappings.foo.target = "bogus"` yaml → 加载抛 `ConfigError`

- [x] Task 3：新增 `AssetMapper` 字段映射器（spec ADDED §「M6 SHALL 仅做字段映射」/§「note 渲染 SHALL 遵循固定模板」）
  - [x] SubTask 3.1：在 [eagle_sync.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/eagle_sync.py) 定义 `@dataclass(frozen=True) class AssetWritePlan`：`tags: list[str], rating: int | None, annotation: str, item_name: str, source_path: str, tag_group_updates: dict[str, list[str]]`（tag_group_updates 是"字段名 → 该字段应加入分组的 tag 列表"，用于批量维护 tagGroup）
  - [x] SubTask 3.2：实现内置渲染器函数：
        - `_render_clip_suggestions_list(value: list[dict]) -> str`：按 `priority` 升序，输出 markdown bullet 列表：``- `{start} → {end}` [P{priority}] {reason}``；空 list 返回空字符串
        - `_render_text_block(value: str) -> str`：原样返回（多行保留换行）；空/None 返回空字符串
  - [x] SubTask 3.3：实现 `class AssetMapper`：
        - `__init__(config: MappingConfig, project_slug: str, sync_timestamp: str)`
        - `plan(asset: Asset) -> AssetWritePlan`：
          1. 先 emit 项目 tag `tc:project:{project_slug}`
          2. 遍历 `Asset.__dataclass_fields__`（或 pydantic model_fields）：
             - 若字段名 ∈ `skip_fields` → 跳过
             - 若字段名 ∈ `mappings` 且 `target == "eagle_rating"` → 记 rating（int 值直传）
             - 若 `target == "tag"`：值为 str/enum → emit `tc:{field}:{value}`；值为 None → 跳过；值为 list → 遍历每个元素 emit
             - 若 `target == "note_section"` → 用 `renderer` 渲染（未指定则用 `_render_text_block`）；空结果按 `note_template.empty_section_behavior` 决定是否渲染标题
             - 未在 `mappings` 且字段值非 None：若 `auto_map_unknown` → 视作 `target: tag` 处理（str/enum/list）；否则跳过 + 记 warning
          3. 拼 annotation：`{header}\n\n{sorted_sections}`；header 用 `.format(project_slug=..., sync_timestamp=...)`；sections 按 `order` 升序拼接（`## {title}\n{rendered}\n\n`）
          4. `item_name` 取 `asset.filename`（若有）否则 `Path(asset.path).name`
          5. `tag_group_updates`：把每个 emit 的 tag 归入 `f"{tag_prefix}:{field_name}"` 的 group（`tc:project:xxx` 归入 `tc:project`）
  - [x] SubTask 3.4：单测 [tests/test_eagle_asset_mapper.py](file:///Users/bytedance/Documents/TripClipper_Trae/tests/test_eagle_asset_mapper.py)：
        - `test_plan_default_selected_full` → 构造完整 asset（rating=5, edit_candidate_status=default_selected, shot_function=highlight, similar_group_id=grp_001, edit_candidate_reason="组主选", clip_suggestions=[{"start":"00:00:03.5","end":"00:00:08.2","reason":"..","priority":1}]）→ 断言 tags 集合、rating、annotation 顺序（header → 候选池理由 → 建议剪辑片段）
        - `test_plan_excluded_asset` → status=excluded, 无 clip_suggestions → 断言 tag 含 `tc:edit_candidate_status:excluded`；annotation 中**不含** `## 建议剪辑片段` 标题
        - `test_plan_analysis_failed` → status=analysis_failed, analysis_failure_reason="LLM timeout" → 断言 tag 含 `tc:analysis_status:analysis_failed`；annotation 中**含** `## 分析失败原因` 与 `LLM timeout`
        - `test_plan_auto_map_unknown_field` → 构造 asset 附加字段 `recommend_action="delete"`（用 monkeypatch/额外 dict）；`auto_map_unknown=True` → 断言 tag 含 `tc:recommend_action:delete`
        - `test_plan_strict_mapping_skips_unknown` → 同上但 `auto_map_unknown=False` → 断言 tag **不含** `tc:recommend_action:*`
        - `test_plan_skip_fields_excluded` → 断言 asset_id / path / sha1 值不出现在任何 tag 中
        - `test_plan_clip_suggestions_priority_sort` → 传 3 条 suggestion 乱序 priority → 断言 markdown 输出按 P1→P2→P3 排列
        - `test_plan_project_tag_present` → 断言 tags 首个（或至少含）`tc:project:{slug}`
        - `test_plan_tag_group_updates_grouped_by_field` → 断言 `tag_group_updates["tc:edit_candidate_status"] == ["tc:edit_candidate_status:default_selected"]`

- [x] Task 4：新增 `EagleSyncRunner` 同步执行器（spec ADDED §「二次同步默认 update」/§「M6 SHALL 提供错误容错与硬中止机制」/§「M6 SHALL 写出 eagle_apply_result.json 产物」）
  - [x] SubTask 4.1：定义 `@dataclass class SyncOptions`：`apply: bool = False, skip_synced: bool = False, reset: bool = False, retry_failed: bool = False, skip_unanalyzed: bool = False, strict_mapping: bool = False`
  - [x] SubTask 4.2：定义 `@dataclass class SyncFailure`：`asset_id: str, asset_path: str, stage: str, error: str, retryable: bool`
  - [x] SubTask 4.3：定义 `@dataclass class TagGroupWarning`：`tag_group: str, missing_tags: int, error: str`
  - [x] SubTask 4.4：定义 `@dataclass class EagleApplyResult`：`synced_at: str, project_slug: str, eagle_library_path: str | None, totals: dict[str, int], failures: list[SyncFailure], tag_group_warnings: list[TagGroupWarning], aborted: bool, abort_reason: str | None`
  - [x] SubTask 4.5：实现 `class EagleSyncRunner`：
        - `__init__(client: EagleV2Client, mapper: AssetMapper, config: MappingConfig, options: SyncOptions)`
        - `run(cut_index: CutIndex) -> tuple[CutIndex, EagleApplyResult]`：
          1. **启动期检查**：`client.health_check()`；若失败抛 `EagleUnavailableError`/`EagleVersionError`
          2. **cut_index 校验**：确保能 pydantic parse（外部调用点已 parse，内部 no-op）
          3. **scanned 检查**：若存在 `analysis_status == "scanned"` 且 `not options.skip_unanalyzed` → 抛 `SyncPreconditionError` 阻断
          4. **reset 分支**：若 `options.reset` → 收集所有 `eagle_item_id` 非空的 asset → 二次确认由 CLI 层处理（Runner 层信任已确认）→ `client.move_to_trash(item_ids)`；清空 `eagle_item_id`
          5. **过滤 asset**：跳过 scanned（若有 flag）；跳过 `analysis_status not in {analyzed, analysis_failed}`
          6. **应用 flag**：`skip_synced` → 跳 `synced` 状态；`retry_failed` → 只处理 `failed` 状态
          7. **主循环**：per asset：
             - 若 `dry_run`（即 `not options.apply`）→ 只 mapper.plan()、计入 totals，不调 API
             - 否则：
               - 若 `eagle_item_id` 非空 → `client.update_item(...)`
               - 否则 → `client.add_from_path(...)`；写回 `eagle_item_id`
               - 成功 → 设 `eagle_sync_status = "synced"`
               - 网络层错误 → 计连续失败计数，达阈值 → break 主循环，`aborted = True`
               - 业务层错误 → 记 `SyncFailure`，设 `eagle_sync_status = "failed"`，continue
             - 累积 `tag_group_updates`
          8. **tag group 维护**（仅 apply 且未 aborted）：合并所有 asset 的 `tag_group_updates` → 对每个 group 调 `tag_group_list` 找是否存在 → 存在则 `tag_group_add_tags`；不存在则 `tag_group_create`；失败记 `TagGroupWarning`
          9. 生成 `EagleApplyResult`；返回 `(updated_cut_index, result)`
  - [x] SubTask 4.6：定义 `SyncPreconditionError(Exception)` 与 `EagleAbortError(Exception)`
  - [x] SubTask 4.7：单测 [tests/test_eagle_sync_runner.py](file:///Users/bytedance/Documents/TripClipper_Trae/tests/test_eagle_sync_runner.py)（用 `httpx.MockTransport`）：
        - `test_dry_run_no_write` → apply=False → 断言无 addFromPath 调用；cut_index 未变化
        - `test_apply_full_success` → 3 条 analyzed asset → 断言 3 次 addFromPath；每条 `eagle_sync_status="synced"`；`totals.synced==3`
        - `test_apply_update_existing` → 2 条已同步（`eagle_item_id` 非空） → 断言只调 update_item，无 addFromPath
        - `test_skip_synced_flag` → skip_synced=True + 已同步 asset → 断言 update_item 未被调；`totals.skipped==N`
        - `test_scanned_hard_abort` → 混入 1 条 scanned + skip_unanalyzed=False → 抛 `SyncPreconditionError`；无 API 调用
        - `test_scanned_soft_skip` → 同上但 skip_unanalyzed=True → 断言 scanned 被跳过；`totals.skipped_unanalyzed==1`
        - `test_analysis_failed_included` → 1 条 analysis_failed → 断言被同步，tag 含 `tc:analysis_status:analysis_failed`
        - `test_single_asset_business_failure` → mock addFromPath 对第 2 条返回 500 → 断言其他 asset 继续；`totals.failed==1`；`failures` 有 1 项
        - `test_five_consecutive_network_failures_abort` → mock 连续 5 次 ConnectError → 断言 `aborted=True`, `abort_reason` 含 "eagle_disconnected"；已成功 asset 保持 `synced`
        - `test_reset_flag_moves_to_trash` → 先构造已同步 asset → apply+reset → 断言 move_to_trash 调过 + `eagle_item_id` 清空 + 重新 addFromPath
        - `test_tag_group_maintained` → 3 条 asset 覆盖不同 edit_candidate_status → 断言 tag_group_create/add_tags 被调，group name 是 `tc:edit_candidate_status`
        - `test_tag_group_failure_warning_only` → mock tag_group_add_tags 抛错 → 断言主流程仍成功；`tag_group_warnings` 有 1 项

- [x] Task 5：兑现 [paths.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/paths.py) 的 Eagle 相关 helper（spec §What Changes 第 6 条）
  - [x] SubTask 5.1：确认既有 `eagle_apply_result_path(slug, base_dir)` helper 是否已存在（[paths.py L63-68](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/paths.py#L63-L68) 是占位）；若为 stub，替换为完整实现：`return project_dir(slug, base_dir) / "eagle_apply_result.json"`
  - [x] SubTask 5.2：新增 `eagle_mapping_default_template_path() -> Path`：返回 `Path(__file__).parent / "templates" / "eagle_mapping.default.yaml"`；加入 `__all__`
  - [x] SubTask 5.3：更新 [paths.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/paths.py) 顶部布局图 docstring：`projects/<slug>/` 下追加一行 `└── eagle_apply_result.json`
  - [x] SubTask 5.4：单测 [tests/test_paths.py](file:///Users/bytedance/Documents/TripClipper_Trae/tests/test_paths.py)（新增或补测）：`test_eagle_apply_result_path` / `test_eagle_mapping_default_template_path`：路径拼接正确、后者 `.exists()` 为真

- [x] Task 6：兑现 [config.EagleSync](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/config.py#L56-L63)（spec §What Changes 第 7 条）
  - [x] SubTask 6.1：把占位 dataclass 改为完整字段：
        ```python
        @dataclass
        class EagleSync:
            enabled: bool = True
            api_base_url: str = "http://localhost:41595/api/v2/"
            api_token: str | None = None
            connection_failure_threshold: int = 5
            mapping_overrides: dict | None = None
        ```
  - [x] SubTask 6.2：在 `TripClipperConfig` 或 project config 加载函数里承载 `EagleSync`（若已有则确认 field mapping；否则新增）
  - [x] SubTask 6.3：单测 `test_config_eagle_sync_defaults` → 断言默认值；`test_config_eagle_sync_from_yaml` → 传 yaml 读入并读回一致

- [x] Task 7：修改 CLI [sync-eagle 命令](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/cli.py#L516-L527)（spec ADDED §「`tripclipper sync-eagle <slug>` SHALL 提供 dry-run 与 apply 两种模式」）
  - [x] SubTask 7.1：删除现有占位实现。
  - [x] SubTask 7.2：新命令签名：
        ```python
        @main.command("sync-eagle")
        @click.argument("slug")
        @click.option("--apply/--dry-run", "apply_flag", default=False, ...)
        @click.option("--skip", "skip_synced", is_flag=True, default=False, ...)
        @click.option("--reset", is_flag=True, default=False, ...)
        @click.option("--retry-failed", is_flag=True, default=False, ...)
        @click.option("--skip-unanalyzed", is_flag=True, default=False, ...)
        @click.option("--strict-mapping", is_flag=True, default=False, ...)
        @click.option("--yes", is_flag=True, default=False, help="跳过 --reset 的二次确认（用于 CI）")
        ```
  - [x] SubTask 7.3：函数体：
        1. 加载 project config → 拿 `EagleSync` 配置
        2. 构造 `EagleV2Client(base_url=..., api_token=...)`（用 with block 管理生命周期）
        3. 加载 `MappingConfig`（`load_mapping_config(config.eagle_sync.mapping_overrides)`）；若 `strict_mapping` 覆盖 `auto_map_unknown = False`
        4. `--reset` 时：若 `not yes` → `click.confirm(f"将删除 N 条 Eagle items, 是否继续?", abort=True)`
        5. `AssetMapper(config, project_slug, sync_timestamp=iso_now())`
        6. `EagleSyncRunner(client, mapper, config, options).run(cut_index)`
        7. 写回 `cut_index.json`（apply 且未 aborted 时）
        8. 写 `eagle_apply_result.json`（apply 时）
        9. stdout 打印摘要（`✅ 已同步 N/N 条素材到 Eagle` / `⚠️ M 条失败，详见 eagle_apply_result.json` / `❌ 已中止：...`）
        10. 异常兜底：`EagleUnavailableError`/`EagleVersionError`/`SyncPreconditionError` → 面向用户文案 + `sys.exit(2)`
  - [x] SubTask 7.4：CLI 单测 [tests/test_cli_sync_eagle.py](file:///Users/bytedance/Documents/TripClipper_Trae/tests/test_cli_sync_eagle.py)（用 `CliRunner` + monkeypatch 打桩 EagleV2Client）：
        - `test_dry_run_default` → 断言 exit_code=0；stdout 含"待同步"；无 apply 副作用
        - `test_apply_success` → mock client 全成功 → exit_code=0；stdout 含"已同步"；`eagle_apply_result.json` 存在
        - `test_apply_partial_failure` → mock 1 条业务失败 → exit_code=0；stdout 含"⚠️"；failures 记 1 条
        - `test_eagle_unavailable` → mock health_check 抛 `EagleUnavailableError` → exit_code=2；stderr 含"无法连接到 Eagle"
        - `test_eagle_version_too_low` → mock health_check 抛 `EagleVersionError` → exit_code=2；stderr 含"版本 ≥ 4.0 Build 21"
        - `test_scanned_present_without_flag` → cut_index 混入 scanned → exit_code=2；stderr 含"scanned"
        - `test_reset_confirms` → 传 `--reset` 无 `--yes` → 用 `input="n\n"` → exit_code≠0；无 API 调用
        - `test_reset_yes_bypasses_confirm` → `--reset --yes` → 断言 move_to_trash 被调
        - `test_strict_mapping_flag_overrides_yaml` → 断言 runner 收到 `auto_map_unknown=False`

- [x] Task 8：新增运行时依赖 `httpx`（spec §Impact 依赖更新）
  - [x] SubTask 8.1：在 [pyproject.toml](file:///Users/bytedance/Documents/TripClipper_Trae/pyproject.toml) `[project.dependencies]` 加 `"httpx>=0.27.0"`；在 dev/test extras 加 `"respx>=0.21.0"` 或直接依赖 `httpx.MockTransport`（内置，无需 respx）
  - [x] SubTask 8.2：`.venv/bin/pip install -e .` 更新虚拟环境；确认 `python -c "import httpx"` 无异常

- [x] Task 9：端到端 demo-scan 场景测试（spec §验收口径 步骤 1-3）
  - [x] SubTask 9.1：新增 [tests/test_eagle_sync_demo_scan.py](file:///Users/bytedance/Documents/TripClipper_Trae/tests/test_eagle_sync_demo_scan.py)：
        - `test_dry_run_on_demo_scan` → 用 demo-scan 真 cut_index + Eagle mock → dry-run → 断言待同步计数 == demo-scan 实际 analyzed 素材数；无 API 副作用
        - `test_apply_on_demo_scan_writes_expected_tags` → apply → 抓所有 addFromPath 调用参数 → 断言至少 1 条包含 `tc:project:demo-scan`, `tc:edit_candidate_status:default_selected`, `tc:analysis_status:analyzed`；rating 与 cut_index 一致
        - `test_apply_creates_tag_groups` → apply → 断言 tag_group_create 至少被调用于 `tc:edit_candidate_status`, `tc:shot_function`, `tc:project`
        - `test_reapply_updates_not_creates` → 先 apply 一次（回写 eagle_item_id）→ 再 apply → 第二次断言只调 update_item，无 addFromPath

- [x] Task 10：文档更新
  - [x] SubTask 10.1：[docs/specs/README.md](file:///Users/bytedance/Documents/TripClipper_Trae/docs/specs/README.md) M6 行状态：spec 完成审阅、check_list 全部勾选后由「定稿（待用户审）」改为「已完成」
  - [x] SubTask 10.2：CONTEXT.md 已在 grilling 阶段完成（L44-50 修订 + L86 加 ADR-004）；无需再改
  - [x] SubTask 10.3：确认 [ADR-004](file:///Users/bytedance/Documents/TripClipper_Trae/docs/adr/ADR-004-eagle-sync-as-thin-mapping-layer.md) 与本 spec 无冲突（spec 引用 ADR-004 决策；ADR 引用本 spec 的具体兑现）
  - [x] SubTask 10.4：更新 [eagle_sync.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/eagle_sync.py) module docstring：说明四层职责（EagleV2Client / MappingLoader / AssetMapper / EagleSyncRunner）+ 引用 spec 与 ADR-004

- [x] Task 11：清理占位实现
  - [x] SubTask 11.1：确认 [cli.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/cli.py#L516-L527) 中原 `sync-eagle` stub 完全被 Task 7 替换，无遗留 `click.echo("stub")` 之类
  - [x] SubTask 11.2：确认 [paths.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/paths.py#L63-L68) 中 `eagle_*` 占位 helper 已被 Task 5 兑现
  - [x] SubTask 11.3：确认 [config.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/config.py#L56-L63) 中 `EagleSync` 已被 Task 6 兑现
  - [x] SubTask 11.4：全仓库 grep `TODO.*[Ee]agle|TODO.*sync-eagle|stub.*eagle` 应为空

- [x] Task 12：回归验证
  - [x] SubTask 12.1：`.venv/bin/python -m pytest tests/ --ignore=tests/test_integration_m3.py --ignore=tests/test_integration_m4.py -x` 全通过
  - [x] SubTask 12.2：M0~M5 既有单测无回归（重点关注：CLI 命令面板未被 sync-eagle 变更破坏；paths.py 变更未破坏 M5 exports 路径）
  - [x] SubTask 12.3：`.venv/bin/python -c "from tripclipper.eagle_sync import EagleV2Client, MappingLoader, AssetMapper, EagleSyncRunner"` 无 import 错

- [x] Task 13：todolist 交叉引用
  - [x] SubTask 13.1：确认 [docs/todolist.md](file:///Users/bytedance/Documents/TripClipper_Trae/docs/todolist.md) 中"Eagle 同步防重复导入（sha1 去重）"条目仍在，且引用了本 spec + ADR-004
  - [x] SubTask 13.2：本 spec §「与未来模块的边界」段落已声明 sha1 去重的向后兼容路径；无需再动

- [x] Task 14：项目 sample cut_index 的健康素材筛查（回归风险预防）
  - [x] SubTask 14.1：跑 `.venv/bin/python -c "from tripclipper.exporter import read_cut_index; ci = read_cut_index('demo-scan'); print(sum(1 for a in ci.assets if a.analysis_status == 'analyzed'))"` 记录数量
  - [x] SubTask 14.2：若 demo-scan 无 analysis_failed 素材，构造一个测试 fixture（`tests/fixtures/eagle_sync/cut_index_with_failures.json`）覆盖该场景

- [ ] Task 15：人工端到端验收（用户主导）
  - [ ] SubTask 15.1：确认 Eagle 已启动、版本 ≥ 4.0 Build 21：Eagle 菜单 → 关于 → 记录版本号
  - [ ] SubTask 15.2：跑 `.venv/bin/tripclipper sync-eagle demo-scan --dry-run`：
        - stdout 含 Eagle 版本号、待同步 N 条素材摘要
        - `projects/demo-scan/cut_index.json` 与 Eagle 库均无变化（前后 SHA / mtime 检查）
  - [ ] SubTask 15.3：跑 `.venv/bin/tripclipper sync-eagle demo-scan --apply`：
        - stdout 含 `✅ 已同步 N / N`
        - Eagle 左侧标签面板出现 `tc:project:demo-scan` / `tc:edit_candidate_status` / `tc:shot_function` 等 tag group（可折叠展开查看）
        - Eagle 中任一 default_selected 素材的 item：rating 星级正确；tags 含预期 `tc:...` tag；annotation 含斜体头部 + 至少一个 `##` 区块
        - Eagle 中筛选 tag `tc:edit_candidate_status:excluded` 能定位到 excluded 素材
        - `projects/demo-scan/eagle_apply_result.json` 存在，schema 符合 spec §What Changes 第 4 条
  - [ ] SubTask 15.4：验证默认 update：在 Eagle 手工把某 item rating 改成 1 星 → 重跑 `--apply` → 确认 rating 被 cut_index 值覆盖回原值
  - [ ] SubTask 15.5：验证 `--skip`：跑 `sync-eagle demo-scan --apply --skip`：
        - stdout 含 `跳过已同步 N 条`
        - Eagle 库无变化（可用 addFromPath 网络监控确认）
  - [ ] SubTask 15.6：验证 Eagle 未启动：手工 quit Eagle，跑 `--apply` → 立即报错，非 0 退出，cut_index 无变化
  - [ ] SubTask 15.7：验证 scanned 阻断：手工把某 asset 的 `analysis_status` 改成 `scanned`，跑 `--apply` → 启动期报错；加 `--skip-unanalyzed` → 该条被跳过、其他正常
  - [ ] SubTask 15.8：验证 note 视觉：Eagle 中打开一条 default_selected 素材的 annotation，确认：
        - 首行是斜体 `_TripClipper · demo-scan · synced ..._`
        - `##` markdown 标题渲染为加粗大字（Eagle 支持基础 markdown）
        - 时间码反引号包裹，等宽字体显示
  - [ ] SubTask 15.9：验证 `--reset`：跑 `sync-eagle demo-scan --apply --reset` → 交互确认 y → Eagle 中原 item 进入回收站；cut_index 中 `eagle_item_id` 全清；然后重跑 `--apply` → 全新创建

## Task Dependencies

- Task 2 依赖 Task 5（`load_mapping_config` 需要 `eagle_mapping_default_template_path()`）。
- Task 3 依赖 Task 2（消费 `MappingConfig`）。
- Task 4 依赖 Task 1、Task 3（消费 `EagleV2Client` + `AssetMapper`）。
- Task 5 与 Task 1-4 独立，可并行。
- Task 6 与 Task 1-5 独立（config 改动仅供 Task 7 消费）。
- Task 7 依赖 Task 1-6 全部完成。
- Task 8（httpx 依赖）在 Task 1 前置；理想上先做。
- Task 9 依赖 Task 1-7 全部完成 + demo-scan 项目存在（既有）。
- Task 10 与 Task 1-9 可并行；Task 10.1 在 check_list 全勾之后。
- Task 11 在 Task 5-7 之后（清理它们各自替换的占位）。
- Task 12 在 Task 1-11 之后（全量回归）。
- Task 13 独立。
- Task 14 与 Task 3-4 可并行（构造 fixture 用于测试）。
- Task 15 依赖 1-14 全部完成 + 用户本机 Eagle 环境就绪。

## 实施建议顺序

1. **底座**：Task 8（httpx 依赖）→ Task 5（paths helper）→ Task 6（config）→ Task 2（mapping loader）
2. **核心**：Task 1（客户端）→ Task 3（mapper）→ Task 4（runner）→ 各自单测
3. **CLI 与 E2E**：Task 7（CLI）→ Task 9（demo-scan E2E）→ Task 14（fixture 补齐）
4. **收尾**：Task 11（清理占位）→ Task 12（回归）→ Task 13（todolist 交叉引用）→ Task 10（文档）
5. **验收**：Task 15（用户主导）
