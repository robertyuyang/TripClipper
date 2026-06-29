# M4 Check List

> 阶段：实施前的验收清单。所有项必须在 M4 标记"已完成"前逐项勾选。
> 验收纪律：与 M3 同——**测试零 mock、严格只打真模型、缺 key 即失败、不许 skip**。

## A. 文档与决策一致性

- [x] [`CONTEXT.md`](../../../CONTEXT.md) 已落地，定义 `rating` / `similar_selection` / `edit_candidate_status` 三正交字段
- [x] [`docs/adr/ADR-001-group-arbitration-via-llm.md`](../../adr/ADR-001-group-arbitration-via-llm.md) 已落地
- [x] [`docs/adr/ADR-002-deterministic-candidate-pool.md`](../../adr/ADR-002-deterministic-candidate-pool.md) 已落地
- [x] [`docs/specs/M4-similar-clustering/spec.md`](./spec.md) 与本 check_list、[`task_list.md`](./task_list.md) 内容一致
- [x] [`docs/specs/README.md`](../README.md) 中 M4 状态更新为"已完成"

## B. 数据契约扩展（向后兼容）

- [x] [`src/tripclipper/models.py`](../../../src/tripclipper/models.py) 新增 `ClusteringInfo` BaseModel
- [x] [`CutIndex`](../../../src/tripclipper/models.py) 新增 `clustering: Optional[ClusteringInfo] = None`，向后兼容（老 `cut_index.json` 反序列化 `clustering=None`）
- [x] M0/M1/M2/M3 既有单测仍全部通过（无 BREAKING）

## C. 本地启发式聚组（[`clusterer.py`](../../../src/tripclipper/clusterer.py)）

- [x] 模块级常量已 hardcode（`_TIME_WINDOW_SECONDS=60` / `_SUBJECT_SIMILARITY_THRESHOLD=0.6` /
      `_TAGS_JACCARD_THRESHOLD=0.5` 等）
- [x] `_text_jaccard_2gram` 在"海边夕阳人物 / 海边人物夕阳"语序大变化用例上返回 ≤ 0.5（2-gram 数学：交 3 / 并 7 ≈ 0.43；语义轨阈值 0.6 不命中，由强信号轨 modified_time≤60s + 同 subject_type 兜底）
- [x] `_tags_jaccard` 正确处理空集合（返回 0.0）
- [x] `_similarity_signals` 双轨规则两个轨道分别独立单测覆盖
- [x] 强信号轨：60s 边界内同 `subject_type` 命中；超过 60s 不命中；`subject_type` 不一致不命中
- [x] 语义信号轨：`subject_type` + `shot_scale` 同 + (`primary_subject` Jaccard ≥ 0.6 或 tags Jaccard ≥ 0.5) 命中
- [x] `_UnionFind` 传递闭包正确（A-B、B-C → `{A,B,C}` 同组）
- [x] `cluster_candidates` 显式过滤 `analysis_status != "analyzed"` 的素材

## D. 候选池生成（[`clusterer.py`](../../../src/tripclipper/clusterer.py)）

- [x] 起始集 = 所有 `analyzed` 且 `similar_selection ∈ {none, primary}` 的素材
- [x] **不**截断（无 `target_pool_size`）
- [x] 主体×景别平衡触发条件：`len(起始集) ≥ 20` **且** 单桶 > 50%
- [x] 平衡修剪：把目标桶 `rating` 最低的素材降为 `alternate` 直到占比 ≤ 50%
- [x] 修剪上限：≤ 起始集总数的 20%（保护极端样本）
- [x] `needs_review` 雷同组成员 + 非 analyzed 素材统一标 `edit_candidate_status="needs_review"`，**不进** `default_candidates`
- [x] `edit_candidate_reason` 文案符合 spec Q6 模板（6 种状态各一句中文）
- [x] `edit_candidate_priority` 在同 status 内按 `rating` desc 排序

## E. 组级 LLM 仲裁（[`arbiter.py`](../../../src/tripclipper/arbiter.py)）

- [x] `Arbiter.__init__` 在 `ModelConfig.is_usable() == False` 抛 `ArbiterError`
- [x] 缺 `TRIPCLIPPER_MODEL_API_KEY` 抛 `ArbiterError("环境变量 TRIPCLIPPER_MODEL_API_KEY 未设置")`
- [x] system prompt 渲染 `editing_intent` 非 None 字段；5 字段全 None 时整段不出现
- [x] `arbitrate(group)` 单次模型调用、单组上限 12（caller 在 `cluster_runner` 截断）
- [x] 每条素材只送 `thumbnail_path` base64 + 文本 anchor（asset_id / rating / subject_type）
- [x] `_parse_arbitration` 校验所有返回的 asset_id 都在组内；非则 `needs_review=True`
- [x] `confidence` 缺失或不在 [0,1] → `needs_review=True`
- [x] `confidence < 0.6` → `needs_review=True`
- [x] `basis` 元素不在 PRD §6.2 五选项集合内 → 过滤，剩余为空时 `needs_review=True`
- [x] `primary_asset_id=null` → `needs_review=True`
- [x] 可重试错误重试 1 次（共 2 次尝试）；非瞬时不重试
- [x] 仲裁失败向上抛分类异常；不直接修改 `Asset`

## F. cluster 流程编排（[`cluster_runner.py`](../../../src/tripclipper/cluster_runner.py)）

- [x] 硬卡：`analysis` 缺失或 `status ∉ {completed, partial}` → 报错并退出
- [x] 软警告：`analysis.stage="sample"` 时 stderr 打 warning，继续
- [x] 重跑自动清空 `similar_groups` / `default_candidates` / `clustering` / `assets[*].similar_*` /
      `assets[*].edit_candidate_*`，然后从头跑
- [x] 阶段头尾：写 `clustering.stage="cluster"` / `status="running"` / `started_at` → 增量落盘 →
      阶段结束写 `status` 终态 / `finished_at` / `groups_count` / `arbitration_failures` / `error_summary`
- [x] 增量落盘：每完成 1 个组的仲裁全量落盘一次
- [x] 单组 > 12 条素材时按 rating Top12 截断；其余直接标 `similar_selection="alternate"`、
      `similar_reason="组内素材过多，仅 rating Top 12 参与组级仲裁"`
- [x] 仲裁失败 → 整组 `similar_selection="needs_review"` + `cut.clustering.arbitration_failures += 1` +
      `cut.failures` 追加 `Failure(stage="cluster")` + 继续下一组（不中断）
- [x] 最终调 `apply_similarity_states` + `build_default_candidates` 把状态写回 `assets`

## G. CLI 与编排

- [x] `tripclipper analyze <slug> --stage cluster` 命令存在并接线到 `cluster_runner.cluster`
- [x] 摘要输出含：`total_groups` / `primary_decided` / `needs_review_groups` / `arbitration_failures` /
      `pool_size` / `alternate_count` / `needs_review_count` / `log_path`
- [x] `tripclipper run <slug>` 在 full 完成后自动追加 cluster
- [x] `RunResult.cluster` 字段存在并在 CLI 摘要打印 `[cluster]` 一行
- [x] 错误兜底——`ArbiterError` 等业务异常以面向用户的中文文案打印并 `sys.exit(非0)`，不抛堆栈
- [x] 错误文案**不**出现 API key

## H. 日志（[`logs.py`](../../../src/tripclipper/logs.py)）

- [x] `projects/<slug>/logs/cluster-<ISO8601>.jsonl` 文件路径正确
- [x] 事件类型齐全：`stage_start` / `stage_end` / `cluster_start` / `cluster_done` /
      `arbitration_start` / `arbitration_done` / `arbitration_failed` / `candidates_start` / `candidates_done`
- [x] 日志严格脱敏：**不**含 API key、Authorization header、完整 prompt、模型响应 `content`
- [x] 每次跑独立生成新 JSONL，不覆盖也不追加旧文件

## I. Unit 测试（零 mock 模型）

- [x] [`tests/test_clusterer.py`](../../../tests/test_clusterer.py) 覆盖：Jaccard / 双轨规则 / 并查集 / 候选池平衡分支（4 个分支：触发 / 不触发 /
      修剪上限 / needs_review 不进池）
- [x] [`tests/test_arbiter.py`](../../../tests/test_arbiter.py) 纯函数部分覆盖：`_parse_arbitration` 6 种合法/非法/越界场景
- [x] [`tests/test_cluster_runner.py`](../../../tests/test_cluster_runner.py) 覆盖：重跑清空、增量落盘计数、失败三处写入、状态机
- [x] 日志脱敏单测断言 Authorization / sk-xxx 字面值不出现

## J. Integration 测试（真打模型，原地 demo-scan）

- [x] `test_arbiter_real_model`：demo-scan 三条连号样本真打 Arbiter；返回字段断言通过
- [x] `test_full_pipeline_with_cluster`：demo-scan 原地跑 cluster；端到端断言通过（包含 setup 清空 + 真打）
- [x] `test_cluster_rerun_clears_old_state`：第二次 cluster 时旧状态被清空、新日志文件生成
- [x] 缺 `TRIPCLIPPER_MODEL_API_KEY` 时所有 integration 测试直接 fail（不 skip）
- [x] 缺 `projects/demo-scan/` 时所有 integration 测试直接 fail（不 skip）

## K. CLI 测试

- [x] `analyze demo-scan --stage cluster` 退出码 0 + 摘要 + cut_index 更新
- [x] `analyze <未init> --stage cluster` 退出码非 0 + 友好提示
- [x] `analyze <未scan> --stage cluster` 退出码非 0 + 友好提示
- [x] `analyze <仅sample> --stage cluster` 退出码 0 + stderr 含 warning
- [x] `run demo-scan` 跑完包含 `[cluster]` 行

## L. 验收终判

- [x] `pytest tests/` 在配置完整的本地环境下**全部通过**（含真打模型测试）
- [x] [`projects/demo-scan/cut_index.json`](../../../projects/demo-scan/cut_index.json) 已被一次真实 cluster 跑过、
      含至少 1 个 `SimilarGroup`、含 `default_candidates` 列表、含 `clustering.status="completed"` 或 `"partial"`
- [x] 手动跑 `tripclipper analyze demo-scan --stage cluster` 一次，肉眼检查 `similar_reason` 是真实自然语言
      （而非模板）、`edit_candidate_reason` 是 spec Q6 列出的中文模板之一
- [x] [`docs/specs/README.md`](../README.md) 中 M4 状态 → 已完成；状态注释中明确指出"folder-as-project 重构未做、暂存"
