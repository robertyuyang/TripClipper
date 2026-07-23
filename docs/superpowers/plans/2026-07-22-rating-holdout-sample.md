# 评分留出样本实施计划

> 迁移说明（2026-07-23）：本文保留当时的实现路径用于追溯。评分调优工具和实验资产现已迁入仓库级 `rating-lab/`；后续 15 条样本已并入 45 条开发集，不再作为留出集。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从 26shidu 剩余视频中排除原 30 条调优样本，确定性抽取 15 条独立留出样本并生成盲评文件。

**Architecture:** 复用现有 `calibrate_rating.py prepare`，新增可选 `--exclude-manifest` 参数；命令在抽样前按 `asset_id` 过滤，并继续使用现有分层抽样、独占写入、CSV 和 HTML 生成逻辑。

**Tech Stack:** Python 3.10、argparse、pytest、现有 TripClipper 评分校准模块。

## Global Constraints

- 留出样本只包含视频。
- 原 30 条调优样本不能出现在留出样本中。
- 原 30 条已用完旧 2 星视频，因此留出配额固定为 `1:0,2:0,3:7,4:6,5:2`，总计 15 条。
- 使用独立目录 `projects/26shidu/rating-validation`。
- 不调用模型，不修改 `cut_index.json`，不覆盖已有文件。

---

### Task 1: prepare 排除既有 manifest

**Files:**
- Modify: `scripts/calibrate_rating.py`
- Test: `tests/test_rating_calibration.py`

**Interfaces:**
- Consumes: `prepare --exclude-manifest PATH`，PATH 指向现有样本 manifest。
- Produces: 与排除 manifest 没有重复 `asset_id` 的新 manifest、人工 CSV 和盲评 HTML。

- [ ] **Step 1: 写失败的命令级测试**

构造包含多个视频素材的临时 `cut_index.json` 和排除 manifest，执行带 `--exclude-manifest` 的 `prepare`，断言新样本数量满足配额且与排除集合无交集。

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest -q tests/test_rating_calibration.py::test_prepare_script_excludes_assets_from_existing_manifest`

Expected: FAIL，原因是 `--exclude-manifest` 尚未定义。

- [ ] **Step 3: 实现最小过滤逻辑**

读取排除 manifest，校验 `project_slug` 和 `project_fingerprint` 与当前项目一致，收集非空 `asset_id`，在素材类型过滤后、调用 `build_manifest` 前排除这些素材。

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m pytest -q tests/test_rating_calibration.py::test_prepare_script_excludes_assets_from_existing_manifest`

Expected: PASS。

### Task 2: 生成 26shidu 留出样本

**Files:**
- Create: `projects/26shidu/rating-validation/sample_manifest.json`
- Create: `projects/26shidu/rating-validation/manual_labels.csv`
- Create: `projects/26shidu/rating-validation/manual-review.html`
- Modify: `README.md`

**Interfaces:**
- Consumes: 原调优 manifest、当前 `cut_index.json` 和固定配额。
- Produces: 15 条不重叠视频及独立盲评页面。

- [ ] **Step 1: 执行 prepare**

Run: `.venv/bin/python scripts/calibrate_rating.py prepare --cut-index projects/26shidu/cut_index.json --manifest projects/26shidu/rating-validation/sample_manifest.json --exclude-manifest projects/26shidu/rating-calibration/sample_manifest.json --quotas 1:0,2:0,3:7,4:6,5:2 --seed 20260722`

Expected: 生成 15 条样本及两个盲评文件。

- [ ] **Step 2: 核对真实产物**

断言样本数和唯一 ID 均为 15、全部为视频、媒体文件全部存在、与原 30 条交集为空，人工 CSV/HTML 不含 `baseline_rating`。

- [ ] **Step 3: 更新 README**

记录留出样本命令，并注明留出标签只用于最终验收，不再反向修改 Prompt。

- [ ] **Step 4: 运行回归验证**

Run: `.venv/bin/python -m pytest -q tests/test_rating_calibration.py tests/test_provider.py`

Expected: 全部通过。

- [ ] **Step 5: 运行静态验证**

Run: `.venv/bin/python -m compileall -q scripts/calibrate_rating.py src/tripclipper/rating_calibration.py`

Run: `git diff --check`

Expected: 两条命令均退出码 0。
