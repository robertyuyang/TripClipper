# Session Splitting Spec

> 状态：**待用户审**。本文件由 2026-07 grilling 会话（Q1–Q11 + 架构复议）落地。
> 覆盖：以"活动/session"为粒度自动拆分素材，为 Eagle 同步、review.html、导出等下游功能提供统一的 session 归属数据。
> 依赖：M0 数据契约（已完成）、M2 本地素材扫描（已完成）。
> 不在范围：本 change **不做** LLM 辅助切段、不做 EXIF/creation_time 时间源升级、不做 `project.yaml` 预声明行程；这三条演进方向已进 [docs/todolist.md](../../todolist.md) 三节 "Session 切分升级"。
> 关联决策：Q7=B（用 `Asset.modified_time`）、Q9=A（时间缺失归入 `session_00_unknown`）、"零参数默认功能"（放弃 CLI `--session-gap-hours` / `--split-by-session` 开关）。

## Why

用户手里的素材实际是**一次次活动/session 的集合**：上午海边、下午桌游、晚上聚餐——同一天可能有 3–5 段完全不同的行程。当前 TripClipper 把整个项目当一个扁平的素材池，Eagle 里 200 张素材挤在一个 folder 下无法按行程翻阅、review.html 也没有 session 分组的呈现。

如果不引入 session 概念，每个下游功能都要各自实现"什么算一段行程"的启发式：
- Eagle 同步想按行程建子 folder → 要算一遍
- review.html 想按行程分组展示 → 要算一遍
- 未来 M5 export 想按行程拆包 → 又要算一遍
- 未来 LLM 辅助识别行程、`project.yaml` 预声明行程（见 [todolist.md](../../todolist.md#L86-L131)）→ 都要接入"session 归属"这个决策点

把 session 切分做成**分析阶段的一等公民**，产出与 `similar_group_id` / `SimilarGroup` 完全对偶的持久化字段（`session_id` / `Session`），是让下游功能干净叠加的关键。

## What Changes

### 1. M0 数据契约：新增 `Asset.session_id` + `CutIndex.sessions`

- [models.py](../../../src/tripclipper/models.py) 的 `Asset`（第 158 行 `similar_group_id` 旁边）新增：
  ```python
  session_id: Optional[str] = None
  ```
  字段语义：素材归属的 session id，形如 `session_01`、`session_02`、`session_00_unknown`。由 scan 阶段的 session_splitter 写入。

- 新增 `Session` 模型（放在 [models.py](../../../src/tripclipper/models.py) 的 `SimilarGroup` 之后，与之对偶）：
  ```python
  class Session(BaseModel):
      model_config = _MODEL_CONFIG

      session_id: str
      asset_ids: list[str] = Field(default_factory=list)
      started_at: Optional[datetime] = None
      ended_at: Optional[datetime] = None
      asset_count: int = 0
  ```

- `CutIndex`（第 292 行附近）新增：
  ```python
  sessions: list[Session] = Field(default_factory=list)
  ```
  放在 `similar_groups` 旁边。

- **`SCHEMA_VERSION` 不 bump**：所有新增字段可选或有默认值，向后兼容读旧 cut_index.json（旧文件读出 `session_id=None` / `sessions=[]`）。

### 2. 新增模块 `src/tripclipper/session_splitter.py`

- **纯函数 + 无 LLM + 无 IO**。
- 入口：`split_sessions(assets: list[Asset], *, gap_hours: float = SESSION_GAP_HOURS) -> list[Session]`。
- 常量：`SESSION_GAP_HOURS = 1.0`（模块级常量，暴露在代码里；不做 CLI 参数）。
- 算法：
  1. 用 `modified_time` 有值的 asset 按时间升序排序。
  2. 相邻两个 asset 的时间差 `>= gap_hours` 时切一刀。
  3. 每段生成一个 `Session`，`session_id = f"session_{i:02d}"`（从 01 开始）。
  4. `modified_time` 为 None 的 asset 单独归入 `session_id="session_00_unknown"`（若有则输出，无则不输出）。
- 输出：`list[Session]`，同时不改 asset 本身；由调用方再遍历一次写回 `asset.session_id`。
- 或提供第二个函数 `apply_sessions(assets, sessions) -> None` 把 `session_id` 写回 asset。

### 3. `src/tripclipper/scan.py`：scan 完自动切段

- `scan()` 函数在写盘之前（现有流程完成后）调用 `session_splitter.split_sessions`，得到 sessions，然后：
  - `apply_sessions(assets, sessions)` 写 `asset.session_id`
  - `cut_index.sessions = sessions`
- 加一行日志（跟现有 scan 摘要风格一致）："切分为 N 个 session（gap=1h）"。
- **无参数暴露到 CLI**。

### 4. `src/tripclipper/eagle_sync.py`：默认按 session 建 folder

- 新增 `EagleClient.folder_create(name: str, parent_id: Optional[str] = None) -> str`：包 `POST /api/v2/folder/create`。跟现有 `tag_group_create` 对称。
- `EagleClient.add_from_path`（[eagle_sync.py L253-L271](../../../src/tripclipper/eagle_sync.py#L253-L271)）新增可选参数 `folder_id: Optional[str] = None`，非空时写入 request body 的 `folderId`。
- sync flow 层（在 `SyncOptions`/`sync_project` 附近，具体位置待实现时定）：
  - 首次同步或首次遇到某 session_id 时，`folder_create(name=session.session_id 或人类可读名, parent_id=<项目父 folder id>)`，memo 到 dict。
  - 项目父 folder：`folder_create(name=f"TripClipper: {project.slug}")`，同样 memo。
  - 调 `add_from_path(..., folder_id=<session 子 folder id>)`。
- **存量 item 不迁移**（Q5=B）：若 asset 已有 `eagle_item_id`，跳过 folder 归属，写 warning `"item already synced; folder assignment skipped"`。
- **无参数暴露到 CLI**（无 `--split-by-session` 开关）。旧项目 `sessions=[]` 时退化为不建子 folder，全部素材放在项目父 folder 下（或不建父 folder，见"待确认"）。

### 5. dry-run 输出："Sessions preview" 段

- `sync-eagle --dry-run` 在现有 `[dry-run] 待同步 N 条` 之后追加：
  ```
  Sessions preview (gap=1h):
    session_01  2026-06-15 09:30 → 12:15  n=42
    session_02  2026-06-15 14:20 → 18:05  n=87
    session_00_unknown                    n=3
  ```
- session 数 > 12 时 head+尾各 5 段截断，中间显示 `... (N sessions omitted) ...`。

### 6. tests

- `tests/test_session_splitter.py`：
  - 3 段清晰间隔 → 3 个 session
  - 全部素材间隔 < gap → 1 个 session
  - 全部间隔 > gap → N 个 session
  - 部分 asset `modified_time=None` → 归入 `session_00_unknown`
  - 空 assets → 空 sessions
- `tests/test_scan.py`（补充断言）：scan 完 `cut_index.sessions` 非空且每个 asset 有 `session_id`。
- `tests/test_eagle_sync.py`（补充）：mock EagleClient 验证 `folder_create` + `add_from_path(folder_id=...)` 调用顺序。

### 7. review.html：Session 视图切换（Q12=B）

- 顶栏在 overview 之下、过滤器之上新增视图切换 tab：**扁平视图 / Session 视图**（默认扁平视图，与现有行为一致）。
- **扁平视图**：保持现状（一个大表格 + 相似组 sticky 卡片 + 过滤器）。表格新增一列 `session` 显示 `asset.session_id`（`session_00_unknown` 用灰色徽章）。
- **Session 视图**：按 `session_id` 分组显示，每段一个可展开卡片：
  - 卡片头：`session_XX · 2026-06-15 09:30 → 12:15 · N 张`
  - 卡片头缩略图条：前 6 张 asset 缩略图（超出显示 `+M`）
  - 展开后：该 session 的 asset 列表（复用现有表格行的字段/样式，但不显示 session 列本身）
  - `session_00_unknown` 排在最末，卡片头显示"时间信息缺失"提示
- 过滤器行为：
  - Session 视图下过滤器仍生效（新增 `filter-session` 下拉，选中后只显示该 session 的卡片）
  - 其他过滤器（subject_type / shot_scale / status / similar / candidate）在两种视图下行为一致
- overview 头部追加一行摘要：`共 N 个 session（含 unknown X 张）`
- 交互细节：
  - 切换视图 tab 保留当前过滤器状态
  - session 卡片可全部折叠/展开（顶栏加两个按钮 `全部折叠` / `全部展开`）
  - 折叠状态默认展开

不在 M3 范围（明确延后到 [todolist.md](../../todolist.md#L68-L131)）：
- 用 EXIF `DateTimeOriginal` / 视频 `creation_time` 替代 `modified_time`。
- LLM 辅助合并/拆分 session、生成语义化 folder 名。
- `project.yaml` `trips:` 预声明。

## Impact

- **影响的能力**：
  - M2 scan：新增一步 session 切分（deterministic，秒级完成）。
  - M6 Eagle 同步：默认按 session 分 folder。
  - review.html：新增 Session 视图 + 视图切换 + session 列。
  - M4 clustering / M5 export：暂不消费，但字段已就位。
- **影响的代码**：
  - 新增 `src/tripclipper/session_splitter.py`。
  - 修改 `src/tripclipper/models.py`（3 处：`Asset.session_id`、`Session` 类、`CutIndex.sessions`）。
  - 修改 `src/tripclipper/scan.py`（scan 完追加 session 切分调用）。
  - 修改 `src/tripclipper/eagle_sync.py`（新增 `folder_create`、`add_from_path` 加参、sync flow 建 folder + memo）。
  - 修改 `src/tripclipper/exporter.py`（overview 追加 session 摘要、传 `sessions[]` 到模板）。
  - 修改 `src/tripclipper/templates/review.html.tmpl`（视图切换 tab + Session 视图卡片 + session 列 + 过滤器）。
  - 新增 `tests/test_session_splitter.py`；补充 `tests/test_scan.py`、`tests/test_eagle_sync.py`、`tests/test_exporter.py`（session 视图 HTML 断言）。
  - 回写 [docs/specs/README.md](../README.md) 模块索引表。
- **数据契约**：`Asset.session_id` / `CutIndex.sessions` / `Session` 全部可选或有默认，向后兼容。**不 bump `SCHEMA_VERSION`**。
- **无 BREAKING**。

## 关键设计决策（grilling Q1–Q11 + 架构复议）

### Q1：行程边界判定
按素材时间排序，相邻两个 asset 间隔 `>= gap_hours` 就切一刀。理由：`modified_time` 已经在 scan 阶段就位，零成本；比"按日历日切"更符合"跨天连续拍摄仍是一段"的直觉。

### Q2：分层结构
扁平的活动段（`session_01`、`session_02`……）。**不做**"多天出行 = 顶层 + 每天多段 = 里层"的两级结构。理由：命名简单，产品第一版够用；如果未来用户需要"这一次东京行"的语义聚合，走 [todolist.md](../../todolist.md#L107-L131) 的 `project.yaml trips:` 那条路。

### Q3'：Eagle folder 一级平铺 + slug 前缀（Q13 修正）
早期 grilling 时定了"两级：项目父 folder + session 子 folder"，本轮修正为**一级平铺**，folder 名带项目 slug 前缀避免多项目撞名。理由：产品早期用户项目数少，父 folder 增加视觉层级而未带来收益；未来若多项目同时活跃，再回头加父 folder。

### Q4：Session 命名 `{slug} · {session_id} · {起始时间}`（Q14 敲定）
形如 `tokyo · session_01 · 2026-06-15 09:30`。分隔符 ` · `（中点带空格），避开 Eagle folder 名不支持的字符。`session_00_unknown` 简化为 `{slug} · session_00_unknown`（无时间）。

### Q5：存量 item 不迁移（=B）
`item/update` 无 `folderId`，无法把已同步的老 item 移入 folder。老 item 保持原状，写 warning。存量库补跑此功能形同虚设，但这个代价用户接受。

### Q6：无 CLI 参数（架构复议：从"塞进 sync-eagle"简化为"零参数默认"）
- session 切分在 scan 阶段自动发生，不需要 `analyze --stage session` 子命令。
- `sync-eagle` 默认按 session 建 folder，不需要 `--split-by-session` 开关。
- 切段阈值写死为常量 `SESSION_GAP_HOURS = 1.0`，不暴露 CLI。

### Q7：时间字段用 `modified_time`（=B）
纯启发式，简单实现。demo-scan 上验证过 `modified_time` 与视频 `creation_time` 差异 ≤ 60s，切段结果一致。EXIF 升级已进 todo。

### Q8：无阈值参数
见 Q6。默认 1 小时。

### Q9：`modified_time` 缺失归入 `session_00_unknown`
数据不丢，用户能一眼看到"这几条时间信息坏了"。

### Q10：复用现有分析前置条件
`sync-eagle` 现有的 `analysis_status == scanned` 阻断（[eagle_sync.py L737-L742](../../../src/tripclipper/eagle_sync.py#L737-L742)）不变。session 切分本身在 scan 阶段完成，与分析状态无关。

### Q11：Dry-run 输出 "Sessions preview"
见 What Changes §5。

### Q12：review.html 加 Session 视图（=B 中量方案）
在 §7 详述。选 B 不选 A（仅加列/过滤器）：session 是"分析结果的核心结构"，在核心视图里必须有专门呈现；也不选 C（时间轴 + 侧边导航）：本 spec 定位是"引入数据契约 + 呈现"，重量 UX 演进走增量。

### 架构复议：session 切分归"分析阶段"而非"同步阶段"
用户提问："这实际是一种素材的分析，放在分析环节合理吗？" — 是的。session 是"素材间关系分析"的结论（与 M4 `similar_group_id` 对偶），应该持久化到 cut_index.json，让 M6/M5/review.html 消费同一份产物。这个复议避免了未来 3 条演进路径（EXIF / LLM / project.yaml trips）需要返工。

## 待确认

- 旧项目（`sessions=[]`）同步到 Eagle 时，是否仍建项目父 folder？还是完全跳过 folder 逻辑、退化到 M6 原始行为？
- `session_00_unknown` 是否也需要建 folder，还是这些 asset 直接放项目父 folder 下？
- session 名字最终以 `session_id`（`session_01`）还是 `Q4 命名格式`（`session_01_2026-06-15_09-30`）作为 Eagle folder 名？
