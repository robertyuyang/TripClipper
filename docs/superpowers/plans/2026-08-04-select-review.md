# select-review 只读选片验收页实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为每个选片任务生成完全只读、离线单文件的 `select-review.html`，并提供自动生成与幂等 CLI 重建入口。

**Architecture:** 新增独立的选片审阅渲染器，读取 `brief.md`、`state.json` 和项目 `cut_index.json`，构造经过转义的页面上下文并套用包内 HTML 模板；现有 `SelectionRunner` 只在选片成功后调用渲染器并把失败降级为警告。CLI 新增 `select-review` 命令，重建时只覆盖目标 HTML，不触碰任何输入文件。

**Tech Stack:** Python 3.12、Pydantic 2、Click、标准库 `json/html/pathlib/webbrowser`、原生 HTML/CSS/JavaScript、pytest。

## Global Constraints

- 页面产物固定为 `projects/<slug>/selections/<task>/select-review.html`。
- 页面严格只读，不修改 `state.json`、`events.jsonl`、`brief.md`、`cut_index.json`。
- 候选按 `state.candidates` 原顺序平铺；多分类候选只渲染一次；筛选不重排。
- 单播放器只定位当前候选；播放至 `end_sec` 自动暂停；不自动播放下一条。
- 不改造项目级 `exports/review.html`，不实现票据 02/03、本地服务或状态写回。
- 自动测试使用手工数据和脚本化测试，不访问网络或真实模型。
- 最终用原工作区 `26shidu/30秒欢快快剪` 数据人工验收，并确认四个输入文件哈希不变。

---

## 文件结构

- Create: `src/tripclipper/clip_selection/review.py` — 只读加载、素材关联、路径解析、页面上下文与模板渲染。
- Create: `src/tripclipper/clip_selection/templates/select-review.html.tmpl` — 单播放器、摘要、候选列表、筛选和播放边界交互。
- Modify: `src/tripclipper/paths.py` — 增加任务级审阅页路径函数。
- Modify: `src/tripclipper/clip_selection/runner.py` — 成功后自动生成，并返回路径或降级错误。
- Modify: `src/tripclipper/cli.py` — 输出自动生成结果，增加幂等 `select-review` 命令和 `--open`。
- Modify: `pyproject.toml` — 打包选片审阅模板。
- Modify: `README.md` — 记录用户可见命令和只读用途。
- Create: `tests/test_select_review.py` — 渲染器、路径、降级、安全和输入哈希测试。
- Modify: `tests/test_clip_selection.py` — Runner 自动生成成功/失败以及 CLI 摘要测试。

---

### Task 1: 只读渲染器与页面数据契约

**Files:**
- Create: `tests/test_select_review.py`
- Create: `src/tripclipper/clip_selection/review.py`
- Modify: `src/tripclipper/paths.py`

**Interfaces:**
- Consumes: `read_cut_index(path: Path) -> CutIndex`、`SelectionState.model_validate_json(...)`。
- Produces: `selection_review_html_path(slug, task_name, base_dir=None) -> Path`、`render_selection_review(slug, task_name, base_dir=None) -> Path`、`SelectionReviewError`。

- [ ] **Step 1: 写路径和核心渲染失败测试**

```python
def test_selection_review_path_is_inside_task_directory(tmp_path: Path) -> None:
    assert selection_review_html_path("demo", "快剪", tmp_path) == (
        tmp_path / "demo" / "selections" / "快剪" / "select-review.html"
    )

def test_render_review_joins_assets_and_preserves_candidate_order(review_task) -> None:
    output = render_selection_review("demo", "快剪", base_dir=review_task.base_dir)
    html = output.read_text(encoding="utf-8")
    assert html.index("candidate-001") < html.index("candidate-002")
    assert "people &lt;one&gt;.mp4" in html
```

- [ ] **Step 2: 运行测试确认红灯**

Run: `PYTHONPATH=src <python> -m pytest tests/test_select_review.py -q`

Expected: FAIL，提示 `tripclipper.clip_selection.review` 或路径函数不存在。

- [ ] **Step 3: 实现最小只读加载与上下文构造**

```python
class SelectionReviewError(RuntimeError):
    pass

def render_selection_review(slug: str, task_name: str, *, base_dir=None) -> Path:
    task_dir = selection_task_dir(slug, task_name, base_dir)
    brief = _read_required(task_dir / "brief.md", "Brief")
    state = SelectionState.model_validate_json(_read_required(task_dir / "state.json", "选片状态"))
    cut = read_cut_index(_required_path(cut_index_path(slug, base_dir), "素材索引"))
    context = _build_context(brief, state, cut)
    target = selection_review_html_path(slug, task_name, base_dir)
    target.write_text(_render_template(context), encoding="utf-8")
    return target.resolve()
```

素材路径严格按 `path → relative_path → file → filename` 解析；相对路径以 `cut.project.source_folder` 为基准。总时长复用“按素材分组、排序区间、重叠并集”的算法。

- [ ] **Step 4: 增加关联、安全和降级用例**

```python
def test_render_review_escapes_text_and_script_terminator(review_task) -> None:
    html = render_selection_review(...).read_text(encoding="utf-8")
    assert "<script>alert" not in html
    assert "<\\/script>" in html

def test_render_review_marks_missing_non_video_and_invalid_ranges(review_task) -> None:
    html = render_selection_review(...).read_text(encoding="utf-8")
    assert "素材索引不存在" in html
    assert "非视频素材" in html
    assert "时间范围错误" in html
```

- [ ] **Step 5: 运行渲染器测试确认绿灯**

Run: `PYTHONPATH=src <python> -m pytest tests/test_select_review.py -q`

Expected: PASS。

### Task 2: 单播放器模板与只读交互

**Files:**
- Create: `src/tripclipper/clip_selection/templates/select-review.html.tmpl`
- Modify: `src/tripclipper/clip_selection/review.py`
- Modify: `tests/test_select_review.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: Task 1 生成的安全页面上下文 JSON。
- Produces: DOM 标识 `review-player`、`candidate-list`、`category-filters`；JS 函数 `selectCandidate`、`replayCurrent`、`moveCurrent`、`clampToCandidateRange`。

- [ ] **Step 1: 写单播放器与交互契约测试**

```python
def test_review_contains_one_player_and_read_only_controls(review_task) -> None:
    html = render_selection_review(...).read_text(encoding="utf-8")
    assert html.count('id="review-player"') == 1
    assert 'id="candidate-list"' in html
    assert "timeupdate" in html and "seeking" in html
    assert "replayCurrent" in html and "moveCurrent(-1)" in html
    assert "autoplay" not in html
    assert "fetch(" not in html and "localStorage" not in html
```

- [ ] **Step 2: 运行测试确认红灯**

Run: `PYTHONPATH=src <python> -m pytest tests/test_select_review.py::test_review_contains_one_player_and_read_only_controls -q`

Expected: FAIL，模板尚无交互契约。

- [ ] **Step 3: 实现页面结构和播放器控制**

```javascript
function selectCandidate(index) {
  currentIndex = index;
  player.pause();
  player.src = candidate.mediaUri || "";
  player.addEventListener("loadedmetadata", () => {
    player.currentTime = candidate.startSec;
  }, {once: true});
}

player.addEventListener("timeupdate", () => {
  if (current && player.currentTime >= current.endSec) {
    player.pause();
    player.currentTime = current.endSec;
  }
});
```

分类筛选基于每个候选的 `categoryIds` 集合显隐已有条目；上一条/下一条只遍历当前可见候选，切换后不调用 `play()`；重新播放才定位起点并调用 `play()`。

- [ ] **Step 4: 运行页面契约测试确认绿灯**

Run: `PYTHONPATH=src <python> -m pytest tests/test_select_review.py -q`

Expected: PASS。

### Task 3: 自动生成、幂等 CLI 与失败降级

**Files:**
- Modify: `src/tripclipper/clip_selection/runner.py`
- Modify: `src/tripclipper/cli.py`
- Modify: `tests/test_clip_selection.py`
- Modify: `tests/test_select_review.py`

**Interfaces:**
- Consumes: `render_selection_review(...) -> Path`。
- Produces: `SelectionResult.review_html_path: Path | None`、`SelectionResult.review_error: str | None`；CLI `tripclipper select-review <slug> <task-name> [--base-dir PATH] [--open]`。

- [ ] **Step 1: 写 Runner 自动生成和失败降级测试**

```python
def test_completed_selection_returns_review_path(...):
    result = run_selection(...)
    assert result.review_html_path == result.task_dir / "select-review.html"
    assert result.review_error is None

def test_review_failure_does_not_change_completed_state(monkeypatch, ...):
    monkeypatch.setattr("tripclipper.clip_selection.runner.render_selection_review", failing_renderer)
    result = run_selection(...)
    assert result.state.status == "completed"
    assert result.review_html_path is None
    assert "模板损坏" in result.review_error
```

- [ ] **Step 2: 运行测试确认红灯**

Run: `PYTHONPATH=src <python> -m pytest tests/test_clip_selection.py -q`

Expected: FAIL，结果对象没有审阅页字段或 Runner 未调用渲染器。

- [ ] **Step 3: 实现 Runner 降级和 CLI**

```python
try:
    review_path = render_selection_review(slug, task_name, base_dir=base_dir)
except (OSError, ValueError, SelectionReviewError) as exc:
    review_path = None
    review_error = str(exc)

@main.command("select-review")
@click.argument("slug")
@click.argument("task_name")
@click.option("--base-dir", type=click.Path(path_type=Path))
@click.option("--open", "open_browser", is_flag=True)
def select_review_command(...):
    output = render_selection_review(slug, task_name, base_dir=base_dir)
    click.echo(f"审阅页面: {output}")
    if open_browser:
        webbrowser.open(output.as_uri())
```

自动生成失败时 `select` 仍退出 0，输出“选片已成功，但审阅页生成失败”；显式 `select-review` 失败时退出非零。

- [ ] **Step 4: 写并运行 CLI 幂等与输入哈希测试**

```python
def test_select_review_cli_is_idempotent_and_preserves_inputs(review_task) -> None:
    before = review_task.input_hashes()
    first = CliRunner().invoke(main, ["select-review", "demo", "快剪", "--base-dir", str(review_task.base_dir)])
    second = CliRunner().invoke(main, ["select-review", "demo", "快剪", "--base-dir", str(review_task.base_dir)])
    assert first.exit_code == second.exit_code == 0
    assert review_task.input_hashes() == before
```

Run: `PYTHONPATH=src <python> -m pytest tests/test_clip_selection.py tests/test_select_review.py -q`

Expected: PASS。

### Task 4: 文档、完整验证、代码审查与真实验收

**Files:**
- Modify: `README.md`
- Review: all select-review files above
- Generate only: `/Users/bytedance/Documents/src/robert/TripClipper_Codex_AfterTrae/projects/26shidu/selections/30秒欢快快剪/select-review.html`

**Interfaces:**
- Consumes: 最终 CLI。
- Produces: 用户可直接打开的真实审阅页、验证记录和单一中文提交。

- [ ] **Step 1: 更新 README 用法**

```markdown
tripclipper select-review <slug> <task-name> [--base-dir PATH] [--open]
```

说明命令只读重建任务级页面，`--open` 用默认浏览器打开，不修改选片状态与项目索引。

- [ ] **Step 2: 运行静态与完整自动测试**

Run: `PYTHONPATH=src <python> -m compileall -q src tests`

Expected: exit 0。

Run: `PYTHONPATH=src <python> -m pytest -q`

Expected: 全部 PASS，0 failures。

- [ ] **Step 3: 按 `code-review` 做标准与规格双轴审查并修复确认问题**

Fixed point: `5f641e3`。

Diff: `git diff 5f641e3...HEAD`（提交前审查时使用等价的工作区 diff）。

Spec: `docs/superpowers/specs/2026-08-04-select-review-design.md`。

- [ ] **Step 4: 记录真实输入哈希并执行用户指定命令**

```bash
shasum -a 256 \
  projects/26shidu/cut_index.json \
  projects/26shidu/selections/30秒欢快快剪/state.json \
  projects/26shidu/selections/30秒欢快快剪/brief.md \
  projects/26shidu/selections/30秒欢快快剪/events.jsonl

tripclipper select-review 26shidu "30秒欢快快剪" \
  --base-dir /Users/bytedance/Documents/src/robert/TripClipper_Codex_AfterTrae/projects \
  --open
```

Expected: 原工作区生成目标 HTML，浏览器打开后显示 5 个候选和唯一播放器。

- [ ] **Step 5: 浏览器逐条验证真实数据并复核哈希**

逐条切换 5 个候选，核对每条播放器加载源文件、定位 `start_sec`、到 `end_sec` 暂停；检查分类筛选、重新播放、上一条、下一条。再次运行同一 `shasum -a 256`，四个摘要必须逐字相同，并保持页面打开。

- [ ] **Step 6: 只暂存本任务文件并提交**

```bash
git diff --check
git add docs/superpowers/plans/2026-08-04-select-review.md README.md pyproject.toml \
  src/tripclipper/paths.py src/tripclipper/cli.py \
  src/tripclipper/clip_selection/runner.py src/tripclipper/clip_selection/review.py \
  src/tripclipper/clip_selection/templates/select-review.html.tmpl \
  tests/test_clip_selection.py tests/test_select_review.py
git diff --cached --check
git diff --cached
git commit -m "实现只读选片验收页"
```

Expected: 提交仅包含 select-review 实现、测试、计划和必要文档；真实生成的项目 HTML 不进入提交。

---

## 自检结果

- 规格覆盖：产物路径、只读、安全转义、单播放器、分类筛选、区间控制、自动生成、失败降级、幂等命令、离线测试和真实验收均有对应任务。
- 范围控制：未规划候选编辑、状态写回、本地服务、票据 02/03 或项目级 `review.html` 修改。
- 接口一致：统一使用 `render_selection_review`、`selection_review_html_path`、`review_html_path/review_error` 字段。
- 占位扫描：无 `TBD`、`TODO` 或未定义的后续实现项。
