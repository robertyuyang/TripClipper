# Check List — 把 M4 决策接入 review.html

> 阶段：实施前的验收清单。所有项必须在本 change 标"已完成"前逐项勾选。
> 验收纪律：与 M5-early 同——**单测白盒断言 HTML 结构 + class + data-* 属性；视觉部分用户主导，不写 selenium。**

## A. 文档与决策一致性

- [x] [spec.md](spec.md) 引用 PRD FR-6 / FR-8、M5-early spec 第 22-47 行的"M4 完成后替换占位渲染分支"承诺
- [x] [task_list.md](task_list.md) 11 个 Task 与 spec.md 中 7 个 Requirement 一一对应（5 ADDED + 2 MODIFIED + 1 REMOVED = 8 项，其中 REMOVED 不需单独 Task，归入 Task 6.1）
- [x] [docs/specs/README.md](file:///Users/bytedance/Documents/TripClipper_Trae/docs/specs/README.md) 模块索引追加本 change 一行

## B. 数据契约不动

- [x] 本 change **不修改** [models.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/models.py) 任何字段；仅消费 M4 已写入的 `similar_groups` / `default_candidates` / `assets[*].similar_*` / `edit_candidate_*`
- [x] M0/M1/M2/M3/M4 既有 pytest 用例无回归（运行 `.venv/bin/python -m pytest tests/ --ignore=tests/test_integration_m4.py --ignore=tests/test_integration_m3.py` 全通过）

## C. similar_group 列单元格渲染

- [x] `_format_similar_cell` 纯函数存在且不依赖文件 IO / 网络
- [x] `similar_selection=None / "none"` → 返回 `""`（不渲染 `（待 M4）`）
- [x] `similar_selection="primary"` → 单元格含 `group_id` + `primary` + `rank=1` 三段，`primary` 包在 `<span class="sel-primary">` 内
- [x] `similar_selection` ∈ {alternate, rejected, needs_review} 各自的 css class 渲染正确（`sel-alternate` / `sel-rejected` / `sel-needs-review`）
- [x] `similar_reason` 非空时第二行 `<span class="muted">` 显示截断后内容
- [x] `similar_reason` 长度 100 时截断到 79 + 省略号（中文按 unicode 字符计）

## D. edit_candidate_status 列单元格渲染

- [x] `_format_candidate_cell` 纯函数存在
- [x] `edit_candidate_status=None` → 返回 `""`
- [x] `default_selected` → 单元格含 `default_selected` + `priority=N`，且 `default_selected` 包在 `<span class="cand-default">` 内
- [x] `alternate` / `excluded` / `needs_review` 各自 css class 渲染正确，且**不**附 priority
- [x] `edit_candidate_reason` 非空时第二行 `<span class="muted">` 显示截断后内容

## E. 相似组面板渲染

- [x] `_render_similar_groups_section` 纯函数存在
- [x] `cut.similar_groups=[]` → 返回 `""`（模板替换后页面不含 `class="group-card"` 与 `<section class="similar-groups">`）
- [x] `similar_groups` 含 1 组、`confidence=0.85` → 卡头含 `group_1` + `85%`
- [x] `confidence=None` → 卡头无百分号
- [x] `basis=["同一景点","相近构图"]` → 渲染 2 个 `.basis-chip` 元素，文本顺序与 basis 一致
- [x] `needs_review=True` → 卡头追加 `<span class="chip-warn">待人工确认</span>`
- [x] 成员列表按 `similar_rank` 升序排列（None 末尾）
- [x] 每个成员行含 `<img class="group-thumb">` 或 `<div class="no-thumb-mini">×</div>`、文件名、selection chip、similar_reason（仅有时）、星级
- [x] 每个成员 `<li>` 含 `data-asset-id="{aid}"`，供 JS click 跳转

## F. _asset_to_row 增改

- [x] `placeholder_m4` 局部变量与两处占位使用全部移除
- [x] `<tr>` 含 `data-similar-group-id="{gid or ''}"`、`data-edit-candidate-status="{status or ''}"` 两个新属性
- [x] 其他 data-* 属性保持原样（asset-id / subject-type / shot-scale / status / rating / search）

## G. 模板（review.html.tmpl）

- [x] 新增 `__SIMILAR_GROUPS_HTML__` 占位符（紧接 `__PROJECT_HEADER_HTML__` 之后、`<div class="controls">` 之前）
- [x] 表头 `similar_group` 改为"相似组"、`edit_candidate_status` 改为"候选池状态"；`data-key` 不变
- [x] controls 区追加 `#filter-similar` 与 `#filter-candidate` 两个 `<select>`
- [x] CSS 新增：`.similar-groups`、`.group-card`、`.basis-chip`、`.chip-warn`、`.members`、`.group-thumb`、`.no-thumb-mini`、`.muted`、`.sel-primary/alternate/rejected/needs-review`、`.cand-default/alternate/excluded/needs-review`、`.same-group-hover`、`.flash` + `@keyframes flash`
- [x] CSS 删除：`.placeholder-m4`
- [x] JS `applyFilters` 增加 in-group / not-in-group / 候选池等值匹配分支
- [x] JS 新增 `.members li` click → `scrollIntoView` + `.flash` 1500ms
- [x] JS 新增 `<tr.asset-row>` mouseenter/leave → 同组其他行 `.same-group-hover` 切换
- [x] 列数保持 15 列（thead `<th>` 计数）
- [x] CSP 头不变；JSON 注入边界 `</script>` 转义不变

## H. render_review_html 主入口

- [x] 调用 `_render_similar_groups_section(cut_index)` 拿到 groups_html
- [x] `template.replace` 链含 `__SIMILAR_GROUPS_HTML__` 替换
- [x] 原有 `__PROJECT_HEADER_HTML__` / `__TABLE_ROWS_HTML__` / `__JSON_DATA__` 替换顺序与脱敏边界不变

## I. 单元测试

- [x] `_format_similar_cell` 单测 5+1 用例（4 selection + none + 截断）
- [x] `_format_candidate_cell` 单测 5 用例（4 status + None）
- [x] `_render_similar_groups_section` 单测 ≥ 4 用例（有组/空组/confidence None/needs_review）
- [x] `_asset_to_row` 含 data-similar-group-id / data-edit-candidate-status 属性的断言
- [x] `render_review_html` 端到端用例：有组 / 无组各 1 个

## J. demo-scan 真数据渲染（端到端）

- [x] `test_render_demo_scan_includes_group_card`：含 `class="group-card"`、`group_1`、置信度百分号、basis chip 文本、primary 行 asset_id
- [x] `test_render_demo_scan_table_cells_have_real_m4`：不含 `（待 M4）` 字面；至少 1 处 `sel-primary`；至少 7 处 `cand-default`
- [x] `test_render_no_groups_omits_section`：手工构造无组 cut_index，渲染输出不含 `group-card`、不含字面 `__SIMILAR_GROUPS_HTML__`

## K. CLI 端到端

- [x] [test_cli_export.py](file:///Users/bytedance/Documents/TripClipper_Trae/tests/test_cli_export.py) 新增 fixture 含 M4 数据
- [x] `test_export_with_m4_data_renders_group_card` 跑 CliRunner，读 review.html 文本，断言含 `group-card` / `sel-primary` / `cand-default`

## L. 人工视觉验收（用户主导）

- [x] 跑 `.venv/bin/tripclipper export demo-scan --html --open`，浏览器打开 review.html
- [x] 组面板可见，含 1 张 `group_1` 卡片
- [x] 卡片成员点击 → 表格行黄色 flash 1.5s
- [x] 表内 primary 行 `sel-primary`（绿）、alternate 行 `sel-alternate`（蓝）
- [x] hover primary 行时 alternate 行变浅蓝（`same-group-hover`）
- [x] `filter-similar=in-group` 工作（只剩 2 行）
- [x] `filter-candidate=alternate` 工作
- [x] devtools console 无 CSP 错误、无 JS 错误

## M. 验收终判

- [x] 上述 A-L 全部勾选完成
- [x] [docs/specs/README.md](file:///Users/bytedance/Documents/TripClipper_Trae/docs/specs/README.md) wire-m4-into-review-html 行状态更新为"已完成"
