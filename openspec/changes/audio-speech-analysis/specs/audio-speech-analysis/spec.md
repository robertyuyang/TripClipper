## ADDED Requirements

### Requirement: 音频分析配置必须明确且完整
系统 SHALL 使用 `ModelConfig.audio_analysis_model` 执行视频音频分析，并在 `AnalysisInfo.audio_analysis_model` 中记录实际模型。字段缺失时，`sample` 和 `full` MUST 在分析前给出可执行的配置错误；软件配置中出现旧字段 `transcription_model` 时，MUST 明确提示改名。

#### Scenario: 已配置音频模型
- **WHEN** `sample` 或 `full` 启动时配置了 `audio_analysis_model: google/gemini-3.5-flash`
- **THEN** 系统使用该值发送音频请求，并把它记录在本次分析运行信息中

#### Scenario: 缺少音频模型
- **WHEN** `sample` 或 `full` 启动时没有配置 `audio_analysis_model`
- **THEN** 系统在任何视觉或音频模型请求前停止，并指出缺失的配置字段

#### Scenario: 出现旧配置字段
- **WHEN** 软件配置中包含 `transcription_model`
- **THEN** 系统拒绝该配置，并提示用户将其改名为 `audio_analysis_model`

### Requirement: 已选视频默认执行音频分析
系统 SHALL 把音频分析作为 `sample` 和 `full` 处理每个已选 `Asset.type="video"` 素材时不可关闭的默认步骤，并且 MUST NOT 把该流程应用于独立的 `Asset.type="audio"` 素材。

#### Scenario: 已选视频包含音轨
- **WHEN** `sample` 或 `full` 选中的视频满足 `metadata.has_audio=true`
- **THEN** 系统无需启用开关即可提取并分析其音频

#### Scenario: 视频没有音轨
- **WHEN** 已选视频满足 `metadata.has_audio=false`
- **THEN** 系统把 `speech_quality` 写为 `none`，保持 `transcript_path=null`，不创建转写文件，也不调用音频 Provider

#### Scenario: 存在独立音频素材
- **WHEN** `sample` 或 `full` 遇到 `Asset.type="audio"` 素材
- **THEN** 系统保持其原有行为，不执行本视频人声分析流程

### Requirement: 音频提取必须生成有界且对齐原时间轴的分块
系统 SHALL 使用 `ffmpeg` 从已选视频中提取 16 kHz、单声道、16-bit PCM WAV，并 SHALL 把完整音频时间轴切成最长 300 秒、互不重叠的分块。每个分块 MUST 提供原视频起点偏移和持续时间。

#### Scenario: 音频短于分块上限
- **WHEN** 提取后的音频短于 300 秒
- **THEN** 提取器返回一个从 0 秒开始、持续时间等于源音频时长的分块

#### Scenario: 音频超过分块上限
- **WHEN** 提取后的音频长于 300 秒
- **THEN** 提取器返回完整覆盖时间轴的连续无重叠分块，最后一块可以短于 300 秒

#### Scenario: 可以复用提取缓存
- **WHEN** 非 force 运行发现有效缓存，且缓存记录的源文件指纹与当前视频匹配
- **THEN** 系统复用已有分块

#### Scenario: 请求强制运行
- **WHEN** 分析使用 `--force`
- **THEN** 系统重新提取音频，不复用之前的提取缓存

### Requirement: 每个分块必须按原语言分析人类口语
系统 SHALL 为每个音频块分别向 OpenAI-compatible `/chat/completions` 发送请求，使用 `audio_analysis_model` 和包含 base64 WAV 的 `input_audio`。请求 MUST 要求只返回一个 JSON 对象，其中只包含人声分类和句子或连续发言级的人类口语片段；文本保持原语言，不翻译、不总结。

#### Scenario: 包含中英混说
- **WHEN** 分块中同时包含中文和英文口语
- **THEN** 返回的转写契约按实际语言保留内容，不执行翻译

#### Scenario: 只有非语言声音
- **WHEN** 分块只包含音乐、歌唱、笑声、哭声、欢呼或环境声，没有可辨认的口语表达
- **THEN** prompt 和解析规则不要求把这些声音生成成人声片段

#### Scenario: 代理不支持 reasoning effort
- **WHEN** 兼容端点明确因为不支持 `reasoning_effort` 而拒绝首次请求
- **THEN** Provider 去掉该参数额外重试一次，再决定该块是否失败

### Requirement: 分块响应必须经过校验和规范化
系统 SHALL 校验顶层 JSON、`speech_quality` 枚举和每个人声片段。片段 MUST 满足 `0 <= start_sec < end_sec <= chunk.duration_sec`；Parser SHALL 丢弃非法片段并记录非阻断 warning，同时保留合法兄弟片段、加上分块起点偏移、按原视频开始时间排序，并合并同一块内的重叠片段。

#### Scenario: 单个片段非法
- **WHEN** 响应同时包含一个越界片段和一个合法片段
- **THEN** Parser 只丢弃非法片段，记录 warning，并保留已转换为原视频时间的合法片段

#### Scenario: 同一块内片段重叠
- **WHEN** 两个合法人声片段在时间上重叠
- **THEN** Parser 用覆盖两者的最小连续区间替换它们，并按时间顺序拼接非空文本

#### Scenario: 分类与合法人声矛盾
- **WHEN** 分块返回 `speech_quality=none`，同时包含合法人声片段
- **THEN** Parser 把该块分类纠正为 `unclear` 并记录 warning

#### Scenario: clear 但没有可辨认文本
- **WHEN** 分块返回 `speech_quality=clear`，但保留片段的文本全部为空
- **THEN** Parser 把该块分类降为 `unclear` 并记录 warning

#### Scenario: 无法保留可信分类
- **WHEN** 顶层响应不可解析，或校验后无法建立可信分类
- **THEN** 系统把该块标记为失败，而不是把它分类为 `none`

### Requirement: 素材级人声质量必须保守聚合
系统 SHALL 在任意成功块为 `clear` 时把素材分类为 `clear`；否则在任意成功块为 `unclear` 或包含人声片段时分类为 `unclear`；只有所有块均成功且一致无人声时才分类为 `none`。

#### Scenario: 所有块均成功且无人声
- **WHEN** 每个分块都成功返回 `none`，且没有合法人声片段
- **THEN** 素材得到 `speech_quality=none`

#### Scenario: 任意成功块包含清晰人声
- **WHEN** 至少一个成功块包含基本可理解的清晰人声
- **THEN** 素材得到 `speech_quality=clear`

#### Scenario: 有人声但没有清晰片段
- **WHEN** 没有成功块为 `clear`，但至少一个成功块为 `unclear` 或包含人声片段
- **THEN** 素材得到 `speech_quality=unclear`

### Requirement: 不完整分析不得误判为无人声
系统 SHALL 独立处理和重试每个分块。任意块失败时，系统 MUST 记录分析不完整；可以根据成功块的正向证据保留 `clear` 或 `unclear`，但成功块均无人声而仍有失败块时，MUST 保持 `speech_quality=null`。

#### Scenario: 部分分析检测到人声
- **WHEN** 一个或多个分块失败，而成功块能够确认清晰或不清晰人声
- **THEN** 素材获得基于现有证据的分类，并记录音频分析不完整 warning

#### Scenario: 部分分析未检测到人声
- **WHEN** 一个或多个分块失败，所有成功块均报告无人声
- **THEN** 素材保持 `speech_quality=null`，因为失败块中仍可能存在人声

#### Scenario: 所有分块失败
- **WHEN** 所有分块均失败
- **THEN** 素材保持 `speech_quality=null`，系统不创建或替换正式转写文件

### Requirement: 转写必须原子持久化并通过路径独立引用
系统 SHALL 把成功的转写数据保存到 `projects/<slug>/cache/transcripts/<asset_id>.json`，内容包含 `speech_quality` 和有序的 `{start_sec, end_sec, text}` 片段。系统 SHALL 先完整校验临时文件并原子替换正式文件，再更新素材的相对 `transcript_path` 和 `speech_quality`；`cut_index.json` MUST NOT 内嵌完整转写文本。

#### Scenario: 完整转写成功
- **WHEN** 所有分块均成功，且候选转写通过校验
- **THEN** 系统原子发布转写文件，随后才更新素材引用和分类

#### Scenario: 候选转写非法
- **WHEN** 临时转写文件未通过本地校验，或原子发布失败
- **THEN** 系统保持已有正式文件和素材字段不变

#### Scenario: 首次产生部分结果
- **WHEN** 部分分块失败、成功块检测到人声，且不存在旧的有效转写
- **THEN** 系统可以发布成功块片段，同时记录结果未覆盖完整视频

#### Scenario: 部分结果已有完整前序版本
- **WHEN** 部分分块失败，且已经存在完整有效转写
- **THEN** 系统保持原转写、`transcript_path` 和 `speech_quality` 不变

### Requirement: 音频分析必须支持增量与 force 重跑
系统 SHALL 把 `metadata.has_audio=true` 且 `speech_quality=null` 的视频视为音频待处理素材，即使画面分析已经成功。非 force 运行 MUST 能够只执行缺失的音频子步骤；`--force` SHALL 重跑画面和音频，并在新完整结果通过校验前保护已有转写。

#### Scenario: 画面结果存在但音频结果缺失
- **WHEN** 非 force 的 `full` 遇到画面已分析、包含音轨且 `speech_quality=null` 的视频
- **THEN** 系统执行音频分析，不重复调用视觉模型

#### Scenario: 强制替换成功
- **WHEN** `--force` 运行的所有音频块均成功，且新转写通过校验
- **THEN** 系统替换已有转写并更新素材字段

#### Scenario: 强制替换不完整
- **WHEN** `--force` 运行出现音频块失败或转写非法，且已有有效转写
- **THEN** 系统保持之前的转写和音频分析素材字段

### Requirement: 音频失败必须与画面结果隔离
系统 SHALL 把音频提取、请求和解析失败记录到 `Asset.failures`、`CutIndex.failures` 和结构化日志中，同时不得删除画面字段，也不得把已成功完成画面分析的素材改为 `analysis_failed`。日志 MUST 隐去 API key 和 Authorization，并且 MUST 省略音频 base64、完整 prompt 和完整原始响应。

#### Scenario: 画面成功后音频提取失败
- **WHEN** 画面分析成功，而音频提取失败
- **THEN** 画面结果保持可用，音频结果保持 null 或保留上一次有效值，并记录非阻断音频失败

#### Scenario: 模型请求包含敏感载荷
- **WHEN** 音频模型请求失败
- **THEN** 诊断输出不包含凭证、音频编码、完整 prompt 或完整原始响应

### Requirement: cut index 必须向后兼容读取
系统 SHALL 写出 schema version `0.4` 的 `cut_index.json`，其中包含可选的 `Asset.speech_quality`、已有的可选 `Asset.transcript_path` 和可选的 `AnalysisInfo.audio_analysis_model`。系统 MUST 能读取缺少新字段的 `0.3` 索引，把这些字段按 null 处理，并保留已有素材和画面分析数据。

#### Scenario: 读取旧索引
- **WHEN** 系统读取不含音频分析字段的有效 `0.3` 索引
- **THEN** 系统把新增字段默认成 null，且不改变已有素材数据

#### Scenario: 再次保存旧索引
- **WHEN** 新版本软件写出之前加载的 `0.3` 索引
- **THEN** 输出使用 schema version `0.4`

### Requirement: 导出和 review 必须能够消费人声分析结果
系统 SHALL 在 `assets.csv` 中包含 `speech_quality`。`review.html` SHALL 展示每个素材的人声质量，并在转写可用时展示片段时间范围和文本；引用的转写缺失或不可读时，MUST 显示明确的局部降级提示，同时继续渲染其他素材。

#### Scenario: 导出清晰人声
- **WHEN** 素材满足 `speech_quality=clear`
- **THEN** 对应 CSV 行和 review 条目都展示 `clear`，使用户能够识别值得试听的素材

#### Scenario: 转写文件可用
- **WHEN** `review.html` 渲染的素材引用了有效转写
- **THEN** 页面展示人声片段的原视频时间范围和原语言文本

#### Scenario: 转写引用损坏
- **WHEN** 生成 review 时发现 `transcript_path` 缺失、不可读或内容非法
- **THEN** 页面为该素材显示降级提示，并继续渲染其他素材

### Requirement: Eagle 必须展示并可筛选人声分析结果
系统 SHALL 为非 null 的 `speech_quality` 写入 `tc:speech_quality:<value>` Eagle 标签。系统 SHALL 在 Eagle 描述中新增“语音识别”章节：有效转写按原视频时间范围和原语言文本逐段展示，`none` 明确显示未检测到人声，转写引用缺失、不可读或内容非法时显示局部降级提示。系统 MUST NOT 把任意转写文本写入 Eagle 标签，且单个素材的转写读取失败 MUST NOT 中断其余素材同步。

#### Scenario: 同步清晰人声素材
- **WHEN** 素材满足 `speech_quality=clear` 且引用有效转写
- **THEN** Eagle 标签包含 `tc:speech_quality:clear`，描述的“语音识别”章节按原视频时间范围展示所有原语言片段

#### Scenario: 同步无人声素材
- **WHEN** 素材满足 `speech_quality=none`
- **THEN** Eagle 标签包含 `tc:speech_quality:none`，描述的“语音识别”章节显示“未检测到人声”

#### Scenario: Eagle 转写引用损坏
- **WHEN** 素材已有非 null 人声质量，但同步时发现转写引用缺失、不可读或内容非法
- **THEN** Eagle 描述为该素材显示“转写文件不可用”，同步继续处理其他素材

#### Scenario: 人声分析尚未执行
- **WHEN** 素材满足 `speech_quality=null`
- **THEN** Eagle 不写人声质量标签，也不写“语音识别”章节
