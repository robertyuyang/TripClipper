# 把 M4 决策接入 review.html Spec

> 状态：**待用户审**。本文件为 M4 完成后兑现 [M5-early spec.md](../M5-early-html-report/spec.md) §22-47 "M4 完成后替换占位渲染分支"承诺的增量交付。
> 覆盖：PRD FR-6（相似组识别）的可视化层、PRD FR-8（review.html）剩余的两个占位列，以及一个组级聚合面板。
> 依赖：M4-similar-clustering（已完成）、M5-early-html-report（已完成）。
> 不在范围：CSV/MD 导出（留给 M5 完整版）、可编辑能力（PRD 明确"第一版只读"）、server 化（M7）。

## Why

M4 已经在 [cut_index.json](file:///Users/bytedance/Documents/TripClipper_Trae/projects/demo-scan/cut_index.json) 写入 `similar_groups` / `default_candidates` / `clustering` / `assets[*].similar_*` / `assets[*].edit_candidate_*` 完整字段，但 [exporter.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/exporter.py#L350-L376) 的 `_asset_to_row` 仍把 `similar_group` / `edit_candidate_status` 两列硬编码成 `"（待 M4）"` 占位符 —— 这是 M5-early 时刻意留下的 graceful degrade 分支，M4 落地后应当兑现。

光把两列换上真值（选项 1）只能让用户"在表里看到 M4 写了什么"。要做到 PRD FR-6 期望的"用户在浏览器里**直观判断 M4 决策得好不好**"，需要让用户**一组一组按缩略图横向对比**：primary / alternate / rejected 各是哪几条素材，confidence 多高，basis 是什么，每条素材的中文 reason 是什么。表格行单看是不够的，因为 9 条素材里只有 2 条进了 group，用户翻表很难"成组"地看。

所以做"完整 M4 视图"（选项 2）：表格行单元格填真值 + 表格上方加一块"相似组面板"按组卡片化展示。

## What Changes

### 1. 表格内两列接入真数据（兑现 M5-early 承诺）

[exporter.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/exporter.py) 替换两个 `placeholder_m4` 占位：

- **similar_group 列**：
  - 无组（`similar_selection in {None, "none"}`）→ 空字符串
  - 有组 → 主行 `group_id · selection · rank=N`；下一行用 `<span class="muted">` 显示 `similar_reason`（截断 80 字符）
  - 配色：`primary` 绿色、`alternate` 蓝色、`rejected` 灰色、`needs_review` 橙色
- **edit_candidate_status 列**：
  - `default_selected` → `default_selected · priority=N`，绿色
  - `alternate` / `excluded` / `needs_review` → 状态文本，颜色区分
  - 第二行用 `<span class="muted">` 显示 `edit_candidate_reason`（截断 80 字符）
  - `None` → 空（理论不出现，仅防御）

### 2. 新增"相似组面板"区块

模板新增 `__SIMILAR_GROUPS_HTML__` 占位符，位于项目头之下、controls 之上。渲染规则：

- 没有 `similar_groups` 或全部为空时 → 整块不渲染（不留空容器）。
- 每个 `SimilarGroup` 一个 `<div class="group-card">`，包含：
  - **卡片头**：`group_id` · `confidence`（百分比，`needs_review=True` 时加"待人工确认"红色 chip）· basis（中文逗号连接）
  - **成员列表**（按 `similar_rank` 升序）：
    - 缩略图（80×60，沿用 `_thumbnail_uris` 第一张）
    - 文件名 + asset_id 末 6 位
    - `similar_selection` 状态 chip（与列内同色板一致）
    - `similar_reason` 中文文本（仅 `analyzed` 素材有；空则隐藏）
    - 星级 `★★★★☆`
  - 点击成员行 → 滚动表格到对应 `<tr>` 并临时高亮 1.5s（`background-color` transition）

### 3. 表格行"同组联动高亮"

每个 `<tr.asset-row>` 加 `data-similar-group-id` 属性。JS 监听 `mouseenter` / `mouseleave`，当前行有 group 时给同组其他行加 `.same-group-hover` 类（淡蓝背景）。无组的行不触发。

### 4. controls 区新增筛选

在现有 `subject_type` / `shot_scale` / `analysis_status` 三个 `<select>` 之后追加：

- `<select id="filter-similar">`：`全部 / 仅相似组成员 / 仅非相似组`
- `<select id="filter-candidate">`：`全部 / default_selected / alternate / excluded / needs_review`

筛选与既有逻辑串联（and 关系）。

### 5. 表头

`similar_group` 列表头由"similar_group"改为"相似组"，`edit_candidate_status` 改为"候选池状态"。data-key 不变，保持排序兼容。

### 6. 不变项（明确锁定）

- 模板**列数不变**（保持 15 列），仅替换两列内容 + 新增上方面板。
- CSP 头不变。
- `__JSON_DATA__` 序列化与脱敏边界（`model_config_summary` 清空）不变。
- 抽屉（点击行展开 metadata pre 块）逻辑不变。
- 排序、搜索、`subject_type` / `shot_scale` / `analysis_status` 筛选逻辑不变。

## Impact

- 影响的能力：M3/M4 跑完后，用户可在 review.html 直观核对 Arbiter 的 primary/alternate 决策与候选池入选/落选逻辑。
- 影响的代码：
  - 修改 [exporter.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/exporter.py)：替换两列占位、新增 `_format_similar_cell` / `_format_candidate_cell` / `_render_similar_groups_section` 三个纯函数、`_asset_to_row` 增加 `data-similar-group-id` 属性、`render_review_html` 增加 `__SIMILAR_GROUPS_HTML__` 替换。
  - 修改 [review.html.tmpl](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/templates/review.html.tmpl)：新增占位符、新增组面板 CSS、表头中文化、controls 新增两个 select、JS 增补筛选 + 联动高亮 + 跳转滚动。
  - 修改 [tests/test_exporter.py](file:///Users/bytedance/Documents/TripClipper_Trae/tests/test_exporter.py)：新增组面板渲染、两列单元格渲染、空 group 不渲染面板、demo-scan 真数据渲染 4 类断言。
  - 修改 [tests/test_cli_export.py](file:///Users/bytedance/Documents/TripClipper_Trae/tests/test_cli_export.py)：补一个 M4 数据 fixture 的端到端断言（output 含组卡片 + 两列真数据）。
  - 更新 [docs/specs/README.md](file:///Users/bytedance/Documents/TripClipper_Trae/docs/specs/README.md) 模块索引追加本 change 行。
- 不改动 M0 数据契约。无 **BREAKING**。

## ADDED Requirements

### Requirement: 表格 similar_group 列展示真实组信息

系统 SHALL 在 review.html 的 `similar_group` 列对**有组成员**渲染 `group_id · selection · rank=N`，并在第二行显示截断后的 `similar_reason`。

#### Scenario: primary 成员
- **WHEN** asset 的 `similar_selection="primary"` 且 `similar_group_id="group_1"`、`similar_rank=1`、`similar_reason="画面清晰稳定，构图完整"`
- **THEN** 该单元格 HTML 包含 `group_1` 与 `primary` 与 `rank=1` 三处文本
- **AND** 第二行 `<span class="muted">画面清晰稳定，构图完整</span>`
- **AND** `primary` 文本使用 `.sel-primary`（绿色）class

#### Scenario: 无组成员
- **WHEN** asset 的 `similar_selection in {None, "none"}`
- **THEN** 该单元格内容为空字符串（不渲染 `（待 M4）` 占位符）

#### Scenario: needs_review 成员
- **WHEN** asset 的 `similar_selection="needs_review"`
- **THEN** 状态 chip 使用 `.sel-needs-review`（橙色）class
- **AND** 第二行显示 `similar_reason`（如"组内置信度不足，待人工确认"）

### Requirement: 表格 candidate 列展示候选池状态与原因

系统 SHALL 在 `edit_candidate_status` 列渲染状态 + 优先级 + 截断后的 `edit_candidate_reason`。

#### Scenario: 默认入选
- **WHEN** asset 的 `edit_candidate_status="default_selected"` 且 `edit_candidate_priority=3`
- **THEN** 单元格首行包含 `default_selected · priority=3`
- **AND** 第二行 `<span class="muted">非雷同高星素材，默认入选</span>`

#### Scenario: 为平衡降为 alternate
- **WHEN** asset 的 `edit_candidate_status="alternate"` 且 `edit_candidate_reason="为景别平衡入选 alternate"`
- **THEN** 单元格第二行包含中文 reason 截断后内容
- **AND** 状态文本不再附 priority（`alternate` / `excluded` / `needs_review` 无 priority）

### Requirement: 顶部"相似组面板"按组卡片化展示

系统 SHALL 在项目头之下、controls 之上渲染一组 `<div class="group-card">`，每个 SimilarGroup 一张卡。

#### Scenario: 有效组
- **WHEN** `cut.similar_groups` 含一组 `group_1`、`primary=asset_A`、`alternate=[asset_B]`、`confidence=0.85`、`basis=["同一景点","相近构图"]`、`needs_review=False`
- **THEN** 页面包含一个 `.group-card`，卡片头含 `group_1` 与 `85%` 与 `同一景点` 与 `相近构图`
- **AND** 卡片内 2 行成员，按 `similar_rank` 升序排列
- **AND** 每行含缩略图 `<img src="file://..."`、文件名、selection chip、similar_reason、星级
- **AND** 不渲染 `needs_review` chip

#### Scenario: 整组 needs_review
- **WHEN** `group.needs_review=True`
- **THEN** 卡片头追加 `<span class="chip-warn">待人工确认</span>`（红/橙色 chip）

#### Scenario: 没有相似组
- **WHEN** `cut.similar_groups` 为空列表
- **THEN** 页面不渲染 `.group-card` 容器，也不留空 `<section>`
- **AND** 模板中 `__SIMILAR_GROUPS_HTML__` 替换为空字符串

### Requirement: 同组行联动高亮

系统 SHALL 在 `<tr.asset-row>` 上挂 `data-similar-group-id` 属性；JS 监听 hover 事件，把同组其他行临时加 `.same-group-hover` class。

#### Scenario: hover 进组成员
- **WHEN** 用户鼠标进入 `data-similar-group-id="group_1"` 的行
- **THEN** 所有其他 `data-similar-group-id="group_1"` 的行获得 `.same-group-hover` class
- **AND** 当前行不被加该 class（自己已经有 `:hover` 视觉）

#### Scenario: hover 离开
- **WHEN** 鼠标离开当前行
- **THEN** 所有同组行移除 `.same-group-hover`

#### Scenario: hover 无组成员
- **WHEN** 用户 hover 的行 `data-similar-group-id=""`
- **THEN** 不触发任何联动

### Requirement: 组卡片成员点击跳转到表格行

系统 SHALL 在组卡片每个成员行上挂 click，跳转到表格中对应的 `<tr>` 并临时高亮 1.5s。

#### Scenario: 点击成员
- **WHEN** 用户点击组卡片里 asset_id=`asset_0bca48` 的成员行
- **THEN** 页面滚动到 `<tr data-asset-id="asset_0bca48">` 进入视口
- **AND** 该 `<tr>` 临时加 `.flash` class（黄色背景 transition），1500ms 后移除

### Requirement: controls 区新增两个筛选

系统 SHALL 在 controls 区追加两个 `<select>`：`#filter-similar`（全部 / 仅相似组成员 / 仅非相似组）与 `#filter-candidate`（全部 / default_selected / alternate / excluded / needs_review）。

#### Scenario: 仅相似组成员
- **WHEN** 用户选择 `filter-similar=in-group`
- **THEN** 仅 `data-similar-group-id` 非空的行显示
- **AND** 行数计数器更新

#### Scenario: 候选池筛选
- **WHEN** 用户选择 `filter-candidate=default_selected`
- **THEN** 仅 `data-edit-candidate-status=default_selected` 的行显示
- **AND** 与既有 search / subject_type / shot_scale / status / similar 筛选 AND 组合

## MODIFIED Requirements

### Requirement: 表格列数与列序

复用 [M5-early spec](../M5-early-html-report/spec.md) 中表格列定义；本 change **不增删列**，仅：
- 把表头 `similar_group` 中文化为"相似组"
- 把表头 `edit_candidate_status` 中文化为"候选池状态"
- 替换 `_asset_to_row` 中这两列内容

### Requirement: 模板占位符集合

由 M5-early 的三个（`__PROJECT_HEADER_HTML__` / `__TABLE_ROWS_HTML__` / `__JSON_DATA__`）扩展为四个，新增 `__SIMILAR_GROUPS_HTML__`。其他占位符语义与脱敏边界**不变**。

## REMOVED Requirements

### Requirement: M4 字段占位符 `（待 M4）`
**Reason**：M4 已落地，[cut_index.json](file:///Users/bytedance/Documents/TripClipper_Trae/projects/demo-scan/cut_index.json) 已经写入完整字段；占位文本不再有意义。
**Migration**：[exporter.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/exporter.py#L350) 中 `placeholder_m4 = '<span class="placeholder-m4">（待 M4）</span>'` 与 `.placeholder-m4` CSS 一并删除。
