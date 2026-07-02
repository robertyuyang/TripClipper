# Session Splitting Tasks

> 阶段：**待开始**。本任务清单实施 [session-splitting/spec.md](./spec.md) 的落地。
> 依赖前置：M0 / M2 / M6 已完成。
> 拍板决策：本会话 grilling Q1–Q11 + 架构复议（session 归分析阶段、零 CLI 参数默认功能）。

## 任务清单

- [ ] **Task 1**：M0 数据契约新增字段（[src/tripclipper/models.py](../../../src/tripclipper/models.py)）
  - [ ] SubTask 1.1：在 `Asset.similar_group_id` 旁新增 `session_id: Optional[str] = None`
  - [ ] SubTask 1.2：在 `SimilarGroup` 类之后新增 `Session` 类，含 `session_id / asset_ids / started_at / ended_at / asset_count` 5 个字段
  - [ ] SubTask 1.3：在 `CutIndex.similar_groups` 旁新增 `sessions: list[Session] = Field(default_factory=list)`
  - [ ] SubTask 1.4：把 `Session` 加进 `__all__` 导出
  - [ ] SubTask 1.5：**不 bump** `SCHEMA_VERSION`，保持 "0.3"
  - [ ] SubTask 1.6：`tests/test_models.py` 补充：`Asset.session_id` 默认 None、`Session` 序列化/反序列化、`CutIndex.sessions` 默认空、旧 cut_index.json 兼容读取

- [ ] **Task 2**：新增 [`src/tripclipper/session_splitter.py`](../../../src/tripclipper/session_splitter.py)
  - [ ] SubTask 2.1：定义常量 `SESSION_GAP_HOURS = 1.0`
  - [ ] SubTask 2.2：实现 `split_sessions(assets: list[Asset], *, gap_hours: float = SESSION_GAP_HOURS) -> list[Session]`
    - 按 `modified_time` 升序排序（None 的 asset 剔除到单独一组）
    - 相邻间隔 `>= gap_hours * 3600` 秒时切段
    - `session_id` 从 `session_01` 开始编号
    - `modified_time=None` 的 asset 归到 `session_00_unknown`（若有则输出该 Session；若无则不输出）
    - 每段 `Session` 填 `started_at / ended_at / asset_ids / asset_count`
  - [ ] SubTask 2.3：实现 `apply_sessions(assets: list[Asset], sessions: list[Session]) -> None`：把 `session_id` 写回 `asset.session_id`
  - [ ] SubTask 2.4：新增 `tests/test_session_splitter.py`：
    - 5 个 asset 都在 30 分钟内 → 1 个 session
    - 5 个 asset 每两个之间隔 2 小时 → 5 个 session
    - 3+2 混合，中间 90 分钟 gap → 2 个 session
    - 2 个 asset `modified_time=None` → 输出 `session_00_unknown`
    - 空 assets → 空 sessions

- [ ] **Task 3**：scan 集成（[src/tripclipper/scan.py](../../../src/tripclipper/scan.py)）
  - [ ] SubTask 3.1：在 `scan()` 函数写盘前追加：
    ```python
    from tripclipper.session_splitter import split_sessions, apply_sessions
    sessions = split_sessions(assets)
    apply_sessions(assets, sessions)
    cut_index.sessions = sessions
    ```
  - [ ] SubTask 3.2：日志摘要追加 `切分为 N 个 session（gap=1h）`
  - [ ] SubTask 3.3：`tests/test_scan.py` 补充：demo scan 后 `cut_index.sessions` 非空、每个 asset 有 `session_id`

- [ ] **Task 4**：EagleClient 支持 folder（[src/tripclipper/eagle_sync.py](../../../src/tripclipper/eagle_sync.py)）
  - [ ] SubTask 4.1：新增 `EagleClient.folder_create(name: str, parent_id: Optional[str] = None) -> str`，包 `POST /api/v2/folder/create`（body 含 `name` + 可选 `parent`），返回 folder id
  - [ ] SubTask 4.2：`EagleClient.add_from_path` 新增 `folder_id: Optional[str] = None` 参数；非空时写入 body 的 `folderId`
  - [ ] SubTask 4.3：`tests/test_eagle_sync.py` 补充：mock 验证 folder_create request body + add_from_path 传 `folderId` 时的 body

- [ ] **Task 5**：sync flow 按 session 建 folder（[src/tripclipper/eagle_sync.py](../../../src/tripclipper/eagle_sync.py)）
  - [ ] SubTask 5.1：**不建项目父 folder**（Q13）。folder 一级平铺。
  - [ ] SubTask 5.2：遍历 asset 时按 `asset.session_id` 分组；首次遇到某 session_id 时 `folder_create(name=<slug 前缀 · session 详细名>)` → memo `session_folder_id[session_id]`
    - session folder 名格式（Q14）：`{slug} · {session_id} · {started_at:%Y-%m-%d %H:%M}`
    - `session_00_unknown`：`{slug} · session_00_unknown`（无时间）
    - 分隔符 ` · `（U+00B7 中点带空格）
    - `started_at` 从 `CutIndex.sessions` 里对应 `Session` 取
  - [ ] SubTask 5.3：调 `add_from_path(..., folder_id=session_folder_id[session_id])`
  - [ ] SubTask 5.4：若 asset 已有 `eagle_item_id`：跳过 folder 归属，warning `"item already synced; folder assignment skipped"`
  - [ ] SubTask 5.5：`cut_index.sessions` 为空时（旧项目）：完全跳过 folder 逻辑，asset 直接平铺入 Eagle 根目录

- [ ] **Task 6**：dry-run "Sessions preview"（[src/tripclipper/eagle_sync.py](../../../src/tripclipper/eagle_sync.py)）
  - [ ] SubTask 6.1：`sync-eagle --dry-run` 输出末尾追加 `Sessions preview (gap=1h):` 段
  - [ ] SubTask 6.2：每行显示 `session_id / 起止时间 / n=<count>`，`session_00_unknown` 特殊显示无时间
  - [ ] SubTask 6.3：session 数 > 12 时 head+尾各 5，中间 `... (N sessions omitted) ...`
  - [ ] SubTask 6.4：`tests/test_eagle_sync.py` 补充 dry-run 输出断言

- [ ] **Task 7**：review.html Session 视图（[src/tripclipper/exporter.py](../../../src/tripclipper/exporter.py) + [src/tripclipper/templates/review.html.tmpl](../../../src/tripclipper/templates/review.html.tmpl)）
  - [ ] SubTask 7.1：exporter.py 把 `cut_index.sessions` 序列化后注入模板（asset_ids / started_at / ended_at / asset_count / 缩略图前 6 张）
  - [ ] SubTask 7.2：overview 头部追加 `共 N 个 session（含 unknown X 张）` 摘要行
  - [ ] SubTask 7.3：模板新增 `扁平视图 / Session 视图` tab 切换（顶栏，overview 之下、过滤器之上）
  - [ ] SubTask 7.4：扁平视图主表格新增 `session` 列（`session_00_unknown` 用灰色徽章）
  - [ ] SubTask 7.5：过滤器行新增 `<select id="filter-session">`，选项由 sessions 动态填充；两种视图下均生效
  - [ ] SubTask 7.6：Session 视图卡片模板：卡片头（session_id + 起止时间 + 张数 + 6 缩略图条 + 溢出计数）+ 展开区（复用表格行样式）
  - [ ] SubTask 7.7：`全部折叠 / 全部展开` 顶栏按钮（Session 视图下显示）
  - [ ] SubTask 7.8：`session_00_unknown` 卡片排最末，加"时间信息缺失"提示
  - [ ] SubTask 7.9：JS：视图切换保留过滤器状态；过滤器改变时同时更新两种视图 DOM
  - [ ] SubTask 7.10：`tests/test_exporter.py` 补充：视图 tab 存在、Session 卡片渲染、session 列存在、overview 摘要正确

- [ ] **Task 8**：文档同步
  - [ ] SubTask 8.1：更新 [docs/specs/README.md](../README.md) 模块索引表状态
  - [ ] SubTask 8.2：如有必要，回写 [docs/specs/M6-eagle-sync/spec.md](../M6-eagle-sync/spec.md) 加一条 "本模块产出被 session-splitting 扩展" 的引用

- [ ] **Task 9**：手动验收（按 [check_list.md](./check_list.md) 逐项）
  - [ ] SubTask 9.1：demo-scan 项目跑通 scan → analyze → sync-eagle --apply 全流程
  - [ ] SubTask 9.2：Eagle 里视觉核对：父 folder + 子 folder 结构正确
  - [ ] SubTask 9.3：cut_index.json 字段核对
  - [ ] SubTask 9.4：dry-run 输出核对
  - [ ] SubTask 9.5：浏览器打开 review.html 视觉核对：视图 tab 切换、Session 卡片、过滤器联动

## 建议执行顺序

1. Task 1 → Task 2（数据结构 + 纯函数模块，最独立）
2. Task 3（scan 集成，端到端跑通"数据侧"）
3. Task 4 → Task 5 → Task 6（Eagle 侧，可用 mock 先行）
4. Task 7（review.html，前端可与 Eagle 并行）
5. Task 8 → Task 9（文档同步 + 手动验收）

## 待办 / 待用户拍板（先跑 spec 待确认项）

- 无。全部 14 项决策（Q1–Q14）已闭环。
