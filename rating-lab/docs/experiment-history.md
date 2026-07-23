# 评分 Prompt 调优实验历史

## 数据批次

### `initial-30`

最初建立的 30 条固定样本，用于人工盲评和多轮候选 Prompt 比较。

历史运行：

- `run-001`：模型调用失败，保留失败记录。
- `run-002` 至 `run-005`：模型调用成功并生成比较结果。

现有运行文件没有稳定记录每次所用 Prompt 的版本，因此实验历史不猜测版本映射。

### `extension-15`

后来新增的 15 条样本，抽样时排除了初始 30 条。它最初被称为验证或留出样本，但随后参与了差异复核和 Prompt 调优，因此已并入 `development-v1`。

历史运行：

- `run-001`：模型调用失败，保留失败记录。
- `run-002`：模型调用成功并生成比较结果。

## 人工复核

当前统一开发集由 45 条唯一素材组成：

```text
initial-30   30条
extension-15 15条
合计         45条
```

45 条差异复核页面位于
`rating-lab/reports/development-v1/rating-gap-review-45.html`。

人工意见采用第一次有效导出的
`rating-lab/datasets/development-v1/annotations.csv`：

- 45 条记录。
- 8 条文字评语。
- 第二次几乎为空的导出未纳入实验室。

解释规则见 [rating-policy.md](rating-policy.md)。

## 目录迁移

2026-07-23，评分调优工具和实验资产从分散位置迁入仓库级 `rating-lab/`：

- `scripts/calibrate_rating.py` → `rating-lab/cli.py`
- `src/tripclipper/rating_calibration.py` → `rating-lab/rating_lab/` 的职责模块
- `prompts/` 中的评分 Prompt → `rating-lab/prompts/`
- `projects/26shidu/rating-calibration/` → `development-v1/initial-30`
- `projects/26shidu/rating-validation/` → `development-v1/extension-15`

迁移后不保留旧目录、符号链接或兼容入口。26shidu 只作为素材和 `cut_index.json` 的只读来源。
