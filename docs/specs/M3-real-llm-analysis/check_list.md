# M3 验收清单

## 如何手动验证本模块

> M3 是 Stage 2 真实大模型分析层，没有页面，验收靠：CLI `analyze`/`run` + 检查 `cut_index.json.assets` 的分析字段 + `projects/<slug>/logs/analyze-*.jsonl` + 真实集成测试。前置需 `.env` 含 `TRIPCLIPPER_MODEL_API_KEY`、`ffmpeg`/`ffprobe`（M2）、`tests/videos/` 5 个视频齐全。

```bash
# 0) 环境准备
export PATH="/opt/homebrew/bin:$PATH"          # ffmpeg/ffprobe
cat .env | grep TRIPCLIPPER_MODEL_API_KEY      # 确认 key 在
ls tests/videos/                                # 5 个视频齐全

# 1) 先 M1 init + M2 scan，再 M3 sample
tripclipper init --config ./project.yaml
tripclipper analyze --stage scan --config ./project.yaml
tripclipper analyze <slug> --stage sample --concurrency 5
# 打印：阶段开始 → 进度 → 分析完成（成功 N / 失败 M / 跳过 K），退出码 0

# 2) 检查分析产物
cat projects/<slug>/cut_index.json | jq '.assets[0]'    # summary/tags/rating/subject_type/... 已填充
cat projects/<slug>/cut_index.json | jq '.analysis'      # stage=sample / status=completed|partial / started_at / finished_at
ls projects/<slug>/logs/                                 # analyze-<ISO>.jsonl 已生成
head -1 projects/<slug>/logs/analyze-*.jsonl             # stage_start 事件
tail -1 projects/<slug>/logs/analyze-*.jsonl             # stage_end 事件

# 3) 全量分析（默认跳过已 analyzed）
tripclipper analyze <slug> --stage full
# 打印「跳过 N 个已完成素材」

# 4) 强制重分析
tripclipper analyze <slug> --stage full --force

# 5) 一键编排
tripclipper run <slug> --pause-after sample --concurrency 5

# 6) 失败路径：缺 key
mv .env .env.bak
tripclipper analyze <slug> --stage sample
# → 退出码非 0，stderr 含「环境变量 TRIPCLIPPER_MODEL_API_KEY 未设置」，cut_index.json 未被污染
mv .env.bak .env

# 7) 真实集成测试全绿（零 mock、真打 gemini-3.5-flash）
pytest -q tests/test_provider.py tests/test_analyzer.py tests/test_cli_analyze.py
```

**重点核对**：分析字段（summary/tags/rating/subject_type/primary_subject/people_presence/shot_scale/shot_function/audio_strategy）齐全且通过枚举/范围校验；`rating ∈ [1,5]`；`summary` 中文；`segments` 缺失或格式错时**不**影响其他字段；阶段状态 `running → completed/partial/failed` 正确流转；增量落盘每 5 个一次；崩溃后无 `analyzing` 僵尸态；日志**不**含 API key / Authorization / 完整 prompt / 模型 content；密钥**不**进 `cut_index.json`/CSV/HTML/日志。

## 真实模型分析（Stage 2）调用 OpenAI 兼容协议
- [ ] 视频素材的 sample 分析成功：`tripclipper analyze <slug> --stage sample` 抽出 `min(sample_size, len(assets))` 个素材，每个素材发起一次真实模型调用
- [ ] 每个成功素材 `analysis_status="analyzed"`，`summary`/`tags`/`rating`/`subject_type`/`primary_subject`/`people_presence`/`shot_scale`/`shot_function`/`audio_strategy` 被填充且通过枚举/范围校验
- [ ] `cut_index.analysis.stage="sample"`、`status="completed"` 或 `"partial"`、`started_at`/`finished_at` 被写入
- [ ] 不在任何情况下伪造分析结果写入 `cut_index.json`（缺 key/请求失败/解析失败时只写 `failures`，不写伪造分析字段）

## 模型 key 缺失
- [ ] `.env` 缺失或不含 `TRIPCLIPPER_MODEL_API_KEY` 时，`Provider` 构造阶段抛 `ProviderError`
- [ ] CLI 以非 0 退出码结束，输出明确文案「环境变量 TRIPCLIPPER_MODEL_API_KEY 未设置」
- [ ] `cut_index.json` 未被污染（不写入任何伪造的分析字段）
- [ ] 仅向 `CutIndex.failures` 追加一条 `stage="analyze"`、`target=<slug>` 的项目级失败记录

## 模型返回非法 JSON / 字段校验失败
- [ ] 单个素材模型响应无法解析为合法 JSON 或字段校验失败（枚举非法、`rating` 越界）时**不重试**
- [ ] 该素材标 `analysis_status="analysis_failed"`
- [ ] `Asset.failures` 追加 `reason="非法 JSON: ..."` 或 `"枚举值非法: ..."`、`blocking=True`、`suggestion="模型输出格式异常：检查 prompt 或更换 vision_model"`
- [ ] 其他素材继续处理，阶段结束时按成功/失败比例标 `partial` 或 `completed`

## 瞬时错误的指数退避重试
- [ ] HTTP 429 / 5xx / `httpx.TimeoutException` / `httpx.NetworkError` 触发重试
- [ ] 重试至多 2 次（共 3 次尝试），间隔 1s → 4s + 随机抖动
- [ ] 三次都失败时该素材标 `analysis_failed`，`Failure.suggestion="瞬时错误：建议稍后重跑 analyze --force"`
- [ ] 4xx 非 429、JSON 解析失败、Pydantic 校验失败**不重试**

## 已分析素材的跳过与强制
- [ ] `tripclipper analyze <slug> --stage full`（不带 `--force`）跳过 `analysis_status="analyzed"` 素材，仅处理 `scanned`/`analysis_failed`
- [ ] CLI 打印「跳过 N 个已完成素材」
- [ ] `tripclipper analyze <slug> --stage full --force` 处理所有素材（含 `analyzed`），用新结果覆盖旧结果

## editing_intent 注入 system prompt
- [ ] `cut_index.project.editing_intent` 中所有非 None 字段渲染进 system prompt
- [ ] 5 个字段全 None 时整段不出现，模型按通用标准评分
- [ ] 只填部分字段时只渲染非 None 字段（单元测试 7.7 覆盖）

## 阶段级与素材级状态写入
- [ ] 阶段开始时写 `AnalysisInfo.stage` / `status="running"` / `started_at`
- [ ] 每完成 5 个素材增量落盘一次 `cut_index.json`（12 个素材触发 3 次落盘：5+5+2）
- [ ] 阶段结束时写 `status="completed"`（全成功）/ `"partial"`（部分失败）/ `"failed"`（整体失败）、`finished_at`、`error_summary`
- [ ] `AnalysisStatus.analyzing` 仅在内存中用于线程协调，**不**落盘；崩溃后只剩 `scanned`/`analyzed`/`analysis_failed`，无僵尸态

## 一键编排 run 命令
- [ ] `tripclipper run <slug>` 按 scan → sample → full 串行执行，默认一路跑完不暂停
- [ ] `tripclipper run <slug> --pause-after sample` 在 sample 完成后阻塞等用户回车，按下后继续 full
- [ ] `--concurrency N` 参数传递到 sample/full 两阶段
- [ ] `run` 绕过 `analyze` 的 stage 硬卡（不需要先单独跑 scan）

## 密钥与产物的分离
- [ ] CLI 启动时 `python-dotenv` 加载项目根 `.env`，注入 `os.environ`（不覆盖已存在变量）
- [ ] 密钥**不**出现在 `cut_index.json` 任何字段
- [ ] 密钥**不**出现在 `projects/<slug>/logs/analyze-*.jsonl` 任何行
- [ ] 密钥**不**出现在 CLI 错误文案、stdout、stderr
- [ ] `.env` 已加入 `.gitignore`（已落地）
- [ ] `projects/*/logs/` 已加入 `.gitignore`（已落地）

## segments 草稿由 M3 顺手产出
- [ ] 分析视频素材时模型顺手产出 `Asset.segments`（0-3 段），每段含 `in_`/`out`/`role`/`reason`/`audio_strategy`
- [ ] segments 非空时每段通过 Pydantic 校验（`Segment.in_`/`out`/`role` 字段就绪）
- [ ] segments 不强制非空（模型自由判断废片/过场不出 segments）
- [ ] segments 字段缺失或格式错时整段丢弃为空列表，**不**影响该素材其他字段成功落盘
- [ ] segments 字段缺失时 `analysis_status` 仍能转为 `analyzed`

## 结构化 JSONL 日志
- [ ] `projects/<slug>/logs/analyze-<ISO8601>.jsonl` 文件在每次 `analyze`/`run` 时生成
- [ ] 文件首行包含 `stage_start` 事件（`stage`/`total`/`concurrency`/`project_slug`）
- [ ] 文件末行包含 `stage_end` 事件（`stage`/`succeeded`/`failed`/`skipped`/`duration_ms`）
- [ ] 中间行包含 `call_start`/`call_end` 事件（`asset_id`/`attempt`/`status`/`http_code`/`latency_ms` 等）
- [ ] 重试每次产生独立的 `call_start`/`call_end` 行（attempt 编号递增）
- [ ] 日志文件**不**包含 API key 字面值
- [ ] 日志文件**不**包含 `Authorization` header
- [ ] 日志文件**不**包含完整 prompt 字面值
- [ ] 日志文件**不**包含模型响应 `content` 字段
- [ ] 跨线程并发写入由模块级 `threading.Lock` 保护，JSONL 行格式不损坏

## CLI 接口形状
- [ ] `tripclipper analyze <slug> --stage sample [--concurrency N]` 工作
- [ ] `tripclipper analyze <slug> --stage full [--force] [--concurrency N]` 工作
- [ ] `tripclipper run <slug> [--pause-after sample] [--concurrency N]` 工作
- [ ] 未初始化项目执行 analyze → 退出码非 0、提示先 `tripclipper init`、不抛未捕获堆栈
- [ ] 已 init 但未 scan 执行 analyze → 退出码非 0、提示先 `tripclipper scan`
- [ ] `analyze --stage full` 在 sample 未完成时打印 warning 但继续（软警告）

## 安全与一致性
- [ ] 项目目录的 `cut_index.json` 由 `read_cut_index`/`write_cut_index` 读写（沿用 M0 边界）
- [ ] 任何错误文案/日志/落盘文件不含密钥明文
- [ ] M3 未重新定义任何 M0 字段或枚举（仅消费 `AnalysisStatus`/`SubjectType`/`PeoplePresence`/`ShotScale`/`ShotFunction`/`Asset`/`Segment`/`Failure`/`AnalysisInfo`）

## 测试与回写
- [ ] `tests/test_provider.py` 全部用例通过（unit + integration）
- [ ] `tests/test_analyzer.py` 全部用例通过（unit + integration）
- [ ] `tests/test_cli_analyze.py` 全部用例通过
- [ ] Integration 测试**真打** cherryin 上的 `google/gemini-3.5-flash`，无 mock provider、无录制回放
- [ ] 缺 `TRIPCLIPPER_MODEL_API_KEY` 测试直接 fail，错误信息明确告知缺什么；**不**使用 `pytest.skipif`
- [ ] 缺 `tests/videos/<文件名>` 测试直接 fail，错误信息明确告知缺哪个文件
- [ ] Unit 测试不替换任何业务函数行为（喂构造字符串测 `_parse_response` 不算 mock 模型）
- [ ] 不构造伪造的"分析结果"写回 `cut_index.json` 当真结果用
- [ ] `docs/specs/README.md` 中 M3 状态更新为已完成
- [ ] `pytest -q` 全绿（PATH 含 `/opt/homebrew/bin`、`.env` 有效、`tests/videos/` 齐全）
