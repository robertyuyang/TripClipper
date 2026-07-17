## 为什么要做

TripClipper 目前能够分析视频画面，却无法识别素材中值得试听的人声位置，导致用户在素材筛选和精剪时仍需逐条试听。把带时间范围的粗略人声分析加入现有 `sample` 和 `full` 流程，可以帮助用户快速发现包含清晰表达的视频，同时不承诺生成可直接发布的逐字字幕。

## 变更内容

- 把所选视频素材的音频分析作为 `sample` 和 `full` 的默认步骤，并与画面分析相互独立。
- 提取 16 kHz 单声道 WAV，并把长音频切成最长 300 秒、互不重叠的分块交给 Gemini 分析。
- 识别人类口语片段，按原语言生成粗略转写，并把视频分类为 `none`、`unclear` 或 `clear`。
- 把完整人声片段保存在素材级独立转写 JSON 中，`cut_index.json` 只持久化 `speech_quality` 和 `transcript_path`。
- 支持分块级重试、结果校验、部分成功聚合、转写文件原子替换，以及不重复画面分析的音频增量补跑。
- 在 `assets.csv` 中导出人声质量，在 `review.html` 中展示人声质量和转写片段；转写数据不可用时明确降级提示。
- Eagle 同步写入 `tc:speech_quality:<none|unclear|clear>` 标签，并在描述中写入带原视频时间范围的“语音识别”章节。
- **破坏性变更**：把 `ModelConfig.transcription_model` 和 `AnalysisInfo.transcription_model` 改名为 `audio_analysis_model`；软件配置仍使用旧字段时，给出明确迁移错误。
- 把 `cut_index.json` schema minor version 从 `0.3` 升为 `0.4`，同时继续兼容读取 `0.3` 索引，缺失的音频分析字段按 `null` 处理。

## 能力范围

### 新增能力

- `audio-speech-analysis`：覆盖视频音频提取、Gemini 分块人声分析、转写校验与持久化、增量和失败隔离编排、schema 兼容，以及 review/export 消费。

### 修改已有能力

- 无。

## 影响范围

- 修改 `src/tripclipper/config.py` 和 `src/tripclipper/models.py` 中的配置与持久化模型。
- 扩展扫描/分析编排、模型 Provider 集成、缓存路径、转写存储、结构化日志和失败记录。
- 扩展 CSV、HTML 导出和 Eagle 薄映射层。
- 音频发现和提取依赖 `ffprobe`/`ffmpeg`，音频理解通过现有 OpenAI-compatible 模型端点调用 `google/gemini-3.5-flash`。
- 需要补充单元测试、组件测试、Provider 合约测试、迁移测试、CLI 测试和导出测试；独立音频素材、说话人区分、翻译、本地 VAD 和发布级字幕不在范围内。
