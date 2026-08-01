# 选片 Agent Harness

采用 Policy 保护状态架构：

```text
minimal_policy_guarded/     离线最小原型
production_policy_guarded/  生产级独立实现
```

Agent 自主选择 Tool。候选状态提案先检查证据、项目作用、分类引用、复核理由和替代关系。拒绝结果作为 observation 返回 LLM，已保存候选不变。Policy 不规定 Tool 调用顺序，因此不是固定 Workflow。

## 最小原型

```bash
PYTHONPATH=src:. .venv/bin/python -m experiments.clip_selection.minimal_policy_guarded
```

不需要网络，结果 JSON 输出到标准输出。

## 生产版本

读取 `projects/<slug>/cut_index.json`，使用现有模型配置和 API Key。结果写到 `projects/<slug>/selections/`；追加帧写到独立 selection cache；不修改 `cut_index.json`。

```bash
PYTHONPATH=src:. .venv/bin/python -m experiments.clip_selection.production_policy_guarded \
  26shidu --target-duration-sec 45 --style 快节奏旅行
```

参数：

- `--max-review-clips`
- `--max-rounds`
- `--max-frame-requests`
- `--selection-id`
- `--output`
- `--resume`

运行循环：

1. Harness 把 Selection Brief、项目索引、当前状态和 observation 交给模型。
2. 模型自主选择一个 Tool。
3. 查询类 Tool 直接执行；状态类 Tool 先经过 Policy。
4. 范围查看得到的图像进入下一轮模型输入。
5. 每轮原子保存有效状态和运行记录。
6. 连续两次结束请求之间候选结构不变，且容量、必要分类和复核预算通过，才标记 `completed`。

## 运行指标

```bash
PYTHONPATH=src:. .venv/bin/python -m experiments.clip_selection.compare \
  path/to/selection-1.json path/to/selection-2.json
```

报告包含轮数、帧请求数、被拒动作数、检查点数、候选数、主选数和待复核数。

## 验证

```bash
PYTHONPATH=src:. .venv/bin/python -m pytest tests/clip_selection_variants -q
```

真实模型运行需要有效模型配置、API Key 和网络。追加抽帧需要 ffmpeg。当前实现不接入现有 `tripclipper run`、roughcut 或正式分析 Prompt。
