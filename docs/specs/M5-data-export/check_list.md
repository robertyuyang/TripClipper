# Check List — M5 数据包导出与报告补全

> 阶段：实施前的验收清单。所有项必须在本 change 标「已完成」前逐项勾选。
> 验收纪律：与 M3/M4/M5-early 同——单测白盒断言 + demo-scan 真数据端到端 + CLI stdout 断言；视觉部分用户主导，不写 selenium。

## A. 文档与决策一致性

- [x] [spec.md](spec.md) 明确把 PRD §FR-7 的 CSV/MD 输出列入 REMOVED Requirements 并解释裁剪原因
- [x] [spec.md](spec.md) 明确兑现路径：cut_index 副本 + review.html 表格 + review.html 头部总览条 + CLI stdout 摘要
- [x] [task_list.md](task_list.md) 12 个 Task 与 spec.md 中 6 个 Requirement 一一覆盖（5 ADDED + 2 MODIFIED + 1 REMOVED）
- [x] [docs/specs/README.md](file:///Users/bytedance/Documents/TripClipper_Trae/docs/specs/README.md) M5 行状态在审阅完成后更新

## B. 数据契约不动

- [x] 本 change **不修改** [models.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/models.py) 任何字段
- [x] M0~M4、M5-early、wire-m4-into-review-html 既有 pytest 用例无回归（`.venv/bin/python -m pytest tests/ --ignore=tests/test_integration_m3.py --ignore=tests/test_integration_m4.py` 全通过）
- [x] M5-early Q9 安全边界继承：副本与 HTML 均不出现 `model_config_summary` 非空内容

## C. `_compute_overview_counts` 纯函数

- [x] 函数存在且不依赖 IO / 网络
- [x] 返回 `OverviewCounts` dataclass（frozen=True）
- [x] `rating_distribution` 6 个 key 全存在（1, 2, 3, 4, 5, None），缺者补 0
- [x] `candidate_counts` 4 个 key 全存在（default_selected / alternate / excluded / needs_review），缺者补 0
- [x] `similar_group_count` / `similar_member_count` / `similar_needs_review_count` 从 `cut_index.similar_groups` 正确累计
- [x] 单测：完整数据、空 similar_groups、全 None candidate、空 assets 共 4 用例全过

## D. `_render_overview_section` 纯函数

- [x] 函数存在
- [x] 输出含 `<div class="overview">` 外层容器
- [x] rating 分布行始终渲染：含 `★5 ×N · ★4 ×N · ★3 ×N · ★2 ×N · ★1 ×N · 未评级 ×N` 字面
- [x] `similar_group_count > 0` → 渲染相似组行，文本含 `相似组 N 个（共 M 条；K 条待人工确认）`
- [x] `similar_group_count == 0` → **不**渲染相似组行（不输出 `相似组 0 个`）
- [x] 候选池四值之和 > 0 → 渲染候选池行，文本含 `候选池：default_selected ×N · alternate ×N · excluded ×N · needs_review ×N`
- [x] 候选池四值之和 == 0 → **不**渲染候选池行
- [x] 单测：完整数据、无组、无候选池、全空 共 4 用例全过

## E. 总览条接入 `_render_project_header`

- [x] 总览条在 `<dl>` 之后、`notice_html`/`failures_html` 之前渲染
- [x] 既有 `_render_project_header` 单测无回归（原 `<dl>` 内容、failures 块、notice 块仍按原口径渲染）
- [x] 新增断言：输出 HTML 含 `class="overview"`

## F. `copy_cut_index` 纯函数

- [x] 函数存在，签名 `(slug, *, base_dir=None) -> Path`
- [x] 调用既有 `_dump_cut_index_json` 序列化，**沿用同一脱敏边界**
- [x] 写入路径 `projects/<slug>/exports/cut_index.json`，目录不存在时自动创建
- [x] 项目不存在 → 抛 `ExportError`
- [x] 单测：正常路径、副本独立性、不存在 slug、脱敏边界 共 4 用例全过

## G. `_summarise_for_stdout` 纯函数

- [x] 函数存在，签名 `(cut_index: CutIndex) -> str`
- [x] 消费 `_compute_overview_counts` 输出（**不重复实现聚合**）
- [x] 输出首行 `📊 项目「{project_name}」总览`
- [x] 第 2 行 `素材总数：N（video=N, image=N）`
- [x] 第 3 行 `分析状态：analyzed=N, scanned=N, analysis_failed=N`
- [x] 第 4 行 rating 分布（始终在）
- [x] 第 5 行（如适用）相似组聚合
- [x] 第 6 行（如适用）候选池聚合
- [x] 数字与 review.html 总览条字面**逐项一致**（共享 `_compute_overview_counts`）
- [x] 单测：完整数据、无组、全 None 候选池 共 3 用例全过

## H. CLI `export` 命令重构

- [x] `--html/--no-html` flag **已移除**
- [x] `--cut-index-only` flag 新增（默认 False）
- [x] `--open/--no-open` flag 保留
- [x] 默认行为：同时写 review.html + cut_index 副本，并打印 stdout 摘要
- [x] `--cut-index-only`：仅写 cut_index 副本，stdout 不含 review.html 路径行
- [x] `--cut-index-only --open` 组合：webbrowser 不被调用，stderr 含警告
- [x] `ExportError` 兜底：面向用户文案 + 非 0 退出

## I. paths.py 死代码清理

- [x] `assets_csv_path` / `segments_csv_path` / `summary_md_path` 三个函数已删除
- [x] `__all__` 中三个条目已删除
- [x] 文件头 docstring 中 `assets.csv` / `segments.csv` / `summary.md` 三行已删除
- [x] grep `assets_csv_path|segments_csv_path|summary_md_path` 在 `src/` 与 `tests/` 无任何匹配（test 用 import 失败断言除外）
- [x] 新增 `exported_cut_index_path` helper，加入 `__all__`
- [x] docstring 顶部布局图含 `exports/cut_index.json` 与 `exports/review.html` 两行

## J. 模板（review.html.tmpl）

- [x] 新增 `.overview` / `.overview-row` CSS
- [x] **未**新增任何模板占位符（总览条由 Python 侧拼入 `__PROJECT_HEADER_HTML__`）
- [x] 原 4 个占位符（`__PROJECT_HEADER_HTML__` / `__TABLE_ROWS_HTML__` / `__JSON_DATA__` / `__SIMILAR_GROUPS_HTML__`）语义不变
- [x] 表格列结构、行抽屉、筛选/排序/搜索 JS 行为不变

## K. demo-scan 真数据端到端

- [x] `test_render_demo_scan_includes_overview_section`：含 `.overview` class、`★5 ×` 字面、`相似组 1 个` 字面、`候选池：default_selected ×` 字面
- [x] `test_render_no_groups_omits_overview_similar_row`：手工构造无组数据，渲染输出**不含** `相似组` 字面
- [x] `test_copy_cut_index_demo_scan_end_to_end`：副本 `model_config_summary == {}`，`assets` 长度与活动文件一致

## L. CLI 端到端

- [x] `test_export_writes_both_files_and_prints_summary`：默认 export 写两个文件、stdout 含两路径行 + 摘要
- [x] `test_export_cut_index_only`：仅写 cut_index 副本、stdout 不含 review.html 行、含摘要
- [x] `test_export_open_with_cut_index_only_warns`：stderr 含冲突警告、webbrowser 不被调用
- [x] 既有 `test_export_no_html_*` 已移除或改为「不识别 --no-html」断言

## M. 人工视觉验收（用户主导）

- [ ] `tripclipper export demo-scan --open` 浏览器打开 review.html，头部总览条三行可见、数字与 stdout 摘要一致
- [ ] `tripclipper export demo-scan --cut-index-only` 终端仅打印副本路径 + 摘要，无 review.html 行
- [ ] 验证副本与活动文件解耦：`export` 后 SHA1，再跑 `analyze --force`，活动 cut_index SHA 变化、副本 SHA 不变
- [ ] 验证脱敏：`grep -F "$TRIPCLIPPER_MODEL_API_KEY" projects/demo-scan/exports/cut_index.json` 返回空；`jq '.project.model_config_summary' projects/demo-scan/exports/cut_index.json` 输出 `{}`

## N. 验收终判

- [ ] 上述 A-M 全部勾选完成
- [ ] [docs/specs/README.md](file:///Users/bytedance/Documents/TripClipper_Trae/docs/specs/README.md) M5 行状态更新为「已完成」
- [x] [exporter.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/exporter.py) 文件头 module docstring 中 `M5-early` 表述升级为 `M5`
