# 四套选片 Harness 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**目标：** 实现 Agent 主导状态、Policy 保护状态两种架构的最小原型和生产版本，共四套独立可运行实现，并用同一契约和测试样本比较。

**架构：** 四套实现共享选片数据契约、假模型和测试输入。两套 Agent 主导版本允许合法 Tool 调用直接改变状态；两套 Policy 保护版本要求所有状态变化先通过业务规则。生产版本增加真实 `cut_index.json` 读取、OpenAI-compatible 模型适配、帧查看、预算、检查点、原子写入和独立 CLI。

**技术栈：** Python 3.10、Pydantic 2、Click、httpx、pytest、现有 TripClipper 配置与媒体能力。

## 全局约束

- 不修改正式评分 Prompt。
- 不写回 `cut_index.json`。
- 不接入现有 `tripclipper run`。
- 所有结果写入独立选择文件。
- 四套实现使用相同 `SelectionBrief`、`SelectionRun`、`CandidateClip` 和状态枚举。
- 测试不访问外部网络，不要求真实 API Key。
- 不引入新依赖。

## 文件结构

```text
experiments/clip_selection/
  __init__.py
  contracts.py
  testing.py
  minimal_agent_owned/
    __init__.py
    agent.py
    harness.py
    tools.py
    __main__.py
  minimal_policy_guarded/
    __init__.py
    agent.py
    harness.py
    policy.py
    tools.py
    __main__.py
  production_agent_owned/
    __init__.py
    agent.py
    harness.py
    tools.py
    store.py
    __main__.py
  production_policy_guarded/
    __init__.py
    agent.py
    harness.py
    policy.py
    tools.py
    store.py
    __main__.py
tests/clip_selection_variants/
  test_contracts.py
  test_minimal_agent_owned.py
  test_minimal_policy_guarded.py
  test_production_agent_owned.py
  test_production_policy_guarded.py
  test_cli.py
```

### Task 1：共享数据契约与测试替身

**文件：**
- Create: `experiments/__init__.py`
- Create: `experiments/clip_selection/__init__.py`
- Create: `experiments/clip_selection/contracts.py`
- Create: `experiments/clip_selection/testing.py`
- Test: `tests/clip_selection_variants/test_contracts.py`

**接口：**
- `SelectionBrief(target_duration_sec, style, max_review_clips, ...)`
- `CandidateClip(clip_id, asset_id, start_sec, end_sec, source, status, evidence, project_role, ...)`
- `SelectionRun(selection_id, project_slug, brief, clips, categories, unresolved, run_status, ...)`
- `AgentAction(name, arguments)`
- `AgentDecision(action, rationale)`
- `ScriptedAgent.decide(context) -> AgentDecision`

- [ ] 写失败测试：枚举、时间范围、Brief 正数约束、JSON round-trip、未知字段拒绝。
- [ ] 运行 `pytest tests/clip_selection_variants/test_contracts.py -v`，确认失败。
- [ ] 用 Pydantic 实现最小共享契约；所有模型设置 `extra="forbid"`。
- [ ] 实现按顺序返回动作的 `ScriptedAgent`，动作耗尽时返回 `request_finish`。
- [ ] 重跑测试，确认通过。
- [ ] 提交 `test: define shared clip selection contracts`。

### Task 2：最小 Agent 主导状态原型

**文件：**
- Create: `experiments/clip_selection/minimal_agent_owned/__init__.py`
- Create: `experiments/clip_selection/minimal_agent_owned/agent.py`
- Create: `experiments/clip_selection/minimal_agent_owned/tools.py`
- Create: `experiments/clip_selection/minimal_agent_owned/harness.py`
- Create: `experiments/clip_selection/minimal_agent_owned/__main__.py`
- Test: `tests/clip_selection_variants/test_minimal_agent_owned.py`

**接口：**
- `MinimalAgentOwnedHarness.run(agent, initial_run) -> SelectionRun`
- Tool：`list_assets`、`inspect_range`、`upsert_candidate`、`set_categories`、`request_finish`
- Tool 只做 Schema、时间范围和引用合法性检查；合法状态直接写入内存。

- [ ] 写失败测试：脚本 Agent 可自由加入缺少项目作用的 `primary`，结束时仅做统一终态检查。
- [ ] 运行目标测试，确认失败。
- [ ] 实现 Prompt 常量和动作说明；Prompt 不引用生产评分 Prompt。
- [ ] 实现内存 Tool dispatcher 和 Agent 循环。
- [ ] 实现最大轮数与动作轨迹记录。
- [ ] 实现从内置 fixture 运行并打印 JSON 的 `python -m experiments.clip_selection.minimal_agent_owned`。
- [ ] 重跑测试，确认通过。
- [ ] 提交 `feat: add minimal agent-owned selection harness`。

### Task 3：最小 Policy 保护状态原型

**文件：**
- Create: `experiments/clip_selection/minimal_policy_guarded/__init__.py`
- Create: `experiments/clip_selection/minimal_policy_guarded/agent.py`
- Create: `experiments/clip_selection/minimal_policy_guarded/tools.py`
- Create: `experiments/clip_selection/minimal_policy_guarded/policy.py`
- Create: `experiments/clip_selection/minimal_policy_guarded/harness.py`
- Create: `experiments/clip_selection/minimal_policy_guarded/__main__.py`
- Test: `tests/clip_selection_variants/test_minimal_policy_guarded.py`

**接口：**
- `SelectionPolicy.validate_transition(before, action, after) -> list[str]`
- `SelectionPolicy.validate_finish(run) -> list[str]`
- `MinimalPolicyGuardedHarness.run(agent, initial_run) -> SelectionRun`

- [ ] 写失败测试：缺少证据或项目作用的 `primary` 被拒绝；错误作为 observation 返回 Agent；后续修正动作可通过。
- [ ] 运行目标测试，确认失败。
- [ ] 复用同一 Prompt 意图与 Tool 名称，实现候选状态变更提案。
- [ ] 实现无调用顺序要求的 transition Policy。
- [ ] Harness 在 Policy 通过后才提交内存状态；拒绝时保留旧状态。
- [ ] 实现从同一 fixture 运行并打印 JSON 的模块入口。
- [ ] 重跑测试，确认通过。
- [ ] 提交 `feat: add minimal policy-guarded selection harness`。

### Task 4：生产共同行为约束

**文件：**
- Modify: `experiments/clip_selection/contracts.py`
- Modify: `experiments/clip_selection/testing.py`
- Test: `tests/clip_selection_variants/test_contracts.py`

**接口：**
- `ProjectSnapshot.from_cut_index(path) -> ProjectSnapshot`
- `ModelClient.decide(system_prompt, context, images) -> AgentDecision` Protocol
- `FrameSource.inspect(asset_id, start_sec, end_sec) -> FrameObservation` Protocol
- `RunBudget(max_rounds, max_frame_requests)`

- [ ] 写失败测试：从现有 `CutIndex` 建只读快照、稳定 SHA-256、素材查询、时间范围校验。
- [ ] 运行测试，确认失败。
- [ ] 增加生产共用 Protocol、快照和预算模型，不增加运行逻辑。
- [ ] 增加 `FakeModelClient`、`FakeFrameSource`，记录调用供生产测试断言。
- [ ] 重跑测试，确认通过。
- [ ] 提交 `feat: define production selection ports`。

### Task 5：生产 Agent 主导状态实现

**文件：**
- Create: `experiments/clip_selection/production_agent_owned/__init__.py`
- Create: `experiments/clip_selection/production_agent_owned/agent.py`
- Create: `experiments/clip_selection/production_agent_owned/tools.py`
- Create: `experiments/clip_selection/production_agent_owned/store.py`
- Create: `experiments/clip_selection/production_agent_owned/harness.py`
- Test: `tests/clip_selection_variants/test_production_agent_owned.py`

**接口：**
- `AgentOwnedSelectionHarness.run(request) -> SelectionRun`
- `AgentOwnedSelectionHarness.resume(selection_path) -> SelectionRun`
- `AgentOwnedSelectionStore.save_checkpoint(run)` 使用临时文件替换目标文件。
- 状态 Tool 通过基础校验后直接提交；完整 Policy 仅在 `request_finish` 时执行。

- [ ] 写失败测试：读取 cut index 不修改源文件；多轮查看和状态更新；每轮检查点；中断恢复；预算耗尽输出 `incomplete`。
- [ ] 运行目标测试，确认失败。
- [ ] 实现独立选片 Prompt、Agent 决策解析和模型错误映射。
- [ ] 实现查询、已有帧读取、范围查看、候选更新、分类更新和结束 Tool。
- [ ] 实现源哈希、原子检查点和恢复时哈希比对。
- [ ] 实现 Harness 循环、预算计数、动作轨迹和强制结束。
- [ ] 重跑测试，确认通过。
- [ ] 提交 `feat: add production agent-owned selection harness`。

### Task 6：生产 Policy 保护状态实现

**文件：**
- Create: `experiments/clip_selection/production_policy_guarded/__init__.py`
- Create: `experiments/clip_selection/production_policy_guarded/agent.py`
- Create: `experiments/clip_selection/production_policy_guarded/tools.py`
- Create: `experiments/clip_selection/production_policy_guarded/policy.py`
- Create: `experiments/clip_selection/production_policy_guarded/store.py`
- Create: `experiments/clip_selection/production_policy_guarded/harness.py`
- Test: `tests/clip_selection_variants/test_production_policy_guarded.py`

**接口：**
- `PolicyGuardedSelectionHarness.run(request) -> SelectionRun`
- `PolicyGuardedSelectionHarness.resume(selection_path) -> SelectionRun`
- 每次候选、分类和结束提案均先经过 `SelectionPolicy`；Policy 不规定 Tool 顺序。

- [ ] 写失败测试：非法状态变化不落盘；Policy 错误返回模型；修正后可继续；容量按时间并集计算；复核数量受限。
- [ ] 运行目标测试，确认失败。
- [ ] 使用同一 Prompt 目标、Tool 名称和模型接口实现 Agent 层。
- [ ] 实现 transition Policy：证据、项目作用、替代引用、复核预算、必要分类引用。
- [ ] 实现 finish Policy：必要分类、主选容量、未解决高优先级问题、稳定审计轮。
- [ ] 实现原子 Store 和源哈希恢复检查。
- [ ] 实现 Harness 循环；拒绝动作只生成 observation，不改变已提交状态。
- [ ] 重跑测试，确认通过。
- [ ] 提交 `feat: add production policy-guarded selection harness`。

### Task 7：真实模型和帧适配器

**文件：**
- Create: `experiments/clip_selection/openai_model.py`
- Create: `experiments/clip_selection/frame_source.py`
- Test: `tests/clip_selection_variants/test_production_adapters.py`

**接口：**
- `OpenAISelectionModel(ModelConfig).decide(...) -> AgentDecision`
- `ProjectFrameSource(ProjectSnapshot, cache_dir).inspect(...) -> FrameObservation`

- [ ] 写失败测试：httpx MockTransport 请求体、JSON 动作解析、错误分类；已有帧命中；范围抽帧命令参数安全。
- [ ] 运行测试，确认失败。
- [ ] 实现 OpenAI-compatible JSON 动作调用，使用新的选片 Prompt，不调用或修改 `Provider._render_system_prompt`。
- [ ] 实现已有帧优先；范围内无帧时调用现有安全 ffmpeg 抽帧能力并写独立 cache。
- [ ] 确保路径从 `asset_id` 白名单解析，不接受模型提交任意文件路径。
- [ ] 重跑测试，确认通过。
- [ ] 提交 `feat: add selection model and frame adapters`。

### Task 8：四套 CLI 与端到端对比

**文件：**
- Create: `experiments/clip_selection/production_agent_owned/__main__.py`
- Create: `experiments/clip_selection/production_policy_guarded/__main__.py`
- Create: `experiments/clip_selection/compare.py`
- Test: `tests/clip_selection_variants/test_cli.py`

**接口：**
- 四个 `python -m ...` 入口。
- 生产入口参数：`slug`、`--base-dir`、`--target-duration-sec`、`--style`、`--max-review-clips`、`--max-rounds`、`--max-frame-requests`、`--resume`。
- `compare.py` 输出轮数、拒绝动作数、检查点数、最终状态和候选差异。

- [ ] 写失败测试：四个入口 `--help`；最小入口离线成功；生产入口缺项目时失败；假适配器端到端成功。
- [ ] 运行测试，确认失败。
- [ ] 实现四个入口和稳定退出码。
- [ ] 实现同一 fixture 的结构化比较报告。
- [ ] 重跑目标测试，确认通过。
- [ ] 提交 `feat: add clip selection variant CLIs`。

### Task 9：验证与说明

**文件：**
- Create: `experiments/clip_selection/README.md`
- Modify: `docs/clip-selection/2026-08-01-agentic-clip-selection-design.md`

- [ ] 记录四个目录用途、运行命令、共同契约、关键差异和限制。
- [ ] 明确生产版本仍是候选实现，不接入现有 `run` 或 roughcut。
- [ ] 运行 `pytest tests/clip_selection_variants -q`，期望全部通过。
- [ ] 运行现有相关回归：`pytest tests/test_provider.py tests/test_cut_index.py tests/test_roughcut_planner.py -q`，期望全部通过。
- [ ] 运行四个最小示例及比较命令，确认生成合法 JSON。
- [ ] 运行 `git diff --check`，期望无输出。
- [ ] 提交 `docs: document clip selection harness comparison`。
