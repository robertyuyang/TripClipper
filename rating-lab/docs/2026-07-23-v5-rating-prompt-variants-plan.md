# v5 三版评分 Prompt 实验实施计划

> **供智能体执行：** 必须使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`，逐项执行本计划。所有步骤使用复选框跟踪。

**目标：** 修正 5 条统一人工评分，创建平衡、保守和高召回三份完整 v5 Prompt，在相同 45 条开发集上运行三版，自动计算指标并生成三版并排人工复核 HTML。

**架构：** 三份 Prompt 是结构一致、可独立运行的完整快照。每个候选版本分别运行 `initial-30` 和 `extension-15`，比较工具负责合并两批结果、计算指标、筛选关键素材并渲染离线复核页；TripClipper 生产链路不导入候选 Prompt。

**技术栈：** Python 3.10、argparse、pytest、JSON、CSV、离线 HTML、现有 TripClipper Provider。

## 全局约束

- 统一 `development-v1/human-labels.csv` 是 v5 指标的唯一权威评分基准。
- 只修改已确认的 5 条评分，其余 40 条保持不变。
- 两个批次目录中的历史 `human-labels.csv` 不修改。
- 人工文字评语优先于错误类型和单纯数值差。
- 三版 Prompt 都是完整文件，不在运行时动态拼接。
- 平衡版是实验室默认候选；三版都不自动进入生产。
- 每版必须完整产生 45 条成功结果才进入排名。
- 任何输出文件或运行目录已存在时停止，不覆盖历史。
- v2、v3、v4 和 strict-v1 Prompt 保持不变。
- 不夹带当前工作区中与 `rating-lab` 无关的修改。

---

### 任务 1：修正统一人工评分

**文件：**

- 修改：`rating-lab/datasets/development-v1/human-labels.csv`
- 修改：`rating-lab/tests/test_dataset_integrity.py`
- 修改：`rating-lab/docs/rating-policy.md`

**接口：**

- 输入：根目录统一人工标签、批次历史标签和 `annotations.csv`。
- 产出：根目录唯一权威标签中恰好 5 条裁定差异。

- [ ] **步骤 1：写入失败测试**

在 `test_dataset_integrity.py` 增加：

```python
def test_authoritative_labels_apply_exactly_five_adjudications() -> None:
    expected_changes = {
        "asset_49ba9c5ba398": ("2", "4"),
        "asset_2dc71a50d977": ("2", "4"),
        "asset_88844cf7f24f": ("1", "3"),
        "asset_08c943eb9686": ("1", "4"),
        "asset_5b691e6d1dbf": ("2", "4"),
    }
    historical: dict[str, str] = {}
    for batch in ("initial-30", "extension-15"):
        path = DATASET_ROOT / "batches" / batch / "human-labels.csv"
        with path.open(encoding="utf-8-sig", newline="") as handle:
            historical.update(
                {
                    row["asset_id"]: row["expected_rating"]
                    for row in csv.DictReader(handle)
                }
            )
    with (DATASET_ROOT / "human-labels.csv").open(
        encoding="utf-8-sig", newline=""
    ) as handle:
        authoritative = {
            row["asset_id"]: row["expected_rating"]
            for row in csv.DictReader(handle)
        }

    changes = {
        asset_id: (historical[asset_id], rating)
        for asset_id, rating in authoritative.items()
        if historical[asset_id] != rating
    }

    assert changes == expected_changes
```

- [ ] **步骤 2：运行测试并确认失败**

运行：

```bash
.venv/bin/python -m pytest -q \
  rating-lab/tests/test_dataset_integrity.py::test_authoritative_labels_apply_exactly_five_adjudications
```

预期：失败，实际差异为空。

- [ ] **步骤 3：只修改 5 条统一评分**

按 `asset_id` 修改根目录 `human-labels.csv`：

```text
asset_49ba9c5ba398  2 → 4
asset_2dc71a50d977  2 → 4
asset_88844cf7f24f  1 → 3
asset_08c943eb9686  1 → 4
asset_5b691e6d1dbf  2 → 4
```

其他列和其他 40 条记录原样保留。

- [ ] **步骤 4：补充评分口径说明**

在 `rating-policy.md` 明确：

```text
根目录 human-labels.csv 是当前权威评分。
批次 human-labels.csv 是迁移时的历史评分。
五条裁定已直接进入权威评分，不再另建 adjudicated-labels.csv。
```

- [ ] **步骤 5：运行数据完整性测试**

运行：

```bash
.venv/bin/python -m pytest -q rating-lab/tests/test_dataset_integrity.py
```

预期：全部通过，仍为 45 个唯一素材和 8 条文字评语。

- [ ] **步骤 6：提交评分修正**

```bash
git add \
  rating-lab/datasets/development-v1/human-labels.csv \
  rating-lab/tests/test_dataset_integrity.py \
  rating-lab/docs/rating-policy.md
git commit -m "data(rating-lab): 应用5条人工评分裁定"
```

---

### 任务 2：创建三份完整 v5 Prompt

**文件：**

- 创建：`rating-lab/prompts/single-highlight-v5-balanced.txt`
- 创建：`rating-lab/prompts/single-highlight-v5-conservative.txt`
- 创建：`rating-lab/prompts/single-highlight-v5-recall.txt`
- 修改：`rating-lab/tests/test_review.py`

**接口：**

- 输入：v4 公共契约和 v5 设计文档。
- 产出：三份可直接传给 `rating-lab/cli.py run --rating-guide` 的 UTF-8 文本。

- [ ] **步骤 1：写入三版 Prompt 契约测试**

增加：

```python
def _read_prompt(name: str) -> str:
    return (Path(__file__).parents[1] / "prompts" / name).read_text(
        encoding="utf-8"
    )


def test_v5_prompts_share_non_negotiable_contract() -> None:
    prompts = [
        _read_prompt("single-highlight-v5-balanced.txt"),
        _read_prompt("single-highlight-v5-conservative.txt"),
        _read_prompt("single-highlight-v5-recall.txt"),
    ]

    for prompt in prompts:
        assert "素材总评分必须等于最佳片段的评分" in prompt
        assert "主体显著性" in prompt
        assert "持续且非叙事性的倾斜" in prompt
        assert "横竖方向本身不决定评分" in prompt
        assert "趣味动作" in prompt
        assert "少见运镜" in prompt
        assert "不得编造" in prompt


def test_v5_balanced_encodes_default_thresholds() -> None:
    prompt = _read_prompt("single-highlight-v5-balanced.txt")

    assert "实验室默认候选" in prompt
    assert "主体过小、处于边缘或构图意图不清时，最高 3 星" in prompt
    assert "内容意义不明、只能给出泛化用途时，最高 2 星" in prompt
    assert "一个足够强且清楚可见的证据" in prompt


def test_v5_conservative_requires_multiple_high_rating_evidence() -> None:
    prompt = _read_prompt("single-highlight-v5-conservative.txt")

    assert "至少两项相互独立的可见证据" in prompt
    assert "只有一个普通正向证据时，最高 3 星" in prompt
    assert "优先降低高分误判" in prompt


def test_v5_recall_accepts_one_strong_visible_highlight() -> None:
    prompt = _read_prompt("single-highlight-v5-recall.txt")

    assert "一个足够强且清楚可见的趣味细节" in prompt
    assert "局部高光不因占素材比例小而降级" in prompt
    assert "不放宽事实依据和时间范围要求" in prompt
```

- [ ] **步骤 2：运行测试并确认因文件不存在而失败**

运行：

```bash
.venv/bin/python -m pytest -q rating-lab/tests/test_review.py -k v5
```

预期：4 个测试均因对应 Prompt 文件不存在而失败。

- [ ] **步骤 3：创建平衡版**

以 v4 的完整章节为基础，保持最佳片段契约、观察顺序、证据类型和输出要求，并写入以下精确规则：

```text
4 星：
- 主体或视觉中心清楚可辨。
- 至少一项具体且有区分度的证据。
- 能说明为何大概率入片，而不是只有泛化用途。
- 一个足够强且清楚可见的趣味动作、人物反应、小细节或少见运镜可以满足证据门槛。

5 星：
- 满足 4 星。
- 另有两项独立强证据，或一个清楚的高潮、关键反应、事件峰值或罕见视觉时刻。

上限：
- 主体过小、处于边缘或构图意图不清时，最高 3 星。
- 主体理解明显受阻时，最高 2 星。
- 持续且非叙事性的倾斜导致观看不自然时，最高 2 星。
- 内容意义不明、只能给出泛化用途时，最高 2 星。
```

- [ ] **步骤 4：创建保守版**

公共规则与平衡版一致，仅把高分门槛写为：

```text
4 星必须同时满足：
- 主体显著且视觉中心明确。
- 具有具体入片用途。
- 至少两项相互独立的可见证据。
- 不依赖项目上下文也能成立。

5 星：
- 满足 4 星。
- 额外具有动作高潮、关键人物反应、稀有视觉、特殊光线或明确重点展示价值。

只有一个普通正向证据时，最高 3 星。
```

- [ ] **步骤 5：创建高召回版**

公共规则与平衡版一致，仅把高分门槛写为：

```text
4 星：
- 技术可用且有合法时间范围。
- 一个足够强且清楚可见的趣味细节、人物反应、少见运镜、事件变化或视觉证据即可成立。

5 星：
- 一个特别强的局部高光可以成立。
- 必须说明具体重点展示处理，不能只使用抽象形容词。

局部高光不因占素材比例小而降级。
不放宽事实依据和时间范围要求。
```

- [ ] **步骤 6：运行 Prompt 测试和完整评分实验室测试**

运行：

```bash
.venv/bin/python -m pytest -q rating-lab/tests/test_review.py
.venv/bin/python -m pytest -q rating-lab/tests
```

预期：全部通过。

- [ ] **步骤 7：提交三版 Prompt**

```bash
git add rating-lab/prompts rating-lab/tests/test_review.py
git commit -m "feat(rating-lab): 新增v5三版评分提示词"
```

---

### 任务 3：实现三版结果合并和关键素材筛选

**文件：**

- 创建：`rating-lab/rating_lab/variants.py`
- 创建：`rating-lab/tests/test_variants.py`
- 修改：`rating-lab/rating_lab/evaluation.py`

**接口：**

- `load_variant_results(variant_dir: Path) -> list[dict[str, object]]`
- `load_labels(path: Path) -> list[dict[str, str]]`
- `load_annotations(path: Path) -> list[dict[str, str]]`
- `build_variant_comparison(variant_results, labels, annotations) -> dict[str, object]`
- 复用：`compare_ratings(records, labels) -> dict[str, object]`

- [ ] **步骤 1：写入失败测试**

创建 `test_variants.py`：

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest


def _record(asset_id: str, rating: int) -> dict[str, object]:
    return {
        "asset_id": asset_id,
        "relative_path": f"{asset_id}.mp4",
        "candidate_rating": rating,
        "summary": f"{asset_id} 摘要",
        "clip_suggestions": [],
        "error": None,
    }


def test_load_variant_results_combines_two_batches_without_duplicates(
    tmp_path: Path,
) -> None:
    from rating_lab.variants import load_variant_results

    for batch, records in (
        ("initial-30", [_record("a", 4)]),
        ("extension-15", [_record("b", 3)]),
    ):
        path = tmp_path / batch
        path.mkdir()
        (path / "results.json").write_text(json.dumps(records), encoding="utf-8")

    assert [row["asset_id"] for row in load_variant_results(tmp_path)] == ["a", "b"]


def test_load_variant_results_rejects_duplicate_assets(tmp_path: Path) -> None:
    from rating_lab.variants import load_variant_results

    for batch in ("initial-30", "extension-15"):
        path = tmp_path / batch
        path.mkdir()
        (path / "results.json").write_text(
            json.dumps([_record("same", 4)]), encoding="utf-8"
        )

    with pytest.raises(ValueError, match="重复素材"):
        load_variant_results(tmp_path)


def test_build_variant_comparison_selects_key_review_assets() -> None:
    from rating_lab.variants import build_variant_comparison

    results = {
        "balanced": [_record("annotated", 4), _record("split", 5), _record("same", 3)],
        "conservative": [
            _record("annotated", 3),
            _record("split", 2),
            _record("same", 3),
        ],
        "recall": [_record("annotated", 4), _record("split", 4), _record("same", 3)],
    }
    labels = [
        {"asset_id": "annotated", "expected_rating": "4"},
        {"asset_id": "split", "expected_rating": "4"},
        {"asset_id": "same", "expected_rating": "3"},
    ]
    annotations = [
        {"asset_id": "annotated", "human_rating_reason": "人工意见"},
        {"asset_id": "split", "human_rating_reason": ""},
        {"asset_id": "same", "human_rating_reason": ""},
    ]

    comparison = build_variant_comparison(results, labels, annotations)

    assert comparison["key_asset_ids"] == ["annotated", "split"]
    assert comparison["variants"]["balanced"]["metrics"]["sample_count"] == 3
    assert comparison["assets"][0]["has_human_reason"] is True
```

- [ ] **步骤 2：运行测试并确认模块缺失**

运行：

```bash
.venv/bin/python -m pytest -q rating-lab/tests/test_variants.py
```

预期：因 `rating_lab.variants` 不存在而失败。

- [ ] **步骤 3：实现文件加载**

在 `variants.py` 实现：

```python
def load_variant_results(variant_dir: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for batch in ("initial-30", "extension-15"):
        path = variant_dir / batch / "results.json"
        records.extend(json.loads(path.read_text(encoding="utf-8")))
    asset_ids = [str(row.get("asset_id") or "") for row in records]
    if len(asset_ids) != len(set(asset_ids)):
        raise ValueError(f"候选版本中存在重复素材：{variant_dir}")
    return records


def load_labels(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def load_annotations(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))
```

- [ ] **步骤 4：实现比较和关键筛选**

`build_variant_comparison()` 必须：

- 校验三个版本的 `asset_id` 集合完全一致。
- 调用 `compare_ratings()` 计算每版指标。
- 为每条素材附加统一评分、原始导出评分、人工评语、错误类型和三版结果。
- 按以下条件设置 `is_key_review`：
  - 有文字评语。
  - 三版最大分减最小分至少 2。
  - 任一版与统一评分相差至少 2。
  - 至少一版完全命中且至少一版没有命中。
- 按“有评语、版本分歧、最大误差、原顺序”排序。

返回结构：

```python
{
    "schema_version": 1,
    "variants": {
        name: {"metrics": compare_ratings(records, labels)}
        for name, records in variant_results.items()
    },
    "key_asset_ids": [
        row["asset_id"] for row in assets if row["is_key_review"]
    ],
    "assets": assets,
}
```

- [ ] **步骤 5：运行测试**

运行：

```bash
.venv/bin/python -m pytest -q rating-lab/tests/test_variants.py
.venv/bin/python -m pytest -q rating-lab/tests/test_evaluation.py
```

预期：全部通过。

- [ ] **步骤 6：提交比较逻辑**

```bash
git add \
  rating-lab/rating_lab/variants.py \
  rating-lab/rating_lab/evaluation.py \
  rating-lab/tests/test_variants.py
git commit -m "feat(rating-lab): 支持三版结果汇总比较"
```

---

### 任务 4：生成三版并排人工复核页面

**文件：**

- 创建：`rating-lab/rating_lab/templates/variant_review.html.tmpl`
- 修改：`rating-lab/rating_lab/review.py`
- 修改：`rating-lab/tests/test_review.py`

**接口：**

- `write_variant_review_html(path: Path, comparison: Mapping[str, object], source_folder: str) -> None`
- 输入：`build_variant_comparison()` 的结果。
- 产出：含 45 条素材、三版并排信息、本地保存和 CSV 导出的离线 HTML。

- [ ] **步骤 1：写入失败测试**

```python
def test_write_variant_review_html_contains_variants_and_key_filter(
    tmp_path: Path,
) -> None:
    from rating_lab.review import write_variant_review_html

    comparison = {
        "variants": {
            "v5-balanced": {"metrics": {"sample_count": 1}},
            "v5-conservative": {"metrics": {"sample_count": 1}},
            "v5-recall": {"metrics": {"sample_count": 1}},
        },
        "key_asset_ids": ["asset-1"],
        "assets": [
            {
                "asset_id": "asset-1",
                "relative_path": "day/a.mp4",
                "expected_rating": 4,
                "original_expected_rating": 2,
                "human_rating_reason": "人工意见",
                "model_error_type": "none",
                "is_key_review": True,
                "variant_results": {
                    "v5-balanced": {"candidate_rating": 4, "summary": "平衡"},
                    "v5-conservative": {"candidate_rating": 3, "summary": "保守"},
                    "v5-recall": {"candidate_rating": 5, "summary": "召回"},
                },
            }
        ],
    }
    output = tmp_path / "review.html"

    write_variant_review_html(output, comparison, str(tmp_path))

    html = output.read_text(encoding="utf-8")
    assert "v5-balanced" in html
    assert "v5-conservative" in html
    assert "v5-recall" in html
    assert "关键复核" in html
    assert "偏好版本" in html
    assert "localStorage" in html
    assert "导出 CSV" in html
    assert "asset-1" in html
```

- [ ] **步骤 2：运行测试并确认函数不存在**

运行：

```bash
.venv/bin/python -m pytest -q \
  rating-lab/tests/test_review.py::test_write_variant_review_html_contains_variants_and_key_filter
```

预期：导入 `write_variant_review_html` 失败。

- [ ] **步骤 3：实现安全数据嵌入**

在 `review.py` 中：

```python
def _safe_json(value: object) -> str:
    return (
        json.dumps(value, ensure_ascii=False)
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )


def write_variant_review_html(
    path: Path,
    comparison: Mapping[str, object],
    source_folder: str,
) -> None:
    source_root = Path(source_folder).expanduser().resolve(strict=False)
    payload = dict(comparison)
    for row in payload["assets"]:
        media_path = (source_root / row["relative_path"]).resolve(strict=False)
        row["media_uri"] = (
            media_path.as_uri() if media_path.is_relative_to(source_root) else ""
        )
    template = (
        Path(__file__).parent / "templates" / "variant_review.html.tmpl"
    ).read_text(encoding="utf-8")
    rendered = template.replace("__VARIANT_REVIEW_DATA__", _safe_json(payload))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(rendered)
```

实现时复制 `assets` 数据，禁止原地修改调用方传入的 `comparison`。

- [ ] **步骤 4：实现离线页面**

模板必须实现：

- 顶部三版指标卡。
- “关键复核 / 全部 45 条”筛选。
- 有评语、版本分歧和最大误差排序。
- 每条视频与人工信息。
- 三版星级、summary、最佳片段时间和理由并排展示。
- 偏好版本单选和补充意见。
- 使用包含数据集和版本名的 localStorage key 自动保存。
- 导出字段：

```text
asset_id
relative_path
expected_rating
human_rating_reason
balanced_rating
conservative_rating
recall_rating
preferred_variant
review_note
```

- [ ] **步骤 5：运行页面测试**

运行：

```bash
.venv/bin/python -m pytest -q rating-lab/tests/test_review.py
```

预期：全部通过。

- [ ] **步骤 6：提交复核页面**

```bash
git add \
  rating-lab/rating_lab/review.py \
  rating-lab/rating_lab/templates/variant_review.html.tmpl \
  rating-lab/tests/test_review.py
git commit -m "feat(rating-lab): 新增三版并排复核页面"
```

---

### 任务 5：增加 `compare-variants` 命令

**文件：**

- 修改：`rating-lab/cli.py`
- 修改：`rating-lab/tests/test_cli.py`
- 修改：`rating-lab/README.md`

**接口：**

- 命令：

```text
rating-lab/cli.py compare-variants
  --variant NAME=DIR
  --labels PATH
  --annotations PATH
  --source-folder PATH
  --output-dir PATH
```

- 每个 `--variant` 目录包含 `initial-30/results.json` 和 `extension-15/results.json`。
- 输出：每版 `combined-results.json`、每版 `metrics.json`、汇总 `comparison.json` 和 `v5-variant-review.html`。

- [ ] **步骤 1：写入 CLI 失败测试**

使用三个临时版本目录，每版各写两批结果，执行：

```python
command = [
    sys.executable,
    "rating-lab/cli.py",
    "compare-variants",
    "--variant",
    f"v5-balanced={balanced_dir}",
    "--variant",
    f"v5-conservative={conservative_dir}",
    "--variant",
    f"v5-recall={recall_dir}",
    "--labels",
    str(labels_path),
    "--annotations",
    str(annotations_path),
    "--source-folder",
    str(tmp_path),
    "--output-dir",
    str(output_dir),
]
```

断言：

```python
assert completed.returncode == 0, completed.stderr
assert (output_dir / "comparison.json").exists()
assert (output_dir / "v5-variant-review.html").exists()
for variant_dir in (balanced_dir, conservative_dir, recall_dir):
    assert (variant_dir / "combined-results.json").exists()
    assert (variant_dir / "metrics.json").exists()
```

- [ ] **步骤 2：运行测试并确认子命令不存在**

运行：

```bash
.venv/bin/python -m pytest -q rating-lab/tests/test_cli.py -k compare_variants
```

预期：命令返回非零，argparse 报告无此子命令。

- [ ] **步骤 3：实现参数解析**

新增 `compare-variants`，要求 `--variant` 恰好出现三次且名称唯一。解析函数：

```python
def _parse_variant(value: str) -> tuple[str, Path]:
    try:
        name, raw_path = value.split("=", 1)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("候选版本格式应为 NAME=DIR") from exc
    if not name or not raw_path:
        raise argparse.ArgumentTypeError("候选版本格式应为 NAME=DIR")
    return name, Path(raw_path)
```

- [ ] **步骤 4：实现独占输出**

命令流程：

1. 加载三版结果、统一标签和评语。
2. 任一版不是 45 条或包含失败记录时退出，不创建部分汇总。
3. 确认所有目标文件均不存在。
4. 为每版写入 `combined-results.json` 和 `metrics.json`。
5. 在 `output-dir` 写入 `comparison.json`。
6. 调用 `write_variant_review_html()` 写入 `v5-variant-review.html`。

所有 JSON 使用 UTF-8、`ensure_ascii=False`、两空格缩进和末尾换行。

- [ ] **步骤 5：运行 CLI 和全套测试**

运行：

```bash
.venv/bin/python -m pytest -q rating-lab/tests/test_cli.py
.venv/bin/python -m pytest -q rating-lab/tests
```

预期：全部通过。

- [ ] **步骤 6：更新实验室 README**

加入三版运行目录和 `compare-variants` 示例，不改生产使用说明。

- [ ] **步骤 7：提交命令**

```bash
git add rating-lab/cli.py rating-lab/tests/test_cli.py rating-lab/README.md
git commit -m "feat(rating-lab): 增加三版实验比较命令"
```

---

### 任务 6：运行三版完整 45 条实验

**文件：**

- 创建：`rating-lab/runs/development-v1/candidates/v5-balanced/`
- 创建：`rating-lab/runs/development-v1/candidates/v5-conservative/`
- 创建：`rating-lab/runs/development-v1/candidates/v5-recall/`
- 创建：`rating-lab/reports/development-v1/v5-variants/comparison.json`
- 创建：`rating-lab/reports/development-v1/v5-variants/v5-variant-review.html`

**接口：**

- 输入：两个固定批次、三份 v5 Prompt、26shidu 只读 `cut_index.json`。
- 产出：135 条成功模型评分、三版指标和并排复核页。

- [ ] **步骤 1：运行平衡版两批**

```bash
.venv/bin/python rating-lab/cli.py run \
  --cut-index projects/26shidu/cut_index.json \
  --manifest rating-lab/datasets/development-v1/batches/initial-30/manifest.json \
  --rating-guide rating-lab/prompts/single-highlight-v5-balanced.txt \
  --output-dir rating-lab/runs/development-v1/candidates/v5-balanced/initial-30 \
  --concurrency 3

.venv/bin/python rating-lab/cli.py run \
  --cut-index projects/26shidu/cut_index.json \
  --manifest rating-lab/datasets/development-v1/batches/extension-15/manifest.json \
  --rating-guide rating-lab/prompts/single-highlight-v5-balanced.txt \
  --output-dir rating-lab/runs/development-v1/candidates/v5-balanced/extension-15 \
  --concurrency 3
```

预期：45 条成功、0 条失败。

- [ ] **步骤 2：运行保守版两批**

```bash
.venv/bin/python rating-lab/cli.py run \
  --cut-index projects/26shidu/cut_index.json \
  --manifest rating-lab/datasets/development-v1/batches/initial-30/manifest.json \
  --rating-guide rating-lab/prompts/single-highlight-v5-conservative.txt \
  --output-dir rating-lab/runs/development-v1/candidates/v5-conservative/initial-30 \
  --concurrency 3

.venv/bin/python rating-lab/cli.py run \
  --cut-index projects/26shidu/cut_index.json \
  --manifest rating-lab/datasets/development-v1/batches/extension-15/manifest.json \
  --rating-guide rating-lab/prompts/single-highlight-v5-conservative.txt \
  --output-dir rating-lab/runs/development-v1/candidates/v5-conservative/extension-15 \
  --concurrency 3
```

预期：45 条成功、0 条失败。

- [ ] **步骤 3：运行高召回版两批**

```bash
.venv/bin/python rating-lab/cli.py run \
  --cut-index projects/26shidu/cut_index.json \
  --manifest rating-lab/datasets/development-v1/batches/initial-30/manifest.json \
  --rating-guide rating-lab/prompts/single-highlight-v5-recall.txt \
  --output-dir rating-lab/runs/development-v1/candidates/v5-recall/initial-30 \
  --concurrency 3

.venv/bin/python rating-lab/cli.py run \
  --cut-index projects/26shidu/cut_index.json \
  --manifest rating-lab/datasets/development-v1/batches/extension-15/manifest.json \
  --rating-guide rating-lab/prompts/single-highlight-v5-recall.txt \
  --output-dir rating-lab/runs/development-v1/candidates/v5-recall/extension-15 \
  --concurrency 3
```

预期：45 条成功、0 条失败。

- [ ] **步骤 4：生成指标和复核页**

```bash
.venv/bin/python rating-lab/cli.py compare-variants \
  --variant v5-balanced=rating-lab/runs/development-v1/candidates/v5-balanced \
  --variant v5-conservative=rating-lab/runs/development-v1/candidates/v5-conservative \
  --variant v5-recall=rating-lab/runs/development-v1/candidates/v5-recall \
  --labels rating-lab/datasets/development-v1/human-labels.csv \
  --annotations rating-lab/datasets/development-v1/annotations.csv \
  --source-folder "$(jq -r '.project.source_folder' projects/26shidu/cut_index.json)" \
  --output-dir rating-lab/reports/development-v1/v5-variants
```

预期：生成三版合并结果、三版指标、汇总 JSON 和 45 条复核 HTML。

- [ ] **步骤 5：验证结果数量**

运行：

```bash
.venv/bin/python -c 'import json; from pathlib import Path
root=Path("rating-lab/runs/development-v1/candidates")
for name in ("v5-balanced", "v5-conservative", "v5-recall"):
    rows=json.loads((root/name/"combined-results.json").read_text(encoding="utf-8"))
    assert len(rows)==45
    assert all(not row["error"] for row in rows)
comparison=json.loads(Path("rating-lab/reports/development-v1/v5-variants/comparison.json").read_text(encoding="utf-8"))
assert len(comparison["assets"])==45
assert len(comparison["key_asset_ids"])>=8'
```

预期：退出码为 0。

- [ ] **步骤 6：提交实验结果**

```bash
git add \
  rating-lab/runs/development-v1/candidates \
  rating-lab/reports/development-v1/v5-variants
git commit -m "data(rating-lab): 记录v5三版45条实验"
```

---

### 任务 7：最终验证和交付复核入口

**文件：**

- 验证：`rating-lab/`
- 验证：TripClipper Provider

**接口：**

- 输入：任务 1–6 的全部结果。
- 产出：测试、编译、数据数量和生产隔离均通过的 v5 三版实验。

- [ ] **步骤 1：运行全部实验室和 Provider 测试**

```bash
.venv/bin/python -m pytest -q rating-lab/tests tests/test_provider.py
```

预期：0 失败。

- [ ] **步骤 2：运行编译检查**

```bash
.venv/bin/python -m compileall -q rating-lab/cli.py rating-lab/rating_lab
```

预期：退出码为 0。

- [ ] **步骤 3：验证旧 Prompt 未改变和生产未接入**

```bash
git diff 8c1ff78 -- \
  rating-lab/prompts/single-highlight-v2.txt \
  rating-lab/prompts/single-highlight-v3.txt \
  rating-lab/prompts/single-highlight-v4.txt \
  rating-lab/prompts/strict-v1.txt

rg -n "single-highlight-v5|v5-balanced|v5-conservative|v5-recall" src
```

预期：两个命令都无输出。

- [ ] **步骤 4：检查提交范围**

```bash
git diff --check
git status --short
git log -7 --oneline
```

预期：

- `rating-lab` 范围没有未提交改动。
- 用户原有无关改动保持原状态。
- v5 实验提交彼此独立。

- [ ] **步骤 5：交付人工复核入口**

向用户提供：

```text
rating-lab/reports/development-v1/v5-variants/v5-variant-review.html
```

并报告三版指标，但不替用户做最终偏好裁定。
