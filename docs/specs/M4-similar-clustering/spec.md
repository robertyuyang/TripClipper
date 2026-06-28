# M4 雷同素材识别与默认候选池 Spec（grilling Q1–Q19 拍板）

> 状态：**定稿**。本文件由 grilling 会话的 Q1–Q19 全套决策落地而成。
> 覆盖：PRD FR-6；TD 8（雷同分组与候选池）。
> 依赖：M0（`models`/`paths`/`cut_index`）、M1（`init_project` 与 `project.yaml`）、
> M2（`scan_project` 已写 `assets[*].metadata.modified_time`）、M3（`assets[*]` 已写
> `summary`/`tags`/`rating`/`subject_type`/`shot_scale`/`primary_subject` 等分析字段）。
> 角色：M4 在 M3 输出之上，完成**雷同素材聚组**与**默认剪辑候选池生成**。
> 它 **不** 做导出（M5）、Eagle 同步（M6）、FastAPI（M7）。
> 关联 ADR：[ADR-001](../../adr/ADR-001-group-arbitration-via-llm.md)（聚组+仲裁）、
> [ADR-002](../../adr/ADR-002-deterministic-candidate-pool.md)（候选池后处理）。

## Why

PRD FR-6 是 TripClipper MVP 的**核心去重价值**所在——避免用户在 12 条 5 星海边日落里再次手动挑选。
M3 已让每条素材具备绝对画面质量评分（`rating`）与丰富语义字段，但 M3 故意**不**做雷同判定与候选池生成
（M3 Q22 明确划给 M4）。M4 的任务是把这条产品承诺落地：
- 把"物理时间相邻 / 画面相近 / 主体一致"的素材聚成 `SimilarGroup`；
- 为每组挑出 `primary` 主选（FR-6 列的 10+ 主选维度由 LLM 真打缩略图判定）；
- 在组主选与非雷同高星基础上做"主体×景别基础平衡"，产出**默认剪辑候选池**。

M4 严格遵守 M3 立下的纪律——**不许伪造分析结果**、**不许 mock 模型**、**真打钱真验真效果**。

## What Changes

- 新增核心模块 [`src/tripclipper/clusterer.py`](../../../src/tripclipper/clusterer.py)：本地启发式聚组 + 候选池生成（纯函数主导）。
  - `cluster_candidates(assets: list[Asset]) -> list[CandidateGroup]`：双轨规则 +
    并查集生成 `>1` 个素材的候选组；单元素素材直接当 non-grouped 处理。
  - `_similarity_signals(a: Asset, b: Asset) -> SignalReport`：纯函数，输出强信号轨/语义信号轨的命中情况，便于 spec 验证。
  - `_text_jaccard_2gram(s1, s2) -> float`：2-gram Jaccard，对短中文片段稳定。
  - `_tags_jaccard(t1, t2) -> float`：集合 Jaccard。
  - `build_default_candidates(cut: CutIndex) -> list[DefaultCandidate]`：起始集 + 主体×景别平衡 + reason 生成。
  - `apply_similarity_states(cut: CutIndex, groups: list[SimilarGroup]) -> None`：纯函数，把
    `similar_group_id` / `similar_selection` / `similar_rank` / `similar_reason` 写回 `assets[*]`。
- 新增核心模块 [`src/tripclipper/arbiter.py`](../../../src/tripclipper/arbiter.py)：组级 LLM 仲裁。
  - `Arbiter(config: ModelConfig, editing_intent: EditingIntent)`：构造时读 key、渲染含 `editing_intent` 的 system prompt。
  - `arbitrate(group: CandidateGroup) -> ArbitrationResult`：单组一次模型调用，返回
    `primary_asset_id` / `alternate_asset_ids` / `rejected_asset_ids` / `confidence` / `basis` / `reason_by_asset`。
  - `_parse_arbitration(text: str) -> ArbitrationResult`：纯函数。剥 markdown 代码栅、JSON 解析、
    校验所有 asset_id 都在该组内、校验 `confidence ∈ [0,1]`、`basis` 枚举合法（同 PRD §6.2 五选项）。
  - `_should_retry(...)`：与 [`provider.py`](../../../src/tripclipper/provider.py) 一致复用纯函数语义（实现可直接 import）。
  - 重试策略：与 M3 相同——瞬时错误重试 1 次（M3 是 2 次，M4 调用更便宜故只重试 1 次，决策 16），仍失败整组 `needs_review`。
- 新增核心模块 [`src/tripclipper/cluster_runner.py`](../../../src/tripclipper/cluster_runner.py)：M4 流程编排。
  - `cluster(slug, *, base_dir=None) -> ClusterResult`：
    1. 读 `cut_index.json`；硬卡 `analysis` 已存在且 `status ∈ {completed, partial}`，否则报错。
    2. 软警告：`analysis.stage="sample"` 时打 warning（仅基于 sample 聚组）。
    3. 重跑语义：若 `clustering.status` 已存在则清空 `similar_groups` / `default_candidates` /
       `assets[*].similar_*` / `assets[*].edit_candidate_*`（决策 13）。
    4. 写 `clustering.stage="cluster"` / `status="running"` / `started_at`；落盘。
    5. 调 `clusterer.cluster_candidates`（仅 `analysis_status="analyzed"` 素材入聚组——决策 12）。
    6. 对每个 `>1` 候选组（按 rating Top12 截断）调 `Arbiter.arbitrate`；每组完成增量落盘一次（决策 8）。
    7. 调 `clusterer.apply_similarity_states` 把仲裁结果写回 `assets`。
    8. 调 `clusterer.build_default_candidates` 生成候选池 + 写 `assets[*].edit_candidate_*`。
    9. 写 `clustering.status="completed"/"partial"` / `finished_at` / `groups_count` /
       `arbitration_failures` / `error_summary`；最终落盘。
  - `ClusterResult` dataclass：`total_groups`、`primary_decided`、`needs_review_groups`、`arbitration_failures`、
    `pool_size`、`alternate_count`、`needs_review_count`、`excluded_count`、`started_at`、`finished_at`、`log_path`、`cut_index_path`。
- 修改 [`src/tripclipper/models.py`](../../../src/tripclipper/models.py)：
  - 新增 `ClusteringInfo` BaseModel：`stage` / `provider` / `vision_model` / `text_model` / `started_at` /
    `finished_at` / `status` / `error_summary` / `groups_count` / `arbitration_failures`（决策 8b）。
  - 在 `CutIndex` 上加 `clustering: Optional[ClusteringInfo] = None`（默认空，向后兼容；决策 11）。
- 修改 [`src/tripclipper/cli.py`](../../../src/tripclipper/cli.py)：
  - `analyze --stage cluster` 接线；调 `cluster_runner.cluster`。
  - `--stage` 枚举追加 `cluster`。
- 修改 [`src/tripclipper/runner.py`](../../../src/tripclipper/runner.py)：
  - `run` 在 full 完成后追加 cluster 步骤；`RunResult` 新增 `cluster: Optional[ClusterResult]`。
- 修改 [`src/tripclipper/logs.py`](../../../src/tripclipper/logs.py)：
  - `AnalyzeLogger` 复用类不动；新增 `ClusterLogger` 或在原 logger 加 `cluster_*` 事件方法。
  - 新增日志路径 `analyze_log_path(slug, ts, base_dir, kind="analyze"|"cluster")` 或新增 `cluster_log_path`。
  - 日志文件 `projects/<slug>/logs/cluster-<ISO8601>.jsonl`（决策 13b）。
- 新增测试文件：
  - [`tests/test_clusterer.py`](../../../tests/test_clusterer.py)：纯函数单测（聚组规则、并查集、Jaccard、候选池平衡）。
  - [`tests/test_arbiter.py`](../../../tests/test_arbiter.py)：`_parse_arbitration` 纯函数单测 + 真打模型单测（与 M3 Q1/Q2 同纪律）。
  - [`tests/test_cluster_runner.py`](../../../tests/test_cluster_runner.py)：流程编排单测（增量落盘、状态机、failure 三处）。
  - [`tests/test_integration_m4.py`](../../../tests/test_integration_m4.py)：端到端真打模型，直接在 [`projects/demo-scan/`](../../../projects/demo-scan/) 原地跑（决策 10）。
- 文档：本 spec + ADR-001 + ADR-002 + [`CONTEXT.md`](../../../CONTEXT.md) 已同步落地。

不在 M4 范围（明确延后）：
- **路径 2 候选池**：候选池也走 LLM 的方案；ADR-002 已拒绝。
- **CSV/MD/HTML 导出**：M5 完整版。
- **review.html 更新**：M5-early 已有的 HTML 报告需要 M5/M5-late 决定是否追加雷同组折叠视图，**不在 M4 范围**。
- **Eagle 同步**：M6。
- **folder-as-project CLI 重构**：grilling Q14 拍板暂存为未来 refactor 里程碑，M4 沿用现有 slug 形态。

## Impact

- 影响的能力：M5 导出消费 M4 写入的 `similar_groups`/`default_candidates`/`clustering`/`assets[*].similar_*` 与 `edit_candidate_*`；
  M6 Eagle 同步消费同一批字段；M7 FastAPI 状态面板消费 `clustering` 头尾。
- 影响的代码：
  - 新增 [`src/tripclipper/clusterer.py`](../../../src/tripclipper/clusterer.py)、[`arbiter.py`](../../../src/tripclipper/arbiter.py)、
    [`cluster_runner.py`](../../../src/tripclipper/cluster_runner.py)。
  - 修改 [`src/tripclipper/models.py`](../../../src/tripclipper/models.py)（加 `ClusteringInfo` 与 `CutIndex.clustering` 字段）。
  - 修改 [`src/tripclipper/cli.py`](../../../src/tripclipper/cli.py)（加 `--stage cluster`）。
  - 修改 [`src/tripclipper/runner.py`](../../../src/tripclipper/runner.py)（`run` 串到 cluster）。
  - 修改 [`src/tripclipper/logs.py`](../../../src/tripclipper/logs.py) 与 [`paths.py`](../../../src/tripclipper/paths.py)
    （加 cluster 日志路径与事件方法）。
  - 新增 4 个测试文件。
  - 回写 [`docs/specs/README.md`](../README.md) 模块状态（M4 → 已完成）。
- **数据契约扩展**：`CutIndex` 加 `clustering` 字段；该字段默认空，老的 `cut_index.json` 读取时 `clustering=None` 不影响。
  非 BREAKING（决策 11）。M0 spec 不需要回写，仍属于"只增不改"契约纪律。

## 关键设计决策（grilling Q1–Q19）

### Q1 雷同主选挑选采用「本地启发式聚组 + 组级 LLM 仲裁」
- 详见 [ADR-001](../../adr/ADR-001-group-arbitration-via-llm.md)。
- 拒绝路径 A（纯本地启发式）：FR-6 列的 10+ 主选维度纯规则只覆盖 rating 一项。
- 拒绝路径 C（embedding 聚类）：引入新模型类别、不覆盖图像维度。

### Q2 / Q3 默认候选池采用确定性后处理（零 LLM）；不同时支持两种方案
- 详见 [ADR-002](../../adr/ADR-002-deterministic-candidate-pool.md)。
- 拒绝"两种都支持靠测试看效果"：5 条真实素材 + 1 个雷同组无法形成对照实验，
  双倍代码 + 双倍测试矩阵 + 双倍配置面，仅为开关而开关。

### Q4 本地启发式聚组规则：双轨 + 并查集
两条素材进入同一候选组当且仅当满足以下任一条：
- **强信号轨**：`abs(modified_time_a - modified_time_b) ≤ 60s` **且** `subject_type_a == subject_type_b`
- **语义信号轨**：`subject_type` 一致 **且** `shot_scale` 一致 **且**
  (`primary_subject` 2-gram Jaccard ≥ 0.6 **或** `tags` 集合 Jaccard ≥ 0.5)

阈值作为 `clusterer.py` 模块级常量 hardcode，不开放 `project.yaml` 配置（YAGNI）：
```
_TIME_WINDOW_SECONDS = 60
_SUBJECT_SIMILARITY_THRESHOLD = 0.6
_TAGS_JACCARD_THRESHOLD = 0.5
```

传递性走并查集（A-B 相似 + B-C 相似 → `{A, B, C}` 同组）；Arbiter 后续可在仲裁阶段标 `rejected` 纠正误聚。

### Q5 组级仲裁：单组上限 12、仅缩略图、整组结构输出
- 单次仲裁最多 12 条素材；超过按 `rating` desc 取 Top12 进 LLM，其余按 `rating` desc 标 `alternate`、
  `similar_reason="组内素材过多，仅 rating Top 12 参与组级仲裁"`。
- 每条只送缩略图（不送 frames）；抖动/帧间稳定性维度**不覆盖**，写入 spec "已知近似"。
- 模型一次返回：
  ```json
  {
    "primary_asset_id": "asset_xxx" | null,
    "alternate_asset_ids": ["asset_yyy", ...],
    "rejected_asset_ids": ["asset_www", ...],
    "confidence": 0.0..1.0,
    "basis": ["同一动作", "相近构图"],     // 从 PRD §6.2 五选项中选
    "reason_by_asset": {
      "asset_xxx": "人物表情完整且构图最稳",
      "asset_yyy": "表情自然但有轻微抖动",
      "asset_www": "主体被遮挡"
    }
  }
  ```
- `primary_asset_id=null` 或 `confidence < 0.6` 时整组标 `needs_review`（FR-6「置信度不足时不应强行给出主选」）。
- `basis` 限定从 PRD §6.2 枚举：`同一景点 / 同一动作 / 相近构图 / 相近画面内容 / 相近声音内容`。
- `reason_by_asset` 强制中文，每条素材一句相对判断。

模块复用：`arbiter.py` 新写，**不复用** `Provider.analyze`（语义不同），但**复用** `_should_retry` 等纯函数与重试纪律。

### Q6 候选池生成：不截断 + 仅大池触发平衡 + needs_review 不进池
- **起始集** = 所有 `analysis_status="analyzed"` 素材中 `similar_selection ∈ {none, primary}` 的并集。
- **不引入 `target_pool_size`**：FR-6 没要求总数，截断徒增复杂度。
- **主体×景别平衡**：仅当 `len(候选池) ≥ 20` **且** 某一 `(subject_type, shot_scale)` 桶占比 > 50% 时触发；
  把该桶 `rating` 最低的素材降为 `alternate`，直到占比 ≤ 50%；修剪上限不超过候选池总数的 20%（保护极端样本）。
- **needs_review 处理**：
  - 雷同组置信度不足（含仲裁失败）的所有组员 `edit_candidate_status="needs_review"`，**不进候选池也不进 alternate**；
  - `analysis_status != "analyzed"` 的孤立素材同样 `edit_candidate_status="needs_review"`，理由"分析未完成"。
- **edit_candidate_reason** 中文模板：
  - `"非雷同高星素材，默认入选"`（直接进 default_selected）
  - `"组『{group_id}』主选，默认入选"`（组主选进 default_selected）
  - `"组『{group_id}』备选"`（组 alternate）
  - `"组『{group_id}』被仲裁判定不推荐"`（组 rejected）
  - `"为景别平衡入选 alternate"`（被平衡修剪降级）
  - `"所在雷同组置信度不足，待人工确认"`（needs_review 组员）
  - `"分析未完成，待人工确认"`（非 analyzed 素材）

### Q7 CLI 命令形状
- `tripclipper analyze <slug> --stage cluster`：单步触发 M4；硬卡 `analysis.status ∈ {completed, partial}`；
  软提示 `analysis.stage="sample"` 时打 warning。
- `tripclipper run <slug>` 扩展：自动追加 cluster 步骤（scan → sample → full → cluster）。
- `tripclipper run --pause-after sample` 行为不变（在 sample 后阻塞）。
- `cluster` 默认串行（不并发），单次组级调用足够快。

### Q8 阶段头尾：新增 `cut_index.clustering` 字段
- 新增 `ClusteringInfo` BaseModel（结构对齐 `AnalysisInfo`，补 `groups_count`、`arbitration_failures`）。
- `CutIndex.clustering: Optional[ClusteringInfo] = None`。
- 阶段开始写 `stage="cluster"` / `status="running"` / `started_at`；
- 增量落盘：每完成 1 个组的仲裁就全量落盘一次（典型 5-10 个组，落 5-10 次完全可接受）；
- 阶段结束写 `status="completed"/"partial"/"failed"` / `finished_at` / `groups_count` / `arbitration_failures` / `error_summary`。

### Q9 模块布局：三文件
- [`clusterer.py`](../../../src/tripclipper/clusterer.py)：本地启发式聚组 + 候选池生成（纯函数主导，能离线测）。
- [`arbiter.py`](../../../src/tripclipper/arbiter.py)：组级 LLM 仲裁（与 [`provider.py`](../../../src/tripclipper/provider.py) 平级）。
- [`cluster_runner.py`](../../../src/tripclipper/cluster_runner.py)：流程编排（仿 [`analyzer.py`](../../../src/tripclipper/analyzer.py)）。
- 不复用 [`runner.py`](../../../src/tripclipper/runner.py)：那是顶层 scan→sample→full→cluster 一键入口；
  `cluster_runner.py` 是 M4 模块内部编排。
- 组级仲裁**不**用线程池（5-10 组规模、串行更易调试）。

### Q10 测试策略
- **Arbiter 真打模型**（与 M3 同纪律）：用 `projects/demo-scan/` 的 3 条天然连号样本（NO20250612-114146/114246/114346）
  构造候选组，断言返回的 `primary_asset_id ∈ 组内素材`、`confidence ∈ [0,1]`、`basis ⊆ PRD 五选项`。
- **端到端真打模型**：直接在 [`projects/demo-scan/`](../../../projects/demo-scan/) **原地跑**（决策 10d）。
  - 副作用：每次 pytest 会覆盖 `projects/demo-scan/cut_index.json` 的 `similar_groups`/`default_candidates`/`clustering` 字段；
    这些字段在 .gitignore 内不污染 git；用户的手动 cluster 输出会被测试覆盖（接受此代价）。
  - 测试 setup：**主动清空** `cut.similar_groups`/`cut.default_candidates`/`cut.clustering` 三个字段后落盘，
    再触发 cluster；teardown 不还原，允许用户跑完 pytest 后直接打开 `cut_index.json` 查看真实输出。
  - 前置：`cut.analysis.status="completed"` 且 `assets` 非空（demo-scan 已满足）。
- **Unit 测试**：
  - `clusterer` 纯函数：2-gram Jaccard、tags Jaccard、强信号轨/语义信号轨命中、并查集传递闭包。
  - 候选池：构造**合成 30 条 fixture**（mock Asset 列表）覆盖主体×景别平衡触发 / 不触发两个分支、
    `len < 20` 不触发分支、修剪上限 20% 命中分支、`needs_review` 不进池分支。
  - Arbiter：`_parse_arbitration` 合法 JSON / 非法 JSON / `primary_asset_id` 引用了不在组内的 asset_id（必须被拒）/
    `confidence < 0.6` 整组 `needs_review` / `basis` 越界枚举降级。
  - 阶段头尾、增量落盘（每组一次）。

### Q11 数据契约扩展处理
- 在 M4 spec 本段（MODIFIED Requirements）声明扩 `CutIndex.clustering`；
- 新增字段全部可选、向后兼容（老 cut_index.json 读取时 `clustering=None`）；
- M0 spec 不回写（M0 的口径是"数据契约只增不删/不改既有字段"，加字段在该口径内）。

### Q12 sample 之后能跑 cluster 但只对 analyzed 素材聚组
- 硬卡：`analysis` 不存在或 `status ∉ {completed, partial}` 报错（"项目尚未完成分析"）。
- 软警告：`analysis.stage="sample"` 时打 warning（"仅基于 sample 阶段的 N 个素材聚组"）。
- 处理范围：`clusterer.cluster_candidates` 显式过滤 `analysis_status="analyzed"` 素材；
  其他素材（scanned / analyzing / analysis_failed）统一标 `edit_candidate_status="needs_review"`、
  `edit_candidate_reason="分析未完成，待人工确认"`，**不参与聚组也不进候选池**。

### Q13 重跑语义：默认自动清空重跑，不需要 flag
- cluster 重跑时**自动清空** `similar_groups`/`default_candidates`/`assets[*].similar_*`/`assets[*].edit_candidate_*`/
  `clustering`，然后从头跑。
- 理由：M4 调用量是 M3 的 ~20%（5-10 次 vs 25 次单素材），用户重跑大概率是想看新结果；
  M3 `--force` 是因为 full 重跑 100 次模型调用很贵需要显式确认，M4 不在这个量级。
- **不引入 `--force` flag**：避免与 M3 `--force` 语义混淆（M3 是"包含 analyzed 素材"，M4 没有"跳过已聚组素材"的语义）。
- 每次跑独立生成 `logs/cluster-<ISO8601>.jsonl`，不覆盖也不追加旧文件（与 [M3 Q24](../M3-real-llm-analysis/spec.md) 同纪律）。

### Q14 folder-as-project CLI 重构：暂存为未来 refactor，不在 M4 范围
- 用户在 grilling 中提出"所有命令统一输入文件夹路径"的设计，被采纳为未来重构方向；
- 本 M4 沿用现有 `<slug>` 形态以避免在 FR-6 同期混入横切重构。
- 暂存目录建议：`docs/specs/M-future-folder-as-project/`（M4 之后单独立项）。

### Q15 聚组传递性：并查集（传递闭包）
- A-B 相似 + B-C 相似 → `{A, B, C}` 同组。
- 实现：[`union_find.py`](../../../src/tripclipper/clusterer.py)（合并到 clusterer.py 模块内私有类）。
- 理由："宁可多组，不要漏组"——Arbiter 会在仲裁阶段标 `rejected` 纠正误聚。

### Q16 Arbiter 失败：与 M3 同纪律但只重试 1 次
- 与 M3 [Q13](../M3-real-llm-analysis/spec.md) 同纪律：可重试错误（429 / 5xx / 超时 / 网络）重试 1 次（M3 为 2 次，M4 调用更便宜故 1 次足够）；
- 仍失败 → 整组 `needs_review`、`arbitration_failures += 1`、**其他组继续**。
- 非瞬时错误（400/401/JSON 非法/校验失败）：不重试，直接 `needs_review`。
- `Failure.suggestion` 区分瞬时（"重跑 cluster 重试"）与非瞬时（"检查 prompt / 换 vision_model"）。

### Q17 editing_intent 影响主选：拼进 Arbiter system prompt
- `Arbiter.__init__(config, editing_intent)` 接收 intent，构造一次 system prompt 复用；
- 渲染规则同 M3 Q19：只渲染非 None 字段；5 字段全 None 时整段不出现，模型按通用标准判断。
- **不**在本地后处理对模型返回的 primary 再加权（路径 B 的核心是让 LLM 一次性权衡所有维度）。

### Q18 组内 similar_rank 排序
- `primary` → `rank=1`
- `alternate_asset_ids` 按 Arbiter 返回顺序 → `rank=2,3,...`
- `rejected_asset_ids` 接着排
- `needs_review` 组员按 `rating` desc → `rank`

### Q19 JSONL 日志事件
- 复用 [`logs.py`](../../../src/tripclipper/logs.py) 风格；事件名：
  - `stage_start` / `stage_end`（M4 stage="cluster"）
  - `cluster_start`（本地聚组开始）/ `cluster_done`（含 `groups_count`）
  - `arbitration_start`（单组送 LLM 前，含 `group_id`、`asset_count`）/ `arbitration_done`（含 `confidence`、`primary_asset_id`、`latency_ms`）/
    `arbitration_failed`（含 `group_id`、`http_code`、`error`、`retry_attempt`）
  - `candidates_start` / `candidates_done`（含 `pool_size`、`alternate_count`、`needs_review_count`、`excluded_count`）
- 严格脱敏复用 [M3 Q24](../M3-real-llm-analysis/spec.md) 规则：日志**绝不**含 API key、Authorization header、完整 prompt、模型响应 `content`。

## ADDED Requirements

### Requirement: 雷同素材识别 SHALL 由本地启发式 + 组级 LLM 仲裁组合产出
系统 SHALL 在 `tripclipper analyze <slug> --stage cluster` 期间，按"本地启发式聚组（双轨规则 + 并查集）+
组级 LLM 仲裁"产出 `SimilarGroup`；系统 SHALL NOT 在任何情况下伪造 `similar_*` 字段写入 `cut_index.json`。

#### Scenario: 行车记录仪连号样本被聚成一组
- **WHEN** 项目 `assets` 包含 `NO20250612-114146`、`NO20250612-114246`、`NO20250612-114346` 三条素材，
  `subject_type=building`、`modified_time` 在 60 秒内
- **THEN** 系统 SHALL 通过强信号轨把三条素材聚成同一候选组
- **AND** 调一次 Arbiter，返回 `primary_asset_id` 必须是三条素材之一、`confidence ∈ [0,1]`
- **AND** `cut_index.similar_groups` 至少有 1 个 `SimilarGroup`，每条素材的 `similar_group_id` 已写入

#### Scenario: 雷同组置信度不足时整组待人工确认
- **WHEN** Arbiter 返回 `primary_asset_id=null` 或 `confidence < 0.6`
- **THEN** 该组所有组员 `similar_selection="needs_review"`、`similar_reason` 写入原因
- **AND** 该组所有组员 `edit_candidate_status="needs_review"`、`edit_candidate_reason="所在雷同组置信度不足，待人工确认"`
- **AND** `cut_index.clustering.arbitration_failures` 不增加（仅仲裁调用失败时才增）

#### Scenario: Arbiter 调用失败但其他组继续
- **WHEN** 某组 Arbiter 调用因 HTTP 429 / 5xx / 超时连续失败（重试 1 次仍失败）
- **THEN** 该组所有组员标 `similar_selection="needs_review"`、`similar_reason="仲裁失败，待人工确认"`
- **AND** `cut_index.clustering.arbitration_failures += 1`
- **AND** 其他组继续仲裁；整体阶段在结束时根据成功/失败比例标 `status="partial"` 或 `completed`

#### Scenario: 单组超过 12 条素材时只送 Top12 仲裁
- **WHEN** 启发式聚出的某组包含 18 条素材
- **THEN** 系统 SHALL 按 `rating` desc 取 Top12 进 Arbiter
- **AND** 其余 6 条按 `rating` desc 直接标 `similar_selection="alternate"`、
  `similar_reason="组内素材过多，仅 rating Top 12 参与组级仲裁"`

### Requirement: 默认剪辑候选池 SHALL 由确定性后处理产出
系统 SHALL 在仲裁完成后，纯本地规则生成 `default_candidates`；
系统 SHALL NOT 为候选池本身调用任何 LLM。

#### Scenario: 起始集 = 非雷同 + 组主选
- **WHEN** cluster 完成、所有 `analyzed` 素材就绪
- **THEN** 系统 SHALL 把 `similar_selection ∈ {none, primary}` 的素材纳入起始集
- **AND** 不引入 `target_pool_size`，不按总数截断

#### Scenario: 主体×景别平衡修剪
- **WHEN** 候选池总数 ≥ 20 **且** 某一 `(subject_type, shot_scale)` 桶占比 > 50%
- **THEN** 系统 SHALL 把该桶 `rating` 最低的素材降为 `edit_candidate_status="alternate"`、
  `edit_candidate_reason="为景别平衡入选 alternate"`，直到该桶占比 ≤ 50%
- **AND** 修剪降级总数 SHALL NOT 超过候选池总数的 20%

#### Scenario: needs_review 素材不进候选池
- **WHEN** 某素材 `analysis_status != "analyzed"` 或 `similar_selection="needs_review"`
- **THEN** 该素材 `edit_candidate_status="needs_review"`、`edit_candidate_reason` 区分 "分析未完成"/"所在雷同组置信度不足"
- **AND** 该素材 SHALL NOT 出现在 `default_candidates` 列表中

### Requirement: cluster 阶段头尾与增量落盘
系统 SHALL 在 cluster 阶段开始写 `clustering.stage="cluster"`/`status="running"`/`started_at`；
每完成 1 个组的仲裁全量落盘 `cut_index.json` 一次；
阶段结束写 `status="completed"/"partial"/"failed"` 终态与 `finished_at`、`groups_count`、`arbitration_failures`、`error_summary`。

### Requirement: cluster 命令的硬卡与软警告
系统 SHALL 在 `tripclipper analyze <slug> --stage cluster` 启动时校验 `cut_index.analysis`：
- `analysis` 为空或 `status ∉ {completed, partial}` → 报错并指引 "请先运行 'tripclipper analyze <slug> --stage full'"，**非 0 退出**
- `analysis.stage="sample"` → 打 warning "警告：仅基于 sample 阶段的 N 个素材聚组；建议先跑 full 再 cluster"，**继续执行**

### Requirement: cluster 重跑自动清空旧分组
系统 SHALL 在 cluster 启动时若发现 `clustering.status` 已存在，自动清空 `cut.similar_groups`/`cut.default_candidates`/
`assets[*].similar_group_id`/`assets[*].similar_selection`/`assets[*].similar_rank`/`assets[*].similar_reason`/
`assets[*].edit_candidate_status`/`assets[*].edit_candidate_priority`/`assets[*].edit_candidate_reason`/`cut.clustering`，
然后从头执行；系统 SHALL NOT 引入 `--force` flag（M4 调用便宜，默认重跑）。

### Requirement: 结构化 JSONL 日志（cluster）
系统 SHALL 在每次 cluster 执行时向 `projects/<slug>/logs/cluster-<ISO8601>.jsonl` 追加结构化日志：
阶段级 `stage_start`/`stage_end`、本地聚组 `cluster_start`/`cluster_done`、仲裁级
`arbitration_start`/`arbitration_done`/`arbitration_failed`、候选池 `candidates_start`/`candidates_done`。
日志 SHALL NOT 包含 API key、Authorization header、完整 prompt 字面值、模型响应 `content` 字段。

### Requirement: run 命令扩展到 cluster
系统 SHALL 在 `tripclipper run <slug>` 中按 scan → sample → full → cluster 串行执行；
`--pause-after sample` 行为不变；该命令绕过 `analyze` 的 stage 硬卡，由编排自身确保前置 stage 已完成。

## MODIFIED Requirements

### Requirement: CutIndex 增加 clustering 字段（向后兼容）
系统 SHALL 在 `CutIndex` 上新增 `clustering: Optional[ClusteringInfo] = None` 字段；
新增字段默认为空，老的 `cut_index.json` 读取时 `clustering=None`，不影响 M0-M3 既有行为；
本次扩展属于"数据契约只增不改"原则范围内的兼容扩展，**非 BREAKING**。

## REMOVED Requirements

（暂无。）
