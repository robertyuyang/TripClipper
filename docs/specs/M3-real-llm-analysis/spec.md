# M3 真实大模型分析（Stage 2） Spec（grilling Q1–Q25 拍板）

> 状态：**定稿**。本文件由 grilling 会话的 Q1–Q25 全套决策落地而成。
> 覆盖：PRD FR-3、FR-4、FR-5；TD 6（Stage 2 模型分析）+ TD 8 中「画面类型与景别」一片
> 依赖：M0（`models`/`config`/`cut_index`/`paths`/`security`）、M1（项目目录与 `cut_index.json` 已初始化）、M2（`assets` 已扫描、`thumbnail_path`/`frame_paths`/`metadata` 已就位）
> 角色：M3 是 Stage 2 **真实大模型分析**层。它把 M2 扫描出来的素材交给一个 OpenAI 兼容协议的真实视觉模型，产出 `summary`/`tags`/`rating`/`subject_type`/`primary_subject`/`people_presence`/`shot_scale`/`shot_function`/`audio_strategy` 与 `segments` 草稿，写回 `cut_index.json`。它**不**做雷同分组（M4）、默认候选池（M4）、转写（延后）、CSV/MD/HTML 导出（M5）、Eagle（M6）、FastAPI（M7）。

## Why

PRD 把 Stage 2 的"真实模型分析"列为产品核心承诺：FR-3 样本分析、FR-4 全量分析、FR-5 主体类型与景别识别。PRD §2、§9.2 与 TD 6、TD 12 反复强调「禁止伪造分析结果」「禁止 mock 推断」「分析必须由真实模型完成」。M0 的 `Asset` 数据结构、`AnalysisStatus`、`AnalysisInfo`、`Failure` 已为此预留全部字段；M1/M2 已经把 `cut_index.json` 写到了「assets 已扫描、媒体信息与缩略图就位、`analysis_status=scanned`」的状态。M3 的任务是把这条产品承诺真正落地：以**严格只打真模型、零 mock**的纪律，写出可重入、可恢复、并发受控、失败可定位、密钥不外泄的分析引擎。

## What Changes

- 新增核心模块 `src/tripclipper/provider.py`：薄封装的 OpenAI 兼容 vision provider。
  - `Provider(config: ModelConfig, editing_intent: EditingIntent)`：构造时读环境变量取 key；缺 key 或 `is_usable=False` 即抛 `ProviderError`。
  - `analyze(asset: Asset) -> AnalysisResult`：单素材分析。一个方法内部按 `asset.type` 分叉（视频塞缩略图+至多 3 张关键帧，图片塞自身路径，音频仅文本元数据）。一次模型调用产出全部字段。
  - `_parse_response(text: str) -> AnalysisResult`：纯函数。剥 markdown 代码栅、解析 JSON、校验枚举/数值范围；非法值降级为 `other`/`None`，越界 `rating` 置 `None`。
  - `_should_retry(...)`：纯函数。判定是否瞬时错误（429 / 5xx / `httpx.TimeoutException` / `httpx.NetworkError`）。
  - prompt 模板为模块级常量（system prompt），`editing_intent` 在构造时渲染（见决策 12）。
  - 重试策略：仅瞬时错误重试 2 次（共 3 次尝试），间隔 1s → 4s + 抖动；业务错误（4xx 非 429、JSON 非法、字段越界）不重试。
  - `apply_analysis(asset, result)`：纯函数，把已校验的结果写回 `Asset`，状态转 `analyzed`。
  - `AnalysisResult`：轻量 dataclass，字段对应 `Asset` 的分析字段子集。
- 新增核心模块 `src/tripclipper/analyzer.py`：流程编排层。
  - `sample_analyze(slug, *, base_dir=None, concurrency=5) -> AnalyzeResult`：实现 FR-3。读 `cut_index.json` → 分层随机抽样（按 `AssetType` + 文件夹分布分层；固定 seed） → 线程池调 `Provider.analyze` → 增量落盘（每 5 个写一次） → 写回 `AnalysisInfo`（`stage=sample`、`status=running→completed/partial`）。
  - `full_analyze(slug, *, base_dir=None, force=False, concurrency=5) -> AnalyzeResult`：实现 FR-4。默认跳过 `analysis_status=analyzed` 的素材；`force=True` 时全量重分析。其余流程同 sample，不抽样。
  - `AnalyzeResult`：dataclass。`stage`、`total`、`succeeded`、`failed`、`skipped`、`errors: list[(asset_id, reason)]`、`started_at`、`finished_at`。
- 新增 `src/tripclipper/runner.py`（可后置到 task_list 阶段定）：一键编排 `run(slug, *, pause_after_sample=False)`，按 scan→sample→full 串起 M2/M3。绕过分步硬卡（自身确保前置 stage 已完成）。
- 修改 `src/tripclipper/cli.py`：
  - 启用现有 `analyze --stage sample|full` 接线（M2 占位时已预留）。
  - 新增 `--force`、`--concurrency` 参数。
  - 新增 `tripclipper run <slug> [--pause-after sample] [--concurrency N]` 命令。
  - 启动时自动加载项目根目录的 `.env`（`python-dotenv`），把密钥注入 `os.environ`。
- 修改 `pyproject.toml`：新增依赖 `httpx`、`python-dotenv`（已落地）。
- 修改 `.gitignore`：新增 `.env`（已落地）。
- 新增 `tests/test_provider.py` 与 `tests/test_analyzer.py`：见「测试策略」。

不在 M3 范围（明确延后）：
- **转写（whisper）**：当前版本 audio_strategy 由 vision 推断，已知精度有限；用户 `.env` 即使配了 `transcription_model` 也不调用。
- **雷同分组与默认候选池**（TD 8 余下两片）：归 M4。
- **CSV/MD/HTML 导出、Eagle、FastAPI**：归 M5/M6/M7。

## Impact

- 影响的能力：M4 雷同分组消费 M3 写入的 `summary`/`tags`/`subject_type`/`shot_scale`/`shot_function`/`segments`（如保留）；M5 导出消费 `rating`/`audio_strategy`；M6 Eagle 同步消费 `rating`/`tags`；M7 FastAPI `POST /analyze` 复用 `analyzer.sample_analyze`/`full_analyze`。
- 影响的代码：
  - 新增 `src/tripclipper/provider.py`、`src/tripclipper/analyzer.py`（可能含 `runner.py`）。
  - 修改 `src/tripclipper/cli.py`：接线 `analyze --stage sample/full` 与 `run` 命令、加载 `.env`。
  - 修改 `pyproject.toml`、`.gitignore`（已落地）。
  - 新增 `tests/test_provider.py`、`tests/test_analyzer.py`、`tests/test_cli_analyze.py`。
  - 回写 `docs/specs/README.md` 模块状态（M3 → 已完成）。
- 不改动 M0 数据契约与字段口径；M3 仅**消费** M0 已定义的 `Asset` 分析字段、`AnalysisStatus` 枚举、`AnalysisInfo`、`Failure`、`SubjectType`/`PeoplePresence`/`ShotScale`/`ShotFunction`。无 **BREAKING**。

## 关键设计决策（grilling Q1–Q21）

### Q1 / Q2 测试纪律：严格只打真模型、零 mock、缺 key 即失败、不许 skip
- 与 M2 完全对齐。M3 测试**不**通过 mock provider 或录制响应来验证模型路径。
- API key 是测试硬依赖；项目根目录的 `.env` 必须含 `TRIPCLIPPER_MODEL_API_KEY`。缺 key 测试直接 fail（不做 `skipif`），错误信息明确告知缺什么。
- 单人本地开发场景；不引入 CI 配置。

### Q3 模型与协议
- `provider="openai_compatible"`、`base_url=https://open.cherryin.ai/v1`、`vision_model="google/gemini-3.5-flash"`、`text_model="google/gemini-3.5-flash"`、`language="zh-CN"`、`sample_size=25`。
- 这些值写在用户的 `project.yaml.model_config` 里；M3 直接消费 `ModelConfig`。

### Q4 Provider 接口粒度：单一 `analyze(asset)` 通用方法
- 一个公共方法，内部按 `asset.type` 分叉。理由：`gemini-3.5-flash` 多模态走同一套 vision API，类型分叉是实现细节，调用方不关心。

### Q5 Prompt 策略：一次调用、一份 prompt 产出全部字段
- 不拆轮。Pydantic + 自定义 `_parse_response` 校验兜底，校验不过即标 `analysis_failed`、记 `Failure`，**绝不写伪造字段**。

### Q6 样本选择：分层随机抽样（固定 seed）
- 第一层按 `AssetType`（video/image/audio）分层、第二层按 `relative_path` 顶层目录分层；层内固定 seed 随机。
- 满足 FR-3 「覆盖不同素材类型、时间分布、文件夹分布、画面差异」。
- 不依赖 M2 的 `metadata`（即使元数据缺失也能稳定抽样）。

### Q7 模块组织：单文件 `provider.py`
- 不拆包。`provider.py` 含 `Provider` 类、`AnalysisResult` dataclass、`ProviderError`、`apply_analysis` 函数、prompt 模板常量。
- 跟现有 `scan.py`/`project.py`/`security.py` 风格一致。

### Q8 并发：线程池
- `concurrent.futures.ThreadPoolExecutor`，默认并发 5；CLI 提供 `--concurrency N`。
- 每线程一个 `Provider` 实例（`httpx.Client` 非线程安全，每线程独立持有）。
- 不引入 asyncio。

### Q9 流程编排放 `analyzer.py`
- `provider.py` 只管"怎么调模型"；`analyzer.py` 管"调哪些素材、抽样、增量落盘、状态机、失败记录"。
- 与 M2 的"`scan.py` 管扫描、`cli.py` 接线"对齐。

### Q10 已分析素材的处理：默认跳过、`--force` 重跑
- `full_analyze` 默认只处理 `analysis_status ∈ {scanned, analysis_failed}` 的素材。
- `--force` 全量重分析，覆盖现有结果。
- CLI 打印「跳过 N 个已完成素材」「失败 M 个素材将重试」。

### Q11 .env 自动加载
- 用 `python-dotenv` 在 CLI 启动时加载项目根目录的 `.env`，把密钥注入 `os.environ`。
- `Provider.__init__` 仍从 `os.environ` 读 key，加载顺序：项目目录 `.env` → 进程环境。
- 密钥**只**进 `os.environ`，绝不进 `cut_index.json`/CSV/HTML/日志（沿用 M0 `summarize_model_config` 边界）。
- `.env` 已加入 `.gitignore`。

### Q12 阶段头尾 + 增量落盘 + `analyzing` 不落盘
- 阶段开始：`AnalysisInfo.stage=<sample|full>`、`status="running"`、`started_at` 写入。
- 阶段过程：每完成 5 个素材加锁全量写一次 `cut_index.json`。
- 阶段结束：`status="completed"`（全成功）/`"partial"`（部分失败）/`"failed"`（整体失败），`finished_at`、`error_summary` 写入。
- `AnalysisStatus.analyzing` 仅在内存中用于线程池协调；**不**落盘。崩溃后素材要么是 `analyzed`（已成功落盘）、要么是 `scanned`（未跑到），不会留「卡在 analyzing 的僵尸态」。

### Q13 重试：仅瞬时错误指数退避
- 重试条件：HTTP 429、5xx、`httpx.TimeoutException`、`httpx.NetworkError`。
- 重试次数：2 次（共 3 次尝试），间隔 1s → 4s + 随机抖动。
- 不重试：4xx（非 429）、JSON 解析失败、Pydantic/枚举校验失败——这些重试也无意义。
- 重试全部失败后，标 `analysis_failed`、记 `Failure`，`Failure.suggestion` 区分瞬时（建议 `--force` 重跑）与非瞬时（建议检查 prompt/换 vision_model）。

### Q14 CLI 命令形状
- `tripclipper analyze <slug> --stage sample [--concurrency N]`
- `tripclipper analyze <slug> --stage full [--force] [--concurrency N]`
- 单一 `analyze` 动词 + `--stage` 枚举；`--force`/`--concurrency` 是 stage 无关的通用参数。

### Q15 阶段依赖：分步硬卡 + `run` 编排绕过
- `analyze` 命令硬卡：`cut_index.assets` 为空或没有 `scanned/analyzed/analysis_failed` 状态的素材即报错；错误信息明确告诉用户先跑 `tripclipper scan`。
- `analyze --stage full` 软提示：`AnalysisInfo.stage != "sample" || status != "completed"` 时打印 warning 但继续。
- `run` 命令绕过硬卡：`tripclipper run <slug> [--pause-after sample] [--concurrency N]`，按 scan → sample → full 串。默认一路跑完不暂停；加 `--pause-after sample` 才在 sample 完成后等用户回车。

### Q16 / Q25 测试素材：直读 `tests/videos/` 固定 5 个视频文件
- M3 集成测试主样本（5 个真实视频，覆盖 3 种来源）：
  1. `tests/videos/DJI_20260612134026_0001_D.MP4`（23MB，无人机航拍 / extreme_wide / landscape）
  2. `tests/videos/DJI_20260613145058_0115_D.MP4`（111MB，无人机航拍变种 / 不同时段）
  3. `tests/videos/IMG_4306.mov`（43MB，iPhone 录制 / 通用 / 可能有人物）
  4. `tests/videos/NO20250612-114146-064576F.mp4`（60MB，行车记录仪 / 第三种来源 / 车内/路上场景）
  5. `tests/videos/NO20250612-114246-064577F.mp4`（60MB，行车记录仪 / 紧邻连号 / 为 M4 雷同分组预留天然真实样本）
- 测试范围限定：**仅视频**。`tests/videos/` 里没有图片/音频素材；图片/音频路径靠 `_build_user_content` 的 unit 测试覆盖分支逻辑，不做 integration。
- `tests/videos/` 已加入 `.gitignore`（M2 已落地）；测试代码硬编码这 5 个文件名做 fixture，缺即 fail 并提示「M3 集成测试需要 tests/videos/{文件名} 存在」。
- 测试运行**仅在开发者本地**；不上 CI、不打包样本进仓库。

### Q17 测试覆盖：Integration（4 个真打模型）+ Unit（一堆纯函数）
- Integration（真打 Gemini，受 key + 素材双依赖；只覆盖视频路径）：
  1. `test_provider_analyzes_video_real_model` — 真喂 `DJI_20260612134026_0001_D.MP4`（最小，省钱），断言返回 `AnalysisResult` 必填字段非空、枚举合法、`rating ∈ [1,5]`、`summary` 是中文非空。
  2. `test_provider_emits_segments_for_video` — 真喂 `IMG_4306.mov`，断言 `segments` 字段如果非空则每个 `Segment` 的 `in_`/`out`/`role` 通过校验（不强制 segments 非空，模型自由判断；见 Q22）。
  3. `test_full_pipeline_sample_real_model` — 端到端：用 5 个素材构造的临时项目跑 `scan` + `sample_analyze`，断言 `cut_index.json.assets[*].analysis_status=analyzed`、`AnalysisInfo.status=completed`、`error_summary` 合理、`logs/analyze-*.jsonl` 文件生成且包含 `stage_start`/`stage_end` 事件。
  4. `test_provider_invalid_key` — 用错误 key 构造 `Provider`，断言抛 `ProviderError`、`cut_index.json` 未被污染、`CutIndex.failures` 追加项目级失败记录。
- Unit（纯函数，零 mock 也零模型调用）：
  - `_parse_response`：合法 JSON / 非法 JSON / 缺字段 / 枚举非法降级 / `rating` 越界置 None / 含 markdown 代码栅的剥离 / `segments` 字段缺失或格式错时被丢弃但其他字段保留。
  - `_should_retry`：429 / 5xx / 4xx 非 429 / `httpx.TimeoutException` / `httpx.NetworkError`。
  - 分层抽样：给定 `(10 video, 80 image, 10 audio, 多目录)` 100 个素材，断言抽 25 个时三类按比例都被抽到、目录覆盖均匀、固定 seed 可复现。
  - `--force` 跳过判定：`analyzed` 素材在 `force=False` 跳过、`force=True` 处理。
  - 增量落盘：12 个素材完成时落盘 3 次（5+5+2 的边界）。
  - `_build_user_content` 分支：video（缩略图+至多 3 帧）/image（单图）/audio（无图，仅文本元数据）三种类型分别构造正确的 content 列表。
  - `editing_intent` 渲染：5 字段全 None 时 system prompt 不含 intent 段；部分非 None 时只渲染非 None 字段。
  - 日志写入：写入 `logs/analyze-*.jsonl` 时不含 API key、不含 Authorization header、不含完整 prompt 字面值。
- 「零 mock」纪律解释：单测 `_parse_response("...")` 喂手工构造字符串测纯解析函数，**不**算 mock 模型——没有任何伪造的"分析结果"被写入 `cut_index.json` 当真结果用。约束的是「不许伪造分析结果当真」，不是「不许测纯函数」。

### Q18 失败记录：三处都写
- `Asset.failures`：每素材级失败。`stage="analyze"`、`target=asset.id`、`reason=` 具体原因（如 `"HTTP 429 after 3 retries"`/`"非法 JSON: ..."`/`"枚举值非法: subject_type=外星人"`）、`blocking=True`、`suggestion=` 区分瞬时/非瞬时。
- `CutIndex.failures`：项目级阻塞失败。`stage="analyze"`、`target=project.slug`、`reason=` 整体阻断原因（如 `"API key 未设置"`/`"Provider 初始化失败"`）。
- `AnalysisInfo.error_summary`：阶段级一句话摘要（如 `"3/25 素材分析失败（2 次 429、1 次非法 JSON）"`），CLI 输出与 M5 HTML 报告头部直接复用。

### Q19 `editing_intent` 注入：可选段渲染（None 字段不渲染）
- PRD §3/§13 与 TD 6/L86/L141 三处明文要求 `editing_intent` 必须喂给模型分析。
- M0/M1 已把它聚合为 `EditingIntent`（5 个 Optional 字段）写入 `cut_index.project.editing_intent`。
- M3 prompt 渲染规则：在 system prompt 的 `editing_intent` 段中，**只渲染非 None 字段**；5 个字段全 None 时整段不出现，模型按通用标准评分。
- 实现位置：`Provider.__init__(config, editing_intent)` 接收 intent，构造一次 system prompt 复用。
- 解释「为什么 demo-scan 没写也合法」：M0/M1 设计上允许 5 个字段全空（`Optional[str] = None`），保留「快速 init 后再补」的弹性；M3 必须能处理「全空」的合法情况。

### Q20 转写：暂不调用
- M3 不集成 whisper / 转写。`audio_strategy` 由 vision 模型基于画面（嘴动？场景类型？）+ `metadata.has_audio` 推断；prompt 显式告知模型「无法听到实际音频，基于画面推测」，避免它瞎猜。
- M3 spec 明确这是已知近似；未来 milestone（M5+）若不够准再接入 whisper。

### Q21 输出语言：prompt 写死中文
- system prompt 强制 `summary`/`primary_subject` 输出中文；`tags` 中文。
- `ModelConfig.language` 字段保留但 M3 暂不消费（YAGNI）。

### Q22 `segments` 草稿：M3 顺手产出，模型自由
- M3 让 vision 模型一次调用顺手产出 `Asset.segments`（1-3 段高光片段，每段含 `in_`/`out`/`role`/`reason`/`audio_strategy`）。
- 不强制每视频至少 1 段；模型自由判断（废片/过场可不出）。
- segments 字段在 `_parse_response` 中宽容校验：`segments` 缺失或格式错时丢弃整个 segments 列表（置为空），但**不影响**其他主字段成功落盘。
- 理由：一次调用顺手出 segments 比 M4 再调一次便宜约 50%；模型分析整段视频时给 segments 比 M4 拿 summary/tags 反推更准；M4 消费这些 segments 草稿做雷同分组与最终筛选——M3 给草稿、M4 做筛选是不同职责。

### Q23 Prompt 模板：spec 只定契约，字面归实现
- spec 已穷尽 prompt 必须满足的契约：输出字段（含枚举/范围/语言）、`editing_intent` 注入规则、`segments` 可选、强制中文、JSON 唯一输出、不许有 markdown 散文。
- 完整 prompt 字面值作为 `provider.py` 模块级常量 `_SYSTEM_PROMPT` 在实现阶段写出，验收只看「输出符合契约」，不锁定字面值。
- 后续迭代 prompt 文案不需要修订 spec，只要不破坏契约即可。

### Q24 日志：结构化 JSONL 调用级 + 阶段级 + 严格脱敏
- 文件位置：`projects/<slug>/logs/analyze-<ISO8601_timestamp>.jsonl`，每次 analyze 一个文件。
- 格式：JSON Lines（每行一个 JSON 对象，可流式 append、可 `jq` 查询、进程崩溃不损坏整文件）。
- 调用级事件（每次模型调用 1+ 行，重试每次一行）：
  - `call_start`：`ts`、`asset_id`、`attempt`、`asset_type`、`frame_count`
  - `call_end`：`ts`、`asset_id`、`attempt`、`status`（`success`/`retry`/`failure`）、`http_code`、`latency_ms`、`prompt_tokens`、`completion_tokens`（若响应含 `usage`）、`error`（错误分类，不含 stacktrace）
- 阶段级事件：
  - `stage_start`：`ts`、`stage`、`total`、`concurrency`、`project_slug`
  - `stage_end`：`ts`、`stage`、`succeeded`、`failed`、`skipped`、`duration_ms`
- 严格脱敏：日志写入器**绝不**记录 API key、`Authorization` header、完整 prompt 字面值、模型响应的 `content` 字段。Unit 测试验证脱敏。
- 实现：手写 JSONL 写入器（不引入 `python-json-logger`），写文件操作用模块级 `threading.Lock` 保护跨线程 append。
- `logs/` 加入 `.gitignore`。

### Q25 测试素材范围（见 Q16）
- 决策已与 Q16 合并：M3 集成测试用 `tests/videos/` 下 5 个真实视频文件，仅覆盖视频路径，不引入图片/音频 integration 测试。

## ADDED Requirements

### Requirement: 真实模型分析（Stage 2）SHALL 调用 OpenAI 兼容协议
系统 SHALL 通过 OpenAI 兼容的 `/chat/completions` 接口调用 `ModelConfig.vision_model`，使用 base64 编码的 `image_url` 多模态消息块传入素材的缩略图与关键帧；系统 SHALL NOT 在任何情况下伪造分析结果写入 `cut_index.json`。

#### Scenario: 视频素材的样本分析成功
- **WHEN** 用户对一个已扫描完成的项目执行 `tripclipper analyze <slug> --stage sample`
- **THEN** 系统 SHALL 用分层随机抽样从 `assets` 中选出 `min(sample_size, len(assets))` 个素材，对每个素材发起一次真实模型调用
- **AND** 每个成功素材的 `analysis_status` 转为 `analyzed`，`summary`/`tags`/`rating`/`subject_type`/`primary_subject`/`people_presence`/`shot_scale`/`shot_function`/`audio_strategy` 字段被填充且通过枚举/范围校验
- **AND** `cut_index.analysis.stage="sample"`、`status="completed"`（或 `partial`）、`started_at`/`finished_at` 被写入

#### Scenario: 模型 key 缺失
- **WHEN** 项目目录下 `.env` 缺失或不含 `TRIPCLIPPER_MODEL_API_KEY`
- **THEN** 系统 SHALL 在 `Provider` 构造阶段抛 `ProviderError`，CLI 以非 0 退出码结束并输出明确文案「环境变量 TRIPCLIPPER_MODEL_API_KEY 未设置」
- **AND** `cut_index.json` 未被污染（不写入任何伪造的分析字段，仅向 `failures` 追加一条 `stage="analyze"` 的项目级失败记录）

#### Scenario: 模型返回非法 JSON
- **WHEN** 单个素材的模型响应无法解析为合法 JSON 或字段校验失败（枚举非法、`rating` 越界）
- **THEN** 系统 SHALL **不重试**该错误，将该素材标 `analysis_status="analysis_failed"`，向 `Asset.failures` 追加一条 `reason="非法 JSON: ..."` / `"枚举值非法: ..."`、`blocking=True`、`suggestion="模型输出格式异常：检查 prompt 或更换 vision_model"`
- **AND** 其他素材继续处理，整体阶段在结束时根据成功/失败比例标 `partial` 或 `completed`

#### Scenario: 瞬时错误的指数退避重试
- **WHEN** 单个素材的模型调用返回 HTTP 429 / 5xx 或抛 `httpx.TimeoutException`/`httpx.NetworkError`
- **THEN** 系统 SHALL 重试至多 2 次（共 3 次尝试），间隔 1s → 4s + 随机抖动
- **AND** 三次都失败时，标该素材为 `analysis_failed`，`Failure.suggestion="瞬时错误：建议稍后重跑 analyze --force"`

#### Scenario: 已分析素材的默认跳过
- **WHEN** 用户对一个已存在 `analyzed` 素材的项目执行 `tripclipper analyze <slug> --stage full`（不带 `--force`）
- **THEN** 系统 SHALL 跳过 `analysis_status="analyzed"` 的素材，仅处理 `scanned`/`analysis_failed` 素材
- **AND** CLI 打印「跳过 N 个已完成素材」

#### Scenario: 强制重新分析
- **WHEN** 用户执行 `tripclipper analyze <slug> --stage full --force`
- **THEN** 系统 SHALL 处理所有素材（含 `analyzed`），用新结果覆盖旧结果

### Requirement: editing_intent 注入到 system prompt
系统 SHALL 把 `cut_index.project.editing_intent` 中所有非 None 字段渲染进 system prompt；5 个字段全 None 时整段不出现，模型按通用标准评分。

### Requirement: 阶段级与素材级状态写入
系统 SHALL 在阶段开始时写 `AnalysisInfo.stage`/`status="running"`/`started_at`，每完成 5 个素材增量落盘一次，阶段结束时写 `status` 终态与 `finished_at`、`error_summary`；`AnalysisStatus.analyzing` 仅用于内存协调，不落盘。

### Requirement: 一键编排 run 命令
系统 SHALL 提供 `tripclipper run <slug> [--pause-after sample] [--concurrency N]`，按 scan → sample → full 串行执行；该命令绕过 `analyze` 的 stage 硬卡，由编排自身确保前置 stage 已完成。

### Requirement: 密钥与产物的分离
系统 SHALL 通过 `python-dotenv` 加载项目根目录 `.env`、把 `TRIPCLIPPER_MODEL_API_KEY` 注入 `os.environ`；密钥 SHALL NOT 出现在 `cut_index.json`/CSV/HTML/日志/对话记录中（沿用 M0 `summarize_model_config` 边界）。

### Requirement: segments 草稿由 M3 顺手产出
系统 SHALL 在分析视频素材时让模型顺手产出 `Asset.segments`（0-3 段），每段含 `in_`/`out`/`role`/`reason`/`audio_strategy`；segments 不强制非空（模型自由判断）；segments 字段缺失或格式错时整段丢弃为空列表，**不影响**该素材其他字段成功落盘与 `analysis_status` 转为 `analyzed`。

### Requirement: 结构化 JSONL 日志
系统 SHALL 在每次 `analyze`/`run` 执行时向 `projects/<slug>/logs/analyze-<ISO8601>.jsonl` 追加结构化日志：阶段级 `stage_start`/`stage_end` 事件、调用级 `call_start`/`call_end` 事件（含 `asset_id`、`attempt`、`http_code`、`latency_ms`、`status`）。日志 SHALL NOT 包含 API key、`Authorization` header、完整 prompt 字面值或模型响应 `content` 字段。`logs/` SHALL 加入 `.gitignore`。

## MODIFIED Requirements

（暂无；M3 仅消费 M0 已定义字段，不修改既有契约。）

## REMOVED Requirements

（暂无。）
