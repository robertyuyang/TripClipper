# M5 数据包导出与报告补全 Spec

> 状态：**待用户审**。本文件由 2026-06-29 会话讨论定稿，作为 [M5-early spec](../M5-early-html-report/spec.md) 的兑现与补全，对照 PRD §FR-7「数据包导出」做了显著裁剪。
> 覆盖：PRD FR-7（裁剪版）、FR-8 剩余「项目级聚合视图」部分、TD 9 中 review.html 的头部聚合区。
> 依赖：M3、M4、M5-early、wire-m4-into-review-html（均已完成）。

## Why

[M5-early spec](../M5-early-html-report/spec.md) §「与 M5 完整版的边界」承诺 M5 完整版会补齐四样东西：`assets.csv` / `segments.csv` / `summary.md` / `cut_index 副本`。回顾这四件事在 MVP 实际使用场景下的价值，**只有 `cut_index 副本` 站得住**：

| 候选产物 | 想象用途 | 真实评估 | 决策 |
| --- | --- | --- | --- |
| `cut_index 副本` | 不可变快照、机器可读事实源（PRD FR-7「机器可读项目索引」） | 与活动状态 `cut_index.json` 解耦，保证导出快照不被后续 `analyze --force` / `cluster --rerun` 覆写；M6 Eagle 同步、未来回归对比都需要这个稳定基线 | **做** |
| `assets.csv` | Excel/Numbers 筛选、给协作者 | review.html 的表头排序 + 三组筛选器 + 搜索框已完整覆盖筛选场景；MVP 单人使用没有"发给协作者"的真实场景；CSV 是 cut_index.json 的有损扁平化副本（segments / similar_groups 拍平失真），多一处维护点 | **砍** |
| `segments.csv` | 片段级筛选 | 同上；且 segments 时间码由模型基于静态帧推断，置信度本就偏低（详见 [trustworthy-clip-timecodes spec](../trustworthy-clip-timecodes/spec.md)），把不准的数据「正式化」到 CSV 反向放大问题 | **砍** |
| `summary.md` | 项目级聚合摘要 | 同一份数据换个媒介——若是 MVP 内部使用，review.html 头部加一个「总览条」即可（rating 分布 + 雷同组计数 + 待人工确认计数），完全覆盖；若是发给外部读者，目前没这个场景 | **合并到 review.html 头部** |

PRD FR-7 §806 写「输出：机器可读项目索引、素材级表格、片段级表格和项目总结」，§816「表格字段可用于筛选」与 §817「项目总结能帮助用户快速理解可用素材分布」。本模块的裁剪兑现方式：

- **机器可读项目索引**：由 `exports/cut_index.json` 副本兑现。
- **素材级表格 / 片段级表格 / 「筛选」诉求**：由 [review.html](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/templates/review.html.tmpl) 兑现（FR-8 范围内已实现完整筛选/排序/搜索）。
- **项目总结**：由 review.html 头部新增「总览条」兑现；新增 CLI stdout 摘要兑现「跑完一眼看到结果」诉求。

CSV/MD 不进 MVP 主路径。若后续真出现「需要发给非命令行用户一份表格」的具体场景，再起独立 change 补 `render_assets_csv`，本模块的目录结构与 path helper 已为它留好位置。

## What Changes

### 1. `tripclipper export <slug>` 产出 `exports/cut_index.json` 副本

- 修改 [exporter.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/exporter.py)：新增 `copy_cut_index(slug, *, base_dir=None) -> Path`。
  - 读 `projects/<slug>/cut_index.json` → 用 `CutIndex` 反序列化 → 调用 [`_dump_cut_index_json`](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/exporter.py#L655-L665) 以**相同的脱敏边界**序列化（`project.model_config_summary` 清空，沿用 M5-early Q9 安全决策）→ 写入 `projects/<slug>/exports/cut_index.json`。
  - 与活动 `cut_index.json` 解耦：副本是不可变快照，后续 `analyze --force` / `cluster` 不会再触它；下一次 `tripclipper export` 才会覆写。
- 新增 [paths.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/paths.py) 辅助：`exported_cut_index_path(slug, base_dir) -> Path`，返回 `projects/<slug>/exports/cut_index.json`。

### 2. review.html 头部新增「总览条」

- 修改 [exporter.py `_render_project_header`](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/exporter.py#L578-L652)：在现有 `<dl>` 之后、`notice_html` 之前新增 `overview_html` 区块，包含三组聚合数据：
  - **rating 分布**：`★5 ×N · ★4 ×N · ★3 ×N · ★2 ×N · ★1 ×N · 未评级 ×N`（统计 `assets[*].rating`，`None` 计入「未评级」）。
  - **相似组聚合**：`相似组 N 个（共 M 条素材；K 条待人工确认）`，数据来自 `cut_index.similar_groups`（无组时整行隐藏）。
  - **候选池聚合**：`候选池：default_selected ×N · alternate ×N · excluded ×N · needs_review ×N`（统计 `assets[*].edit_candidate_status`，`None` 不计入；全为 `None` 时整行隐藏）。
- 模板侧：复用现有 `__PROJECT_HEADER_HTML__` 占位符——`_render_project_header` 的返回值字符串里直接拼入总览条；**不**新增模板占位符。
- CSS：新增 `.overview` / `.overview-row` 两个轻量样式（行式排版、12~13px 字号、灰底浅蓝边）。无 JS 改动。

### 3. CLI 跑完打印 stdout 摘要

- 修改 [cli.py `export` 命令](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/cli.py#L489-L504)：成功后追加打印一段聚合摘要到 stdout：

  ```
  已生成 review.html: /abs/path/to/projects/<slug>/exports/review.html
  已生成 cut_index 副本: /abs/path/to/projects/<slug>/exports/cut_index.json

  📊 项目「<project_name>」总览
    素材总数：N（video=N, image=N）
    分析状态：analyzed=N, scanned=N, analysis_failed=N
    rating 分布：★5 ×N · ★4 ×N · ★3 ×N · ★2 ×N · ★1 ×N · 未评级 ×N
    相似组：N 个（共 M 条；K 条待人工确认）
    候选池：default_selected ×N · alternate ×N · excluded ×N · needs_review ×N
  ```

- 摘要数据由新增的纯函数 `_summarise_for_stdout(cut_index: CutIndex) -> str` 产出，**与 review.html 总览条共用同一组聚合逻辑**（提取到 `_compute_overview_counts(cut_index) -> OverviewCounts` 纯函数，输出 `dataclass`，两边消费）。
- 当 `cut_index.similar_groups` / `assets[*].edit_candidate_status` 为空时，对应行省略而非显示 "0 个"，保持输出简洁。

### 4. CLI flag 裁剪 + 错误兜底

- 当前 [export 命令](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/cli.py#L475-L504) 含 `--html/--no-html` + `--open/--no-open` 两个 flag。`--no-html` 当前会以 exit code 2 退出报错（M5-early 占位）。
- 本模块**移除** `--no-html` 这个语义：导出始终输出 `review.html` + `cut_index.json` 两件。`--html` flag 保留作兼容（不再有 `--no-html`），即把 `--html/--no-html` 改为单一无值 flag 或直接删除。
- **决策**：直接删除 `--html/--no-html` flag，简化命令面板。Export 命令的契约变成「跑就两件都出」。
- 新增 `--cut-index-only` flag（默认 `False`）：用于回归测试 / 自动化场景，跳过 HTML 渲染只写 cut_index 副本，加速。
- `--open/--no-open` 保留不变。
- 错误兜底沿用 M5-early：`ExportError` 以面向用户文案打印 + `sys.exit(非0)`。

### 5. 清理 paths.py 的死代码

- 删除 [paths.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/paths.py) 中未被消费的三个 helper：`assets_csv_path` / `segments_csv_path` / `summary_md_path`（grep 确认 src/ 与 tests/ 都没消费者；docstring 顶部布局示意里同步删除对应文件名）。
- 这是 YAGNI 收口的物理体现：path helper 存在会暗示「未来要实现 renderer」，删除以避免误导。

### 6. 不变项（明确锁定）

- `cut_index.json`（活动文件）schema 不变；副本只是同 schema 的拷贝。
- review.html 模板的 `__PROJECT_HEADER_HTML__` / `__TABLE_ROWS_HTML__` / `__JSON_DATA__` / `__SIMILAR_GROUPS_HTML__` 四个占位符不变。
- 表格列结构、行抽屉、筛选 / 排序 / 搜索 JS 行为不变。
- M5-early Q9 的脱敏边界（`model_config_summary` 清空）继续适用于副本与 review.html。

## Impact

- 影响的能力：
  - `tripclipper export <slug>` 成为 M5 完整版形态：产出 review.html + cut_index 副本，并打印项目级摘要。
  - M6 Eagle 同步与未来回归脚本可消费 `exports/cut_index.json` 作为稳定基线。
  - 用户在不打开浏览器的情况下，仅靠 CLI 输出即可判断「这批跑得怎么样」。
- 影响的代码：
  - 修改 [exporter.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/exporter.py)：新增 `copy_cut_index` / `_compute_overview_counts` / `_summarise_for_stdout` / `_render_overview_section`；改 `_render_project_header` 拼入总览条；改 `render_review_html` 不变；移除文件头 docstring 中关于 `assets.csv` 等的描述（若有）。
  - 修改 [cli.py `export` 命令](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/cli.py#L470-L504)：删除 `--html/--no-html`、新增 `--cut-index-only`、调用 `copy_cut_index` 与 `_summarise_for_stdout`。
  - 修改 [paths.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/paths.py)：新增 `exported_cut_index_path`；删除 `assets_csv_path` / `segments_csv_path` / `summary_md_path` 及对应 `__all__` 与 docstring 条目。
  - 修改 [templates/review.html.tmpl](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/templates/review.html.tmpl)：新增 `.overview` / `.overview-row` CSS。
  - 修改 [tests/test_exporter.py](file:///Users/bytedance/Documents/TripClipper_Trae/tests/test_exporter.py)：新增 `_compute_overview_counts` / 总览条 HTML / `copy_cut_index` 三组单测。
  - 修改 [tests/test_cli_export.py](file:///Users/bytedance/Documents/TripClipper_Trae/tests/test_cli_export.py)：新增 stdout 摘要断言、`--cut-index-only` 行为断言、移除对 `--no-html` 报错的断言。
  - 更新 [docs/specs/README.md](file:///Users/bytedance/Documents/TripClipper_Trae/docs/specs/README.md) 模块索引：M5 行状态 → 「待开始」改「定稿（待用户审）/ 开发中」。
- 不改 M0 数据契约。无 **BREAKING**（除 CLI flag `--no-html` 移除——MVP 内部命令，无外部消费者，可接受）。

## ADDED Requirements

### Requirement: `tripclipper export <slug>` SHALL 产出 review.html 与 cut_index 副本两件

系统 SHALL 在执行 `tripclipper export <slug>` 时同时产出 `projects/<slug>/exports/review.html` 与 `projects/<slug>/exports/cut_index.json` 两个文件。

#### Scenario: 默认行为
- **WHEN** 用户对一个已完成 sample/full 分析的项目执行 `tripclipper export <slug>`
- **THEN** 系统 SHALL 在 `exports/` 下生成 `review.html` 与 `cut_index.json` 两个文件
- **AND** stdout 包含两个文件的绝对路径

#### Scenario: 仅写 cut_index 副本
- **WHEN** 用户执行 `tripclipper export <slug> --cut-index-only`
- **THEN** 系统 SHALL 仅生成 `exports/cut_index.json`，不渲染 `review.html`
- **AND** stdout 不包含 `review.html` 路径行

### Requirement: cut_index 副本 SHALL 与活动文件解耦且脱敏

副本 SHALL 是不可变快照，后续 `analyze --force` / `cluster` 不重写副本，仅 `tripclipper export` 重写。副本序列化 SHALL 沿用 M5-early Q9 决策清空 `project.model_config_summary` 字段。

#### Scenario: 副本独立于活动文件
- **WHEN** 用户在 `tripclipper export` 后执行 `tripclipper analyze --stage sample --force`
- **THEN** `projects/<slug>/cut_index.json` SHALL 被覆写
- **AND** `projects/<slug>/exports/cut_index.json` SHALL 保持不变

#### Scenario: 副本脱敏
- **WHEN** 用户执行 `tripclipper export <slug>` 后读取副本
- **THEN** 副本 JSON 中 `project.model_config_summary` SHALL 为空对象 `{}`
- **AND** 副本中 SHALL NOT 出现 `os.environ[api_key_env]` 的值字面值

### Requirement: review.html 头部 SHALL 渲染项目级总览条

review.html 头部信息块 SHALL 在现有 `<dl>` 之后渲染一段「总览条」，包含 rating 分布、相似组聚合、候选池聚合三组数据。

#### Scenario: 完整数据
- **WHEN** 项目含 10 条 analyzed 素材（rating: 5,5,4,4,4,3,2,None,None,None）、1 个相似组（3 成员、0 待人工确认）、6 条 default_selected / 3 条 alternate / 0 条 excluded / 1 条 needs_review
- **THEN** 头部包含文本 `★5 ×2 · ★4 ×3 · ★3 ×1 · ★2 ×1 · ★1 ×0 · 未评级 ×3`
- **AND** 包含 `相似组 1 个（共 3 条；0 条待人工确认）`
- **AND** 包含 `候选池：default_selected ×6 · alternate ×3 · excluded ×0 · needs_review ×1`

#### Scenario: 无相似组
- **WHEN** `cut_index.similar_groups` 为空列表
- **THEN** 头部 SHALL NOT 渲染相似组聚合行（整行省略，而非显示 `相似组 0 个`）

#### Scenario: 无候选池
- **WHEN** 所有素材 `edit_candidate_status` 均为 `None`
- **THEN** 头部 SHALL NOT 渲染候选池聚合行

### Requirement: `tripclipper export` SHALL 在 stdout 打印项目级聚合摘要

CLI 在导出成功后 SHALL 打印一段不超过 10 行的中文摘要，覆盖素材总数、按类型计数、按 analysis_status 计数、rating 分布、相似组聚合、候选池聚合。

#### Scenario: 跑完一眼可读
- **WHEN** 用户执行 `tripclipper export <slug>`
- **THEN** stdout 在文件路径行之后 SHALL 包含 `📊 项目「<project_name>」总览` 标题行
- **AND** 包含至少四行明细：素材总数、分析状态、rating 分布、（如适用）相似组、（如适用）候选池

#### Scenario: 摘要数据与 review.html 总览条一致
- **WHEN** 同一次 export
- **THEN** stdout rating 分布的数字与 review.html 头部总览条 rating 分布的数字 SHALL 完全一致（由共享纯函数 `_compute_overview_counts` 保证）

### Requirement: paths.py SHALL 移除未使用的 CSV/MD 路径辅助

[paths.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/paths.py) SHALL 删除 `assets_csv_path` / `segments_csv_path` / `summary_md_path` 三个 helper 及其 `__all__` 条目与 docstring 中对应文件名。

#### Scenario: import 应失败
- **WHEN** 任何代码尝试 `from tripclipper.paths import assets_csv_path`
- **THEN** SHALL 抛出 `ImportError`（确认无残留消费者）

## MODIFIED Requirements

### Requirement: `tripclipper export <slug>` 命令面板

由 M5-early 的 `--html/--no-html` + `--open/--no-open` 调整为 `--cut-index-only` + `--open/--no-open`：
- 移除 `--html/--no-html`：导出始终包含 review.html，除非显式 `--cut-index-only`。
- 新增 `--cut-index-only`：跳过 review.html，仅写 cut_index 副本（用于自动化 / 回归）。
- 保留 `--open/--no-open`：成功后是否打开 HTML（`--cut-index-only` 时无效，给提示）。

### Requirement: PRD §FR-7「数据包导出」MVP 兑现方式

PRD §806 的「机器可读项目索引、素材级表格、片段级表格和项目总结」四件输出 SHALL 按以下方式在 MVP 阶段兑现：
- **机器可读项目索引**：`exports/cut_index.json` 副本（本模块）。
- **素材级表格 / 片段级表格 / 表格字段筛选**：由 [review.html](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/templates/review.html.tmpl) 表格 + 表头筛选/排序/搜索覆盖（FR-8 已实现）。CSV 输出明确**不在 MVP 范围**。
- **项目总结**：由 review.html 头部「总览条」+ CLI stdout 摘要兑现。

## REMOVED Requirements

### Requirement: M5 完整版的 `assets.csv` / `segments.csv` / `summary.md` 产出
**Reason**：见 §Why 评估表——三者在 MVP 单人使用场景下无真实消费者；CSV 是 cut_index.json 的有损扁平化副本，多一处维护点；summary.md 与 review.html 头部总览条信息重复，二选一保留更轻的视图。
**Migration**：
- `assets.csv` / `segments.csv`：将「筛选 / 排序 / 搜索」诉求引导至 review.html 表头控件。若未来出现「需要给非命令行用户一份表格」的具体场景，再起独立 change 增量补 `render_assets_csv`。
- `summary.md`：聚合数据已迁移到 review.html 头部「总览条」与 CLI stdout 摘要。`paths.py:summary_md_path` 一并删除。

## 与未来模块的边界

- **M6 Eagle 同步** SHALL 消费 `exports/cut_index.json` 副本（不可变基线），不直接读 `cut_index.json` 活动文件，避免同步过程中被并发的 `analyze` 改变状态。
- 若未来回归出现「需要把 cut_index 关键字段拍平给 BI 工具消费」的需求，可在本模块基础上增量加 `render_assets_csv` / `render_segments_csv`，无需重写 export 命令骨架。

## 验收口径（人类可执行）

1. 在已跑过 `analyze --stage sample` 的项目（如 `demo-scan`）上跑 `tripclipper export demo-scan`：
   - `projects/demo-scan/exports/review.html` 与 `projects/demo-scan/exports/cut_index.json` 同时生成。
   - stdout 含 `已生成 review.html: ...` 与 `已生成 cut_index 副本: ...` 两行，以及一段 `📊 项目「...」总览` 标题的中文摘要。
2. 在浏览器打开 `review.html`，头部应在原有「项目名 / slug / source_folder / ...」`<dl>` 之后出现一行总览条，含 rating 分布、相似组（demo-scan 有 1 组）、候选池三组聚合数字。
3. 跑 `tripclipper export demo-scan --cut-index-only`：仅 `cut_index.json` 被覆写，`review.html` mtime 不变。
4. 验证副本与活动文件解耦：跑 `tripclipper export demo-scan` 后立即跑 `tripclipper analyze --stage sample demo-scan --force`，对比 `cut_index.json` 与 `exports/cut_index.json` 文件 SHA256：前者变化，后者保持原值。
5. 验证脱敏：`grep -F "$TRIPCLIPPER_MODEL_API_KEY" projects/demo-scan/exports/cut_index.json` 应为空；`jq '.project.model_config_summary' projects/demo-scan/exports/cut_index.json` 应为 `{}`。
6. 验证 paths.py 清理：`python -c "from tripclipper.paths import assets_csv_path"` SHALL 报 `ImportError`。
