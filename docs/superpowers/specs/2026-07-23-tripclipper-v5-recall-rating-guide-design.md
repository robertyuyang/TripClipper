# TripClipper 接入 V5 召回版评分规则设计

## 目标

将已经在 `rating-lab` 的 45 条开发集上完成模型实验和人工复核的
`single-highlight-v5-recall.txt` 固定接入 TripClipper 正式视觉分析流程。

本次只替换正式评分规则，不修改抽帧、模型调用、结构化输出、剪辑建议或项目数据。

## 已确认决策

- TripClipper 正式流程不增加选择 Prompt 的命令行参数。
- 正式代码固定使用 V5 召回版评分规则。
- `rating-lab` 继续保留 `--rating-guide`，用于独立运行历史版和候选版实验。
- V5 平衡版、高分保守版和召回版全部保留，不删除、不覆盖。
- 不针对“雨衣破洞”等单个案例新增 V6 规则。
- 不自动重跑或覆盖任何现有项目的 `cut_index.json`。

## 代码结构

新增 `src/tripclipper/rating_guide.py`，导出一个生产评分规则常量。
规则内容与已验证的 `rating-lab/prompts/single-highlight-v5-recall.txt` 保持一致。

`src/tripclipper/provider.py` 从该模块导入生产规则，并在调用方没有注入实验规则时使用它。
现有 `rating_guide` 注入能力继续保留，仅供 `rating-lab` 和单元测试执行候选实验；
TripClipper CLI 和正式分析编排不传入该参数。

这样可以同时满足：

1. 正式流程始终使用代码固定的 Prompt。
2. 实验室仍能比较不同版本。
3. 生产代码不在运行时读取或依赖 `rating-lab` 目录。
4. 大段评分规则不继续堆积在 `provider.py` 中。

## 验证

新增测试验证：

- 生产评分规则包含 V5 召回版的核心契约、主体显著性、技术上限和高分门槛。
- `Provider._render_system_prompt()` 未注入实验规则时使用生产规则。
- 显式注入实验规则时仍覆盖生产规则，保证 `rating-lab` 现有能力不回归。
- TripClipper CLI 不出现选择评分 Prompt 的新参数。

运行完整的 `rating-lab` 与 Provider 测试，确认实验工具和正式流程边界保持不变。

## 非目标

- 不修改现有 260 条素材的评分。
- 不把 `rating-lab` 的数据、报告或 Prompt 文件作为 TripClipper 运行时依赖。
- 不继续调优 V5 召回版。
- 不增加项目级 Prompt 配置或环境变量。
