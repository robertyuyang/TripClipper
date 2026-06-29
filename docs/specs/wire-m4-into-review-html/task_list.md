# Tasks — 把 M4 决策接入 review.html

> 阶段：实施前的有序工作清单。每项任务都对应 [spec.md](spec.md) 中的一个或一组 Requirement。
> 实施纪律：与 M3/M4 一致——**单测覆盖纯函数 + 完整 demo-scan 端到端用真 cut_index.json 渲染断言**。HTML 模板的 JS 交互不写 selenium / playwright，靠"渲染出的 HTML 结构 + class + data-* 属性"做白盒断言；视觉部分由用户亲自 open 确认。

## Task 列表

- [x] Task 1：纯函数：similar_group 单元格渲染（spec ADDED §"表格 similar_group 列"）
  - [x] SubTask 1.1：新增 `_format_similar_cell(asset: Asset) -> str` 纯函数
        签名：接受 Asset，返回 `<td>` 内 HTML。
        分支：
          - `similar_selection in (None, SimilarSelection.none)` → 返回 `""`
          - 否则首行 `{group_id} · <span class="sel-{sel_class}">{selection}</span> · rank={rank}`，其中 `sel_class ∈ {primary,alternate,rejected,needs-review}`
          - 第二行（若 `similar_reason` 非空）`<br><span class="muted">{truncate(reason, 80)}</span>`
        全部用户文本走 `html.escape`。
  - [x] SubTask 1.2：单测 `test_format_similar_cell_*`（5 用例）：primary 含完整三段 + reason muted；alternate；rejected；needs_review；none 返回空串。
  - [x] SubTask 1.3：截断单测：`similar_reason` 长度 100 → 截到 79+省略号；含中文计数按 unicode 字符。

- [x] Task 2：纯函数：edit_candidate_status 单元格渲染（spec ADDED §"表格 candidate 列"）
  - [x] SubTask 2.1：新增 `_format_candidate_cell(asset: Asset) -> str` 纯函数
        签名：接受 Asset，返回 `<td>` 内 HTML。
        分支：
          - `edit_candidate_status is None` → 返回 `""`
          - `default_selected` → `<span class="cand-default">default_selected</span> · priority={n}`
          - 其他三态 → `<span class="cand-{state}">{state}</span>`（无 priority）
          - 第二行（若 `edit_candidate_reason` 非空）`<br><span class="muted">{truncate(reason, 80)}</span>`
  - [x] SubTask 2.2：单测 `test_format_candidate_cell_*`（5 用例）：default_selected + priority + reason；alternate（无 priority、有 reason）；excluded；needs_review；None 返回空串。

- [x] Task 3：纯函数：相似组面板渲染（spec ADDED §"相似组面板"）
  - [x] SubTask 3.1：新增 `_render_similar_groups_section(cut: CutIndex) -> str` 纯函数
        - `cut.similar_groups` 为空 → 返回 `""`
        - 否则返回完整 `<section class="similar-groups">...</section>`
        - 每个 SimilarGroup 一个 `<div class="group-card" data-group-id="{gid}">`
        - 卡片头：
          - `<h3>{group_id} · 置信度 {pct}%</h3>` 当 `confidence` 是 number 时（`pct = round(confidence*100)`）；None 时省略置信度段
          - basis chips：每个 basis 一个 `<span class="basis-chip">{b}</span>`
          - 若 `needs_review` → 追加 `<span class="chip-warn">待人工确认</span>`
        - 成员列表 `<ul class="members">`，按 `similar_rank` 升序（None 排末尾）：
          - 每行 `<li data-asset-id="{aid}">`
          - 缩略图：`<img class="group-thumb" src="{first_thumb_uri}">`；无则 `<div class="no-thumb-mini">×</div>`
          - 文件名 + asset_id 末 6 位（灰色）
          - selection chip（同 Task 1 配色）
          - similar_reason（若有，截 80 字）
          - 星级（沿用 `_format_rating`）
  - [x] SubTask 3.2：单测：单组 + primary/alternate；needs_review 卡头含 chip-warn；空 similar_groups → 空串；confidence=None → 卡头无百分号。

- [x] Task 4：修改 `_asset_to_row`（spec MODIFIED §"列序"+ ADDED §"同组联动"）
  - [x] SubTask 4.1：移除 `placeholder_m4` 局部变量与两处占位符使用，替换为 `_format_similar_cell(asset)` 与 `_format_candidate_cell(asset)`。
  - [x] SubTask 4.2：`<tr>` 标签上追加 `data-similar-group-id="{asset.similar_group_id or ''}"` 与 `data-edit-candidate-status="{enum_value(asset.edit_candidate_status)}"`。
  - [x] SubTask 4.3：现有 `test_asset_to_row` 风格单测加 1 个 primary 行 + 1 个无组行，断言 data-* 属性出现与否。

- [x] Task 5：修改 `render_review_html` 主入口
  - [x] SubTask 5.1：调 `_render_similar_groups_section(cut_index)` 拿 `groups_html`。
  - [x] SubTask 5.2：在 template.replace 链中追加 `.replace("__SIMILAR_GROUPS_HTML__", groups_html)`。
  - [x] SubTask 5.3：端到端单测（用 tmp_path + 手工构造 CutIndex）：似 M5-early 既有 `test_render_review_html_*` 风格，新增 `test_render_review_html_with_groups` 与 `test_render_review_html_no_groups`。

- [x] Task 6：修改 [review.html.tmpl](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/templates/review.html.tmpl)
  - [x] SubTask 6.1：新增 CSS 块（在 `</style>` 之前）：
        - `.similar-groups { margin: 8px 0 12px; }`
        - `.group-card { background: #fff; border: 1px solid #d0d7e2; border-radius: 6px; padding: 10px 14px; margin-bottom: 8px; }`
        - `.group-card h3 { font-size: 13px; margin: 0 0 6px; display: flex; align-items: center; gap: 6px; }`
        - `.basis-chip { display: inline-block; background: #eef3fa; color: #2a5db0; padding: 1px 8px; border-radius: 10px; font-size: 11px; font-weight: normal; }`
        - `.chip-warn { background: #fff3e0; color: #c47200; padding: 1px 8px; border-radius: 10px; font-size: 11px; }`
        - `.members { list-style: none; padding: 0; margin: 0; }`
        - `.members li { display: grid; grid-template-columns: 100px 1fr auto auto; gap: 10px; align-items: center; padding: 4px 0; border-top: 1px dashed #eee; cursor: pointer; }`
        - `.members li:first-child { border-top: none; }`
        - `.members li:hover { background: #f5f9ff; }`
        - `.group-thumb { width: 100px; max-height: 70px; object-fit: cover; border-radius: 3px; }`
        - `.no-thumb-mini { width: 100px; height: 60px; background: #eee; display: flex; align-items: center; justify-content: center; color: #888; font-size: 18px; border-radius: 3px; }`
        - `.muted { color: #888; font-size: 11px; }`
        - `.sel-primary { color: #2a8a2a; font-weight: 600; }`
        - `.sel-alternate { color: #1e60c2; }`
        - `.sel-rejected { color: #888; }`
        - `.sel-needs-review { color: #c47200; }`
        - `.cand-default { color: #2a8a2a; font-weight: 600; }`
        - `.cand-alternate { color: #1e60c2; }`
        - `.cand-excluded { color: #888; }`
        - `.cand-needs-review { color: #c47200; }`
        - `tr.same-group-hover { background: #eaf3ff !important; }`
        - `tr.flash { animation: flash 1.5s ease-out; }`
        - `@keyframes flash { 0% { background: #fff3a8; } 100% { background: transparent; } }`
        - 删除既有 `.placeholder-m4 { ... }` 行
  - [x] SubTask 6.2：在 `__PROJECT_HEADER_HTML__` 之后、`<div class="controls">` 之前插入 `__SIMILAR_GROUPS_HTML__` 占位符（独占一行）。
  - [x] SubTask 6.3：表头：`<th data-key="similar_group">similar_group</th>` → `<th data-key="similar_group">相似组</th>`；`<th data-key="edit_candidate_status">edit_candidate_status</th>` → `<th data-key="edit_candidate_status">候选池状态</th>`。data-key 不变。
  - [x] SubTask 6.4：controls 区追加两个 select（紧接 `filter-status` 之后）：
        ```html
        <select id="filter-similar">
          <option value="">相似组: 全部</option>
          <option value="in-group">仅相似组成员</option>
          <option value="not-in-group">仅非相似组</option>
        </select>
        <select id="filter-candidate">
          <option value="">候选池: 全部</option>
          <option value="default_selected">default_selected</option>
          <option value="alternate">alternate</option>
          <option value="excluded">excluded</option>
          <option value="needs_review">needs_review</option>
        </select>
        ```
  - [x] SubTask 6.5：JS `applyFilters` 增加两个新筛选条件分支（in-group：`r.getAttribute('data-similar-group-id') !== ''`；候选池：等值匹配 `data-edit-candidate-status`）；事件监听追加这两个 select id。
  - [x] SubTask 6.6：JS 新增组卡成员点击 → 滚动表格行 + flash：
        ```js
        document.querySelectorAll('.members li').forEach(function(li){
          li.addEventListener('click', function(){
            var aid = li.getAttribute('data-asset-id');
            if (!aid) return;
            var tr = document.querySelector('tr.asset-row[data-asset-id="' + aid + '"]');
            if (!tr) return;
            tr.scrollIntoView({behavior: 'smooth', block: 'center'});
            tr.classList.add('flash');
            setTimeout(function(){ tr.classList.remove('flash'); }, 1500);
          });
        });
        ```
  - [x] SubTask 6.7：JS 新增行 hover → 同组联动：
        ```js
        rows.forEach(function(r){
          var gid = r.getAttribute('data-similar-group-id') || '';
          if (!gid) return;
          r.addEventListener('mouseenter', function(){
            rows.forEach(function(other){
              if (other !== r && other.getAttribute('data-similar-group-id') === gid){
                other.classList.add('same-group-hover');
              }
            });
          });
          r.addEventListener('mouseleave', function(){
            rows.forEach(function(other){ other.classList.remove('same-group-hover'); });
          });
        });
        ```

- [x] Task 7：删除 `.placeholder-m4` CSS（spec REMOVED）
  - 在 Task 6.1 一并删；该 class 现在源码中无引用。

- [x] Task 8：端到端 demo-scan 渲染断言（[test_exporter.py](file:///Users/bytedance/Documents/TripClipper_Trae/tests/test_exporter.py)）
  - [x] SubTask 8.1：新增 `test_render_demo_scan_includes_group_card`：用 `Path("projects/demo-scan/cut_index.json")` 真数据渲染（不写入磁盘，调 render→读 review.html），断言输出 HTML 含：
        - `class="group-card"` 至少 1 处
        - `group_1` 字面
        - `85%` 或 `confidence` 字段对应百分号
        - 两个 basis chip 文本（`同一景点` / `相近构图` 等）
        - primary 行 asset_id 字符串
  - [x] SubTask 8.2：新增 `test_render_demo_scan_table_cells_have_real_m4`：
        - 不含 `（待 M4）` 任何字面
        - 含至少 1 处 `sel-primary` class
        - 含至少 7 处 `cand-default` class（demo-scan 候选池 8 条，扣去 alternate 1 条 ≈ 7）
  - [x] SubTask 8.3：新增 `test_render_no_groups_omits_section`：手工构造 `CutIndex` 但 `similar_groups=[]`，断言 HTML 不含 `class="group-card"`，也不含字面 `__SIMILAR_GROUPS_HTML__`（占位符必须被替换为空串）。

- [x] Task 9：CLI 端到端（[test_cli_export.py](file:///Users/bytedance/Documents/TripClipper_Trae/tests/test_cli_export.py)）
  - [x] SubTask 9.1：在既有 fixture 上追加一条 fixture：含 1 个 SimilarGroup + 2 条 default_selected + 1 条 alternate。
  - [x] SubTask 9.2：新增 `test_export_with_m4_data_renders_group_card`：CliRunner 跑 `export <slug>`，读生成的 review.html，断言包含 `group-card` / `sel-primary` / `cand-default` 三个 class。

- [x] Task 10：文档更新
  - [x] SubTask 10.1：[docs/specs/README.md](file:///Users/bytedance/Documents/TripClipper_Trae/docs/specs/README.md) 模块索引追加一行：
        `| wire-m4-into-review-html | 把 M4 决策接入 review.html | FR-6/FR-8（HTML） | M4、M5-early | 已完成 |`
        （状态在实施完且 checklist 全过后再勾完成；先写 spec 阶段填"待开始"）
  - [x] SubTask 10.2：本 spec 目录下 README 不必单独建，沿用 spec.md/tasks.md/check_list.md 三件套即可。

- [x] Task 11：人工视觉验收
  - [x] SubTask 11.1：跑 `.venv/bin/tripclipper export demo-scan --html --open`，截图核对：
        - 组面板可见、点击成员能跳行 + 黄色 flash
        - 表内 primary 行绿、alternate 行蓝
        - 同组行 hover 联动浅蓝
        - 两个新 filter 工作
        - CSP 没有 console error（打开 devtools 看一眼）
  - 用户主导，不写自动化。

## Task Dependencies

- Task 4 依赖 Task 1 / Task 2（要调用两个新格式化函数）。
- Task 5 依赖 Task 3（要调用面板渲染函数）。
- Task 6 与 Task 1-5 可并行（模板与 Python 互不依赖；最后联调时端到端测试一起跑）。
- Task 7 内嵌在 Task 6.1，不单独执行。
- Task 8 依赖 Task 1-6 全部完成。
- Task 9 依赖 Task 1-6 全部完成。
- Task 10 可在任何时候做。
- Task 11 依赖 1-10 全部完成。
