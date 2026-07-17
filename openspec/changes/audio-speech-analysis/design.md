## 背景

TripClipper 的 `scan` 阶段已经会记录视频是否包含音轨，但 `sample` 和 `full` 当前仍以画面分析为核心，并把结果写入 `cut_index.json`。模型中虽然已有 `transcript_path` 占位字段和通用的 `transcription_model` 配置字段，但尚未实现音频提取、人声分析、转写数据契约或 review 展示。

本变更横跨配置、持久化模型、Provider 集成、Analyzer 编排、缓存管理、导出与兼容处理。功能面向素材筛选：用户需要定位值得试听的人声，而不是获得逐字准确、可直接发布的字幕。第一版固定通过 OpenAI-compatible 端点调用 `google/gemini-3.5-flash`。

## 目标与非目标

**目标：**

- 在 `sample` 或 `full` 处理的所有已选视频中识别带时间范围的人类口语。
- 按原语言生成句子或一次连续发言级的粗略转写。
- 把视频分类为无人声、只有不清晰人声，或至少存在一段值得试听的清晰人声。
- 通过有界分块处理长视频，把局部时间恢复到原视频时间轴，并容忍单个非法片段。
- 原子持久化转写，支持安全的音频增量补跑。
- 保证音频失败不影响已有画面分析，并明确标记不完整结果。
- 在现有 review/export 流程中展示人声质量和转写内容。
- 在 Eagle 中通过稳定标签筛选人声质量，并在素材描述中直接检查带时间范围的粗略转写。

**非目标：**

- 本地 VAD、说话人识别、diarization，或音乐与环境噪声分类。
- 翻译、内容摘要、置信度或发布级逐字字幕。
- 实时/流式分析、分块重叠、跨块拼句或重复文本消歧。
- 分析 `Asset.type="audio"` 的独立音频素材。
- 从 Eagle 深链到转写时间点。

## 技术决策

### 1. 使用独立的音频分析契约

新增 `SpeechQuality` 枚举（`none`、`unclear`、`clear`）和 `Asset.speech_quality`，并把配置与运行信息中的 `transcription_model` 都改名为 `audio_analysis_model`。音频 prompt 和响应模型由独立的 `AudioAnalysisProvider` 负责，不扩展视觉 Provider 的请求结构。

该命名能够准确表达模型不仅执行转写，还负责识别人声和定性。复用视觉 Provider 会把互不相关的 prompt、媒体编码和校验路径耦合在一起。旧的软件配置字段不会被静默兼容，而是返回可执行的改名提示，因为原有的专用转写模型未必支持通用音频输入。

### 2. 只提取已选视频，并使用固定分块

`scan` 继续只通过 `ffprobe` 写入 `metadata.has_audio`。视频真正被 `sample` 或 `full` 选中后，`AudioExtractor` 才调用 `ffmpeg`，在 `cache/audio/<asset_id>/` 中生成 16 kHz、单声道、16-bit PCM WAV 分块。分块从原视频 0 秒开始，完整覆盖音频时间轴，互不重叠且最长 300 秒；每个 `AudioChunk` 记录文件路径、原视频起点偏移和持续时间。

五分钟 PCM 分块可以把内联 base64 请求控制在 Gemini 预期的请求体量内，也能限制单次重试成本。无重叠设计避免第一版引入重复文本消歧；句子如果在边界处被切开，允许保留为两个片段。非 `--force` 运行可以复用与源文件指纹匹配且通过校验的缓存，`--force` 始终重新提取。

不在 `scan` 阶段提前提取，是因为 `sample` 只分析素材子集，不应为未抽中的视频生成大体积缓存。第一版不增加本地 VAD，因为 Gemini 已能理解音频，引入第二套检测系统会增加调参和结果协调成本。

### 3. 通过 Gemini OpenAI compatibility 逐块分析

`AudioAnalysisProvider` 对每个音频块发送一次 `POST /chat/completions`，使用配置的 `audio_analysis_model`，并以包含 base64 WAV 的 `input_audio` 发送音频。Prompt 要求只返回一个 JSON 对象，字段为 `speech_quality` 和 `speech_segments`；只识别人类口语，按原语言转写，不翻译、不总结。

Provider 首次请求使用较低 reasoning effort。如果兼容代理明确拒绝 `reasoning_effort`，则去掉该参数额外重试一次，再进入现有瞬时错误重试策略。日志和失败信息沿用 secret redaction，并额外禁止记录音频 base64、完整 prompt 和完整原始响应。

### 4. 在本地校验并规范化模型输出

`AudioAnalysisParser` 校验顶层 JSON、枚举和片段字段。每个片段必须满足 `0 <= start_sec < end_sec <= chunk.duration_sec`；非法片段被丢弃并记录 warning，合法兄弟片段继续保留。合法局部时间加上分块起点偏移，再按原视频开始时间排序。

同一块内的重叠片段合并为覆盖两者的最小连续区间，非空文本按时间顺序拼接。`none` 如果同时包含合法片段则纠正为 `unclear`；`clear` 如果所有片段文本均为空也降为 `unclear`。如果校验后无法建立可信分类，则整块失败，不能当成 `none`。

本地规范化可以防止模型格式波动污染持久化数据，同时尽可能保留有效证据。由于分块契约保证跨块不重叠，重叠合并只需在块内执行。

### 5. 保守聚合并原子持久化

所有块成功时，任意块为 `clear` 则素材为 `clear`；否则任意块为 `unclear` 或含合法人声片段，则素材为 `unclear`；只有所有块均为 `none` 且无片段时，素材才为 `none`。

存在失败块时，成功块中的明确人声证据仍可得到 `clear` 或 `unclear`，但必须记录“音频分析不完整”warning。成功块均无人声不能证明失败块也无人声，因此素材保持 `null`。所有块失败时同样保持 `null`。

`TranscriptStore` 先把候选文档写入临时文件并完整校验，再原子替换 `cache/transcripts/<asset_id>.json`。只有替换成功后，Analyzer 才更新 `Asset.transcript_path` 和 `Asset.speech_quality`。部分成功的重跑绝不替换已有完整有效转写；如果不存在旧转写，包含人声证据的部分结果可以落盘，同时在转写契约之外记录不完整 warning。该顺序保证 `cut_index.json` 不会引用缺失或损坏的文件。

### 6. 画面与音频作为独立子步骤

Analyzer 对每个已选视频保留现有画面分析流程，然后执行音频子步骤。`metadata.has_audio=false` 时直接写 `speech_quality=none`，不提取音频也不调用 Provider。提取、请求或解析失败会写入素材、项目和结构化日志，但不得把已经成功的画面 `analysis_status` 改成 `analysis_failed`。

非 `--force` 运行遇到画面已分析、`has_audio=true` 且 `speech_quality=null` 的视频时，只补跑音频，不重复调用视觉模型。`--force` 同时重跑两条路径，但只有所有新音频块成功且新转写通过校验时，才允许替换旧的有效转写。

### 7. 长文本不写入主索引

`cut_index.json` schema version 从 `0.3` 升为 `0.4`，只新增可选的 `speech_quality`、已有的可选相对路径 `transcript_path`，以及 `AnalysisInfo.audio_analysis_model`。素材级转写 JSON 保存 `speech_quality` 和完整的 `{start_sec, end_sec, text}` 列表。无音轨素材不生成转写文件。

Reader 继续接受 `0.3` 索引，并把新增字段默认成 `null`；下一次写入时升级为 `0.4`。`assets.csv` 新增 `speech_quality`。`review.html` 展示分类、片段时间范围和文本；引用文件缺失或不可读时，只对该素材显示明确降级提示，不阻断其余报告。

### 8. Eagle 使用质量标签和独立描述章节

Eagle 的标签只写入低基数的 `tc:speech_quality:<none|unclear|clear>`，以便筛选且避免把任意转写文本污染标签体系。Eagle 描述新增 `## 语音识别` 章节：有片段时逐行写入 ``- `开始时间 → 结束时间` 文本``；`none` 写入“未检测到人声”；`speech_quality` 已存在但转写引用缺失、不可读或校验失败时写入“转写文件不可用”。`speech_quality=null` 时不输出质量标签，也不输出该章节。

`AssetMapper` 继续只生成 Eagle 写计划，但接收项目目录以解析相对 `transcript_path`，并通过专用 renderer 加载、校验和格式化 `TranscriptDocument`。单个素材的转写不可用只降级该素材的描述，不中断其他素材或 Eagle 同步。同步现有 Eagle Item 时仍使用完整覆盖的标签和描述，因此重新执行 `sync-eagle --apply` 会把语音结果更新到已有素材。

## 风险与取舍

- [句子可能横跨五分钟边界并形成两个粗转写片段] → 第一版接受该结果，优先保证原视频时间准确，并明确不承诺逐字字幕。
- [内联 base64 或代理请求体上限可能与 Gemini 文档不同] → 固定 300 秒上限并集中维护该常量，单块请求失败只记录分块错误，不污染其他结果。
- [部分成功会漏掉失败块中的人声] → 不从不完整覆盖推断 `none`，显式记录 warning，并保护已有完整转写。
- [模型时间戳和 JSON 可能不稳定] → 在持久化前执行范围校验、规范化和完整文档校验。
- [音频提取会占用磁盘] → 只为已选视频生成缓存，复用时校验源文件指纹，force 时重新生成。
- [配置字段改名会中断旧安装] → 启动时提供明确迁移提示，同时保持对持久化 `0.3` 索引的读取兼容。
- [音频分析会增加 `sample` 和 `full` 的时延与费用] → 每块只执行一次有界请求，增量运行复用有效结果，无音轨视频不调用模型。
- [逐字稿可能产生超长 Eagle 描述] → 第一版保留完整粗转写以满足人工检查，不复制到标签；后续若遇到 Eagle 字段上限再引入明确截断策略。

## 迁移计划

1. 新增枚举、可选持久化字段和转写模型，支持读取 `0.3`，新写入统一使用 `0.4`。
2. 把软件配置与分析运行信息中的 `transcription_model` 替换为必填的 `audio_analysis_model`，增加旧字段校验并更新示例配置。
3. 在现有 `sample`/`full` 路径中加入提取、Provider、Parser、聚合和 TranscriptStore。
4. 启用增量资格判断和独立失败记录，再扩展 CSV 与 HTML 消费端。
5. 如需回滚代码，可保留未引用的转写缓存；旧 Reader 可以继续读取变更前索引，但只接受 `0.3` 的旧软件再次运行前，需要恢复备份或迁移 `0.4` 索引。

## 待确认问题

第一版没有待确认问题。源设计已经确定模型、分块长度、语言行为、质量枚举、失败语义和排除范围。
