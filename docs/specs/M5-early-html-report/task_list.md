# M5-early Tasks

> 阶段：实现阶段（apply）执行。当前 spec 已定稿（brainstorming Q1–Q10），代码尚未实现。
> 依赖前置：M0（`models`/`cut_index`/`paths`/`security`）、M1（`init_project` 已落地）、M2（`scan_project` 已写入 `thumbnail_path`/`metadata`）、M3（`sample_analyze`/`full_analyze` 已写入分析字段）。
> 纪律提醒（沿用 M3 Q1/Q2）：**测试零 mock、不许 skip**。本模块不直接调模型；fixture 用真 `cut_index.json`（手工构造或 M3 集成测产出），不构造伪造分析结果当真结果用。所有"端到端验证模型输出"靠人眼看 HTML 完成，不在自动化测试范围内。

- [x] Task 1：路径辅助（`src/tripclipper/paths.py`）
  - [x] SubTask 1.1：新增 `exports_dir(slug, base_dir=None) -> Path` —— 返回 `<base_dir>/projects/<slug>/exports/`，沿用现有 `cut_index_path`/`logs_dir` 风格；首次调用时不创建目录（写入时由 exporter 负责 `mkdir(parents=True, exist_ok=True)`）
  - [x] SubTask 1.2：新增 `review_html_path(slug, base_dir=None) -> Path` —— 返回 `exports_dir(slug, base_dir) / "review.html"`
  - [x] SubTask 1.3：`tests/test_paths.py`（如已存在则追加用例）覆盖 `exports_dir`/`review_html_path` 的拼接正确性

- [x] Task 2：HTML 模板（`src/tripclipper/templates/review.html.tmpl`）
  - [x] SubTask 2.1：单文件 HTML 骨架（`<!DOCTYPE html>` + `<head>` + `<body>`），含内联 `<style>`（约 60 行 CSS：`.row-pending` 淡黄背景、`.row-failed` 淡红背景、`.no-thumb` 灰色占位、`.status-analyzed/.status-scanned/.status-failed` 彩标颜色、表格基础样式）
  - [x] SubTask 2.2：HTML 占位符（`__VARNAME__` 风格，渲染时 `str.replace`）：
    - `__PROJECT_HEADER_HTML__`：项目头部信息块（项目名/slug/source_folder/analysis 状态摘要/素材计数/failures 列表）
    - `__TABLE_ROWS_HTML__`：素材表格 `<tr>` 集合
    - `__JSON_DATA__`：完整脱敏 cut_index JSON（用于行抽屉读取 metadata/segments/frame_paths 全图）
  - [x] SubTask 2.3：表格表头按 spec §HTML 视图设计 §3 渲染 15 列：缩略图 / 文件名 / 类型+时长 / 星级 / subject_type / people_presence / shot_scale / shot_function / tags / summary / segments / audio_strategy / similar_group / edit_candidate_status / analysis_status
  - [x] SubTask 2.4：顶部控件：`<input id="search">` 全局搜索框 + `<select id="filter-subject-type">`/`<select id="filter-shot-scale">`/`<select id="filter-status">` 三个筛选 `<select>`
  - [x] SubTask 2.5：内联原生 JS（约 80 行）：
    - 表头点击排序（toggle asc/desc，按字符串/数字自动判断）
    - 三个 `<select>` change 事件触发筛选（多筛选条件 AND）
    - 顶部 `<input>` input 事件触发模糊搜索（`filename` / `summary` / `tags` 任一命中即显示）
    - 行点击切换抽屉显示完整 metadata/segments/frame_paths（数据从 `window.__CUT_INDEX_DATA__ = __JSON_DATA__` 读取）
    - 抽屉里 frame_paths 用 `<img src="file:///...">` 显示全图
  - [x] SubTask 2.6：JS 严格只在 DOM 内操作，**绝不**发起任何 `fetch`/`XMLHttpRequest`/`<form action>`；HTML 顶部 `<meta http-equiv="Content-Security-Policy" content="default-src 'self' file: data:; script-src 'unsafe-inline'; style-src 'unsafe-inline'">` 防止外部资源（可选，加了更稳）

- [x] Task 3：渲染核心（`src/tripclipper/exporter.py`）
  - [x] SubTask 3.1：定义 `ExportError(Exception)`、模块级常量 `_TEMPLATE_PATH = Path(__file__).parent / "templates" / "review.html.tmpl"`
  - [x] SubTask 3.2：`_format_duration(seconds: float | None) -> str` —— 纯函数；`None`/`0` → `""`；否则返回 `mm:ss`
  - [x] SubTask 3.3：`_format_segments(segments: list[Segment] | None) -> str` —— 纯函数；`None`/`[]` → `"（无）"`；否则每段渲染 `<div class="segment">{mm:ss}-{mm:ss} {role}</div>`，多段拼接
  - [x] SubTask 3.4：`_format_status_class(status: AnalysisStatus | None) -> str` —— 纯函数；`analyzed` → `status-analyzed`、`scanned`/`analyzing` → `status-scanned`、`analysis_failed` → `status-failed`、`None`/其他 → `status-other`
  - [x] SubTask 3.5：`_format_row_class(status: AnalysisStatus | None) -> str` —— 纯函数；`analysis_failed` → `row-failed`、`scanned`/`analyzing` → `row-pending`、其他 → `""`
  - [x] SubTask 3.6：`_render_summary_cell(asset: Asset) -> str` —— 纯函数；`analysis_failed` 时取 `failures[-1].reason`（截 80 字符，HTML 转义）；`analyzed` 且 `summary` 非空时返回截断的 `summary`；`analyzed` 且 `summary` 为空 → `"（模型未生成 summary）"`；其他状态 → `"（待分析）"`
  - [x] SubTask 3.7：`_format_tags(tags: list[str] | None) -> str` —— 纯函数；`None`/`[]` → `""`；非空时取前 5 个 `, ` 拼接，超 5 个追加 ` (+{n-5})`
  - [x] SubTask 3.8：`_format_rating(rating: int | None) -> str` —— 纯函数；`None` → `""`；否则 `★` × rating + `☆` × (5-rating)
  - [x] SubTask 3.9：`_thumbnail_uri(asset: Asset, project_dir: Path) -> str | None` —— 纯函数；`thumbnail_path` 为空 → `None`；非空时返回 `file:///{绝对路径}`，**不**校验文件是否真的存在（前端 `<img onerror>` 兜底显示 `[无缩略图]`）
  - [x] SubTask 3.10：`_asset_to_row(asset: Asset, project_dir: Path) -> str` —— 纯函数。把单个 Asset 渲染为 `<tr>...<td>...</td></tr>` HTML 字符串。M4 字段 `similar_group` / `edit_candidate_status` 当前固定渲染 `"（待 M4）"`。所有用户文本（filename/summary/tags 等）经 `html.escape` 处理。`<tr>` 上写入 `data-asset-id`/`data-subject-type`/`data-shot-scale`/`data-status`/`data-rating` 五个 data 属性供 JS 筛选/排序读取
  - [x] SubTask 3.11：`_render_project_header(cut_index: CutIndex) -> str` —— 纯函数。渲染项目头部信息块：项目名/slug/source_folder（HTML 转义）；模型配置只展示 `provider`/`vision_model`/`api_key_env`（不展示密钥值）；`analysis` 状态摘要（含 `cut_index.analysis is None or analysis.status != "completed"` 时的"尚未运行 sample/full 分析"提示）；素材计数（总数/各类型/各 analysis_status 计数）；项目级 `failures` 列表（每条一行 `[stage] target: reason`）
  - [x] SubTask 3.12：`_dump_cut_index_json(cut_index: CutIndex) -> str` —— 纯函数。把 `CutIndex` 序列化为 JSON 字符串。**严格脱敏**：序列化前在副本上 `del cut_index.project.model_config`（用 `model_copy(deep=True)` 确保不污染原对象）。返回的 JSON 字符串需在 HTML 中安全嵌入（替换 `</script>` → `<\/script>`，避免脚本注入）
  - [x] SubTask 3.13：`render_review_html(slug: str, *, base_dir: Path | None = None) -> Path` —— 公共入口。`cut_index_path(slug, base_dir)` 不存在 → 抛 `ExportError("项目 `{slug}` 尚未初始化，请先运行 `tripclipper init`")`；读 `cut_index.json` → 渲染 3 个占位符 → `template.replace("__PROJECT_HEADER_HTML__", ...)` 等 → `exports_dir(slug, base_dir).mkdir(parents=True, exist_ok=True)` → 写入 `review_html_path(slug, base_dir)` → 返回该 Path

- [x] Task 4：CLI 接线（`src/tripclipper/cli.py`）
  - [x] SubTask 4.1：`tripclipper export <slug>` 从占位 `_PLACEHOLDER` 接线到实现；新增 `--html / --no-html`（默认 `True`）、`--open / --no-open`（默认 `False`）、`--base-dir`（沿用其他命令风格）
  - [x] SubTask 4.2：参数处理 —— 当 `--no-html` 时打印「M5-early 当前只支持 HTML 导出，CSV/MD 留给 M5 完整版」并 `sys.exit(2)`
  - [x] SubTask 4.3：调 `exporter.render_review_html(slug, base_dir=base_dir)` → 成功时 stdout 输出 `已生成 review.html: <绝对路径>` → `--open=True` 时调 `webbrowser.open(f"file://{path}")`
  - [x] SubTask 4.4：错误兜底 —— `ExportError` 以 `click.echo(f"导出失败：{exc}", err=True)` + `sys.exit(1)`；不抛裸堆栈

- [x] Task 5：忽略项与依赖
  - [x] SubTask 5.1：`.gitignore` 新增 `projects/*/exports/`（追加在 `projects/*/logs/` 之后）
  - [x] SubTask 5.2：检查 `pyproject.toml` —— 本模块**不引新依赖**（`webbrowser`/`html`/`json` 都是 stdlib），无需修改
  - [x] SubTask 5.3：`MANIFEST.in` 或 `pyproject.toml` 的 `[tool.setuptools.package-data]` 加入 `tripclipper.templates` 包数据，确保 `review.html.tmpl` 被打包（如项目用 setuptools/poetry 而非 src layout 自动包含，需手动声明）

- [x] Task 6：Unit 测试（`tests/test_exporter.py`）
  - 测试约定：**零 mock**。喂手工构造的 `CutIndex` 对象给纯函数，断言渲染输出包含/不包含特定字符串。不调 `Provider.analyze`，不构造伪造分析结果。
  - [x] SubTask 6.1：`_format_duration` —— `None`/`0`/`30.5`（00:30）/`125.0`（02:05）/`3661.0`（61:01）
  - [x] SubTask 6.2：`_format_segments` —— `None` → `"（无）"`；`[]` → `"（无）"`；单段 → 包含 `mm:ss-mm:ss role`；多段 → 多个 `<div class="segment">`
  - [x] SubTask 6.3：`_format_status_class` / `_format_row_class` —— 5 个 AnalysisStatus 值各一次 + `None`
  - [x] SubTask 6.4：`_render_summary_cell` —— `analysis_failed` 取 `failures[-1].reason`、80+ 字符截断；`analyzed` 且 summary 长 → 截断；`analyzed` 且 summary 空 → `"（模型未生成 summary）"`；`scanned` → `"（待分析）"`
  - [x] SubTask 6.5：`_format_tags` —— `None`/`[]`/3 个/5 个/8 个（`"a, b, c, d, e (+3)"`）
  - [x] SubTask 6.6：`_format_rating` —— `None`/`1`/`3`/`5`（断言星号字符数 == 5）
  - [x] SubTask 6.7：`_thumbnail_uri` —— 空字符串/`None` → `None`；非空相对路径 → `file:///` 前缀
  - [x] SubTask 6.8：`_asset_to_row` —— 完整 Asset 喂入，断言 HTML 含正确 data 属性、HTML 转义生效（`<` → `&lt;`）、M4 字段固定 `"（待 M4）"`
  - [x] SubTask 6.9：`_render_project_header` —— 含 / 不含 `analysis`、各种 `analysis.status` 值、有 / 无项目级 failures，断言"尚未运行 sample/full 分析"提示按 spec 触发
  - [x] SubTask 6.10：`_dump_cut_index_json` —— 断言输出 JSON **不**含 `model_config` 键、**不**含 `</script>` 字面值；原 cut_index 对象未被污染（model_config 仍在）
  - [x] SubTask 6.11：`render_review_html` 端到端 —— 用 `tmp_path` 构造完整项目目录（写入手工 `cut_index.json`，含 3 个素材：1 analyzed/1 scanned/1 analysis_failed），调用 `render_review_html`，断言：
    - 文件存在于 `tmp_path/projects/<slug>/exports/review.html`
    - HTML 含 `<table>` 与 3 个 `<tr data-asset-id=`
    - analysis_failed 行有 `class="row-failed"` 且 summary 列含 `failures[-1].reason`
    - similar_group / edit_candidate_status 列固定 `(待 M4)`
    - 头部信息块含项目名、不含密钥值（设 `os.environ["TRIPCLIPPER_MODEL_API_KEY"]="sk-leak-test"` 后断言 HTML 文本**不**含 `"sk-leak-test"`）
  - [x] SubTask 6.12：项目不存在 —— 调用 `render_review_html("not-exist-slug", base_dir=tmp_path)` 应抛 `ExportError`，文案含"尚未初始化"

- [x] Task 7：CLI 测试（`tests/test_cli_export.py`）
  - [x] SubTask 7.1：`click.testing.CliRunner` 跑 `tripclipper export <slug> --html`（用真 `cut_index.json` fixture），断言退出码 0、stdout 含「已生成 review.html」、文件存在
  - [x] SubTask 7.2：未初始化项目跑 `export <slug> --html` → 退出码非 0、stderr 含「尚未初始化」、不抛裸堆栈
  - [x] SubTask 7.3：`--no-html` → 退出码 2、stderr 含「M5-early 当前只支持 HTML 导出」
  - [x] SubTask 7.4：`--open` 不在测试里真打开浏览器 —— monkeypatch `webbrowser.open` 为计数器，断言被调用 1 次

- [x] Task 8：Integration 测试追加（`tests/test_integration_m3.py` 末尾）
  - [x] SubTask 8.1：在 `test_full_pipeline_sample_real_model` 末尾追加 —— 跑完 sample_analyze 后调 `render_review_html`，断言：
    - 返回 Path 存在
    - HTML 文本可解析（含 `<table>` 与 `<tbody>`）
    - 表格 `<tr data-asset-id=` 行数 == `cut_index.assets` 长度
    - 文本**不**含 API key 字面值（取 `os.environ["TRIPCLIPPER_MODEL_API_KEY"]`，按整字符串 `in` 判定）

- [x] Task 9：回写状态与文档
  - [x] SubTask 9.1：`docs/specs/README.md` 模块索引追加一行 `M5-early | 早期 HTML 验证报告 | FR-8 部分；TD 9（HTML） | M3 | 已完成`；调整其他模块的"建议执行顺序"段（在末尾追加一句说明"M3 → M5-early（HTML 验证）→ M4 → M5 完整版（CSV/MD）→ M6 → M7"）
  - [x] SubTask 9.2：实现与 spec 一致——表格列顺序、CSS class 名按 spec 落地，无需回写 spec
  - [x] SubTask 9.3：`pytest -q` 全绿（不含 M3 集成测，因其需要真实 API key；M5-early 新测试 28 项 + 全量非集成测 135 项均通过）

# Task Dependencies
- Task 2 依赖 Task 1（模板里 `__VARNAME__` 占位与 paths 无关，但 cli/exporter 都依赖 paths）
- Task 3 依赖 Task 1、Task 2（exporter 读模板、写到 paths）
- Task 4 依赖 Task 3（CLI 调 exporter）
- Task 5 与 Task 1~Task 4 独立
- Task 6（Unit）依赖 Task 1~Task 3
- Task 7（CLI）依赖 Task 4
- Task 8（Integration）依赖 Task 3，并需 M3 集成测原样能跑（已绿）
- Task 9 依赖 Task 1~Task 8 全绿
