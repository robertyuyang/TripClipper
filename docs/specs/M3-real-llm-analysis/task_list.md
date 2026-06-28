# M3 Tasks

> 阶段：实现阶段（apply）执行。当前 spec 已定稿（Q1–Q25），代码尚未实现。
> 依赖前置：M0（`models`/`config`/`cut_index`/`paths`/`security`）、M1（`init_project` 与 `project.yaml` 已落地）、M2（`scan_project` 已能产出 `assets` + `thumbnail_path`/`frame_paths`/`metadata`）。
> 纪律提醒（沿用 Q1/Q2）：**测试零 mock、严格只打真模型、缺 key 即失败、不许 skip**。`tests/test_provider.py` 与 `tests/test_analyzer.py` 中的 integration 部分必须真打 cherryin 上的 `google/gemini-3.5-flash`；缺 `TRIPCLIPPER_MODEL_API_KEY` 直接 fail，**不**使用 `pytest.skipif`。Unit 部分仅测纯函数（`_parse_response`/`_should_retry`/分层抽样/`_build_user_content` 分支/脱敏写入），不替换任何业务函数行为，不构造伪造的"分析结果"写回 `cut_index.json`。

- [x] Task 1：实现 JSONL 结构化日志写入器（`src/tripclipper/logs.py`）
  - [x] SubTask 1.1：定义 `AnalyzeLogger` 类，构造时接受 `project_slug` 与 `base_dir`，按 `projects/<slug>/logs/analyze-<ISO8601>.jsonl` 计算文件路径（沿用 M0 `paths` 风格新增 `analyze_log_path(slug, ts, base_dir)`）；用模块级 `threading.Lock` 保护跨线程 append
  - [x] SubTask 1.2：实现 `stage_start(stage, total, concurrency, project_slug)` / `stage_end(stage, succeeded, failed, skipped, duration_ms)` 阶段级事件方法（每次写一行 JSON）
  - [x] SubTask 1.3：实现 `call_start(asset_id, attempt, asset_type, frame_count)` / `call_end(asset_id, attempt, status, http_code, latency_ms, prompt_tokens, completion_tokens, error)` 调用级事件方法
  - [x] SubTask 1.4：脱敏白名单——`_scrub(event_dict)` 仅写入显式声明字段；**绝不**写 `Authorization`/`api_key`/完整 prompt/响应 `content`；调用者传入的 `error` 字段截断到 ≤512 字符且不含 stacktrace
  - [x] SubTask 1.5：写入失败要静默吞掉（日志不能拖垮分析流程），但首次失败在 stderr 打印一行 warning

- [x] Task 2：实现 OpenAI 兼容 Provider（`src/tripclipper/provider.py`）
  - [x] SubTask 2.1：定义 `ProviderError(Exception)`、轻量 `AnalysisResult` dataclass（字段对应 `Asset` 的分析字段子集：`summary`/`tags`/`rating`/`subject_type`/`primary_subject`/`people_presence`/`shot_scale`/`shot_function`/`audio_strategy`/`segments`）
  - [x] SubTask 2.2：模块级常量 `_SYSTEM_PROMPT_TEMPLATE`（写死中文输出契约：JSON 唯一输出、枚举/范围、`segments` 可选、`editing_intent` 注入占位、强制中文、无 markdown 散文）。**spec 只锁契约，字面值在本任务里写出，不锁定到 spec**（Q23）
  - [x] SubTask 2.3：`Provider.__init__(config: ModelConfig, editing_intent: EditingIntent)`——`config.is_usable() == False` 直接抛 `ProviderError`；从 `os.environ[config.api_key_env]` 读 key，缺 key 抛 `ProviderError("环境变量 TRIPCLIPPER_MODEL_API_KEY 未设置")`；按 `editing_intent` 渲染 `_system_prompt`（仅渲染非 None 字段；5 字段全 None 时不出现 intent 段——Q19）；持有线程独立的 `httpx.Client`（Q8）
  - [x] SubTask 2.4：`_build_user_content(asset: Asset) -> list[dict]`——按 `asset.type` 分叉：video → 缩略图 base64 + 至多 3 张 frames base64；image → 自身路径 base64（单图）；audio → 仅文本元数据（无图）。所有图片以 OpenAI 兼容 `image_url`（`data:image/jpeg;base64,...`）传入
  - [x] SubTask 2.5：`analyze(asset: Asset) -> AnalysisResult`——单素材分析。构造 messages、POST `<base_url>/chat/completions`、解析响应、走重试循环；**所有**模型调用产物只通过 `_parse_response` 与 `apply_analysis` 进入数据；不在 `analyze` 内直接修改 `Asset`
  - [x] SubTask 2.6：`_parse_response(text: str) -> AnalysisResult`——纯函数。剥 markdown 代码栅（```json ... ```）→ `json.loads` → 字段类型/枚举/范围校验。非法枚举降级为 `other`/`None`；`rating` 越界（不在 [1,5]）置 `None`；`segments` 缺失或格式错时丢弃整段为空列表，**不影响**其他字段（Q22）
  - [x] SubTask 2.7：`_should_retry(exc_or_resp) -> bool`——纯函数。HTTP 429、5xx、`httpx.TimeoutException`、`httpx.NetworkError` 返回 True；4xx 非 429、JSON 解析失败、Pydantic/枚举校验失败返回 False
  - [x] SubTask 2.8：重试循环（仅在 `analyze` 内）——`_should_retry` 命中时等待 1s/4s + 随机抖动（`random.uniform(0, 1)`）后重试，至多 2 次（共 3 次尝试）；超出后向上抛带分类的异常（瞬时 vs 非瞬时）供 `analyzer` 写 `Failure.suggestion`
  - [x] SubTask 2.9：`apply_analysis(asset: Asset, result: AnalysisResult) -> Asset`——纯函数，把已校验的字段写回 `Asset`，`analysis_status` 转 `analyzed`；不接受未经 `_parse_response` 的原始字符串

- [x] Task 3：实现分析编排（`src/tripclipper/analyzer.py`）
  - [x] SubTask 3.1：定义 `AnalyzeResult` dataclass：`stage`/`total`/`succeeded`/`failed`/`skipped`/`errors: list[(asset_id, reason)]`/`started_at`/`finished_at`
  - [x] SubTask 3.2：`_stratified_sample(assets, sample_size, *, seed=42) -> list[Asset]`——纯函数。第一层按 `AssetType` 分层、第二层按 `relative_path` 顶层目录分层；层内固定 seed 随机；不依赖 `metadata`；`sample_size > len(assets)` 时返回全量；可复现（Q6）
  - [x] SubTask 3.3：`sample_analyze(slug, *, base_dir=None, concurrency=5) -> AnalyzeResult`——读 `cut_index.json`（不存在或无 `scanned/analyzed/analysis_failed` 素材即抛带"先跑 tripclipper scan"提示的错）→ 写 `AnalysisInfo.stage="sample"`/`status="running"`/`started_at` → 分层抽样 → 线程池 + 每线程独立 `Provider` 实例 → 每完成 5 个加 `threading.Lock` 全量写一次 `cut_index.json`（Q12）→ 结束写 `status="completed"/"partial"/"failed"`、`finished_at`、`error_summary`
  - [x] SubTask 3.4：`full_analyze(slug, *, base_dir=None, force=False, concurrency=5) -> AnalyzeResult`——同 `sample_analyze` 流程，区别：默认跳过 `analysis_status="analyzed"`（计入 `skipped`），`force=True` 时全量重分析；写 `AnalysisInfo.stage="full"`
  - [x] SubTask 3.5：失败记录三处（Q18）——单素材失败：`Asset.failures.append(Failure(stage="analyze", target=asset.asset_id, reason=..., blocking=True, suggestion=...))`、`analysis_status="analysis_failed"`；项目级失败（如 Provider 初始化失败）：`CutIndex.failures.append(Failure(stage="analyze", target=slug, reason=...))`；阶段摘要：`AnalysisInfo.error_summary="3/25 素材分析失败（2 次 429、1 次非法 JSON）"`
  - [x] SubTask 3.6：接入 `AnalyzeLogger`——阶段头尾发 `stage_start`/`stage_end`；每次 `Provider.analyze` 前后发 `call_start`/`call_end`；attempt 编号从 1 开始递增
  - [x] SubTask 3.7：`AnalysisStatus.analyzing` 仅在内存中用作线程协调标志，**不**通过增量落盘写到 `cut_index.json`（崩溃后仅剩 `scanned`/`analyzed`/`analysis_failed`，无僵尸态——Q12）

- [x] Task 4：实现 `run` 一键编排（`src/tripclipper/runner.py`）
  - [x] SubTask 4.1：`run(slug, *, base_dir=None, pause_after_sample=False, concurrency=5)`——按 scan→sample→full 串起 M2 `scan_project` 与 M3 `sample_analyze`/`full_analyze`；自身确保前置 stage 已完成，绕过 `analyze` 的分步硬卡（Q15）
  - [x] SubTask 4.2：`pause_after_sample=True` 时在 sample 完成后阻塞等用户回车（`input()`），用户中断（Ctrl-C）→ `KeyboardInterrupt` 优雅退出并保留已落盘进度

- [x] Task 5：CLI 接线（`src/tripclipper/cli.py`）
  - [x] SubTask 5.1：CLI 启动时用 `python-dotenv.load_dotenv()` 加载**项目根目录**的 `.env`（Path(cwd)/.env），把密钥注入 `os.environ`；不覆盖已存在的环境变量（`override=False`）
  - [x] SubTask 5.2：`tripclipper analyze <slug> --stage sample [--concurrency N]`：硬卡——若 `cut_index.assets` 为空或无 `scanned/analyzed/analysis_failed` 状态素材，打印"请先跑 tripclipper scan"并 `sys.exit(非0)`；调 `analyzer.sample_analyze`
  - [x] SubTask 5.3：`tripclipper analyze <slug> --stage full [--force] [--concurrency N]`：软警告——若 `AnalysisInfo.stage != "sample"` 或 `status != "completed"`，打印 warning 但继续；调 `analyzer.full_analyze(force=...)`；打印「跳过 N 个已完成素材」「失败 M 个素材将重试」
  - [x] SubTask 5.4：新增 `tripclipper run <slug> [--pause-after sample] [--concurrency N]` 命令，调 `runner.run(...)`
  - [x] SubTask 5.5：错误兜底——`ProviderError`/编排层异常以面向用户的清晰文案打印并 `sys.exit(非0)`，**不**抛未捕获堆栈；密钥**绝不**出现在错误文案中

- [x] Task 6：依赖与忽略项落地
  - [x] SubTask 6.1：`pyproject.toml` 添加 `httpx`、`python-dotenv`（已落地，见 git commit `26cb1f3`）
  - [x] SubTask 6.2：`.gitignore` 加入 `.env`、`projects/*/logs/`（已落地）
  - [x] SubTask 6.3：项目根 `.env` 存放 `TRIPCLIPPER_MODEL_API_KEY=...`（已落地、未入仓库）

- [x] Task 7：Unit 测试（`tests/test_provider.py` 纯函数部分 + `tests/test_analyzer.py` 纯函数部分）
  - 测试约定：**零 mock**。喂手工构造字符串测 `_parse_response` 不算 mock 模型——约束的是"不许伪造分析结果当真写回 `cut_index.json`"，不是"不许测纯函数"（Q17）。
  - [x] SubTask 7.1：`_parse_response`——合法 JSON / 非法 JSON 抛分类异常 / 缺字段 / 枚举非法降级 `other`/`None` / `rating` 越界（0、6、-1、"abc"）置 `None` / 含 markdown 代码栅（```json ... ```）剥离 / `segments` 字段缺失或格式错时整段丢弃但其他字段保留
  - [x] SubTask 7.2：`_should_retry`——HTTP 429 → True / 500 → True / 503 → True / 400 → False / 401 → False / 404 → False / `httpx.TimeoutException` → True / `httpx.NetworkError` → True / `json.JSONDecodeError` → False
  - [x] SubTask 7.3：`_stratified_sample`——给定合成 100 个素材（10 video / 80 image / 10 audio，跨 5 个顶层目录），断言抽 25 个时三类按比例都被抽到、顶层目录覆盖均匀、固定 seed 两次调用结果完全一致；`sample_size > len(assets)` 时返回全量
  - [x] SubTask 7.4：`full_analyze` 跳过判定——构造含 5 个 `analyzed` + 3 个 `scanned` 的 `cut_index`，断言 `force=False` 跳过 5 个、`force=True` 处理全部 8 个（用极小 `concurrency=1` 且后续 mock-free 路径中**不真打模型**——这条用例改为纯函数 `_should_process(asset, force)` 测试，**不**调 `Provider.analyze`）
  - [x] SubTask 7.5：增量落盘边界——构造 12 个素材的完成回调序列，断言落盘被触发 3 次（5+5+2 的边界）；该测试对落盘函数注入"计数 callback"参数而非替换函数本体
  - [x] SubTask 7.6：`_build_user_content` 分支——构造 video / image / audio 三个 `Asset`，断言返回的 content 列表分别包含：video → 1 缩略图 + ≤3 frames 的 `image_url` 项；image → 1 个 `image_url` 项；audio → 0 个 `image_url` 项 + 文本元数据
  - [x] SubTask 7.7：`editing_intent` 渲染——5 字段全 None 时 `_system_prompt` 不含 intent 段；只填 `output_style` 时只渲染该字段；5 字段全填时全部渲染
  - [x] SubTask 7.8：日志脱敏——给 `AnalyzeLogger` 传入故意包含 `Authorization: Bearer sk-xxx`、完整 prompt、模型响应 `content` 的事件 dict，断言落盘 JSONL 中**不**出现这些字面值

- [x] Task 8：Integration 测试（`tests/test_provider.py` 与 `tests/test_analyzer.py` 真打模型部分）
  - 测试约定：**真打 cherryin 上的 `google/gemini-3.5-flash`**。缺 `TRIPCLIPPER_MODEL_API_KEY` 直接 fail（"M3 集成测试需要 .env 配置 TRIPCLIPPER_MODEL_API_KEY"）；缺 `tests/videos/<文件名>` 也直接 fail（"M3 集成测试需要 tests/videos/{文件名} 存在"）。**不** `skipif`、**不** 录制回放、**不** 进 CI。
  - 落地说明：为避免两个 `test_provider.py` / `test_analyzer.py` 文件膨胀且与 unit 部分混跑，集成 4 个用例集中放在新文件 `tests/test_integration_m3.py`（同样零 mock、真打）。原 task_list 文案"放在 test_provider/test_analyzer 里"作为同等纪律的落地变体。
  - [x] SubTask 8.1：`test_provider_analyzes_video_real_model`——真喂 `tests/videos/DJI_20260612134026_0001_D.MP4`（最小、省钱），先 M2 `scan_project` 拿到 `thumbnail_path`/`frame_paths`，构造 `Provider` 调 `analyze`，断言 `AnalysisResult` 必填字段（`summary`/`subject_type`/`shot_scale`/`shot_function`）非空且符合枚举、`rating ∈ [1,5]`、`summary` 为中文（含至少一个 CJK 字符）
  - [x] SubTask 8.2：`test_provider_emits_segments_for_video`——真喂 `tests/videos/IMG_4306.mov`，断言 `segments` 字段如果非空则每个 `Segment.in_`/`out`/`role` 通过 Pydantic 校验（不强制 segments 非空——Q22）
  - [x] SubTask 8.3：`test_full_pipeline_sample_real_model`——端到端：用 5 个 `tests/videos/` 视频（`DJI_20260612134026_0001_D.MP4`/`DJI_20260613145058_0115_D.MP4`/`IMG_4306.mov`/`NO20250612-114146-064576F.mp4`/`NO20250612-114246-064577F.mp4`）的 symlink 在 `tmp_path` 构造临时项目，`init_project` + `scan_project` + `sample_analyze`，断言：
    - `cut_index.json.assets[*].analysis_status="analyzed"`（除模型确实失败的少数）
    - `AnalysisInfo.status="completed"` 或 `"partial"`，`started_at`/`finished_at` 已写入
    - `error_summary` 文案合理（无则为空字符串/None）
    - `projects/<slug>/logs/analyze-*.jsonl` 文件生成、首末行分别含 `stage_start`/`stage_end`、调用级行含 `call_start`/`call_end`
    - 日志文件文本**不**包含 API key 字面值
  - [x] SubTask 8.4：`test_provider_invalid_key`——临时设 `TRIPCLIPPER_MODEL_API_KEY="sk-invalid-xxx"` 构造 `Provider` 真打一次，断言抛 `ProviderError`（或 `analyze` 返回失败状态后 `analyzer` 写入项目级 `Failure`）；断言 `cut_index.json` 中未被写入任何分析字段（`assets[*].summary` 等仍为 `None`/空）；测试结束 restore 原 env

- [x] Task 9：CLI 测试（`tests/test_cli_analyze.py`）
  - [x] SubTask 9.1：`click.testing.CliRunner` 真起 `tripclipper analyze <slug> --stage sample`（**不**绕过模型）；断言退出码 0、stdout 含「分析完成」「成功 N / 失败 M / 跳过 K」摘要、`cut_index.json` 已更新
  - [x] SubTask 9.2：未初始化项目（无 `cut_index.json`）跑 `analyze --stage sample` → 退出码非 0、stderr 提示"先跑 tripclipper init / scan"、不抛堆栈
  - [x] SubTask 9.3：`scanned` 素材为零（项目刚 init 未 scan）→ 退出码非 0、提示"先跑 tripclipper scan"
  - [x] SubTask 9.4：`tripclipper analyze <slug> --stage full --force` → 处理所有素材；不带 `--force` → 跳过 `analyzed` 素材并打印「跳过 N 个已完成素材」
  - [x] SubTask 9.5：`tripclipper run <slug> --pause-after sample` → sample 完成后阻塞、模拟输入回车后继续 full（用 `CliRunner.invoke(..., input="\n")`）

- [x] Task 10：回写状态与文档
  - [x] SubTask 10.1：`docs/specs/README.md` 模块索引把 M3 状态从"规划中"更新为"已完成"
  - [x] SubTask 10.2：如实现与 spec 有偏差（例如重试间隔参数、prompt 字面值），回写 `spec.md` 保持事实源一致；prompt 字面值本身不必回写（Q23 已约定）
  - [x] SubTask 10.3：`pytest -q` 全绿（PATH 含 `/opt/homebrew/bin`、`.env` 含有效 `TRIPCLIPPER_MODEL_API_KEY`、`tests/videos/` 5 个文件齐全）

# Task Dependencies
- Task 2 依赖 Task 1（Provider 调用日志写入器）
- Task 3 依赖 Task 1、Task 2（Analyzer 编排 Provider + 日志）
- Task 4 依赖 Task 3（runner 串 sample/full）
- Task 5 依赖 Task 3、Task 4（CLI 接 analyzer/runner）
- Task 6 与 Task 1~Task 5 独立（已落地）
- Task 7（Unit）依赖 Task 1~Task 3（被测纯函数已就位）
- Task 8（Integration）依赖 Task 1~Task 5
- Task 9（CLI）依赖 Task 5
- Task 10 依赖 Task 1~Task 9 全绿
