# 单一高光评分 Prompt 实施计划

> 迁移说明（2026-07-23）：本文保留当时的实现路径用于追溯。评分调优工具和实验资产现已迁入仓库级 `rating-lab/`；后续 15 条样本已并入 45 条开发集，不再作为留出集。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有评分校准工具中加入单一高光评分 Prompt 和可重复运行的人工基准对比命令。

**Architecture:** 保留现有 `prepare` 与 `run` 数据流。新增独立 Prompt 文件；在 `rating_calibration.py` 中加入纯函数计算指标，在现有 `calibrate_rating.py` 中加入薄的 `compare` 子命令负责文件读写。

**Tech Stack:** Python 3.10、标准库 `csv/json`、pytest、现有 TripClipper 校准模块。

## Global Constraints

- 素材总评分等于素材中最佳可剪片段的评分。
- 局部高光与整段高光完全等价。
- 不修改正式 `cut_index.json`，不运行语音分析。
- 保留现有 `prepare` 和 `run` 行为；只扩展同一工具。
- 输出文件不得覆盖已有结果。

---

### Task 1: 单一高光评分 Prompt

**Files:**
- Create: `prompts/rating-guide-single-highlight-v2.txt`
- Test: `tests/test_rating_calibration.py`

**Interfaces:**
- Consumes: `Provider(..., rating_guide=...)` 已有注入接口。
- Produces: 可直接传给 `calibrate_rating.py run --rating-guide` 的 UTF-8 文本。

- [ ] **Step 1: 写失败测试**

新增测试读取 Prompt，并断言它包含“最佳片段决定素材总评分”“局部高光不得降级”“4/5 星必须定位时间范围”“不考虑重复性”，且不包含旧规则“只有局部片段精彩，素材整体评为 3 星”。

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest -q tests/test_rating_calibration.py::test_single_highlight_prompt_encodes_rating_contract`

Expected: FAIL，原因是 Prompt 文件不存在。

- [ ] **Step 3: 写最小生产 Prompt**

创建完整决策流程、1–5 星门槛、硬性上限、证据要求及 `rating`/`clip_suggestions` 一致性规则。禁止多维加权或整段平均。

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m pytest -q tests/test_rating_calibration.py::test_single_highlight_prompt_encodes_rating_contract`

Expected: PASS。

### Task 2: 评分对比纯函数

**Files:**
- Modify: `src/tripclipper/rating_calibration.py`
- Test: `tests/test_rating_calibration.py`

**Interfaces:**
- Consumes: `compare_ratings(records: Sequence[Mapping[str, object]], labels: Sequence[Mapping[str, object]])`。
- Produces: 包含样本数、成功/失败数、完全一致率、平均绝对误差、相差至少两星数量、4/5 星误判率、4/5 星召回率和混淆矩阵的字典。

- [ ] **Step 1: 写成功场景失败测试**

构造 5 条模型结果和人工标签，精确断言所有指标和混淆矩阵。

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest -q tests/test_rating_calibration.py::test_compare_ratings_reports_calibration_metrics`

Expected: FAIL，原因是 `compare_ratings` 尚不存在。

- [ ] **Step 3: 实现最小纯函数**

按 `asset_id` 对齐数据；失败结果计入 `failed_count` 但不进入评分指标分母；比率在分母为零时返回 `None`。

- [ ] **Step 4: 写校验失败测试**

覆盖重复人工标签、缺失人工标签和非法 `expected_rating`，断言抛出带素材标识的 `ValueError`。

- [ ] **Step 5: 实现输入校验并运行测试**

Run: `.venv/bin/python -m pytest -q tests/test_rating_calibration.py -k compare_ratings`

Expected: PASS。

### Task 3: 复用现有脚本加入 compare 子命令

**Files:**
- Modify: `scripts/calibrate_rating.py`
- Modify: `README.md`
- Test: `tests/test_rating_calibration.py`

**Interfaces:**
- Consumes: `compare --results PATH --labels PATH --output PATH`。
- Produces: 独占创建的 UTF-8 JSON 指标文件，并在终端输出核心指标。

- [ ] **Step 1: 写命令级失败测试**

在临时目录创建结果 JSON 与人工 CSV，执行 `compare`，断言输出 JSON 指标正确；再次执行时断言拒绝覆盖。

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest -q tests/test_rating_calibration.py::test_compare_script_writes_metrics_without_overwriting`

Expected: FAIL，原因是 `compare` 子命令不存在。

- [ ] **Step 3: 实现薄命令层**

读取两个输入文件、调用 `compare_ratings`、以 `x` 模式写输出 JSON，并打印成功数、完全一致率、平均绝对误差和 4/5 星指标。

- [ ] **Step 4: 更新 README**

在现有评分 Prompt 校准章节追加一条 `compare` 命令示例，明确它复用人工基准且无需重新打分。

- [ ] **Step 5: 运行定向回归验证**

Run: `.venv/bin/python -m pytest -q tests/test_rating_calibration.py tests/test_provider.py`

Expected: 全部通过。

- [ ] **Step 6: 运行静态验证**

Run: `.venv/bin/python -m compileall -q src/tripclipper/rating_calibration.py scripts/calibrate_rating.py`

Run: `git diff --check`

Expected: 两条命令均退出码 0。
