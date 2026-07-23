# 评分 Prompt 调优实验室

`rating-lab/` 集中保存评分 Prompt 调优所需的工具、测试、Prompt、开发集、模型运行结果、人工复核报告和实验文档。

它可以读取 TripClipper 项目的 `cut_index.json` 并调用现有 Provider，但不会修改项目数据：

```text
rating-lab → tripclipper
tripclipper ↛ rating-lab
```

26shidu 只是当前 45 条开发集的素材来源，不拥有这里的样本清单、人工评分、评语、模型结果或报告。

## 目录导航

```text
rating-lab/
├── cli.py                     # prepare、run、compare 唯一入口
├── rating_lab/                # 抽样、运行、评估、复核模块
├── tests/                     # 实验室测试和数据完整性测试
├── prompts/                   # 各版候选评分 Prompt
├── datasets/development-v1/  # 当前45条开发集
├── runs/development-v1/      # 七次历史模型运行
├── reports/development-v1/   # 人工盲评和差异复核页面
└── docs/                      # 设计、计划、评分口径和实验历史
```

常用入口：

- 统一开发集：[dataset.json](datasets/development-v1/dataset.json)
- 45 条人工评分：[human-labels.csv](datasets/development-v1/human-labels.csv)
- 第一次有效评语导出：[annotations.csv](datasets/development-v1/annotations.csv)
- 45 条差异复核页：[rating-gap-review-45.html](reports/development-v1/rating-gap-review-45.html)
- 人工解释规则：[rating-policy.md](docs/rating-policy.md)
- 历史运行说明：[experiment-history.md](docs/experiment-history.md)

## 当前开发集

`development-v1` 共 45 条，全部用于 Prompt 调优：

- `initial-30`：最初 30 条。
- `extension-15`：后来新增的 15 条。

后 15 条不再被视为留出集。真正的留出集应在候选 Prompt 冻结后，用未参与调优的新素材重新建立。

两个批次的原始 manifest 和人工标签保存在
`datasets/development-v1/batches/`；统一索引、人工评分和评语保存在
`datasets/development-v1/` 根目录。

## 使用命令

所有命令从仓库根目录执行。

### 生成新的固定样本批次

```bash
.venv/bin/python rating-lab/cli.py prepare \
  --cut-index projects/26shidu/cut_index.json \
  --manifest rating-lab/datasets/development-v2/batches/initial-30/manifest.json
```

`prepare` 会在 manifest 同目录生成 `manual_labels.csv` 和
`manual-review.html`。输出文件已存在时命令会停止，不会覆盖。

### 使用候选 Prompt 运行固定批次

```bash
.venv/bin/python rating-lab/cli.py run \
  --cut-index projects/26shidu/cut_index.json \
  --manifest rating-lab/datasets/development-v1/batches/initial-30/manifest.json \
  --rating-guide rating-lab/prompts/single-highlight-v4.txt \
  --output-dir rating-lab/runs/development-v1/initial-30/run-006 \
  --concurrency 3
```

`run` 只调用视觉模型，不运行语音分析，也不写回正式 `cut_index.json`。每次必须使用新的运行目录。

### 对比模型评分与人工评分

```bash
.venv/bin/python rating-lab/cli.py compare \
  --results rating-lab/runs/development-v1/initial-30/run-005/results.json \
  --labels rating-lab/datasets/development-v1/batches/initial-30/human-labels.csv \
  --output rating-lab/runs/development-v1/initial-30/run-005/comparison-recheck.json
```

结果包含完全一致率、平均绝对误差、相差至少两星的数量、4/5 星精确率与误判率、4/5 星召回率和混淆矩阵。

### 比较三个候选版本

每个候选版本目录包含 `initial-30/results.json` 和
`extension-15/results.json` 后，可以一次性合并 45 条结果、计算三版指标并生成并排
复核页：

```bash
.venv/bin/python rating-lab/cli.py compare-variants \
  --variant v5-balanced=rating-lab/runs/development-v1/candidates/v5-balanced \
  --variant v5-conservative=rating-lab/runs/development-v1/candidates/v5-conservative \
  --variant v5-recall=rating-lab/runs/development-v1/candidates/v5-recall \
  --labels rating-lab/datasets/development-v1/human-labels.csv \
  --annotations rating-lab/datasets/development-v1/annotations.csv \
  --source-folder "/素材根目录" \
  --output-dir rating-lab/reports/development-v1/v5-variants
```

命令要求每版恰好 45 条且没有失败记录，并拒绝覆盖已有的合并结果、指标或报告。

### 运行测试

```bash
.venv/bin/python -m pytest -q rating-lab/tests
```

## Prompt 和生产边界

现有 Prompt 文件按版本独立保存，历史运行目录也彼此独立，禁止覆盖旧版本或旧运行。

未来的 `v5-balanced`、`v5-conservative` 和 `v5-recall` 应保存为三个独立文件。评分实验室默认候选方向可以是平衡版，但候选 Prompt 不会自动进入 TripClipper 正式生产链路；生产切换需要单独验证和决策。
