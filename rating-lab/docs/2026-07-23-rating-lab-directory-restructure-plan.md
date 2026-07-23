# 评分 Prompt 调优实验室目录重构实施计划

> **供智能体执行：** 必须使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`，逐项执行本计划。所有步骤使用复选框跟踪。

**目标：** 将评分 Prompt 调优的代码、测试、Prompt、45 条开发集、七次历史运行和报告集中迁入自包含的 `rating-lab/`，彻底移除 26shidu 下的调优目录和含义模糊的旧代码入口。

**架构：** `rating-lab/cli.py` 是唯一入口，领域代码按抽样、运行、评估和复核拆入 `rating-lab/rating_lab/`。实验数据以 `development-v1` 为统一开发集，同时保留 `initial-30` 和 `extension-15` 两个原始批次；评分实验室单向复用 `tripclipper`，正式代码不反向依赖实验室。

**技术栈：** Python 3.10、argparse、pytest、JSON、CSV、离线 HTML、现有 TripClipper Provider。

## 全局约束

- 所有实验代码、测试、Prompt、数据、报告和文档均位于 `rating-lab/`。
- 不保留旧路径符号链接、兼容脚本、占位文件或重复副本。
- 26shidu 仅作为素材来源；其 `cut_index.json` 是只读输入。
- 初始 30 条和后续 15 条共同组成 45 条 `development-v1`，后续 15 条不再称为留出集。
- 使用第一次有效导出的 `/Users/bytedance/Downloads/rating-review-45-annotations.csv`，忽略第二次几乎为空的导出。
- 文字评语优先于错误类型和数值差；四条无评语的严重偏差视为模型判断符合预期。
- 保留七次历史运行，包括失败运行；不伪造缺失文件或 Prompt 版本。
- 不生成 v5 Prompt，不调用模型，不修改 TripClipper 正式评分链路。
- 不覆盖任何已存在的目标文件；冲突时停止。
- 只提交本计划范围内的文件，不夹带工作区原有改动。

---

### 任务 1：建立迁移基线和自包含测试入口

**文件：**

- 创建：`rating-lab/tests/conftest.py`
- 创建：`rating-lab/tests/test_dataset_integrity.py`
- 移动并拆分：`tests/test_rating_calibration.py`
- 参考：`projects/26shidu/rating-calibration/`
- 参考：`projects/26shidu/rating-validation/`

**接口：**

- 输入：现有两个批次的 manifest、人工标签、历史运行和报告。
- 产出：可从仓库根目录运行的 `rating-lab/tests/`，以及迁移完成后必须满足的数据完整性断言。

- [ ] **步骤 1：记录迁移前不可变基线**

运行：

```bash
.venv/bin/python -m pytest -q tests/test_rating_calibration.py tests/test_provider.py
find projects/26shidu/rating-calibration projects/26shidu/rating-validation -type f | sort
```

预期：

- 评分调优和 Provider 测试全部通过。
- 初始批次包含 30 条，后续批次包含 15 条。
- 历史运行目录为初始批次 5 个、后续批次 2 个。

- [ ] **步骤 2：创建测试路径配置**

创建 `rating-lab/tests/conftest.py`：

```python
"""评分实验室测试路径配置。"""

from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
LAB_ROOT = REPO_ROOT / "rating-lab"
TRIPCLIPPER_SRC = REPO_ROOT / "src"

for path in (LAB_ROOT, TRIPCLIPPER_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
```

- [ ] **步骤 3：先写迁移完成后应通过的数据完整性测试**

创建 `rating-lab/tests/test_dataset_integrity.py`，至少包含：

```python
from __future__ import annotations

import csv
import json
from pathlib import Path


LAB_ROOT = Path(__file__).resolve().parents[1]
DATASET_ROOT = LAB_ROOT / "datasets" / "development-v1"


def test_development_dataset_contains_two_batches_and_45_unique_assets() -> None:
    dataset = json.loads((DATASET_ROOT / "dataset.json").read_text(encoding="utf-8"))
    rows = dataset["assets"]

    assert dataset["dataset_id"] == "development-v1"
    assert dataset["sample_count"] == 45
    assert len(rows) == 45
    assert len({row["asset_id"] for row in rows}) == 45
    assert sum(row["batch"] == "initial-30" for row in rows) == 30
    assert sum(row["batch"] == "extension-15" for row in rows) == 15


def test_human_labels_and_annotations_cover_expected_rows() -> None:
    with (DATASET_ROOT / "human-labels.csv").open(
        encoding="utf-8-sig", newline=""
    ) as handle:
        labels = list(csv.DictReader(handle))
    with (DATASET_ROOT / "annotations.csv").open(
        encoding="utf-8-sig", newline=""
    ) as handle:
        annotations = list(csv.DictReader(handle))

    assert len(labels) == 45
    assert len({row["asset_id"] for row in labels}) == 45
    assert len(annotations) == 45
    assert sum(bool(row["human_rating_reason"].strip()) for row in annotations) == 8


def test_all_seven_historical_runs_are_preserved() -> None:
    runs = LAB_ROOT / "runs" / "development-v1"

    assert sorted(path.name for path in (runs / "initial-30").glob("run-*")) == [
        "run-001", "run-002", "run-003", "run-004", "run-005"
    ]
    assert sorted(path.name for path in (runs / "extension-15").glob("run-*")) == [
        "run-001", "run-002"
    ]


def test_old_project_owned_lab_directories_are_removed() -> None:
    repo_root = LAB_ROOT.parent

    assert not (repo_root / "projects/26shidu/rating-calibration").exists()
    assert not (repo_root / "projects/26shidu/rating-validation").exists()
```

- [ ] **步骤 4：运行完整性测试并确认它因尚未迁移而失败**

运行：

```bash
.venv/bin/python -m pytest -q rating-lab/tests/test_dataset_integrity.py
```

预期：失败原因是 `dataset.json`、统一人工标签、统一评语或新运行目录尚不存在，不是测试导入错误。

- [ ] **步骤 5：将原测试按职责拆入新目录**

将 `tests/test_rating_calibration.py` 中的测试移动并改写导入：

```text
rating-lab/tests/test_sampling.py
  DEFAULT_RATING_QUOTAS
  select_fixed_sample
  build_manifest
  project_fingerprint
  prepare CLI

rating-lab/tests/test_runner.py
  run_calibration
  reserve_run_dir
  write_results
  run CLI

rating-lab/tests/test_evaluation.py
  compare_ratings
  compare CLI

rating-lab/tests/test_review.py
  write_manifest
  write_manual_labels
  write_manual_review_html
  Prompt 内容契约

rating-lab/tests/test_cli.py
  参数解析和帮助输出
```

所有旧导入：

```python
from tripclipper.rating_calibration import function_name
```

分别替换为：

```python
from rating_lab.sampling import function_name
from rating_lab.runner import function_name
from rating_lab.evaluation import function_name
from rating_lab.review import function_name
```

所有子进程命令入口替换为：

```python
[sys.executable, "rating-lab/cli.py", "prepare", "--help"]
```

Prompt 根目录替换为：

```python
Path(__file__).parents[1] / "prompts"
```

- [ ] **步骤 6：运行拆分后的测试并确认因新模块缺失而失败**

运行：

```bash
.venv/bin/python -m pytest -q rating-lab/tests -k "not dataset_integrity"
```

预期：收集阶段失败，提示 `rating_lab.sampling` 等模块不存在。

- [ ] **步骤 7：提交测试迁移**

```bash
git add rating-lab/tests tests/test_rating_calibration.py
git commit -m "test(rating-lab): 建立独立测试边界"
```

---

### 任务 2：拆分评分实验室领域模块

**文件：**

- 创建：`rating-lab/rating_lab/__init__.py`
- 创建：`rating-lab/rating_lab/sampling.py`
- 创建：`rating-lab/rating_lab/runner.py`
- 创建：`rating-lab/rating_lab/evaluation.py`
- 创建：`rating-lab/rating_lab/review.py`
- 移动：`src/tripclipper/templates/rating_manual_review.html.tmpl`
- 删除：`src/tripclipper/rating_calibration.py`

**接口：**

- `sampling.py` 产出：`DEFAULT_RATING_QUOTAS`、`project_fingerprint()`、`select_fixed_sample()`、`build_manifest()`。
- `runner.py` 产出：`reserve_run_dir()`、`run_calibration()`、`write_results()`。
- `evaluation.py` 产出：`compare_ratings()`。
- `review.py` 产出：`write_manifest()`、`write_manual_labels()`、`write_manual_review_html()`。

- [ ] **步骤 1：创建包入口**

创建 `rating-lab/rating_lab/__init__.py`：

```python
"""评分 Prompt 调优实验室。"""
```

- [ ] **步骤 2：移动抽样逻辑**

把以下符号从 `src/tripclipper/rating_calibration.py` 原样移动到 `sampling.py`：

```python
DEFAULT_RATING_QUOTAS
project_fingerprint
_asset_identity
_sample_order
_secondary_balance_key
_balanced_pick
select_fixed_sample
_enum_value
build_manifest
```

使用绝对依赖：

```python
from tripclipper.models import Asset
```

- [ ] **步骤 3：运行抽样测试**

运行：

```bash
.venv/bin/python -m pytest -q rating-lab/tests/test_sampling.py
```

预期：全部通过。

- [ ] **步骤 4：移动运行逻辑**

把以下符号原样移动到 `runner.py`：

```python
reserve_run_dir
write_results
run_calibration
```

使用绝对依赖：

```python
from tripclipper.models import Asset
from tripclipper.provider import AnalysisResult
```

- [ ] **步骤 5：运行模型执行测试**

运行：

```bash
.venv/bin/python -m pytest -q rating-lab/tests/test_runner.py
```

预期：全部通过，并发测试仍保持 manifest 顺序。

- [ ] **步骤 6：移动评估逻辑**

把 `compare_ratings()` 原样移动到 `evaluation.py`，保留全部输入校验和指标字段。

- [ ] **步骤 7：运行评估测试**

运行：

```bash
.venv/bin/python -m pytest -q rating-lab/tests/test_evaluation.py
```

预期：全部通过。

- [ ] **步骤 8：移动复核逻辑和模板**

把以下符号移动到 `review.py`：

```python
write_manifest
write_manual_labels
write_manual_review_html
```

将模板移动为：

```text
rating-lab/rating_lab/templates/rating_manual_review.html.tmpl
```

模板定位改为：

```python
template_path = (
    Path(__file__).parent / "templates" / "rating_manual_review.html.tmpl"
)
```

- [ ] **步骤 9：运行复核测试**

运行：

```bash
.venv/bin/python -m pytest -q rating-lab/tests/test_review.py
```

预期：全部通过，HTML 仍然盲评、转义路径并拒绝覆盖。

- [ ] **步骤 10：删除旧模块并验证依赖方向**

删除 `src/tripclipper/rating_calibration.py`，然后运行：

```bash
rg -n "tripclipper\\.rating_calibration|rating_calibration" src rating-lab \
  --glob '!**/__pycache__/**'
```

预期：活动代码与测试中没有旧模块导入；历史文档可保留旧名称。

- [ ] **步骤 11：提交领域模块拆分**

```bash
git add rating-lab/rating_lab src/tripclipper/rating_calibration.py src/tripclipper/templates/rating_manual_review.html.tmpl
git commit -m "refactor(rating-lab): 拆分实验工具职责"
```

---

### 任务 3：迁移唯一 CLI 和 Prompt

**文件：**

- 创建：`rating-lab/cli.py`
- 删除：`scripts/calibrate_rating.py`
- 移动：`prompts/rating-guide-single-highlight-v2.txt`
- 移动：`prompts/rating-guide-single-highlight-v3.txt`
- 移动：`prompts/rating-guide-single-highlight-v4.txt`
- 移动：`prompts/rating-guide-strict-v1.txt`
- 测试：`rating-lab/tests/test_cli.py`
- 测试：`rating-lab/tests/test_sampling.py`
- 测试：`rating-lab/tests/test_runner.py`
- 测试：`rating-lab/tests/test_evaluation.py`
- 测试：`rating-lab/tests/test_review.py`

**接口：**

- 输入：`prepare`、`run`、`compare` 参数保持原语义。
- 产出：`.venv/bin/python rating-lab/cli.py <command>`。

- [ ] **步骤 1：移动 CLI 并替换模块导入**

将 `scripts/calibrate_rating.py` 移为 `rating-lab/cli.py`。仓库根目录改为：

```python
LAB_ROOT = Path(__file__).resolve().parent
REPO_ROOT = LAB_ROOT.parent
TRIPCLIPPER_SRC = REPO_ROOT / "src"
if str(TRIPCLIPPER_SRC) not in sys.path:
    sys.path.insert(0, str(TRIPCLIPPER_SRC))
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))
```

导入改为：

```python
from rating_lab.evaluation import compare_ratings
from rating_lab.review import (
    write_manifest,
    write_manual_labels,
    write_manual_review_html,
)
from rating_lab.runner import reserve_run_dir, run_calibration, write_results
from rating_lab.sampling import (
    DEFAULT_RATING_QUOTAS,
    build_manifest,
    project_fingerprint,
)
```

其余命令行为保持不变。

- [ ] **步骤 2：迁移并简化 Prompt 文件名**

执行一对一移动：

```text
prompts/rating-guide-single-highlight-v2.txt → rating-lab/prompts/single-highlight-v2.txt
prompts/rating-guide-single-highlight-v3.txt → rating-lab/prompts/single-highlight-v3.txt
prompts/rating-guide-single-highlight-v4.txt → rating-lab/prompts/single-highlight-v4.txt
prompts/rating-guide-strict-v1.txt           → rating-lab/prompts/strict-v1.txt
```

不修改 Prompt 内容。

- [ ] **步骤 3：运行除数据完整性外的评分实验室测试**

运行：

```bash
.venv/bin/python -m pytest -q rating-lab/tests -k "not dataset_integrity"
```

预期：全部通过。

- [ ] **步骤 4：检查唯一入口和旧路径消失**

运行：

```bash
test -f rating-lab/cli.py
test ! -e scripts/calibrate_rating.py
test ! -e prompts/rating-guide-single-highlight-v4.txt
.venv/bin/python rating-lab/cli.py --help
```

预期：前三条退出码为 0；帮助中出现 `prepare`、`run`、`compare`。

- [ ] **步骤 5：提交 CLI 与 Prompt 迁移**

```bash
git add rating-lab/cli.py rating-lab/prompts scripts/calibrate_rating.py prompts
git commit -m "refactor(rating-lab): 集中命令入口和评分提示词"
```

---

### 任务 4：迁移两批数据、历史运行和报告

**文件：**

- 创建：`rating-lab/datasets/development-v1/dataset.json`
- 创建：`rating-lab/datasets/development-v1/human-labels.csv`
- 创建：`rating-lab/datasets/development-v1/annotations.csv`
- 移动：`projects/26shidu/rating-calibration/sample_manifest.json`
- 移动：`projects/26shidu/rating-calibration/manual_labels.csv`
- 移动：`projects/26shidu/rating-calibration/manual_labels.completed.csv`
- 移动：`projects/26shidu/rating-validation/sample_manifest.json`
- 移动：`projects/26shidu/rating-validation/manual_labels.csv`
- 移动：`projects/26shidu/rating-validation/manual_labels.completed.csv`
- 移动：两个批次的七个 `run-*` 目录
- 移动：三个现有人工复核 HTML 和两个盲评 HTML
- 复制来源：`/Users/bytedance/Downloads/rating-review-45-annotations.csv`

**接口：**

- 输入：两个旧 manifest、两份已完成人工标签、第一次有效评语导出。
- 产出：统一 45 条数据集，同时保留两个原始批次和七次历史运行。

- [ ] **步骤 1：创建目标目录并确认无冲突**

运行：

```bash
mkdir -p rating-lab/datasets/development-v1/batches/initial-30
mkdir -p rating-lab/datasets/development-v1/batches/extension-15
mkdir -p rating-lab/runs/development-v1/initial-30
mkdir -p rating-lab/runs/development-v1/extension-15
mkdir -p rating-lab/reports/development-v1
```

随后逐个检查目标文件不存在；任一目标已存在则停止，不覆盖。

- [ ] **步骤 2：移动两批原始资料**

使用以下目标名称：

```text
batches/initial-30/manifest.json
batches/initial-30/human-labels-template.csv
batches/initial-30/human-labels.csv
batches/extension-15/manifest.json
batches/extension-15/human-labels-template.csv
batches/extension-15/human-labels.csv
```

两个 `manual-review.html` 分别移为：

```text
reports/development-v1/manual-review-initial-30.html
reports/development-v1/manual-review-extension-15.html
```

- [ ] **步骤 3：移动七次历史运行**

一对一移动：

```text
projects/26shidu/rating-calibration/run-* → rating-lab/runs/development-v1/initial-30/
projects/26shidu/rating-validation/run-*  → rating-lab/runs/development-v1/extension-15/
```

然后将复核 HTML 从 `extension-15/run-002/` 移到：

```text
rating-gap-review.html    → reports/development-v1/rating-gap-review-extension-15.html
rating-gap-review-45.html → reports/development-v1/rating-gap-review-45.html
```

- [ ] **步骤 4：生成统一 `dataset.json`**

使用 `jq` 读取两个新 manifest：

```bash
jq -s '
  .[0] as $initial |
  .[1] as $extension |
  {
    schema_version: 1,
    dataset_id: "development-v1",
    sample_count: 45,
    sources: [
      {
        project_slug: "26shidu",
        cut_index: "projects/26shidu/cut_index.json",
        role: "read-only-source"
      }
    ],
    batches: [
      {
        batch: "initial-30",
        manifest: "batches/initial-30/manifest.json",
        sample_count: ($initial.assets | length)
      },
      {
        batch: "extension-15",
        manifest: "batches/extension-15/manifest.json",
        sample_count: ($extension.assets | length)
      }
    ],
    assets: (
      ($initial.assets | map({
        asset_id,
        relative_path,
        batch: "initial-30"
      })) +
      ($extension.assets | map({
        asset_id,
        relative_path,
        batch: "extension-15"
      }))
    )
  }
' \
  rating-lab/datasets/development-v1/batches/initial-30/manifest.json \
  rating-lab/datasets/development-v1/batches/extension-15/manifest.json \
  > /tmp/rating-lab-development-v1.json
```

用 `jq '.assets | length == 45 and ([.[].asset_id] | unique | length == 45)'`
确认输出为 `true` 后，将临时文件原子移动到
`rating-lab/datasets/development-v1/dataset.json`。每条素材只保留
`asset_id`、`relative_path` 和新增的 `batch`。

- [ ] **步骤 5：生成统一人工标签**

以 `initial-30/human-labels.csv` 的表头为统一表头，按顺序追加：

1. 初始 30 条数据行。
2. 后续 15 条数据行，不重复表头。

写入临时文件后验证：

```bash
.venv/bin/python -c 'import csv; from pathlib import Path; p=Path("rating-lab/datasets/development-v1/human-labels.csv"); rows=list(csv.DictReader(p.open(encoding="utf-8-sig", newline=""))); assert len(rows)==45; assert len({r["asset_id"] for r in rows})==45'
```

预期：退出码为 0。

- [ ] **步骤 6：复制第一次有效评语导出**

将：

```text
/Users/bytedance/Downloads/rating-review-45-annotations.csv
```

复制为：

```text
rating-lab/datasets/development-v1/annotations.csv
```

验证 45 条、8 条文字评语：

```bash
.venv/bin/python -c 'import csv; from pathlib import Path; p=Path("rating-lab/datasets/development-v1/annotations.csv"); rows=list(csv.DictReader(p.open(encoding="utf-8-sig", newline=""))); assert len(rows)==45; assert sum(bool(r["human_rating_reason"].strip()) for r in rows)==8'
```

预期：退出码为 0。

- [ ] **步骤 7：运行数据完整性测试**

运行：

```bash
.venv/bin/python -m pytest -q rating-lab/tests/test_dataset_integrity.py
```

预期：全部通过，包括旧 26shidu 调优目录已消失。

- [ ] **步骤 8：提交实验数据迁移**

```bash
git add rating-lab/datasets rating-lab/runs rating-lab/reports
git commit -m "data(rating-lab): 迁移45条开发集和历史运行"
```

---

### 任务 5：补齐实验室说明和迁移历史

**文件：**

- 创建：`rating-lab/README.md`
- 创建：`rating-lab/docs/rating-policy.md`
- 创建：`rating-lab/docs/experiment-history.md`
- 修改：`README.md`
- 修改：`docs/superpowers/plans/2026-07-21-rating-calibration-manual-review.md`
- 修改：`docs/superpowers/plans/2026-07-22-rating-holdout-sample.md`
- 修改：`docs/superpowers/plans/2026-07-22-single-highlight-rating-prompt.md`
- 修改：`docs/superpowers/specs/2026-07-21-rating-calibration-manual-review-design.md`
- 修改：`docs/superpowers/specs/2026-07-22-single-highlight-rating-prompt-design.md`

**接口：**

- 输入：最终目录和命令。
- 产出：从仓库 README 能找到实验室；从实验室 README 能完成 prepare、run、compare；历史文档能解释旧路径。

- [ ] **步骤 1：编写 `rating-lab/README.md`**

必须包含：

```text
用途与边界
目录导航
45 条 development-v1 的组成
prepare / run / compare 示例
新建运行目录与不覆盖规则
26shidu 只是只读素材来源
Prompt 版本和运行目录分离
候选 Prompt 不自动进入生产
```

示例命令统一使用：

```bash
.venv/bin/python rating-lab/cli.py run \
  --cut-index projects/26shidu/cut_index.json \
  --manifest rating-lab/datasets/development-v1/batches/initial-30/manifest.json \
  --rating-guide rating-lab/prompts/single-highlight-v4.txt \
  --output-dir rating-lab/runs/development-v1/initial-30/run-006 \
  --concurrency 3
```

- [ ] **步骤 2：记录评分解释规则**

在 `rating-policy.md` 明确：

```text
人工文字评语 > 人工错误类型 > 原始分差
无文字评语的四条严重偏差视为模型判断符合预期
竖版素材在缺少横版要求时不因方向自动降级
45 条全部属于开发集
真正留出集必须在候选 Prompt 冻结后重新抽取
```

- [ ] **步骤 3：记录实验历史**

在 `experiment-history.md` 记录：

- 初始 30 条与后续 15 条的创建背景。
- 七次运行目录及成功或失败状态。
- 45 条复核页和第一次有效评语导出。
- 能确认的 Prompt 版本；无法确认的版本标为“现有文件未记录”，不得猜测。
- 2026-07-23 从 26shidu 项目目录迁入仓库级实验室。

- [ ] **步骤 4：收缩仓库 README**

把仓库 README 的“评分 Prompt 校准”长段落替换为简短入口：

```markdown
### 评分 Prompt 调优实验室

评分标准的抽样、人工标注、候选 Prompt 运行和比较位于
[`rating-lab/`](rating-lab/README.md)。实验室可以把项目
`cut_index.json` 作为只读素材来源，但实验数据不属于任何正式项目，也不会自动写回
TripClipper 的生产产物。
```

- [ ] **步骤 5：给旧设计与计划文档增加迁移说明**

每份历史文档开头增加：

```markdown
> 迁移说明（2026-07-23）：本文保留当时的实现路径用于追溯。评分调优工具和实验资产现已迁入仓库级 `rating-lab/`；后续 15 条样本已并入 45 条开发集，不再作为留出集。
```

不修改文档其余历史叙述。

- [ ] **步骤 6：搜索活动引用**

运行：

```bash
rg -n "scripts/calibrate_rating\\.py|tripclipper\\.rating_calibration|projects/26shidu/rating-(calibration|validation)|prompts/rating-guide" \
  README.md rating-lab src tests \
  --glob '!rating-lab/docs/experiment-history.md'
```

预期：无活动代码、测试或当前说明引用旧入口；实验历史中的旧路径允许存在。

- [ ] **步骤 7：提交文档**

```bash
git add README.md rating-lab/README.md rating-lab/docs docs/superpowers
git commit -m "docs(rating-lab): 统一实验室使用说明"
```

---

### 任务 6：全量验证和安全收尾

**文件：**

- 验证：`rating-lab/`
- 验证：`src/tripclipper/provider.py`
- 验证：Git 工作区与提交范围

**接口：**

- 输入：任务 1–5 的完整迁移结果。
- 产出：通过测试、编译、数量和旧引用检查的自包含评分实验室。

- [ ] **步骤 1：运行评分实验室全套测试**

运行：

```bash
.venv/bin/python -m pytest -q rating-lab/tests
```

预期：全部通过。

- [ ] **步骤 2：运行依赖边界回归测试**

运行：

```bash
.venv/bin/python -m pytest -q tests/test_provider.py
```

预期：全部通过。

- [ ] **步骤 3：运行编译检查**

运行：

```bash
.venv/bin/python -m compileall -q rating-lab/cli.py rating-lab/rating_lab
```

预期：退出码为 0。

- [ ] **步骤 4：验证目录和数据数量**

运行：

```bash
test ! -e projects/26shidu/rating-calibration
test ! -e projects/26shidu/rating-validation
test ! -e scripts/calibrate_rating.py
test ! -e src/tripclipper/rating_calibration.py
test ! -e tests/test_rating_calibration.py
find rating-lab/runs/development-v1 -mindepth 2 -maxdepth 2 -type d -name 'run-*' | wc -l
```

预期：所有 `test` 命令退出码为 0；运行目录数量输出 `7`。

- [ ] **步骤 5：检查差异和未夹带改动**

运行：

```bash
git status --short
git diff --check
git log --oneline -6
```

预期：

- 没有本计划产生但未提交的文件。
- 用户原有的无关工作区修改仍保持原状态。
- 最近提交只包含评分实验室迁移的独立提交。

- [ ] **步骤 6：记录最终验证结果**

在执行记录中报告：

```text
评分实验室测试数量与结果
Provider 回归测试结果
开发集 45 条及批次 30/15
有效文字评语 8 条
历史运行 7 次
旧目录和旧入口已移除
未触碰的用户原有改动
```
