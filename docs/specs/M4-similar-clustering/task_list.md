# M4 Tasks

> 阶段：实现阶段（apply）尚未开始。spec 已定稿（Q1–Q19）。
> 依赖前置：M0（`models`/`paths`/`cut_index`）、M1（`init_project` 与 `project.yaml`）、
> M2（`scan_project` 已写 `assets[*].metadata.modified_time`）、M3（`assets[*]` 已写
> `summary`/`tags`/`rating`/`subject_type`/`shot_scale`/`primary_subject` 等分析字段）。
> 纪律提醒（沿用 M3 Q1/Q2）：**测试零 mock、严格只打真模型、缺 key 即失败、不许 skip**。
> Arbiter 真打 cherryin 上的 `google/gemini-3.5-flash`；端到端集成测试直接在
> [`projects/demo-scan/`](../../../projects/demo-scan/) 原地跑。Unit 部分仅测纯函数
> （Jaccard / 并查集 / 候选池平衡 / `_parse_arbitration` / 状态机），不替换任何业务函数行为，
> 不构造伪造的"分析结果"写回 `cut_index.json`。

- [ ] Task 1：扩展数据契约（[`src/tripclipper/models.py`](../../../src/tripclipper/models.py)）
  - [ ] SubTask 1.1：新增 `ClusteringInfo` BaseModel，字段对齐 `AnalysisInfo`：
        `stage: Literal["cluster"]`、`provider: Optional[str]`、`vision_model: Optional[str]`、
        `text_model: Optional[str]`、`started_at: Optional[datetime]`、
        `finished_at: Optional[datetime]`、`status: Literal["running","completed","partial","failed"]`、
        `error_summary: Optional[str]`、`groups_count: int = 0`、`arbitration_failures: int = 0`
  - [ ] SubTask 1.2：在 `CutIndex` 上加 `clustering: Optional[ClusteringInfo] = None`；更新 `__all__`
  - [ ] SubTask 1.3：补单测：用现有 `cut_index.json` 反序列化时（没有 `clustering` 字段）`clustering=None`、其他字段不变

- [ ] Task 2：实现本地启发式聚组与候选池生成（[`src/tripclipper/clusterer.py`](../../../src/tripclipper/clusterer.py)）
  - [ ] SubTask 2.1：定义模块级常量 `_TIME_WINDOW_SECONDS = 60`、`_SUBJECT_SIMILARITY_THRESHOLD = 0.6`、
        `_TAGS_JACCARD_THRESHOLD = 0.5`、`_SUBJECT_SHOT_BALANCE_TRIGGER_SIZE = 20`、`_SUBJECT_SHOT_BALANCE_RATIO = 0.5`、
        `_SUBJECT_SHOT_BALANCE_MAX_TRIM_RATIO = 0.2`、`_GROUP_ARBITRATION_LIMIT = 12`
  - [ ] SubTask 2.2：`_text_jaccard_2gram(s1: str, s2: str) -> float`——2-gram Jaccard 纯函数；
        中文 1 char = 1 token，按字符切 2-gram；空串/单字直接返回 0
  - [ ] SubTask 2.3：`_tags_jaccard(t1: list[str], t2: list[str]) -> float`——集合 Jaccard；空集合返回 0
  - [ ] SubTask 2.4：`_similarity_signals(a: Asset, b: Asset) -> tuple[bool, str]`——返回 (是否相似, 命中轨道说明)；
        强信号轨：`abs(a.metadata.modified_time - b.metadata.modified_time) ≤ 60s` 且 `subject_type` 一致；
        语义信号轨：`subject_type` + `shot_scale` 一致且（`primary_subject` 2-gram Jaccard ≥ 0.6 或
        `tags` Jaccard ≥ 0.5）；任一轨道命中即视为相似
  - [ ] SubTask 2.5：`_UnionFind` 私有类（标准并查集：`find` / `union` / `groups`）
  - [ ] SubTask 2.6：`cluster_candidates(assets: list[Asset]) -> list[CandidateGroup]`——
        显式过滤 `analysis_status="analyzed"` 素材进入聚组；其余素材跳过；
        两两调 `_similarity_signals`、union；最终输出 `len > 1` 的候选组（单元素组直接当 non-grouped 处理）；
        `CandidateGroup` 是私有 dataclass：`asset_ids: list[str]`、`signal_summary: str`
  - [ ] SubTask 2.7：`apply_similarity_states(cut: CutIndex, groups: list[SimilarGroup]) -> None`——
        把每个 `SimilarGroup` 的 `primary_asset_id` / `alternate_asset_ids` / `rejected_asset_ids` /
        `needs_review_asset_ids` 写回每个组员的 `assets[*].similar_group_id` / `similar_selection` /
        `similar_rank` / `similar_reason`；rank 排序按 spec Q18（primary=1 → alternate → rejected → needs_review）
  - [ ] SubTask 2.8：`build_default_candidates(cut: CutIndex) -> list[DefaultCandidate]`——
        起始集 = `similar_selection ∈ {none, primary}` 的 `analyzed` 素材；
        若 `len(起始集) ≥ 20` 且某 `(subject_type, shot_scale)` 桶占比 > 50%，
        把该桶 rating 最低的素材降为 `edit_candidate_status="alternate"` 直到占比 ≤ 50%；
        修剪上限为起始集总数的 20%；
        每条素材按 `edit_candidate_status` 写 `edit_candidate_priority` 与 `edit_candidate_reason`（中文模板，见 spec Q6）；
        返回 `DefaultCandidate` 列表（仅 `default_selected` 状态的素材）
  - [ ] SubTask 2.9：未 analyzed 素材统一标 `edit_candidate_status="needs_review"`、`edit_candidate_reason="分析未完成，待人工确认"`；
        needs_review 雷同组员标 `edit_candidate_reason="所在雷同组置信度不足，待人工确认"`

- [ ] Task 3：实现组级 LLM 仲裁（[`src/tripclipper/arbiter.py`](../../../src/tripclipper/arbiter.py)）
  - [ ] SubTask 3.1：定义 `ArbiterError(Exception)`、`ArbitrationResult` dataclass
        （`primary_asset_id: Optional[str]`、`alternate_asset_ids: list[str]`、`rejected_asset_ids: list[str]`、
        `confidence: float`、`basis: list[str]`、`reason_by_asset: dict[str, str]`、`needs_review: bool`）
  - [ ] SubTask 3.2：模块级 `_ARBITER_SYSTEM_PROMPT_TEMPLATE` 常量——
        强制中文输出契约：JSON 唯一输出、字段定义、`basis` 限定 PRD §6.2 五选项（同一景点 / 同一动作 / 相近构图 / 相近画面内容 / 相近声音内容）、
        `confidence` 范围 [0,1]、置信度不足时允许 `primary_asset_id=null`、`editing_intent` 注入占位
  - [ ] SubTask 3.3：`Arbiter.__init__(config: ModelConfig, editing_intent: EditingIntent)`——
        `config.is_usable() == False` 直接抛 `ArbiterError`；从 `os.environ[config.api_key_env]` 读 key（缺则抛）；
        渲染 `_system_prompt`（沿用 M3 Q19 渲染规则）；持有 `httpx.Client`
  - [ ] SubTask 3.4：`_build_group_user_content(group_assets: list[Asset]) -> list[dict]`——
        每条素材只送 `thumbnail_path` 的 base64 `image_url`；附带文本"asset_id={id}, rating={r}, subject_type={s}"
        作为 anchor，避免模型混淆素材身份
  - [ ] SubTask 3.5：`arbitrate(group: list[Asset]) -> ArbitrationResult`——
        构造 messages、POST `<base_url>/chat/completions`、走重试循环；
        调用 `_parse_arbitration` 解析；
        校验所有返回的 asset_id 都在输入组内（防模型幻觉），不在则整组 `needs_review=True`
  - [ ] SubTask 3.6：`_parse_arbitration(text: str) -> ArbitrationResult`——纯函数。
        剥 markdown 代码栅 → `json.loads` → 字段类型/枚举/范围校验；
        `confidence` 缺失或不在 [0,1] → `needs_review=True`；
        `confidence < 0.6` → `needs_review=True`（保留 primary 提示，但 caller 据此走 needs_review 路径）；
        `basis` 元素不在五选项集合内 → 过滤掉，剩下为空时整组 `needs_review`；
        `primary_asset_id=null` → `needs_review=True`
  - [ ] SubTask 3.7：复用 `provider._should_retry` 纯函数（直接 import 或镜像同义实现，但**不**抄 prompt 解析）；
        重试策略：可重试错误重试 1 次（共 2 次尝试，对应 spec Q16），间隔 1s + 抖动；非瞬时不重试
  - [ ] SubTask 3.8：失败兜底——`arbitrate` 内部异常（瞬时全部失败 / JSON 非法 / 校验失败）一律向上抛分类异常；
        由 `cluster_runner.py` 统一处理 `arbitration_failures += 1`

- [ ] Task 4：实现 cluster 流程编排（[`src/tripclipper/cluster_runner.py`](../../../src/tripclipper/cluster_runner.py)）
  - [ ] SubTask 4.1：定义 `ClusterResult` dataclass：
        `total_groups`、`primary_decided`、`needs_review_groups`、`arbitration_failures`、
        `pool_size`、`alternate_count`、`needs_review_count`、`excluded_count`、
        `started_at`、`finished_at`、`log_path`、`cut_index_path`
  - [ ] SubTask 4.2：`cluster(slug, *, base_dir=None) -> ClusterResult`——
        1. 读 `cut_index.json`（不存在或 `analysis` 缺失即抛带"先跑 tripclipper analyze --stage full"提示的错）；
        2. 硬卡 `analysis.status ∈ {completed, partial}`；不满足报错退出；
        3. 软警告：`analysis.stage="sample"` 时打 stderr warning，继续；
        4. **重跑清空**：若 `cut.clustering` 非空，清空 `cut.similar_groups`、`cut.default_candidates`、
           `assets[*].similar_*`、`assets[*].edit_candidate_*`、`cut.clustering`，落盘一次；
        5. 写 `cut.clustering = ClusteringInfo(stage="cluster", status="running", started_at=..., provider=..., vision_model=..., text_model=...)`；落盘；
        6. 调 `clusterer.cluster_candidates(cut.assets)` 拿 `CandidateGroup` 列表；发 `cluster_done` 日志（含 `groups_count`）；
        7. 对每个 `CandidateGroup`：
           - 按 rating Top12 截断（超过 12 的尾部素材直接标 `similar_selection="alternate"`、`similar_reason="组内素材过多..."`）；
           - 发 `arbitration_start` 日志；
           - 调 `Arbiter.arbitrate(top12_assets)`；
           - 仲裁返回后构造 `SimilarGroup`：写 `group_id`（自动生成 `group_<n>` 或基于内容 hash）、`asset_ids`、
             `primary_asset_id`、`alternate_asset_ids`、`rejected_asset_ids`、`confidence`、`basis`；
           - 若 `needs_review=True` 则整组 `similar_selection="needs_review"`；
           - 发 `arbitration_done` 日志；
           - 每组完成增量落盘 `cut_index.json` 一次（spec Q8）；
           - 仲裁异常 → catch → 整组 `needs_review`、`similar_reason="仲裁失败，待人工确认"`、
             `cut.clustering.arbitration_failures += 1`、`cut.failures` 追加 `Failure`、发 `arbitration_failed` 日志、继续下一组；
        8. 调 `clusterer.apply_similarity_states(cut, similar_groups)` 把状态写回 `assets`；
        9. 调 `clusterer.build_default_candidates(cut)` 生成候选池；发 `candidates_done` 日志；
        10. 写 `cut.clustering.status="completed"/"partial"/"failed"`、`finished_at`、
            `groups_count`、`arbitration_failures`、`error_summary`；最终落盘；
        11. 返回 `ClusterResult`
  - [ ] SubTask 4.3：增量落盘加锁——单进程串行不需要锁，但要保证落盘原子（`tmp + rename`，沿用 [`cut_index.py`](../../../src/tripclipper/cut_index.py) 既有 writer）
  - [ ] SubTask 4.4：`_summarize_errors(arbitration_failures, needs_review_count)` 生成 `error_summary` 中文文案
        （如 `"2 组仲裁失败、3 组置信度不足"`）

- [ ] Task 5：扩展 JSONL 日志（[`src/tripclipper/logs.py`](../../../src/tripclipper/logs.py)）
  - [ ] SubTask 5.1：新增 `cluster_log_path(slug, ts, base_dir)` 到 [`paths.py`](../../../src/tripclipper/paths.py)：
        `projects/<slug>/logs/cluster-<ts>.jsonl`
  - [ ] SubTask 5.2：复用 `AnalyzeLogger` 或新增 `ClusterLogger`（建议复用现有 logger，加 `kind` 参数）；
        新增事件方法：`cluster_start(stage, total_assets, project_slug)` / `cluster_done(groups_count, eligible_assets)` /
        `arbitration_start(group_id, asset_count)` / `arbitration_done(group_id, confidence, primary_asset_id, http_code, latency_ms)` /
        `arbitration_failed(group_id, http_code, error, retry_attempt)` /
        `candidates_start()` / `candidates_done(pool_size, alternate_count, needs_review_count, excluded_count)`
  - [ ] SubTask 5.3：脱敏：与 M3 Q24 同纪律，日志**绝不**含 API key、Authorization、完整 prompt、模型响应 `content`

- [ ] Task 6：CLI 接线（[`src/tripclipper/cli.py`](../../../src/tripclipper/cli.py)）
  - [ ] SubTask 6.1：`--stage` 枚举追加 `"cluster"`
  - [ ] SubTask 6.2：在 `analyze` 命令中处理 `stage == "cluster"` 分支——
        slug 必填；调 `cluster_runner.cluster(slug, base_dir=...)`；
        打印 `ClusterResult` 摘要（`total_groups` / `primary_decided` / `needs_review_groups` /
        `arbitration_failures` / `pool_size` / `alternate_count` / `needs_review_count` / `log_path`）
  - [ ] SubTask 6.3：错误兜底——`ArbiterError`、`AnalyzerError`（cluster_runner 可能复用）以面向用户的清晰文案打印并 `sys.exit(非0)`；
        密钥**绝不**出现在错误文案

- [ ] Task 7：扩展 run 编排（[`src/tripclipper/runner.py`](../../../src/tripclipper/runner.py)）
  - [ ] SubTask 7.1：`RunResult` 新增 `cluster: Optional[ClusterResult]`
  - [ ] SubTask 7.2：`run(slug, ...)` 在 full 完成后追加调用 `cluster_runner.cluster(slug, base_dir=base_dir)`；
        cluster 失败时记入 `result.notes`、不抛中断（与 M3 `run` 风格一致：分步硬卡由编排自身保证）
  - [ ] SubTask 7.3：CLI `run` 命令的输出摘要补 `[cluster]` 一行（`groups=...  pool_size=...  arbitration_failures=...`）

- [ ] Task 8：Unit 测试（[`tests/test_clusterer.py`](../../../tests/test_clusterer.py) + [`tests/test_arbiter.py`](../../../tests/test_arbiter.py) 的纯函数部分 + [`tests/test_cluster_runner.py`](../../../tests/test_cluster_runner.py)）
  - 测试约定：**零 mock**。喂手工构造字符串测 `_parse_arbitration` 不算 mock 模型——约束的是
    "不许伪造分析结果当真写回 `cut_index.json`"，不是"不许测纯函数"。
  - [ ] SubTask 8.1：`_text_jaccard_2gram`——
        `("海边夕阳人物", "海边夕阳人物")` → 1.0；
        `("海边夕阳人物", "海边人物夕阳")` → ≥ 0.6（语序变化）；
        `("海边", "山顶")` → 0.0；
        空串 / 单字 → 0.0
  - [ ] SubTask 8.2：`_tags_jaccard`——
        `(["海", "夕阳"], ["海", "夕阳"])` → 1.0；
        `(["海", "夕阳"], ["海", "人物"])` → 1/3；
        `([], [])` → 0.0
  - [ ] SubTask 8.3：`_similarity_signals` 强信号轨——
        构造两个 `Asset`，`modified_time` 差 30 秒、`subject_type=building`，断言相似命中"强信号轨"；
        差 90 秒不相似；`subject_type` 不一致不相似
  - [ ] SubTask 8.4：`_similarity_signals` 语义信号轨——
        构造两个 `Asset`，`subject_type` + `shot_scale` 一致、`primary_subject` 文本相似 0.7，断言相似；
        `tags` Jaccard 0.6 也命中；两者都 < 阈值则不相似
  - [ ] SubTask 8.5：`_UnionFind` 并查集传递闭包——
        A 与 B 相似、B 与 C 相似、A 与 C 不直接相似 → `{A, B, C}` 同组
  - [ ] SubTask 8.6：`cluster_candidates` 过滤未 analyzed 素材——
        构造 10 个 `Asset` 中 3 个 `analysis_status="scanned"`、7 个 `analyzed`，断言聚组只对 7 个工作
  - [ ] SubTask 8.7：`build_default_candidates` 主体×景别平衡触发分支——
        合成 30 条 `Asset`，其中 18 条 `(subject_type=building, shot_scale=wide)`、12 条其他类型，
        断言触发修剪、building+wide 桶占比 ≤ 50%、修剪降级总数 ≤ 6
  - [ ] SubTask 8.8：`build_default_candidates` 不触发分支——
        合成 15 条 `Asset` 平均分布，断言 `len < 20` 不触发任何修剪、所有素材进 `default_selected`
  - [ ] SubTask 8.9：`build_default_candidates` 修剪上限分支——
        合成 30 条 `Asset` 中 25 条全部 `(building, wide)`（极端集中），断言修剪 ≤ 6（占比 20%），
        剩余 19 条 building+wide 仍在 default_selected
  - [ ] SubTask 8.10：`build_default_candidates` needs_review 不进池——
        合成 5 条 `analyzed` + 3 条 `analysis_failed` + 2 条 `similar_selection="needs_review"`，
        断言后 5 条全部 `edit_candidate_status="needs_review"`、不在 `default_candidates` 列表
  - [ ] SubTask 8.11：`_parse_arbitration` 合法 JSON / 非法 JSON / `primary_asset_id` 引用不在组内（被拒）/
        `confidence < 0.6` 整组 `needs_review` / `basis` 越界过滤
  - [ ] SubTask 8.12：cluster 重跑清空——构造已有 `clustering.status="completed"` 的 `cut_index`，
        断言 cluster_runner 启动时清空所有 similar/edit_candidate 字段
  - [ ] SubTask 8.13：增量落盘——构造 5 个候选组，断言 `cluster_runner` 写盘次数 ≥ 6（每组一次 + 阶段头尾）；
        测试对落盘函数注入"计数 callback"参数而非替换函数本体
  - [ ] SubTask 8.14：失败记录三处——构造 Arbiter 抛瞬时异常的情形，
        断言：组员 `similar_selection="needs_review"` + `cut.clustering.arbitration_failures += 1` +
        `cut.failures` 追加 `Failure(stage="cluster", target=group_id)`
  - [ ] SubTask 8.15：日志脱敏——给 logger 传入故意含 `Authorization: Bearer sk-xxx` 的事件 dict，
        断言落盘 JSONL 中**不**出现该字面值

- [ ] Task 9：Integration 测试（真打模型，[`tests/test_arbiter.py`](../../../tests/test_arbiter.py) integration 部分 + [`tests/test_integration_m4.py`](../../../tests/test_integration_m4.py)）
  - 测试约定：**真打 cherryin 上的 `google/gemini-3.5-flash`**。缺 `TRIPCLIPPER_MODEL_API_KEY` 直接 fail
    （"M4 集成测试需要 .env 配置 TRIPCLIPPER_MODEL_API_KEY"）；缺 [`projects/demo-scan/`](../../../projects/demo-scan/) 或其 `analysis.status != completed` 也直接 fail。
    **不** `skipif`、**不** 录制回放、**不** 进 CI。
  - [ ] SubTask 9.1：`test_arbiter_real_model`——用 demo-scan 的三条天然连号样本
        （`NO20250612-114146` / `114246` / `114346`）构造 `[Asset, Asset, Asset]` 组，
        真打 Arbiter，断言：
        - 返回的 `primary_asset_id` 必须是三条素材之一（或 None / `needs_review=True`，都合法）
        - `confidence ∈ [0, 1]`
        - 若 `primary_asset_id` 非 None 则 `basis` ⊆ {同一景点, 同一动作, 相近构图, 相近画面内容, 相近声音内容}
        - `reason_by_asset` 每条 reason 含至少一个 CJK 字符
  - [ ] SubTask 9.2：`test_full_pipeline_with_cluster`——端到端，**原地** [`projects/demo-scan/`](../../../projects/demo-scan/) 跑 cluster：
        - **Setup**：主动清空 `cut.similar_groups` / `cut.default_candidates` / `cut.clustering` 三个字段，落盘；
          断言前置 `cut.analysis.status="completed"` 且 `assets` 非空（demo-scan 应满足）；
        - **Action**：调用 `cluster_runner.cluster("demo-scan")`；
        - **Assert**：
          - `cut.similar_groups` 至少有 1 个 `SimilarGroup`（demo-scan 有连号样本天然形成）
          - 该组 `primary_asset_id` 在 `asset_ids` 列表中（若非 `needs_review`）
          - `cut.default_candidates` 不为空、含该组 `primary_asset_id`（若 primary 决定）
          - `cut.clustering.status="completed"` 或 `"partial"`
          - `cut.clustering.groups_count >= 1`
          - `projects/demo-scan/logs/cluster-*.jsonl` 文件生成、首末行分别含 `stage_start` / `stage_end`
          - 日志文本**不**包含 API key 字面值
        - **Teardown**：不还原；允许用户跑完 pytest 后直接打开 `cut_index.json` 查看真实输出
  - [ ] SubTask 9.3：`test_cluster_rerun_clears_old_state`——
        在 SubTask 9.2 完成后（即 demo-scan 已有 `clustering.status="completed"`），再次调用 `cluster_runner.cluster("demo-scan")`，
        断言：旧的 `similar_groups` / `default_candidates` 被清空后重新生成、`clustering.started_at` 是更晚的时间戳、
        新生成新的 `logs/cluster-*.jsonl` 文件（不覆盖旧文件）

- [ ] Task 10：CLI 测试（[`tests/test_cli_analyze.py`](../../../tests/test_cli_analyze.py) 扩展）
  - [ ] SubTask 10.1：`tripclipper analyze demo-scan --stage cluster` → 退出码 0、stdout 含"cluster 完成"摘要；
        cut_index.json 已写 `clustering.status` 终态
  - [ ] SubTask 10.2：`tripclipper analyze <未init> --stage cluster` → 退出码非 0、stderr 提示先 init / scan / analyze、不抛堆栈
  - [ ] SubTask 10.3：`tripclipper analyze <已init未scan> --stage cluster` → 退出码非 0、stderr 提示先 analyze --stage full
  - [ ] SubTask 10.4：`tripclipper analyze <仅 sample 完成> --stage cluster` → 退出码 0 但 stderr 含 warning
        "警告：仅基于 sample 阶段的 N 个素材聚组"
  - [ ] SubTask 10.5：`tripclipper run demo-scan` → scan/sample/full 已就绪时仅跑 cluster；stdout 摘要含 `[cluster]` 一行

- [ ] Task 11：依赖与忽略项
  - [ ] SubTask 11.1：无新依赖（复用 `httpx` / `python-dotenv`）
  - [ ] SubTask 11.2：`.gitignore` 中 `projects/*/logs/` 通配已覆盖 `cluster-*.jsonl`，无需修改
  - [ ] SubTask 11.3：[`docs/specs/README.md`](../README.md) 更新 M4 状态为"实施中"/"已完成"
