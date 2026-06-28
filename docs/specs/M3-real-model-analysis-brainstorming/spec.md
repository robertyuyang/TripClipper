# M3 真实大模型分析（Stage 2）Spec — brainstorming 版本

> 状态：**草案（brainstorming 产出）**。本文件由 2026-06-25 brainstorming 会话产出，与已存在的 `M3-real-llm-analysis/spec.md`（grilling 拍板版）**并存**。两份 spec 之间的取舍由用户后续手动合并决定，本文件不替代它，也不改动 `docs/specs/README.md` 的模块状态表。
> 覆盖：PRD FR-3、FR-4、FR-5；TD §6（Stage 2 模型分析）+ TD §8 中「画面类型与景别」一片。
> 依赖：M0（`models`/`config`/`cut_index`/`paths`/`security`）、M1（项目目录与 `cut_index.json` 已初始化）、M2（`assets` 已扫描，`thumbnail_path`/`frame_paths`/`metadata` 已就位）。
> 不在范围：similar_groups / default_candidates（M4）、CSV/MD/HTML 导出（M5）、Eagle（M6）、FastAPI `/analyze`（M7）。

## Why

PRD §2、§9.2 与 TD §6、§12 反复强调：Stage 2 必须由真实大模型完成，禁止伪造分析结果。M0 已为分析字段（`summary`/`tags`/`rating`/`segments`/`subject_type`/`primary_subject`/`people_presence`/`shot_scale`/`shot_function`/`audio_strategy`）和枚举做了单一来源；M2 已经把素材连同 `thumbnail_path` 与 `frame_paths` 写到了 `cut_index.json`。M3 在此基础上把"真模型"接进来，把上面那些字段填满，并把过程做成可重入、单素材失败隔离、密钥不外泄的最小 MVP。

本次 brainstorming 决策的取舍倾向：**实现尽量薄、模块边界尽量清晰、本地长跑可崩溃可续、单素材失败不污染整批**。

## What Changes

- 新增 `src/tripclipper/provider.py`：OpenAI Compatible 协议层。
  - 类 `OpenAICompatibleProvider(base_url, api_key, vision_model, text_model=None, transcription_model=None, language="zh-CN", timeout_s=60.0)`。
  - 方法 `analyze_visual(*, system_prompt: str, user_text: str, image_data_urls: list[str]) -> str`：单次 `/chat/completions` 调用，多模态消息含 `image_url=data:image/jpeg;base64,...`；返回 raw content 字符串。`temperature=0.2`、`response_format={"type":"json_object"}`（不支持的 provider 会忽略）。
  - 方法 `transcribe(audio_path: Path) -> str`：调 `/audio/transcriptions`（OpenAI Whisper 风格）。仅当 `transcription_model` 配置且素材 `metadata.has_audio=True` 时调一次，结果作为 vision prompt 的文本上下文（截断至 800 字）。
  - 错误类型：`ProviderError`（基类）/ `ProviderAuthError` / `ProviderTimeoutError` / `ProviderHTTPError`。**不在 provider 内部重试**。
- 新增 `src/tripclipper/prompt.py`：请求构造与响应解析。
  - `build_messages(asset, editing_intent, frame_paths, thumbnail_path, transcript_text=None) -> tuple[str, str, list[str]]`：返回 `(system_prompt, user_text, image_data_urls)`。
  - `parse_response(raw: str) -> AnalysisResult`：剥 markdown 代码栅、`json.loads` → `AnalysisResult.model_validate(...)`。校验失败抛 `AnalysisJSONError`。
  - `AnalysisResult` Pydantic：`summary`、`tags: list[str]`、`rating: int (1-5)`、`primary_subject`、`subject_type` / `people_presence` / `shot_scale` / `shot_function`（直接复用 M0 枚举）、`audio_strategy: str`、`segments: list[Segment]`（不限制条数；模型自由判断）。
  - `apply_result(asset: Asset, result: AnalysisResult) -> None`：把 `AnalysisResult` 字段映射回 `Asset`，并把 `analysis_status` 置 `analyzed`。
- 新增 `src/tripclipper/analyze.py`：编排层。
  - `analyze_project(slug, *, stage: Literal["sample","full"], force=False, retry_failed=False, auto_scan=False, base_dir=None) -> AnalyzeResult`。
  - 内部：`read_cut_index` → 检测视频素材是否缺缩略图/帧 → `select_pool` → 串行 for 循环（每个素材：构 prompt → `provider.analyze_visual` → `parse_response`（含一次"严格只输出 JSON"重试）→ `apply_result` → `write_cut_index`）→ 终态写 `analysis.{status,finished_at,error_summary}`。
- 修改 `src/tripclipper/cli.py`：
  - 启用 `analyze --stage sample|full`，加 `--force`、`--retry-failed`、`--auto-scan` 三个 flag。
  - 不新增 `run` 命令（区别于 grilling 版）。
- 修改 `src/tripclipper/security.py`：新增 `resolve_api_key(api_key_env: str) -> str`，**credentials 优先**于环境变量（详见 §「密钥读取」）。
- 修改 `pyproject.toml`：新增依赖 `httpx`（已落地或新增）。**不**新增 `python-dotenv`。
- 新增测试：
  - `tests/test_prompt.py`（纯本地，零模型调用，覆盖解析、枚举降级、JSON 错误路径）。
  - `tests/test_provider.py`（零 mock 真实调用，未设密钥 `pytest.skip`）。
  - `tests/test_analyze.py`（零 mock 端到端真实调用 + 真实视频，未设密钥 `pytest.skip`；非密钥失败路径不需要密钥）。

## Impact

- M4 雷同分组将消费 `summary`/`tags`/`subject_type`/`shot_scale`/`shot_function`/`segments`；M5/M6/M7 消费 `rating`/`audio_strategy`/`tags`。
- 不改 M0 数据契约与字段口径（`schema_version` 不动，仍 `0.2`）。
- 不改 `docs/specs/README.md` 状态表（本 spec 与 `M3-real-llm-analysis/spec.md` 并存，谁是主版本由用户后续合并决定）。

## 关键设计决策（brainstorming 拍板）

> 下文每条决策是本次 brainstorming 单独提问、用户单独选定的结论。

1. **Provider 协议**：只实现 OpenAI Compatible。覆盖 OpenAI、豆包（火山引擎兼容端点）、Qwen DashScope 兼容端点、DeepSeek、Mistral、本地 Ollama。Anthropic / Gemini 等非 OpenAI 协议厂商**不在第一版**支持。
2. **视频喂模**：复用 M2 缓存的关键帧（`cache/frames/`，默认 3 帧）+ 缩略图（`cache/thumbnails/`），不重新抽帧、不本地压缩；以 `data:image/jpeg;base64,...` 形式塞入 `image_url`。
3. **图片喂模**：M2 的 `thumbnail_path` 即原图路径（M2 设计），按同样 data URL 形式单图喂入。
4. **音频喂模**：**M3 第一版直接跳过**音频类素材（标 `analysis_status` 保持 `scanned` 不变；不计入失败）。注意此点与 grilling 版 spec 的"vision 推断 audio_strategy"取舍不同。
5. **转写**：若 `model_config.transcription_model` 已配且素材 `metadata.has_audio=True`，对视频素材额外调一次 transcription；结果作为 vision prompt 的辅助文本上下文（截断至 800 字）。未配则不调。
6. **样本选择**：分层轮流（stratified round-robin），按 `(type, source_folder 下一级父目录)` 分桶，桶内按 `asset_id` 字典序，桶间 round-robin 取直到达 `sample_size` 或耗尽可用素材。完全确定性。
7. **样本规模**：取 `min(sample_size, len(可用素材))`。配 25 但项目只有 8 个 → 跑 8 个，不报错（与"必须先确认样本"的 PRD §5.3 心智一致）。
8. **调度与落盘**：**串行**循环 + **每素材即时落盘**。崩溃恢复时已 `analyzed` 的素材自动跳过，最坏丢"正在分析的当前 1 个"。
9. **JSON 校验失败**：本地 `parse_response` 失败 → 拼一句"上次输出无法解析，请严格只输出 JSON 对象，不要有额外文本"再调一次；第二次仍失败 → 标 `analysis_failed`，不再重试。
10. **HTTP / 超时失败**：**不重试**。直接标该素材 `analysis_failed`，记录 `Failure(reason=...)`。`timeout_s=60`（可由 `model_config.timeout_s` 覆盖）。
11. **重跑策略**：`analyze --stage full` 默认跳过 `analyzed` 素材；`--force` 处理所有（含 `analyzed`，覆盖旧结果）；`--retry-failed` 只处理 `analysis_failed`。三者可组合（互斥优先级：`--force` > `--retry-failed` > 默认）。
12. **缺帧素材的处理**：默认**单步**——发现任一参与分析的视频素材缺 `thumbnail_path` 或 `frame_paths` 时，立即报错 `ScanRequiredError`，提示"请先 `tripclipper analyze --stage scan`，或加 `--auto-scan`"，退出码非 0。`--auto-scan` flag 让 M3 调 M2 的 `scan_project(..., extract_media=True)` 补产后继续。
13. **密钥来源**（双源 + 文件优先）：
    1. 先读 `~/.tripclipper/credentials`（KEY=VALUE 顺序文件，dotenv 风格，`#` 注释，不存在则跳过）。
    2. 文件中找到与 `model_config.api_key_env` 同名键 → 直接返回该值（**credentials 优先**）。
    3. 否则回退到 `os.environ[api_key_env]`。
    4. 两者都没有 → 抛 `CredentialMissing("请把 {name} 放入 ~/.tripclipper/credentials 或设环境变量")`。
    5. credentials 文件**不进** `cut_index.json` / 导出 / 日志。首次创建时建议 chmod 0600（实现层处理）。
14. **rating**：1–5 整数（与 M0 `Asset.rating: Optional[int]` 一致）。校验失败走 §9 的 JSON 重试路径。
15. **segments 上限**：不限制。`parse_response` 只校验单段 `in/out` 不超 `metadata.duration`。
16. **进度可见**：串行循环中按 `[i/total] <asset_id> <type> <status>` 单行 print；阶段结束打印总计 `ok / failed / skipped`。**不引入 tqdm/rich**，**不写持久化日志文件**（区别于 grilling 版）。
17. **模块拆分**：三模块 `provider.py` + `prompt.py` + `analyze.py`。
18. **测试纪律**：零 mock，真实调用真实模型服务。需要环境变量 `TRIPCLIPPER_TEST_BASE_URL` + `TRIPCLIPPER_TEST_API_KEY` + `TRIPCLIPPER_TEST_VISION_MODEL`；**未设全则 `pytest.skip`**（区别于 grilling 版的"缺 key 直接 fail"，原因：MVP 阶段单人开发，不希望默认开发体验里跑 pytest 就掏钱打模型）。非密钥失败路径（`ScanRequiredError` / `CredentialMissing` / `parse_response` 单元）无密钥也能跑。
19. **CLI 错误码**：
    - `ScanRequiredError` → exit 2
    - `CredentialMissing` → exit 3
    - `ProviderError` 让 provider 构造时就抛（鉴权失败、base_url 不可达）→ exit 4
    - 单素材失败但整体走完 → exit 0（PRD §8.1 "单失败不阻塞整体"）
20. **schema_version**：不动，保持 `0.2`。M3 只填 M0 已定义字段。
21. **不在 M3 范围**：
    - 雷同分组与默认候选池（M4）。
    - audio 类素材的真实分析（含 transcription 也不分析 audio 类，只作为 video 的辅助）。
    - 持久化结构化日志（区别于 grilling 版）。
    - `tripclipper run <slug>` 一键编排命令（区别于 grilling 版）。
    - CSV/MD/HTML 导出、Eagle、FastAPI。

## 与既有 `M3-real-llm-analysis/spec.md` 的差异速查

| 主题 | M3-real-llm-analysis（grilling） | 本 spec（brainstorming） |
|---|---|---|
| 并发 | ThreadPoolExecutor 默认 5 | **串行** |
| 落盘节奏 | 每 5 个增量落盘 | **每个素材即时落盘** |
| 重试 | 429/5xx/timeout 指数退避 2 次；JSON 非法不重试 | HTTP/超时不重试；JSON 非法重试 1 次（"请严格输出 JSON"） |
| 密钥来源 | `.env` via python-dotenv → `os.environ` | `~/.tripclipper/credentials` (KEY=VALUE) **优先** + env 回退 |
| 测试缺密钥 | **fail，不 skip** | **`pytest.skip`** |
| 日志 | `projects/<slug>/logs/analyze-<ts>.jsonl` 调用级+阶段级 | **仅 stdout 单行**，无持久化日志 |
| audio 类素材 | vision 推断 audio_strategy（不调转写） | **直接跳过** |
| 缺帧/缩略图 | 由 `run` 编排绕过；`analyze` 本身硬卡 | `analyze` 默认硬卡，提供 `--auto-scan` flag 自动补产 |
| `tripclipper run` | 有 | **无** |
| segments 上限 | 0–3 段 | **不限制**（只校验 in/out ≤ duration） |
| 模块拆分 | `provider.py` + `analyzer.py`（+ 可选 `runner.py`） | `provider.py` + `prompt.py` + `analyze.py` |
| 重跑 flag | `--force` | `--force`、`--retry-failed`、`--auto-scan` |
| 协议 | OpenAI Compatible | OpenAI Compatible（一致） |
| 关键帧/缩略图 | M2 已产物（一致） | M2 已产物（一致） |
| 模型 JSON 输出 | 一次调用全字段 + Pydantic 校验（一致） | 一次调用全字段 + Pydantic 校验（一致） |
| 不做雷同/导出/Eagle | 一致 | 一致 |

> 合并时建议**逐项**拍板，而不是整体二选一——例如可能想保留 grilling 版的"持久化 JSONL 日志"，但采纳本版的"credentials 优先于 env"。

## ADDED Requirements

### Requirement: 真实模型分析（Stage 2）SHALL 调用 OpenAI 兼容协议

系统 SHALL 通过 OpenAI 兼容的 `/chat/completions` 接口调用 `model_config.vision_model`，使用 base64 编码的 `image_url` 多模态消息块传入素材的缩略图与关键帧；系统 SHALL NOT 在任何情况下伪造分析结果写入 `cut_index.json`。

#### Scenario: 视频素材的样本分析成功

- **WHEN** 用户对一个 M2 扫描完成的项目执行 `tripclipper analyze --config <project.yaml> --stage sample`
- **THEN** 系统 SHALL 用分层轮流采样从 `assets`（仅 video/image，跳过 audio）中选出 `min(sample_size, len(可用素材))` 个素材
- **AND** 对每个素材发起一次真实模型调用，成功素材的 `analysis_status` 转为 `analyzed`，`summary`/`tags`/`rating(1-5)`/`subject_type`/`primary_subject`/`people_presence`/`shot_scale`/`shot_function`/`audio_strategy` 字段被填充且通过枚举/范围校验
- **AND** `cut_index.analysis.stage="sample"`、`started_at`/`finished_at` 被写入，终态为 `succeeded`（全成功）或 `completed_with_failures`（部分失败）

#### Scenario: 模型 JSON 输出不合法 → 重试一次

- **WHEN** 模型首次响应无法 `json.loads`，或 Pydantic 校验失败（枚举非法、`rating` 越界、`segments` 越界）
- **THEN** 系统 SHALL 用追加一句"上次输出无法解析为合法 JSON，请严格只输出 JSON 对象，不要有额外文本"重新调用一次
- **AND** 第二次仍失败时，标该素材 `analysis_status="analysis_failed"`，向 `Asset.failures` 追加 `Failure(stage="analyze", reason="JSON 解析/校验失败 …")`

#### Scenario: HTTP 错误或超时不重试

- **WHEN** 单次模型调用返回非 2xx HTTP，或抛超时 / 网络异常
- **THEN** 系统 SHALL 不重试，直接将该素材标 `analysis_failed`，记录 `Failure(reason="ProviderHTTPError: …")` 或 `Failure(reason="ProviderTimeoutError: 60s")`
- **AND** 其余素材继续处理

#### Scenario: 密钥缺失

- **WHEN** `~/.tripclipper/credentials` 既不含 `model_config.api_key_env` 同名键，环境变量也未设
- **THEN** 系统 SHALL 在 provider 构造时抛 `CredentialMissing`，CLI 以 exit 3 结束并提示"请把 {name} 放入 ~/.tripclipper/credentials 或设环境变量"
- **AND** `cut_index.json` 未被污染（仅向 `failures` 追加一条项目级失败记录）

#### Scenario: 重跑默认跳过已 analyzed 素材

- **WHEN** 用户执行 `tripclipper analyze --stage full`（不带 flag）
- **THEN** 系统 SHALL 跳过 `analysis_status="analyzed"` 的素材，处理 `scanned` 与 `analysis_failed`
- **AND** CLI 打印"跳过 N 个已完成素材"

#### Scenario: `--force` 重跑所有

- **WHEN** 用户执行 `tripclipper analyze --stage full --force`
- **THEN** 系统 SHALL 处理所有素材（含 `analyzed`），用新结果覆盖

#### Scenario: `--retry-failed` 只重跑失败

- **WHEN** 用户执行 `tripclipper analyze --stage full --retry-failed`
- **THEN** 系统 SHALL 只处理 `analysis_status="analysis_failed"` 的素材

### Requirement: editing_intent 注入到 system prompt

系统 SHALL 把 `cut_index.project.editing_intent` 中所有非 None 字段渲染进 system prompt；5 个字段全 None 时整段不出现，模型按通用标准评分。

### Requirement: 视频缺帧/缩略图时默认硬卡 + `--auto-scan` 可补产

系统 SHALL 在发现任一参与分析的视频素材缺 `thumbnail_path` 或 `frame_paths` 时，默认抛 `ScanRequiredError` 并以 exit 2 结束；当用户加 `--auto-scan` 时，系统 SHALL 调用 M2 `scan_project(extract_media=True)` 补产后继续分析。

### Requirement: audio 类素材在 M3 第一版被跳过

系统 SHALL NOT 对 `asset.type="audio"` 的素材发起模型分析；它们保持 `analysis_status="scanned"` 不变，不计入 `analyze` 阶段的成功/失败。

### Requirement: transcription 仅作为 video 的可选辅助

系统 SHALL 在 `model_config.transcription_model` 已配置且视频素材 `metadata.has_audio=True` 时，对该视频额外调用一次 transcription，结果（截断 800 字）作为 vision prompt 的辅助文本上下文；未配置 transcription_model 时不调。

### Requirement: 串行 + 即时落盘

系统 SHALL 串行处理每个素材；每个素材分析完成（成功或失败）后立刻写回 `cut_index.json`，使得进程崩溃后最多丢一个未完成素材，已落盘素材在重跑时被默认跳过。

### Requirement: 密钥读取（credentials 优先 + env 回退）

系统 SHALL 通过 `tripclipper.security.resolve_api_key(api_key_env)` 取得密钥；优先级为：`~/.tripclipper/credentials`（KEY=VALUE 顺序文件）→ `os.environ[api_key_env]`；两者皆无时抛 `CredentialMissing`。密钥 SHALL NOT 出现在 `cut_index.json` / CSV / HTML / 日志中（沿用 M0 `summarize_model_config` 边界）。

### Requirement: 进度对用户可见（仅 stdout）

系统 SHALL 在串行循环中按 `[i/total] <asset_id> <type> <status>` 单行打印每个素材的处理结果，并在结束时打印总计 `ok / failed / skipped`。M3 第一版**不**写持久化日志文件。

## MODIFIED Requirements

（暂无；M3 仅消费 M0 已定义字段，不修改既有契约。）

## REMOVED Requirements

（暂无。）

## 安全与一致性约束

- `source_folder` 与素材文件保持只读；M3 不删除/移动/覆盖原始素材。
- 派生产物（如 `--auto-scan` 路径下生成的缩略图与关键帧）只写入项目 `cache/`。
- 密钥（`~/.tripclipper/credentials` 文件内容、`os.environ` 值）不进 `cut_index.json`、不进 stdout 打印、不进任何导出。
- 字段口径以 M0 `models.py` 为唯一来源，M3 不重新定义任何字段或枚举。
