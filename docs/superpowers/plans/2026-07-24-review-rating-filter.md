# review.html 星级筛选实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为导出的 `review.html` 增加固定选项的精确星级筛选，并支持筛选未评分素材。

**Architecture:** 复用每个素材行已有的 `data-rating` 属性，只在静态模板的筛选控件、筛选状态、匹配函数和事件绑定中接入星级条件。通过现有端到端导出测试验证生成页面包含完整控件和筛选逻辑，不改变 Python 数据模型或导出结构。

**Tech Stack:** Python 3、pytest、HTML、原生 JavaScript

## Global Constraints

- 星级筛选固定提供“全部、5 星、4 星、3 星、2 星、1 星、未评分”。
- 具体星级必须精确匹配，不能按“至少几星”匹配。
- “未评分”只匹配空 `data-rating`。
- 新筛选与现有筛选条件同时生效。
- 不修改评分计算、导出数据结构和其他筛选器行为。

---

### Task 1: 接入星级筛选

**Files:**
- Modify: `tests/test_exporter.py`
- Modify: `src/tripclipper/templates/review.html.tmpl`

**Interfaces:**
- Consumes: 素材行现有的 `data-rating` 字符串属性，其中 `"1"` 至 `"5"` 表示具体星级，空字符串表示未评分。
- Produces: `select#filter-rating`；`currentFilters()` 返回的 `frating` 字符串；`rowMatches(r, f)` 对 `data-rating` 的精确匹配行为。

- [ ] **Step 1: 写出失败的端到端测试**

在 `test_render_review_html_with_sessions_end_to_end` 的页面断言中加入：

```python
    assert 'id="filter-rating"' in text
    assert '<option value="5">5 星</option>' in text
    assert '<option value="unrated">未评分</option>' in text
    assert "frating: document.getElementById('filter-rating').value" in text
    assert "r.getAttribute('data-rating') || ''" in text
    assert "'filter-rating'" in text
```

- [ ] **Step 2: 运行测试并确认因缺少控件而失败**

Run:

```bash
PYTHONPATH=src .venv/bin/pytest tests/test_exporter.py::test_render_review_html_with_sessions_end_to_end -v
```

Expected: FAIL，首个失败信息指出生成页面中不存在 `id="filter-rating"`。

- [ ] **Step 3: 实现最小星级筛选**

在 `review.html.tmpl` 的现有筛选栏中加入固定选项：

```html
  <select id="filter-rating">
    <option value="">星级：全部</option>
    <option value="5">5 星</option>
    <option value="4">4 星</option>
    <option value="3">3 星</option>
    <option value="2">2 星</option>
    <option value="1">1 星</option>
    <option value="unrated">未评分</option>
  </select>
```

在 `currentFilters()` 返回值中加入：

```javascript
      frating: document.getElementById('filter-rating').value,
```

在 `rowMatches(r, f)` 中加入精确匹配：

```javascript
    if (f.frating){
      var rating = r.getAttribute('data-rating') || '';
      if (f.frating === 'unrated' ? rating !== '' : rating !== f.frating) return false;
    }
```

在筛选事件 ID 列表中加入 `'filter-rating'`：

```javascript
  ['search', 'filter-rating', 'filter-subject-type', 'filter-shot-scale', 'filter-status', 'filter-similar', 'filter-candidate', 'filter-session'].forEach(function(id){
```

- [ ] **Step 4: 运行目标测试并确认通过**

Run:

```bash
PYTHONPATH=src .venv/bin/pytest tests/test_exporter.py::test_render_review_html_with_sessions_end_to_end -v
```

Expected: PASS。

- [ ] **Step 5: 运行相关测试文件和差异检查**

Run:

```bash
PYTHONPATH=src .venv/bin/pytest tests/test_exporter.py -q
git diff --check
```

Expected: `tests/test_exporter.py` 全部通过，`git diff --check` 无输出。

- [ ] **Step 6: 提交本功能代码**

只暂存本任务修改：

```bash
git add tests/test_exporter.py src/tripclipper/templates/review.html.tmpl
git diff --cached --check
git diff --cached
git commit -m "增加 review 星级筛选"
```

Expected: 创建一个仅包含星级筛选及其测试的中文提交。
