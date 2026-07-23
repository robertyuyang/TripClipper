# 评分 Prompt 调优实验室目录重构设计

日期：2026-07-23

## 背景

当前评分 Prompt 调优能力分散在多个位置：

- 实验命令位于 `scripts/calibrate_rating.py`。
- 核心逻辑位于 `src/tripclipper/rating_calibration.py`。
- 人工复核模板位于 `src/tripclipper/templates/`。
- 测试位于仓库级 `tests/`。
- Prompt 位于仓库级 `prompts/`。
- 30 条初始样本及 15 条后续样本位于 `projects/26shidu/`。

这种结构错误地暗示实验数据属于 26shidu 项目，也让评分调优工具与 TripClipper 正式产出代码之间的边界不清晰。

26shidu 的真实角色只是实验素材来源之一。其 `cut_index.json` 可作为只读输入，但样本清单、人工标签、评语、模型运行结果、比较指标和复核报告都属于评分 Prompt 调优实验室。

## 目标

建立一个仓库级、自包含的 `rating-lab/`：

- 集中保存工具代码、测试、Prompt、数据集、运行结果、报告和实验文档。
- 清楚区分实验资产与 TripClipper 正式项目产物。
- 将现有 30 条和 15 条样本统一为 45 条开发集。
- 保留两批样本及七次历史运行的来源和实验脉络。
- 用职责明确的模块替代两个含义相近的旧 Python 文件。
- 不保留旧目录兼容入口或重复副本。
- 不在本次重构中把候选 Prompt 接入 TripClipper 正式评分链路。

## 非目标

- 不创建新的留出集。
- 不修改评分规则或生成 v5 Prompt。
- 不重新调用模型。
- 不重新解释或覆盖用户已经给出的人工评语。
- 不调整 TripClipper 中与评分调优无关的代码。
- 不把实验样本评分、标签、报告或指标纳入 26shidu 的正式产出。

## 目标目录

```text
rating-lab/
├── README.md
├── cli.py
├── rating_lab/
│   ├── __init__.py
│   ├── sampling.py
│   ├── runner.py
│   ├── evaluation.py
│   └── review.py
├── tests/
│   ├── test_cli.py
│   ├── test_sampling.py
│   ├── test_runner.py
│   ├── test_evaluation.py
│   └── test_review.py
├── prompts/
│   ├── single-highlight-v2.txt
│   ├── single-highlight-v3.txt
│   ├── single-highlight-v4.txt
│   └── strict-v1.txt
├── datasets/
│   └── development-v1/
│       ├── dataset.json
│       ├── human-labels.csv
│       ├── annotations.csv
│       └── batches/
│           ├── initial-30/
│           └── extension-15/
├── runs/
│   └── development-v1/
│       ├── initial-30/
│       └── extension-15/
├── reports/
│   └── development-v1/
└── docs/
    ├── 2026-07-23-rating-lab-directory-restructure-design.md
    ├── rating-policy.md
    └── experiment-history.md
```

## 代码职责

### `cli.py`

评分实验室的唯一命令入口，保留 `prepare`、`run` 和 `compare` 三个子命令。它只负责参数解析、依赖装配、文件读取和用户提示，不承载领域逻辑。

统一调用方式：

```bash
.venv/bin/python rating-lab/cli.py prepare ...
.venv/bin/python rating-lab/cli.py run ...
.venv/bin/python rating-lab/cli.py compare ...
```

### `rating_lab/sampling.py`

负责确定性分层抽样、数据来源指纹、批次 manifest 和合并数据集清单。

### `rating_lab/runner.py`

负责按固定数据集调用模型、并发控制、运行目录预留以及结果文件写入。

### `rating_lab/evaluation.py`

负责人工评分校验、评分对齐、误差指标和混淆矩阵计算。

### `rating_lab/review.py`

负责人工标签 CSV、盲评页面、差异复核页面及相关导出格式。

### 依赖方向

评分实验室可以复用 `tripclipper` 的模型、配置、`cut_index` 读取和 Provider 能力。TripClipper 正式代码不得导入 `rating_lab`。

```text
rating-lab → tripclipper
tripclipper ↛ rating-lab
```

## 数据组织

### 统一开发集

现有初始 30 条和后续 15 条共同组成 `development-v1`，总计 45 条。后续 15 条不再称为留出集。

`dataset.json` 是 45 条开发集的统一索引，至少记录：

- 数据集版本和样本数量。
- 每条素材的稳定标识、相对路径和所属批次。
- 来源项目标识及来源 `cut_index` 路径。
- 来源素材根目录指纹。

来源信息表示数据血缘，不表示数据所有权。数据集始终属于 `rating-lab/`。

### 批次原始资料

`batches/initial-30/` 和 `batches/extension-15/` 保留原始 manifest、人工标签模板和完成人工评分后的文件。文件名统一、批次边界明确，不把两个 manifest 伪装成一个历史文件。

### 人工意见

`human-labels.csv` 保存 45 条统一人工评分。

`annotations.csv` 采用用户第一次导出的有效 45 条复核 CSV，不采用后来几乎为空的第二次导出。解释优先级如下：

1. 人工文字评语。
2. 人工选择的错误类型。
3. 原始人工评分与模型评分的数值差。

若文字评语与错误类型冲突，以文字评语为准。

九条相差至少两星的素材中：

- 四条没有文字评语，记为模型判断符合预期。
- 一条竖版素材的评语明确表示，在缺少横竖版要求时模型判断符合预期。
- 其余四条按文字评语记录为需要 Prompt 改进的案例。

本次重构只忠实迁移这些结论，不改写评分。

## 历史运行

七次历史运行全部保留：

- `initial-30/run-001` 至 `run-005`。
- `extension-15/run-001` 至 `run-002`。

每个运行目录保留现有的 `results.json`、`review.csv` 和已生成的 `comparison.json`。缺少的文件不伪造；失败运行仍然保留，以反映真实实验历史。

运行目录按数据集和批次组织，避免把批次编号与 Prompt 版本错误绑定。只有能够从现有资料确认的 Prompt 版本才写入实验历史文档。

## 报告

现有人工盲评页和评分差异复核页迁入 `reports/development-v1/`。45 条差异复核页作为当前主要入口；30 条和 15 条历史页面保留可追溯名称。

报告中的本地媒体地址可以继续指向 26shidu 的素材根目录，因为它是素材来源。报告本身仍属于评分实验室。

## 迁移规则

- 移动而不是复制实验资产，确保每类数据只有一个真实位置。
- 不创建符号链接、兼容脚本或旧路径占位文件。
- 删除：
  - `scripts/calibrate_rating.py`
  - `src/tripclipper/rating_calibration.py`
  - `src/tripclipper/templates/rating_manual_review.html.tmpl`
  - `tests/test_rating_calibration.py`
- 将顶层评分 Prompt 移入 `rating-lab/prompts/`。
- 将 `projects/26shidu/rating-calibration/` 与 `projects/26shidu/rating-validation/` 的内容按目标结构迁移后移除旧目录。
- 更新仓库 README 中的命令和路径。
- 历史设计与实施文档保留原始叙述，并增加迁移说明；不重写历史记录。

## 安全与失败处理

- 迁移前后分别统计样本、人工标签、评语和运行目录数量。
- 对目标路径采用“不覆盖已有文件”的策略；发生冲突时停止迁移。
- 数据合并按 `asset_id` 校验唯一性。
- 运行工具继续校验数据来源项目及素材根目录指纹。
- `run` 继续使用全新运行目录，禁止覆盖既有实验。
- API 调用失败写入运行结果，不影响其他样本完成。

## 测试与验收

### 代码测试

原有评分调优测试按模块拆入 `rating-lab/tests/`，覆盖：

- 抽样配额、确定性和排除集合。
- manifest、人工标签和盲评页面生成。
- 模型运行的成功、失败和并发行为。
- 指标计算、输入校验和不覆盖规则。
- CLI 的 `prepare`、`run`、`compare`。

### 数据完整性

迁移完成后必须满足：

- `development-v1` 恰好包含 45 个唯一素材。
- 两个批次分别包含 30 条和 15 条。
- 人工评分覆盖 45 条。
- 第一次有效导出的 8 条文字评语全部保留。
- 七个历史运行目录全部保留。
- 45 条差异复核 HTML 存在且包含 45 条素材。
- 旧的两个 26shidu 调优目录不存在。

### 回归验证

- 运行 `rating-lab/tests/` 全部测试。
- 运行受依赖边界影响的 TripClipper Provider 测试。
- 编译检查 `rating-lab/cli.py` 与 `rating-lab/rating_lab/`。
- 搜索活动 README、代码和测试，确保不再引用旧目录或旧模块。

## 后续演进

目录重构完成后，v5 的平衡、保守和高召回三种 Prompt 应分别保存为独立文件，并分别写入独立运行目录。默认使用平衡版仅适用于评分实验室；是否进入 TripClipper 正式生产链路需要单独决策和验证。
