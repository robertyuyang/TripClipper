# 选片 Agent Harness 四套实现

本目录用同一数据契约比较两个维度：运行深度和状态所有权。

```text
minimal_agent_owned/        最小原型，Agent 主导状态
minimal_policy_guarded/     最小原型，Policy 保护状态
production_agent_owned/     生产级能力，Agent 主导状态
production_policy_guarded/  生产级能力，Policy 保护状态
```

四套都包含独立 `agent.py`、`tools.py` 和 `harness.py`。生产版本另有原子 Store；Policy 版本另有 `policy.py`。

## 架构差异

Agent 主导状态版本中，`upsert_candidate` 通过 Schema、素材引用和时间范围校验后直接提交。容量、必要分类、替代引用和稳定审计在结束请求时统一检查。

Policy 保护状态版本中，每次候选状态提案先检查证据、项目作用、分类引用、复核理由和替代关系。拒绝结果作为 observation 返回 LLM，已保存状态不变。Policy 不规定 Tool 调用顺序，因此仍是 Agent，不是固定 Workflow。

## 最小原型

不需要网络：

```bash
PYTHONPATH=src:. .venv/bin/python -m experiments.clip_selection.minimal_agent_owned
PYTHONPATH=src:. .venv/bin/python -m experiments.clip_selection.minimal_policy_guarded
```

两个入口把结果 JSON 输出到标准输出。

## 生产版本

生产版本读取 `projects/<slug>/cut_index.json`，使用现有软件模型配置和 API Key。结果写到 `projects/<slug>/selections/`，追加帧写到独立 selection cache；不修改 `cut_index.json`。

```bash
PYTHONPATH=src:. .venv/bin/python -m experiments.clip_selection.production_agent_owned \
  26shidu --target-duration-sec 45 --style 快节奏旅行

PYTHONPATH=src:. .venv/bin/python -m experiments.clip_selection.production_policy_guarded \
  26shidu --target-duration-sec 45 --style 快节奏旅行
```

共同参数：

- `--max-review-clips`
- `--max-rounds`
- `--max-frame-requests`
- `--selection-id`
- `--output`
- `--resume`

生产循环行为：

1. 把 Selection Brief、项目索引、当前候选状态和最新 observation 交给模型。
2. 模型自主选择一个 Tool。
3. Harness 校验权限、预算和参数，执行 Tool。
4. 范围查看得到的图像进入下一轮模型输入。
5. 每轮原子保存检查点。
6. 连续两次结束请求之间候选结构不变，且容量、必要分类和复核预算通过，才标记 `completed`。

## 对比结果

```bash
PYTHONPATH=src:. .venv/bin/python -m experiments.clip_selection.compare \
  path/to/agent-owned.json path/to/policy-guarded.json
```

报告包含轮数、帧请求数、被拒动作数、检查点数、候选数、主选数和待复核数。

## 验证

```bash
PYTHONPATH=src:. .venv/bin/python -m pytest tests/clip_selection_variants -q
```

真实模型运行需要有效模型配置、API Key 和网络。追加抽帧需要 ffmpeg。两套生产版本当前作为独立候选实现，不接入现有 `tripclipper run`、roughcut 或正式分析 Prompt。

