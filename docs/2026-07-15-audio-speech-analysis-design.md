# 视频人声分析与粗转写设计

## 目标

在现有 `sample` / `full` 素材分析中，自动识别视频里出现人声的时间段，生成可供人工精剪参考的粗略转写，并提供素材级定性字段，帮助用户筛选包含清晰人声的视频。

本功能服务于素材筛选和人工精剪，不以生成可直接发布的高精度字幕为目标。用户仍会在精剪时亲自试听原视频，因此系统优先保证人声片段可定位、分类语义清楚，允许转写存在少量错字或遗漏。

## 已确认的产品决策

- 音频分析模型固定为 `google/gemini-3.5-flash`。
- 配置字段使用 `audio_analysis_model`，不再把通用音频理解模型称为 `transcription_model`。
- 音频分析是 `sample` / `full` 的默认组成部分，不提供关闭开关。
- 第一版直接使用 Gemini 分析音频，不引入本地 VAD。
- 自动识别说话语言，按原语言转写，不翻译；中英混说保持原样。
- 转写采用句子或一次连续发言级分段。
- 第一版支持超大音频：固定切成最多 5 分钟的无重叠分块，分别分析后恢复为原视频时间。
- 音频分析与画面分析独立失败；音频失败不得抹掉或否定已有画面分析结果。

## 范围

### 包含

- 从带音轨的视频中提取分析用音频。
- 识别人类口语的时间范围。
- 对每个人声片段生成粗略原文转写。
- 生成素材级 `speech_quality` 分类。
- 把完整分段结果写入独立转写 JSON，并通过 `Asset.transcript_path` 引用。
- 在 `sample` / `full` 中编排音频分析、重试、增量落盘和失败隔离。
- 对过长音频做固定时长切块并合并结果。

### 不包含

- 本地 VAD 或其他独立语音活动检测模型。
- 说话人识别或 diarization。
- 风噪、音乐、环境声等干扰类型分类。
- 置信度字段。
- 内容摘要或 `content_hint`。
- 翻译。
- 可直接发布的高精度逐字字幕。
- 实时音频或流式转写。
- 相邻分块重叠、重复文本消歧或跨块句子重组。

## 术语与判定口径

### 人声片段

`speech_segment` 表示原视频时间轴中出现可辨认人类说话声的连续区间。画内或画外说话、单人或多人、普通话、方言、英文及中英混说均可计入。

纯音乐、歌唱、笑声、哭声、欢呼等不含口语表达的声音不计入。背景谈话若模型能够确认有人说话，仍计入；如果内容无法可靠辨认，`text` 可以为空字符串。

### 素材级人声质量

`speech_quality` 使用固定枚举：

- `none`：没有检测到人类说话声。
- `unclear`：检测到人声，但所有片段都难以基本听懂；片段的 `text` 可以为空或仅包含模型能辨认的部分。
- `clear`：至少存在一段基本能理解主要表达、值得在精剪时人工试听的人声。

该字段评价的是素材是否包含值得试听的人声，不评价录音是否达到专业制作质量，也不承诺转写逐字准确。

## 数据契约

### `Asset` 新增字段

```json
{
  "speech_quality": "clear",
  "transcript_path": "cache/transcripts/asset_123.json"
}
```

- `speech_quality: Optional[SpeechQuality]`：`none` / `unclear` / `clear`；`null` 表示尚未成功完成音频分析或本次结果不可用。
- `transcript_path` 复用现有字段，保存相对项目目录的路径。
- 无音轨视频直接写 `speech_quality="none"`，`transcript_path=null`，不生成空转写文件。
- 有音轨但分析失败时保持 `speech_quality=null`，不得写成 `none`。

### 独立转写文件

路径：

```text
projects/<slug>/cache/transcripts/<asset_id>.json
```

内容：

```json
{
  "speech_quality": "clear",
  "speech_segments": [
    {
      "start_sec": 12.4,
      "end_sec": 18.9,
      "text": "我们现在到达的是山顶观景台"
    }
  ]
}
```

片段字段：

- `start_sec: float`：片段在原视频中的开始秒数。
- `end_sec: float`：片段在原视频中的结束秒数。
- `text: str`：原语言粗转写；确认有人声但无法辨认内容时允许为空字符串。

`cut_index.json` 不内嵌全部转写文本，避免主索引随长视频快速膨胀。

### Schema 与运行信息

- `ModelConfig.transcription_model` 替换为 `ModelConfig.audio_analysis_model`。
- `AnalysisInfo.transcription_model` 替换为 `AnalysisInfo.audio_analysis_model`，记录本次实际使用的音频分析模型。
- `cut_index.json` schema minor version 从 `0.3` 升为 `0.4`。
- 读取旧 `0.3` 索引时，缺失的 `speech_quality` 和 `audio_analysis_model` 按 `null` 处理，已有素材和画面分析字段保持不变。
- 软件配置中若仍出现旧的 `transcription_model`，启动时给出明确迁移错误并提示改名，不把专用转写模型静默当成通用音频分析模型。
- 本期只分析 `Asset.type="video"` 的音轨；独立 `Asset.type="audio"` 素材保持现有行为，不纳入本设计。

## 配置

软件级配置调整为：

```yaml
model_config:
  provider: "openai_compatible"
  base_url: "https://open.cherryin.ai/v1"
  api_key_env: "TRIPCLIPPER_MODEL_API_KEY"
  vision_model: "google/gemini-3.5-flash"
  text_model: "google/gemini-3.5-flash"
  audio_analysis_model: "google/gemini-3.5-flash"
```

不新增 `audio_analysis_enabled`。如果 `audio_analysis_model` 缺失，`sample` / `full` 应在启动前给出明确配置错误，而不是静默跳过音频分析。

## 架构与组件边界

### 1. `AudioExtractor`

职责：

- 接收视频路径和 `asset_id`。
- 使用 `ffmpeg` 提取 `16 kHz`、单声道、16-bit PCM WAV。
- 按原视频时间轴从 `0` 秒开始，每块最多 300 秒，无重叠切块。
- 输出带原视频起点偏移的 `AudioChunk` 列表。
- 把中间文件放在 `cache/audio/<asset_id>/`，不写入 `cut_index.json`。
- 非 `--force` 运行可复用与源视频指纹匹配的有效缓存；`--force` 重新提取。

接口概念：

```python
AudioChunk(
    path: Path,
    start_offset_sec: float,
    duration_sec: float,
)
```

扫描阶段仍只通过 `ffprobe` 写入 `metadata.has_audio`。音频提取在 `sample` / `full` 真正选中素材后按需执行，避免 `sample` 为未抽中的视频提前生成音频缓存。

### 2. `AudioAnalysisProvider`

职责：

- 使用 `audio_analysis_model`，不复用视觉 `Provider` 的 prompt 和结果模型。
- 调用当前 OpenAI-compatible `POST /chat/completions`。
- 按 Gemini OpenAI compatibility 的 `input_audio` 格式发送 base64 WAV。
- 每个 `AudioChunk` 一次请求。
- 要求模型只返回单一 JSON 对象，字段为 `speech_quality` 和 `speech_segments`。
- 提示模型使用原语言转写、不翻译、不分析环境音、不生成摘要。

第一版使用较低 reasoning effort（若代理支持），因为任务是音频定位与粗转写，不需要复杂推理。代理不支持该参数时应去掉参数重试一次，不能因此判定素材音频失败。

### 3. `AudioAnalysisParser`

职责：

- 校验模型返回的 JSON 结构和枚举。
- 校验片段局部时间满足 `0 <= start_sec < end_sec <= chunk.duration_sec`。
- 将局部时间加上 `chunk.start_offset_sec`，得到原视频时间。
- 丢弃单个非法片段并记录非阻断 warning，保留合法兄弟片段。
- 按 `start_sec` 排序。
- 若同一块内片段重叠，合并为覆盖两者的最小连续区间；按时间顺序拼接非空文本。
- 如果模型返回 `speech_quality="none"` 但仍给出合法片段，纠正该块为 `unclear` 并记录 warning。
- 如果模型返回 `clear` 但所有片段均为空，降为 `unclear` 并记录 warning。

### 4. `TranscriptStore`

职责：

- 合并所有成功块的全局片段并写入临时文件。
- 先完整校验临时文件，再原子替换正式转写文件。
- 成功后才更新 `Asset.transcript_path` 和 `Asset.speech_quality`。
- 全部块失败或只有部分块成功的重跑，不得覆盖上一次完整有效的转写文件。

### 5. `Analyzer` 编排

对 `sample` / `full` 中的每个视频素材：

1. 执行原有画面分析。
2. 若 `metadata.has_audio` 为假，写 `speech_quality="none"` 并结束音频子步骤。
3. 若有音轨，按需提取音频块。
4. 逐块调用 `AudioAnalysisProvider`，每块独立重试和记录结果。
5. 聚合成功块，写入转写文件和素材级字段。
6. 音频失败写入 `Asset.failures`、`CutIndex.failures` 和结构化日志，但不回退已成功的画面分析字段。

已有画面结果但 `speech_quality=null` 的有音轨素材仍属于音频待处理素材。非 `--force` 的 `full` 必须允许只补跑缺失的音频分析，而不重复调用视觉模型。`--force` 同时重跑画面与音频；已有完整有效转写时，只有本次所有音频块均成功且新转写文件通过本地校验后才替换旧结果。

## 数据流

```text
scan
  └─ ffprobe: metadata.has_audio

sample / full（对本次选中素材）
  ├─ 原有视觉分析
  └─ 音频子步骤
      ├─ ffmpeg 提取 16 kHz mono WAV
      ├─ 固定 300 秒无重叠切块
      ├─ Gemini 3.5 Flash 逐块分析
      ├─ 校验局部片段
      ├─ 加回块起点偏移
      ├─ 聚合 speech_quality
      ├─ 原子写 transcript JSON
      └─ 更新 Asset.speech_quality / transcript_path
```

## 分块与聚合规则

### 分块

- 每块最长 300 秒。
- 块之间无重叠。
- 最后一块允许短于 300 秒。
- 分块覆盖完整音频时间轴，不丢弃块边界附近的音频。
- 句子被边界切开时允许形成两个粗转写片段；第一版不跨块拼句。

5 分钟的 16 kHz 单声道 16-bit PCM WAV 约 9.6 MB，base64 后约 12.8 MB，为请求 JSON 和 prompt 留出空间，低于 Gemini 文档所述的 20 MB 内联请求量级。

### 素材级 `speech_quality`

所有块成功时：

1. 任意块为 `clear`，素材为 `clear`。
2. 否则任意块存在人声片段或为 `unclear`，素材为 `unclear`。
3. 所有块均为 `none` 且没有片段，素材为 `none`。

部分块失败时：

1. 成功块中存在 `clear`，素材可标为 `clear`，同时记录“音频分析不完整”warning。
2. 否则成功块中存在人声，素材可标为 `unclear`，同时记录 warning。
3. 成功块均无人声但仍有失败块，素材保持 `null`，因为不能断言失败块中没有人声。
4. 所有块失败，素材保持 `null`，不生成或覆盖正式转写文件。

部分成功且已检测到人声时：

- 如果不存在旧的有效转写，可以写入包含成功块片段的转写文件；warning 必须明确结果未覆盖完整视频。
- 如果已经存在旧的完整有效转写，本次部分结果只进入日志和 warning，不替换旧文件、旧 `transcript_path` 或旧 `speech_quality`。

## 错误处理

### 无音轨

- 不调用 `ffmpeg` 音频提取和 Gemini。
- 写 `speech_quality="none"`。
- `transcript_path=null`。
- 不记失败。

### 音频提取失败

- `speech_quality` 保持 `null` 或保留上一次有效值。
- 不写新的正式转写文件。
- 记录素材级与项目级非阻断失败。
- 画面分析可以继续成功，`Asset.analysis_status` 不因音频子步骤单独失败而改为 `analysis_failed`。

### 模型请求失败

- 沿用瞬时错误重试策略；块级失败不阻止其他块继续。
- 聚合时按“部分块失败”规则处理。
- 错误信息继续经过 secret redaction，不记录音频 base64、完整 prompt 或完整模型原始响应。

### 模型结果非法

- 顶层 JSON 或必需字段完全不可解析：该块失败。
- 单个片段非法：只丢弃该片段并记录 warning。
- 所有片段均被丢弃且无法建立可信分类：该块失败，不把它当作 `none`。

### 增量落盘与崩溃恢复

- 每个素材的正式转写文件采用临时文件加原子替换。
- `cut_index.json` 只在转写文件成功落盘后引用它。
- 进程崩溃后，临时文件不视为有效结果。
- 下次运行对 `has_audio=true` 且 `speech_quality=null` 的素材自动补跑音频子步骤。

## 输出与筛选

`speech_quality` 是下游筛选的单一事实源。第一版至少要求：

- `cut_index.json` 持久化该字段。
- `assets.csv` 导出该字段，便于按 `clear` 过滤。
- `review.html` 展示 `speech_quality`，并展示转写片段的时间范围和文本。
- review 中 `transcript_path` 缺失或文件不可读时显示明确降级提示，不阻断其他素材展示。

Eagle 标签映射和在 Eagle 内点击时间段定位不属于本设计的必交付范围；它们可在数据契约稳定后作为下游映射改动单独实现。

## 测试策略

### 单元测试

- `SpeechQuality` 枚举与新增模型字段序列化。
- 片段时间格式、顺序和视频时长边界校验。
- 单条非法片段被丢弃，合法兄弟片段保留。
- 重叠片段合并和文本拼接。
- `none` 与非空片段矛盾时纠正为 `unclear`。
- `clear` 但所有文本为空时降为 `unclear`。
- 局部时间加分块偏移得到正确的全局时间。
- 全成功、部分失败、全部失败下的素材级质量聚合。

### 组件测试

- `ffmpeg` 真实提取 16 kHz 单声道 WAV。
- 小于、等于和大于 300 秒的输入得到正确块数量、持续时间和偏移。
- 无音轨视频不调用 AudioAnalysisProvider。
- TranscriptStore 原子替换，失败时保留旧文件。
- 已有视觉结果但缺少音频结果时只补跑音频。
- `--force` 重跑失败时不覆盖旧的有效转写。
- 旧 schema `0.3` 索引可加载，新增字段默认 `null`；再次写出后升级为 `0.4`。

### Provider 合约测试

- 请求使用配置的 `audio_analysis_model`。
- 请求包含 `input_audio` 和 base64 WAV，不包含图片。
- prompt 明确要求原语言、不翻译、只识别人类说话声。
- JSON 响应能够通过本地 parser。
- CherryIn 不接受 `reasoning_effort` 时，去掉该参数重试一次。
- 日志不包含 API key、Authorization、音频 base64、完整 prompt 或完整原始响应。

### 真实素材验收

使用仓库中用户提供的真实视频覆盖：

- 无音轨或无人声。
- 清晰单人口播。
- 能确认有人说话但难以听清。
- 中文、英文和中英混说。
- 人声跨越 5 分钟分块边界。
- 至少一个超过 5 分钟的视频。

人工试听并核对：

- `speech_quality` 是否足以筛出值得精听的素材。
- 人声片段是否覆盖实际说话区间。
- 时间偏移在切块后是否仍指向原视频正确位置。
- 粗转写是否足以帮助辨认片段内容，而不要求逐字一致。

## 验收标准

1. `sample` / `full` 对所有本次应处理且带音轨的视频执行音频分析，无关闭开关。
2. 每个成功分析的视频得到 `speech_quality`；有人声时得到带全局秒数和原语言文本的 `speech_segments`。
3. 超过 5 分钟的音频被无重叠切块，合并后的时间仍相对于原视频。
4. 无音轨视频不调用模型并稳定得到 `speech_quality="none"`。
5. 音频失败不破坏画面分析结果，也不会被误记为无人声。
6. 完整转写文本只存在独立 JSON 中，`cut_index.json` 通过路径引用。
7. 已有画面结果但缺少音频结果的素材可以仅补跑音频分析。
8. `assets.csv` 和 `review.html` 能消费 `speech_quality`，用户可以筛选或识别 `clear` 素材。

## 官方能力依据

- Gemini 3.5 Flash 支持 Text、Image、Video、Audio 和 PDF 输入，以及文本和结构化输出：<https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash>
- Gemini 的 OpenAI compatibility 文档给出了 `/chat/completions` 中使用 `input_audio` 发送 base64 WAV 的示例：<https://ai.google.dev/gemini-api/docs/openai>
- Gemini 音频理解文档说明其支持转写、时间戳、自动处理非语音内容，以及大文件使用 Files API：<https://ai.google.dev/gemini-api/docs/audio>
