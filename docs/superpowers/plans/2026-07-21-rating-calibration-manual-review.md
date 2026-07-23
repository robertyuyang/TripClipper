# 评分校准盲评 Implementation Plan

> 迁移说明（2026-07-23）：本文保留当时的实现路径用于追溯。评分调优工具和实验资产现已迁入仓库级 `rating-lab/`；后续 15 条样本已并入 45 条开发集，不再作为留出集。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将默认评分校准样本缩减为 30 条，并让 `prepare` 生成不泄露旧评分的人工盲评 CSV 和单文件 HTML。

**Architecture:** 抽样和盲评产物生成继续放在 `tripclipper.rating_calibration` 纯函数模块中，独立脚本只负责读取项目、调用函数和打印路径。HTML 直接嵌入 30 条素材的本地文件 URI 与安全 JSON，浏览器用 `localStorage` 保存答案并导出 CSV，不需要服务器或额外依赖。

**Tech Stack:** Python 3.10、标准库 `csv/html/json/pathlib`、原生 HTML/CSS/JavaScript、pytest。

## Global Constraints

- 默认仅抽视频，总样本数必须为 30。
- HTML 和人工标注 CSV 不得包含旧评分、候选模型评分或 `baseline_rating` 字段。
- 不修改正式 `cut_index.json`，不调用语音分析。
- 页面不依赖外部字体、框架、CDN 或网络服务。
- 所有文本和路径必须经过 HTML 或 JSON 安全编码。
- 已存在的 manifest、CSV 或 HTML 不得被覆盖。

---

### Task 1: 30 条默认样本与盲评 CSV

**Files:**
- Modify: `src/tripclipper/rating_calibration.py`
- Modify: `scripts/calibrate_rating.py`
- Modify: `tests/test_rating_calibration.py`

**Interfaces:**
- Consumes: `build_manifest(...) -> dict[str, object]` 和 manifest 的 `assets` 行。
- Produces: `DEFAULT_RATING_QUOTAS = {1: 1, 2: 3, 3: 9, 4: 15, 5: 2}`；`write_manual_labels(path: Path, manifest: Mapping[str, object]) -> None`。

- [ ] **Step 1: 写默认配额红灯测试**

```python
def test_default_rating_quotas_total_thirty() -> None:
    from tripclipper.rating_calibration import DEFAULT_RATING_QUOTAS

    assert DEFAULT_RATING_QUOTAS == {1: 1, 2: 3, 3: 9, 4: 15, 5: 2}
    assert sum(DEFAULT_RATING_QUOTAS.values()) == 30
```

- [ ] **Step 2: 运行测试并确认旧总数 50 导致失败**

Run: `.venv/bin/python -m pytest -q tests/test_rating_calibration.py::test_default_rating_quotas_total_thirty`

Expected: FAIL，实际配额仍为 `{1: 1, 2: 6, 3: 15, 4: 25, 5: 3}`。

- [ ] **Step 3: 最小修改默认配额**

```python
DEFAULT_RATING_QUOTAS: dict[int, int] = {1: 1, 2: 3, 3: 9, 4: 15, 5: 2}
```

- [ ] **Step 4: 写盲评 CSV 红灯测试**

```python
def test_write_manual_labels_omits_baseline_rating(tmp_path: Path) -> None:
    from tripclipper.rating_calibration import write_manual_labels

    manifest = {
        "assets": [{
            "asset_id": "asset-1",
            "relative_path": "含,逗号/video.mp4",
            "baseline_rating": 4,
        }]
    }
    path = tmp_path / "manual_labels.csv"
    write_manual_labels(path, manifest)

    text = path.read_text(encoding="utf-8")
    assert "baseline_rating" not in text
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows == [{
        "asset_id": "asset-1",
        "relative_path": "含,逗号/video.mp4",
        "expected_rating": "",
        "expected_action": "",
        "whole_asset_or_clip": "",
        "notes": "",
    }]
```

- [ ] **Step 5: 运行测试并确认函数缺失**

Run: `.venv/bin/python -m pytest -q tests/test_rating_calibration.py::test_write_manual_labels_omits_baseline_rating`

Expected: FAIL with `ImportError: cannot import name 'write_manual_labels'`。

- [ ] **Step 6: 实现独占写入的 CSV 生成函数**

```python
def write_manual_labels(path: Path, manifest: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "asset_id", "relative_path", "expected_rating",
        "expected_action", "whole_asset_or_clip", "notes",
    ]
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for asset in manifest.get("assets", []):
            writer.writerow({
                "asset_id": asset.get("asset_id"),
                "relative_path": asset.get("relative_path"),
                "expected_rating": "",
                "expected_action": "",
                "whole_asset_or_clip": "",
                "notes": "",
            })
```

- [ ] **Step 7: 运行 Task 1 测试**

Run: `.venv/bin/python -m pytest -q tests/test_rating_calibration.py`

Expected: PASS。

### Task 2: 单文件盲评页面与 prepare 接线

**Files:**
- Modify: `src/tripclipper/rating_calibration.py`
- Modify: `scripts/calibrate_rating.py`
- Modify: `tests/test_rating_calibration.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: manifest、`source_folder` 和每条素材的 `relative_path`。
- Produces: `write_manual_review_html(path: Path, manifest: Mapping[str, object], source_folder: str) -> None`；`prepare` 输出 manifest、`manual_labels.csv`、`manual-review.html` 三个路径。

- [ ] **Step 1: 写 HTML 安全和盲评红灯测试**

```python
def test_write_manual_review_html_is_blind_and_escapes_paths(tmp_path: Path) -> None:
    from tripclipper.rating_calibration import write_manual_review_html

    manifest = {
        "project_slug": "demo",
        "assets": [{
            "asset_id": "asset-1",
            "relative_path": 'day/<clip>&".mp4',
            "baseline_rating": 4,
        }],
    }
    path = tmp_path / "manual-review.html"
    write_manual_review_html(path, manifest, "/素材")

    rendered = path.read_text(encoding="utf-8")
    assert "baseline_rating" not in rendered
    assert "旧评分" not in rendered
    assert "<video" in rendered
    assert "导出 CSV" in rendered
    assert "localStorage" in rendered
    assert "day/<clip>" not in rendered
```

- [ ] **Step 2: 运行测试并确认函数缺失**

Run: `.venv/bin/python -m pytest -q tests/test_rating_calibration.py::test_write_manual_review_html_is_blind_and_escapes_paths`

Expected: FAIL with `ImportError: cannot import name 'write_manual_review_html'`。

- [ ] **Step 3: 实现 HTML 数据准备和页面生成**

```python
def write_manual_review_html(
    path: Path,
    manifest: Mapping[str, object],
    source_folder: str,
) -> None:
    items = []
    for row in manifest.get("assets", []):
        relative_path = str(row.get("relative_path") or "")
        media_uri = (Path(source_folder) / relative_path).resolve().as_uri()
        items.append({
            "asset_id": str(row.get("asset_id") or ""),
            "relative_path": relative_path,
            "media_uri": media_uri,
        })
    data_json = json.dumps(items, ensure_ascii=False).replace("</", "<\\/")
    rendered = _MANUAL_REVIEW_TEMPLATE.replace("__ITEMS_JSON__", data_json)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8", errors="strict")
```

模板必须包含：

- 顶部完成计数和“导出 CSV”按钮。
- 每条素材一个 `<video controls preload="metadata">`。
- 1–5 星单选、处理意见、整段/局部选择、备注。
- `localStorage` 按 `project_slug + asset_id` 保存。
- 原生 JS 生成并下载 UTF-8 BOM CSV。
- 深色剪辑台视觉，无外部资源。

- [ ] **Step 4: 让 HTML 写入也使用独占创建**

将 `path.write_text(...)` 改为 `path.open("x", encoding="utf-8")`，确保已有盲评结果不会被覆盖。

- [ ] **Step 5: 写 prepare 三产物集成红灯测试**

扩展 `test_prepare_script_generates_manifest_from_cut_index`：

```python
assert len(manifest["assets"]) == 30
assert (manifest_path.parent / "manual_labels.csv").is_file()
assert (manifest_path.parent / "manual-review.html").is_file()
```

- [ ] **Step 6: 在 prepare 中接线三份产物**

```python
manual_csv_path = args.manifest.parent / "manual_labels.csv"
manual_html_path = args.manifest.parent / "manual-review.html"
write_manual_labels(manual_csv_path, manifest)
write_manual_review_html(
    manual_html_path,
    manifest,
    cut.project.source_folder or "",
)
```

命令输出必须打印三个路径，方便用户直接打开页面。

- [ ] **Step 7: 更新 README 命令说明**

在“评分 Prompt 校准”中说明 `prepare` 默认生成 30 条视频样本及盲评页面，要求先完成人工标注再执行 `run`。

- [ ] **Step 8: 运行针对性验证**

Run: `.venv/bin/python -m pytest -q tests/test_rating_calibration.py tests/test_provider.py`

Expected: 全部 PASS。

Run: `.venv/bin/python -m compileall -q src/tripclipper/rating_calibration.py scripts/calibrate_rating.py`

Expected: exit 0，无输出。

Run: `git diff --check`

Expected: exit 0，无输出。
