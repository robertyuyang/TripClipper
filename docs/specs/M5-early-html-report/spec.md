# M5-early 早期 HTML 验证报告 Spec

> 状态：**定稿（待用户审）**。本文件由 brainstorming 会话（2026-06-28）的 §1–§4 决策定型而成。
> 覆盖：PRD FR-8（本地只读报告）、PRD §6.3、TD 9（review.html 部分）；**裁剪不覆盖** FR-7（CSV/MD 导出留给 M5 完整版）。
> 依赖：M0（`models`/`cut_index`/`paths`/`security`）、M1（`init_project` 已落地）、M2（`scan_project` 已写入 `thumbnail_path`/`metadata`）、M3（`sample_analyze`/`full_analyze` 已写入 `summary`/`tags`/`rating`/`subject_type`/...）。
> 角色：M5-early 是 **早期裁剪版的 M5**，只产出 `projects/<slug>/exports/review.html` 一个产物。它的**第一目的**是给用户在每个后续模块（M3 已完成；M4/M6 即将做）完成后提供一个**人类视觉验证视图**——打开 HTML，按缩略图 + summary 扫一遍，立刻判断模块跑得对不对。第二目的才是 PRD FR-8 的常规交付。

## Why

PRD §2 把"用户得到结构化数据包和本地只读报告"作为 MVP 核心交付之一；FR-8 §820–854 明确 review.html 应展示缩略图、星级、主体类型、人物存在、景别、镜头功能、tags、summary、雷同组状态、推荐片段、声音策略，并对未完成或失败素材有明确状态。

但 M3 已经完成、M4 还没开始，**当前的工程问题**是：每次跑完一个模块，作者只能 `cat cut_index.json | jq` 去读 JSON 去人工核对模型输出是否合理——既看不到缩略图，也看不到 summary 和星级是否对得上画面，验证成本远高于实际开发成本。这导致两个直接后果：(1) M3 之后的模块（M4 雷同分组、M6 Eagle 同步）继续累积，但作者无法稳定判断每一层产出是否真的对；(2) 真正的 M7 启动页要等 M1~M6 全部就位才能做，但启动页的"验证"职能其实只需要一个静态 HTML。

提前做"M5 的 HTML 部分"是**最便宜**的破局点：
- 单文件 HTML，无需启 server、无需引前端依赖；
- 复用 M3 已写入 `cut_index.json` 的字段；
- 对未完成的 M4 字段（`similar_group_id`/`edit_candidate_status`）graceful degrade 占位，M4 完成后只需替换占位渲染分支，不动表格结构；
- M4 完成后再走"M5 完整版"会话补 `assets.csv` / `segments.csv` / `summary.md` / `cut_index 副本`，本模块的 HTML 模板与渲染函数直接被复用、不重写。

## What Changes

- 新增核心模块 `src/tripclipper/exporter.py`：
  - `render_review_html(slug: str, *, base_dir: Path | None = None) -> Path`：纯函数（除写文件外无副作用）。读 `cut_index.json` → 把每个 `Asset` 摊平成模板上下文 dict → 用 `str.replace` 把 3 个 `__VARNAME__` 占位符替换为渲染好的 HTML 片段（见 Q5）→ 写到 `projects/<slug>/exports/review.html` → 返回该 Path。
  - `_asset_to_row(asset, project_dir) -> dict`：纯函数。把单个 `Asset` 模型对象摊平成行级 dict（含缩略图 file URI、星级渲染字符串、tags 截断、segments 渲染字符串、analysis_status 彩标 class 等）；对 M4 字段统一返回占位字符串 `"（待 M4）"`。
  - `_format_duration(seconds: float | None) -> str`：纯函数。`None` → `""`，否则 `mm:ss`。
  - `_format_segments(segments: list[Segment]) -> str`：纯函数。`[]` 或 `None` → `"（无）"`，否则每段 `mm:ss-mm:ss role`，多段以 `<br>` 连接。
  - `_format_status_class(status: AnalysisStatus | None) -> str`：纯函数。映射到 CSS class（`status-analyzed` / `status-scanned` / `status-failed` / `status-other`）。
  - `_render_summary_cell(asset) -> str`：`analysis_status="analysis_failed"` 时显示 `failures[-1].reason`（截断 80 字符），否则显示 `summary`（截断 80 字符）；空字符串返回 `"（待分析）"`。
  - `ExportError(Exception)`：项目不存在 / `cut_index.json` 不可读 / 写文件失败时抛出。
- 新增模板 `src/tripclipper/templates/review.html.tmpl`：单文件 HTML（含内联 CSS + 内联原生 JS），约 200~250 行。占位符：
  - `__PROJECT_HEADER_HTML__`：项目名、slug、source_folder、analysis 状态摘要、素材计数、failures 列表。
  - `__TABLE_ROWS_HTML__`：素材行 HTML（每行一个 `<tr data-asset-id="..." data-subject-type="..." data-shot-scale="..." data-status="...">`）。
  - `__JSON_DATA__`：完整 `cut_index.json` 序列化（用于行点击展开抽屉时取 metadata/segments/frame_paths 全图，避免再发请求）。**严格脱敏**：`__JSON_DATA__` 在序列化前删去 `model_config` 字段（沿用 M0 `summarize_model_config` 边界）。
- 新增 `src/tripclipper/paths.py` 辅助：`exports_dir(slug, base_dir) -> Path`、`review_html_path(slug, base_dir) -> Path`，沿用现有 `cut_index_path`/`logs_dir` 风格。
- 修改 [cli.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/cli.py#L425-L429)：`tripclipper export <slug>` 从占位接线到实现：
  - `--html / --no-html`（默认 `--html`）：是否产出 `review.html`。
  - `--open / --no-open`（默认 `--no-open`）：成功后是否用 `webbrowser.open` 打开生成的 HTML。
  - 其他 flag（`--csv`/`--md` 等）保持占位，留给 M5 完整版。
  - 错误兜底：`ExportError` 以面向用户文案打印 + `sys.exit(非0)`，不抛裸堆栈。
- 修改 `.gitignore`：新增 `projects/*/exports/`（与 `projects/*/logs/` 并列）。
- 新增 `tests/test_exporter.py`：纯函数 + 端到端 unit 测试。
- 新增 `tests/test_cli_export.py`：CLI 测试。
- 修改 `docs/specs/README.md`：模块索引追加一行 `M5-early | 早期 HTML 验证报告 | FR-8 部分；TD 9（HTML） | M3 | 待开始`，并在"建议执行顺序"段后追加一句说明：「M3 → M5-early（HTML 验证）→ M4 → M5 完整版（CSV/MD）→ M6 → M7。提前做 M5-early 是为了让后续模块完成后有低成本的视觉验证视图。」

不在 M5-early 范围（明确延后给 M5 完整版或对应模块）：
- **CSV/MD 导出 + cut_index 副本**：归 M5 完整版。
- **雷同组与默认候选**渲染逻辑（实际数据）：模板里有占位列，M4 完成后替换占位渲染分支即可。
- **Eagle 同步预览**：归 M6。
- **server 化 / 实时刷新**：归 M7（FastAPI 启动页）。
- **编辑/审核能力**：PRD §820–854 明确"第一版只读"；本模块严格只读。

## Impact

- 影响的能力：M3/M4/M6 完成后用户均可通过 `tripclipper export <slug>` 在浏览器里直观验证模型输出是否合理；M5 完整版后续接入时复用本模块的 `_asset_to_row` / 模板，避免重写。
- 影响的代码：
  - 新增 `src/tripclipper/exporter.py`、`src/tripclipper/templates/review.html.tmpl`。
  - 修改 `src/tripclipper/cli.py`（`export` 命令真接线）、`src/tripclipper/paths.py`（加 `exports_dir`/`review_html_path`）、`.gitignore`。
  - 新增 `tests/test_exporter.py`、`tests/test_cli_export.py`。
  - 回写 `docs/specs/README.md` 模块索引与执行顺序说明。
- 不改动 M0 数据契约与字段口径；M5-early 仅**消费** `CutIndex`/`Asset`/`AnalysisInfo`/`Segment`/`Failure`。无 **BREAKING**。

## 关键设计决策（brainstorming Q1–Q4）

### Q1 范围：只做 HTML，不做 CSV/MD
- M5 完整版的 5 样产物（`cut_index 副本` / `assets.csv` / `segments.csv` / `summary.md` / `review.html`）中，CSV/MD 不解决"验证模型输出是否合理"——它们是给后续自动化流程消费的、文本视图同样不带缩略图。
- 提前做这 4 样产物的边际价值低、对 M4 字段的依赖更深（CSV 的 `similar_selection`/`edit_candidate_status` 列必须等 M4），反而增加"M4 后回头改"的工作量。
- 决策：M5-early 只做 `review.html`；其余留给 M5 完整版会话一起做。

### Q2 缩略图引用：本地绝对路径（`file:///abs/path/to/thumb.jpg`）
- 候选方案 A（本地绝对路径）：HTML 里 `<img src="file:///...">`。生成快、文件小、浏览器加载快；**代价**：HTML 文件移动 / 复制到其他机器后路径失效。
- 候选方案 B（base64 内联）：所有缩略图读进内存转 base64 嵌入 HTML。文件可移动；**代价**：100+ 素材时 HTML 涨到几十 MB，浏览器打开变慢；生成阶段把所有缩略图读一遍，I/O 开销大。
- 决策：**方案 A**。本模块的目的是"作者本机验证"，HTML 不需要跨机器迁移；M5 完整版若需要可移植，可加 `--inline-images` flag 走 base64 路径。

### Q3 M4 字段处理：占位列
- 候选方案 A（占位列 `"（待 M4）"`）：模板里 `similar_group` / `edit_candidate_status` 两列存在，M4 完成前文本固定 `"（待 M4）"`，M4 完成后替换 `_asset_to_row` 中的渲染分支，**不动表格结构、不动 CSS**。
- 候选方案 B（M4 前不出该列）：当前 HTML 表格少两列，M4 完成后加列。
- 决策：**方案 A**。HTML 视图与 PRD §6.3 表头列一致；M4 → 完整版只改 `_asset_to_row` 里两个 if-else 分支，不改模板列结构。

### Q4 交互能力：嵌入原生 JS（筛选 + 排序 + 搜索 + 行抽屉）
- 候选方案 A（原生 JS）：约 80 行，无依赖。表头点击排序（升降切换）；`subject_type`/`shot_scale`/`analysis_status` 三列各一个 `<select>` 筛选；顶部一个 `<input>` 模糊匹配 `filename`/`summary`/`tags`；行点击展开抽屉（用 `__JSON_DATA__` 里取，不发请求）。
- 候选方案 B（纯静态表格）：所有素材按 ID 排序展示，靠浏览器 Cmd+F。当素材到 100+ 时无法快速找"1 星 / 失败 / 主体类型 = people"的子集。
- 决策：**方案 A**。验证场景的核心动作就是"筛 1-2 星 + 失败素材"和"按主体类型扫一批"；80 行原生 JS 的成本远低于人工逐行翻看。
- 不引 Vue/React/Alpine 等任何前端框架（YAGNI；模板复杂度远未到框架值得引入的阈值）。

### Q5 模板引擎：不引 jinja2
- 单模板、约 200 行 HTML、占位符仅 3 处（`__PROJECT_HEADER_HTML__` / `__TABLE_ROWS_HTML__` / `__JSON_DATA__`）。
- Python `string.Template`（只支持 `$varname` / `${varname}` 占位）足够；为避免和 HTML 内 `$` 字面值冲突，模板用自定义占位符 `__VARNAME__`，渲染时简单 `replace`。
- 决策：**手写字符串拼接**。M7 真做 FastAPI 启动页时再考虑 jinja2（FastAPI 自带）。

### Q6 命令形态：复用 `tripclipper export <slug> [--html] [--open]`
- 候选方案 A（复用 export）：合 M5 完整版的命令边界；M5 完整版补上 `--csv` / `--md` 等 flag，命令本身不变。
- 候选方案 B（新增 `review` 命令）：体验略好（一个动词专做一件事）；但 M5 完整版后会与 `export` 重叠、维护两条命令。
- 决策：**方案 A**。`export <slug> --html` 是 M5 完整版命令的真子集，M5 早做晚做，CLI 入口不变。

### Q7 spec 位置：单独建 `docs/specs/M5-early-html-report/`
- 维持"一个会话一个模块"纪律。
- M5 完整版另起 `docs/specs/M5-data-export/`，spec 中明确"复用 M5-early 的 `exporter.render_review_html`，新增 CSV/MD 导出函数"。
- README 模块索引加一行 M5-early、执行顺序加一句说明。
- 不修改"依赖图"——M5-early 在依赖关系上属于 M3 之后的可选并行分支，M4 → M5 完整版的主路径不变。

### Q8 测试纪律：沿用 M3 风格（零 mock、不 skipif、用真 cut_index 做 fixture）
- 单测用手工构造或 M3 集成测产出的真实 `cut_index.json` 作输入，断言渲染输出包含/不包含特定字符串（不构造伪造分析结果）。
- 集成测在 `tests/test_integration_m3.py` 末尾追加：跑完 sample_analyze 后立即调 `render_review_html`，断言文件生成、HTML 可解析（最低限度：含 `<table>` 与 `<tbody>`、行数 == `assets` 数）。
- CLI 测验证 `tripclipper export <slug> --html` 的退出码、stdout、文件存在性。
- "零 mock"解释：与 M3 同口径——约束的是"不许伪造分析结果当真写入 `cut_index.json`"，不是"不许给纯函数喂手工字符串"。

### Q9 安全边界：密钥脱敏
- `__JSON_DATA__` 序列化前 **删除** `cut_index.project.model_config` 字段（即使 M0 已规定 `model_config` 不存密钥本体，仍保守删除整段，避免未来字段扩展时漏脱敏）。
- 项目头部信息块只展示 `provider` / `vision_model` / `api_key_env`（即环境变量名，不是值），与 M1 `_print_summary` 一致。
- 单测断言 HTML 文本中**不**包含 `os.environ[api_key_env]` 的值字面值。

### Q10 graceful degrade 规则汇总
- `analysis_status != "analyzed"`：行高亮（CSS class `row-pending` / `row-failed`），summary 列展示"待分析"或 `failures[-1].reason`。
- `thumbnail_path` 为空 / 文件不存在：缩略图位置渲染 `<div class="no-thumb">[无缩略图]</div>`。
- `metadata` 为空 / `duration_seconds` 为空：时长列展示 `""`。
- `tags` 为空：tags 列展示 `""`；非空时截断到 5 个 + 提示总数（`tag1, tag2, ... (+3)`）。
- `summary` 为空且 `analysis_status="analyzed"`：列展示 `"（模型未生成 summary）"`（标记潜在异常）。
- `segments` 为空 / 缺失：推荐片段列展示 `"（无）"`。
- `similar_group_id` / `edit_candidate_status` 无论是否为空：当前固定展示 `"（待 M4）"`，M4 完成后改 `_asset_to_row` 渲染分支。
- `failures` 项目级：头部信息块列出，每条一行：`[stage] target: reason`。

## ADDED Requirements

### Requirement: 早期 HTML 验证报告 SHALL 由 `tripclipper export <slug> --html` 产出
系统 SHALL 提供命令 `tripclipper export <slug> [--html] [--open]`，默认 `--html`；执行后 SHALL 在 `projects/<slug>/exports/review.html` 写入单文件 HTML 报告，并在 `--open` 时调用系统浏览器打开。

#### Scenario: 项目已完成扫描与样本分析
- **WHEN** 用户对一个已跑过 `analyze --stage scan` 与 `analyze --stage sample` 的项目执行 `tripclipper export <slug> --html`
- **THEN** 系统 SHALL 在 `projects/<slug>/exports/review.html` 写入 HTML 文件，文件包含项目头部信息块、素材表格（行数 == `cut_index.assets` 长度）、表头筛选/排序/搜索控件、行点击抽屉
- **AND** CLI 退出码为 0、stdout 含 `已生成 review.html: <绝对路径>`

#### Scenario: 项目尚未初始化
- **WHEN** 用户对一个不存在的 slug 执行 `tripclipper export <slug> --html`
- **THEN** 系统 SHALL 以非 0 退出码结束、stderr 输出"项目 `<slug>` 尚未初始化，请先运行 `tripclipper init`"，**不**生成空 HTML

#### Scenario: 项目已扫描但尚未分析
- **WHEN** 用户对一个 `assets[*].analysis_status="scanned"`（无 `analyzed`）的项目执行 `--html`
- **THEN** 系统 SHALL 正常生成 HTML，每行 summary 列展示 `"（待分析）"`、行 CSS class 含 `row-pending`、`analysis_status` 彩标显示黄色
- **AND** 当 `cut_index.analysis` 为 `None` 或 `analysis.status != "completed"` 时，头部信息块明确提示"尚未运行 sample/full 分析"

#### Scenario: 部分素材分析失败
- **WHEN** `cut_index` 中含 `analysis_status="analysis_failed"` 素材
- **THEN** 该行 SHALL 高亮（CSS class `row-failed`）、summary 列展示 `failures[-1].reason`（截断 80 字符）、彩标显示红色

### Requirement: HTML 报告 SHALL 对未完成模块的字段 graceful degrade
HTML 表格的 `similar_group` / `edit_candidate_status` 列在 M4 完成前 SHALL 渲染固定占位文本 `"（待 M4）"`；M4 完成后 SHALL 切换为真实数据渲染。

### Requirement: HTML 报告 SHALL 不包含 API 密钥与敏感模型配置字面值
系统 SHALL 在 `__JSON_DATA__` 序列化前删去 `cut_index.project.model_config` 字段；HTML 文本（含头部、表格、JSON 数据块）SHALL NOT 出现 `os.environ[api_key_env]` 的值字面值，SHALL NOT 出现 `Authorization` header 字面值。Unit 测试 SHALL 断言此约束。

### Requirement: HTML 报告 SHALL 提供基础筛选/排序/搜索能力
系统 SHALL 在 HTML 内嵌入原生 JS，使用户能：
- 点击表头按列排序（升降切换）；
- 通过 `subject_type` / `shot_scale` / `analysis_status` 三个 `<select>` 单列筛选；
- 通过顶部 `<input>` 模糊匹配 `filename` / `summary` / `tags`（任一字段命中即显示）；
- 点击行展开抽屉显示完整 metadata、segments、frame_paths（数据从 HTML 内嵌的 `__JSON_DATA__` 读取，不发任何网络请求）。

### Requirement: HTML 报告 SHALL 严格只读
HTML 报告 SHALL NOT 提供任何修改 `cut_index.json` 或外部资源的能力；所有交互（排序/筛选/搜索/抽屉）仅在浏览器内 DOM 操作，SHALL NOT 发起网络请求。

### Requirement: `exports/` 目录 SHALL 加入 .gitignore
`projects/*/exports/` SHALL 加入 `.gitignore`（与 `projects/*/logs/` 同级），避免 HTML 报告与缩略图副本入仓库。

## MODIFIED Requirements

（暂无；M5-early 仅消费 M0 已定义字段，不修改既有契约。）

## REMOVED Requirements

（暂无。）

## 与 M5 完整版的边界（前向兼容承诺）

- M5 完整版会话 SHALL 复用本模块的 `exporter.render_review_html`，**不重写**该函数；新增 `render_assets_csv` / `render_segments_csv` / `render_summary_md` / `copy_cut_index` 等同级函数。
- M5 完整版会话 SHALL 在 `_asset_to_row` 中替换 `similar_group_id` / `edit_candidate_status` 的占位渲染为真实数据渲染；表格列结构、CSS、JS 不变。
- 本模块的模板占位符 (`__PROJECT_HEADER_HTML__` / `__TABLE_ROWS_HTML__` / `__JSON_DATA__`) 在 M5 完整版中保持向前兼容；M5 完整版若需扩展头部展示项，新增占位符而不修改既有。

## 验收口径（人类可执行）

1. 跑 `tripclipper export demo-scan --html`，检查 `projects/demo-scan/exports/review.html` 已生成。
2. 在浏览器打开该文件，肉眼确认：
   - 25 个样本素材的缩略图正常显示；
   - 每行 summary 与缩略图画面一致（这是 M3 模型输出质量的视觉验证）；
   - 星级、subject_type、shot_scale、shot_function 与缩略图主观判断匹配；
   - 表头点击能排序、三个筛选 `<select>` 能筛选、搜索框能搜出含关键词的行；
   - 点击任一行能展开抽屉看到完整 metadata 与 segments；
   - `similar_group` / `edit_candidate_status` 两列固定显示 `"（待 M4）"`；
   - 失败素材行红色高亮，summary 列显示失败原因。
3. 跑 `grep -F "$TRIPCLIPPER_MODEL_API_KEY" projects/demo-scan/exports/review.html` 应返回空（密钥不出现）。
