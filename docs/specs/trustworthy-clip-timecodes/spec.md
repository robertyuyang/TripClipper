# Trustworthy Clip Timecodes Spec

> 状态：**待用户审**。本文件为 M3 完成后兑现 PRD §2「禁止伪造分析结果」承诺的增量改动。
> 覆盖：PRD FR-3 / FR-4 中 segments 时间码不可信的修复；TD 6 中 Stage 2 多模态消息的时间戳上下文注入。
> 依赖：M0 数据契约（已完成）、M2 本地素材扫描（已完成）、M3 真实大模型分析（已完成）。
> 不在范围：M4 雷同分组（不消费时间码精度）、M5 CSV/MD 导出、M6 Eagle、M7 启动页、转写 / whisper、视频流多模态模型升级（见 [ADR-003](../../adr/ADR-003-frame-timestamp-annotation.md) §替代方案）。
> 关联决策：[ADR-003 M3 视频 segments 时间码靠"M2 自适应抽帧+写时间戳 + M3 prompt 时间标注 + 严格校验"落地](../../adr/ADR-003-frame-timestamp-annotation.md)。

## Why

M3 让视觉模型在一次调用里顺手产出 `Asset.segments`（高光片段，每段含 `in_`/`out` 时间码），但模型只看到 3 张匿名关键帧 base64 图，**不知道每张图对应整段视频的哪个时间点**——目前的 `in`/`out` 是凭空猜的。三个具体证据：

- [scan.py L294-L342](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/scan.py#L294-L342) 抽帧时计算了时间戳但**算完即扔**，时间戳没有写入 `cut_index.json`。
- [provider.py L358-L399](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/provider.py#L358-L399) `_build_user_content` 把缩略图 + 关键帧 base64 直接拼成 `image_url` content block，**没有文本时间标注**。
- [provider.py L473-L509](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/provider.py#L473-L509) `_coerce_segments` 只做字段宽容校验，**不验证时间码合法性**——格式错、`out<in`、超 `duration` 都原样落盘。

后果：`cut_index.json.assets[*].segments[*].in_`/`out` 是不可信字段；下游 M4/M5/M6 任何消费时间码做对照/导出/Eagle 同步都会拿到错数据；且无可观测信号告诉用户"这条数据有问题"。这违反 PRD §2「禁止伪造分析结果」与 §9.2「分析必须由真实模型完成且结果可信」。

光修一处（譬如只加严格校验）不够：

- 只加严格校验，模型还是没视觉证据，结果是 segments 大面积被丢弃，用户拿到空 `clip_suggestions`，不解决"模型本应能识别但缺上下文"的根本问题。
- 只加时间标注、不严格校验，模型可能仍输出越界值（如 `01:30:00` 但素材只有 4 秒），下游照样污染。
- 只在 M2 写时间戳、M3 不消费，是无效改动。

所以三件事必须一起做：M2 抽帧自适应化 + 写时间戳，M3 prompt 注入时间标注，M3 parser 严格校验。借这次改动顺手把 `Segment` 这个用词不达意的命名换掉（详见 [ADR-003 §决策 第 5 条](../../adr/ADR-003-frame-timestamp-annotation.md)）。

## What Changes

### 1. M2 抽帧自适应化 + 时间戳写入

- [scan.py L74-L75](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/scan.py#L74-L75) 的 `_MAX_FRAMES = 3` 改为按 `duration` 自适应：`frame_count = max(3, min(12, round(duration / 5)))`；`duration` 不可用（`ffprobe` 失败 / 非视频）时退化为 3 帧。
- `_run_ffmpeg_frames()`（[scan.py L294-L342](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/scan.py#L294-L342)）继续在均匀分布时间点抽帧（`timestamps = [duration * (i + 1) / (count + 1) for i in range(count)]`），但**时间戳与路径并列返回**而不是丢弃。
- [scan.py L467](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/scan.py#L467) 处的 `asset.frame_paths = [str(p) for p in frames]` 改成同时写 `asset.frame_timestamps = [...]`，两者索引一一对应、长度相等。

### 2. M0 数据契约：Asset.frame_timestamps + Segment 重命名 + SCHEMA 升版

- [models.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/models.py) 的 `Asset`（第 134 行附近）新增并列字段：

  ```python
  frame_paths: list[str] = Field(default_factory=list)
  frame_timestamps: list[float] = Field(default_factory=list)
  ```

- [models.py L101-L115](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/models.py#L101-L115) 的 `Segment` 类名改为 `ClipSuggestion`；`Asset.segments` 字段名改为 `Asset.clip_suggestions`；保留 9 个字段：`in_` / `out` / `role` / `reason` / `audio_strategy` / `subject_type` / `shot_scale` / `rating` / `tags`（4 个 grilling Q4 决定保留的字段需要在新 prompt 中产出，详见 [ADR-003 §决策 第 6 条](../../adr/ADR-003-frame-timestamp-annotation.md)）。
- `SCHEMA_VERSION` 由 `"0.2"` 升至 `"0.3"`，BREAKING；不提供静默迁移，已有 0.2 的 `cut_index.json` 在 0.3 代码上读直接报错（沿用 M0 spec 的"不兼容时报清晰错误"规则）。
- 用户迁移路径：执行 `tripclipper analyze <slug> --stage full --force` 重跑（详见 [ADR-003 §后果·负面 第 1 条](../../adr/ADR-003-frame-timestamp-annotation.md)）。

### 3. M3 prompt 注入时间标注

- [provider.py `_build_user_content`](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/provider.py#L358-L399) 在每张关键帧 `image_url` content block **之前**插一个 text content block，文案模板：`"第 {i} 张关键帧 @ {MM:SS.S}"`（`i` 从 1 起算；`MM:SS.S` 由 `asset.frame_timestamps[i-1]` 用秒级精度格式化，例：`第 3 张关键帧 @ 02:30.5`）。
- 缩略图（asset.thumbnail_path）前同样插一行 `"缩略图：素材封面"` text block（无时间戳，因为缩略图不在 `frame_timestamps` 索引内）。
- system prompt 增加约束段：「输出的 `in` / `out` 必须落在 `[0, duration]` 区间内（`duration` = {asset.metadata.duration} 秒），且应贴近上述时间标注帧的视觉证据；如视觉证据不足以确定高光段则不输出该 clip_suggestion」。
- system prompt 中 `segments` 字段名改为 `clip_suggestions`；新增 4 个段级字段（`subject_type` / `shot_scale` / `rating` / `tags`）的输出规约，枚举值与 asset 级一致。
- `_MAX_FRAMES_FOR_PROMPT = 3`（[provider.py L56](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/provider.py#L56)）废弃；改为消费 `len(asset.frame_paths)`（M2 已自适应封顶 12）。

### 4. M3 严格时间码校验

- `_coerce_segments`（[provider.py L473-L509](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/provider.py#L473-L509)）改名为 `_coerce_clip_suggestions`，对每段强制三条校验：
  - **格式**：`in` / `out` 必须匹配 `^\d{1,2}:\d{2}:\d{2}(\.\d+)?$` 或可解析为非负浮点秒数；解析失败 → 整段丢弃。
  - **顺序**：`out_seconds > in_seconds` → 不满足则整段丢弃。
  - **边界**：`0 <= in_seconds < out_seconds <= duration`（`asset.metadata.duration` 缺失时仅校验前两条）→ 不满足则整段丢弃。
- 整段丢弃**只丢弃该段**，其他通过校验的 clip_suggestions 正常落盘；主字段 `summary` / `tags` / `rating` 等不受影响；`analysis_status` 仍转 `analyzed`。
- 丢弃事件写入素材级 warning（不是 failure）：`stage="analyze"`、`reason="clip_suggestion 时间码校验失败：{原始值}"`、`blocking=False`。

### 5. 不变项（明确锁定）

- M0 其他 7 个枚举（`asset.type` / `analysis_status` / `subject_type` / `people_presence` / `shot_scale` / `shot_function` / `similar_selection` / `edit_candidate_status`）**不变**。
- M2 媒体探测、主流选择、分数帧率求值、ffprobe / ffmpeg 降级、单文件失败隔离、确定性遍历、合并保活策略**不变**。
- M3 测试纪律（零 mock、缺 key 即失败、5 个真实视频 fixture）**不变**。
- M3 其他 Q1-Q21、Q23-Q25 决策**不变**（仅 Q22 的"segments 草稿"被本 spec MODIFIED）。
- M3 重试策略、并发模型、增量落盘、日志脱敏、`run` 编排**不变**。
- M4 / M5-early / wire-m4-into-review-html 的字段消费面：本 spec 的命名重构（`segments` → `clip_suggestions`）需要同步改这些模块对该字段的引用，但**不改变其语义**（M5-early HTML 列、M4 内部参考都按字段重命名做无损迁移）。

## Impact

- 影响的能力：
  - **M3 输出**：`clip_suggestions` 字段从"不可信"变为"严格校验后落盘"，下游可信引用。
  - **M2 输出**：`Asset.frame_timestamps` 是新字段，老 cut_index.json 不含；从 0.2 升 0.3 后必须 `--force` 重跑。
  - **M4 / M5-early / wire-m4-into-review-html**：消费 `Asset.segments` 的代码需要改名为 `Asset.clip_suggestions`，语义不变。
- 影响的代码：
  - [src/tripclipper/models.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/models.py)：`Segment` → `ClipSuggestion`、`Asset.segments` → `Asset.clip_suggestions`、`Asset.frame_timestamps` 新增、`SCHEMA_VERSION` 升 `"0.3"`。
  - [src/tripclipper/scan.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/scan.py)：`_MAX_FRAMES` 删除，`_compute_frame_count(duration)` 新增；`_run_ffmpeg_frames` 改为返回 `list[tuple[Path, float]]`；`scan_project` 把时间戳写回 `asset.frame_timestamps`。
  - [src/tripclipper/provider.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/provider.py)：`_build_user_content` 增加 text block 注入；`_SYSTEM_PROMPT` 增加时间码约束段 + 字段重命名 + 4 个新字段输出规约；`_coerce_segments` 改名为 `_coerce_clip_suggestions` + 严格校验；`_MAX_FRAMES_FOR_PROMPT` 删除。
  - [src/tripclipper/exporter.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/exporter.py)（M5-early）：HTML 渲染中 `asset.segments` 引用改 `asset.clip_suggestions`。
  - [src/tripclipper/clusterer.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/clusterer.py)、[arbiter.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/arbiter.py)、[cluster_runner.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/cluster_runner.py)（M4）：若引用 `segments` 字段，同步重命名。
  - [tests/test_models.py](file:///Users/bytedance/Documents/TripClipper_Trae/tests/test_models.py)、[tests/test_scan.py](file:///Users/bytedance/Documents/TripClipper_Trae/tests/test_scan.py)（不在 git status 中，已完成 spec 阶段不动）、[tests/test_provider.py](file:///Users/bytedance/Documents/TripClipper_Trae/tests/test_provider.py)、[tests/test_integration_m3.py](file:///Users/bytedance/Documents/TripClipper_Trae/tests/test_integration_m3.py)：补充时间标注与严格校验测试；现有断言中 `segments` 改 `clip_suggestions`。
  - [docs/specs/README.md](file:///Users/bytedance/Documents/TripClipper_Trae/docs/specs/README.md)：模块索引追加本 change 行。
- **BREAKING**：是。`SCHEMA_VERSION` 0.2 → 0.3、字段重命名；用户必须 `--force` 重跑 analyze。

## 关键设计决策

完整决策推导见 [ADR-003](../../adr/ADR-003-frame-timestamp-annotation.md)。本节只列最关键 6 条，便于实现时快速对照：

- **Q1 抽帧数**：`max(3, min(12, round(duration / 5)))`；duration 不可用退化为 3 帧。
- **Q5 时间戳形态**：并列字段 `Asset.frame_timestamps: list[float]`，与 `frame_paths` 索引对齐。
- **Q2 时间戳如何喂模型**：每张图前插独立 text content block `"第 N 张关键帧 @ MM:SS.S"`。
- **Q3 严格校验**：格式可解析 + `out > in` + 落在 `[0, duration]`；不满足整段丢弃，写素材级 warning。
- **Q6 命名**：`Segment` → `ClipSuggestion` / `segments` → `clip_suggestions`；`SCHEMA_VERSION` 0.2 → 0.3（BREAKING）。
- **Q4 ClipSuggestion 4 字段**：保留 `subject_type` / `shot_scale` / `rating` / `tags`，让 prompt 同时产出（赋予 segment 级语义，区别于 asset 级统计）。

## ADDED Requirements

### Requirement: 抽帧数随素材时长自适应

系统 SHALL 在 M2 视频扫描时按 `frame_count = max(3, min(12, round(duration / 5)))` 决定关键帧数量；`duration` 不可用（`ffprobe` 失败或非视频）时退化为 3 帧。

#### Scenario: 60 秒视频抽 12 帧
- **WHEN** 扫描一个 `duration ≈ 60s` 的视频（如 `NO20250612-114146-064576F.mp4`）
- **THEN** `asset.frame_paths` 含 12 条路径，`asset.frame_timestamps` 含 12 个浮点数，索引对齐，时间戳均匀分布在 (0, 60) 区间内

#### Scenario: 4.3 秒视频抽 3 帧（下限保护）
- **WHEN** 扫描一个 `duration ≈ 4.3s` 的视频（如 `DJI_20260612134026_0001_D.MP4`）
- **THEN** `frame_count = max(3, min(12, 1)) = 3`，`asset.frame_paths` 含 3 条路径，`asset.frame_timestamps` 含 3 个浮点数

#### Scenario: 100 秒视频抽 12 帧（上限保护）
- **WHEN** 扫描一个 `duration ≈ 100s` 的视频
- **THEN** `frame_count = max(3, min(12, 20)) = 12`

#### Scenario: duration 不可用退化为 3 帧
- **WHEN** ffprobe 失败、`asset.metadata.duration` 缺省
- **THEN** 抽帧数为 3，`asset.frame_timestamps` 为空列表或长度与 `frame_paths` 匹配的 `[]`

### Requirement: 每帧时间戳写入 cut_index

系统 SHALL 在抽帧后把每帧时间戳（浮点秒数）写入 `Asset.frame_timestamps`，与 `Asset.frame_paths` 索引一一对应且长度相等。

#### Scenario: 时间戳与路径索引对齐
- **WHEN** 视频抽出 N 帧
- **THEN** `len(asset.frame_paths) == len(asset.frame_timestamps) == N`
- **AND** `asset.frame_timestamps[i]` 是 `asset.frame_paths[i]` 对应帧的视频时间（秒），单调递增

#### Scenario: 重复扫描时间戳稳定
- **WHEN** 同一视频两次扫描
- **THEN** `asset.frame_timestamps` 两次结果完全一致（计算公式确定性）

### Requirement: 模型多模态消息附带每帧时间标注

系统 SHALL 在 M3 构造 vision API 的 user content 时，对每张关键帧 `image_url` 之前插入一个 text content block，内容为 `"第 {i} 张关键帧 @ {MM:SS.S}"`（i 从 1 起，时间格式 `分:秒.十分位`）。

#### Scenario: 视频素材插入时间标注
- **WHEN** 分析一个 `frame_timestamps = [10.5, 20.0, 30.5]` 的视频素材
- **THEN** user content 中按顺序包含：`text("缩略图：素材封面")`、`image_url(thumbnail)`、`text("第 1 张关键帧 @ 00:10.5")`、`image_url(frame_1)`、`text("第 2 张关键帧 @ 00:20.0")`、`image_url(frame_2)`、`text("第 3 张关键帧 @ 00:30.5")`、`image_url(frame_3)`

#### Scenario: 图片素材不插入时间标注
- **WHEN** 分析一个 image 素材
- **THEN** user content 仅含 `text("图片素材")` + `image_url(image)`，不含 `MM:SS.S` 标注

#### Scenario: 音频素材无 image_url 也无标注
- **WHEN** 分析一个 audio 素材
- **THEN** user content 仅含元数据 text block，无任何 image_url 与时间标注

### Requirement: prompt 约束 clip_suggestion 时间码合法性

系统 SHALL 在 system prompt 中显式声明：`clip_suggestions[*].in` / `out` 必须落在 `[0, duration]` 区间内；视觉证据不足时该 clip_suggestion 不输出。

#### Scenario: prompt 含 duration 约束
- **WHEN** 构造一个 `duration = 60.0` 视频的 system prompt
- **THEN** prompt 文本包含 `duration = 60.0 秒` 字面（或等价语义）的约束段
- **AND** prompt 文本包含「视觉证据不足时该 clip_suggestion 不输出」的指引

### Requirement: 严格时间码校验，越界整段丢弃

系统 SHALL 在 `_coerce_clip_suggestions` 中对每段 ClipSuggestion 强制三条校验：① `in` / `out` 格式可解析为非负秒数；② `out_seconds > in_seconds`；③ `0 <= in_seconds < out_seconds <= duration`（duration 缺失时仅校验①②）。任一条不通过该段被丢弃。

#### Scenario: 格式非法整段丢弃
- **WHEN** 模型返回 `clip_suggestions = [{"in": "abc", "out": "00:05", ...}, {"in": "00:00", "out": "00:03", ...}]`
- **THEN** 第一段被丢弃，第二段保留，`asset.clip_suggestions` 长度为 1

#### Scenario: out <= in 整段丢弃
- **WHEN** 模型返回 `{"in": "00:10", "out": "00:05", ...}`
- **THEN** 该段被丢弃，`asset.clip_suggestions` 不含此条

#### Scenario: 越界整段丢弃
- **WHEN** 视频 `duration = 4.3`，模型返回 `{"in": "00:00", "out": "01:30", ...}`
- **THEN** 该段被丢弃

#### Scenario: 全部段被丢弃不影响主字段
- **WHEN** 所有 clip_suggestions 都校验失败
- **THEN** `asset.clip_suggestions = []`，但 `asset.summary` / `tags` / `rating` 等主字段正常落盘
- **AND** `asset.analysis_status = "analyzed"`（不降为 `analysis_failed`）
- **AND** `asset.warnings` 追加一条 `stage="analyze"` / `blocking=False` / `reason` 含被丢弃原始时间码值的 WarningItem

### Requirement: ClipSuggestion 4 个段级字段由 prompt 产出

系统 SHALL 在 system prompt 中要求模型为每段 ClipSuggestion 同时产出 `subject_type` / `shot_scale` / `rating` / `tags` 字段，枚举值与 asset 级一致。

#### Scenario: 段级 4 字段非空
- **WHEN** 模型成功产出一段 ClipSuggestion
- **THEN** 该段含 `subject_type ∈ M0 枚举` / `shot_scale ∈ M0 枚举` / `rating ∈ [1, 5]` / `tags: list[str]`

#### Scenario: 4 字段非法时降级
- **WHEN** 模型为某段产出 `subject_type = "外星人"`（非法枚举）
- **THEN** 沿用 M3 现有降级策略：该非法字段置为 `None` 或默认值（如 `"other"`），段本体仍保留（时间码校验通过的前提下）

## MODIFIED Requirements

### Requirement: 字段枚举口径单一来源（M0 spec §字段枚举）

引用 [M0 spec §字段枚举口径单一来源](../M0-data-contract/spec.md)。本 change 不改任何枚举取值，但下列**模型类**与**字段名**变更必须以本 spec 为准（M0 原文保持历史事实源不动）：

- `Segment` 类名 → `ClipSuggestion`
- `Asset.segments` 字段名 → `Asset.clip_suggestions`
- `Asset` 新增字段 `frame_timestamps: list[float] = Field(default_factory=list)`
- `SCHEMA_VERSION` 常量值 `"0.2"` → `"0.3"`

#### Scenario: 0.2 cut_index.json 在 0.3 代码上读取失败
- **WHEN** 用户用 0.3 代码读一个 `schema_version = "0.2"` 的 `cut_index.json`
- **THEN** 沿用 M0 spec 现有规则报清晰错误（"schema_version 不兼容"），不静默迁移
- **AND** 错误消息建议用户执行 `tripclipper analyze <slug> --stage full --force` 重跑

### Requirement: cut_index.json 数据模型与读写（M0 spec §cut_index.json 数据模型）

引用 [M0 spec §cut_index.json 数据模型与读写](../M0-data-contract/spec.md)。`schema_version` 由 `"0.2"` 升至 `"0.3"`；八个顶层键不变。

### Requirement: 媒体信息与浏览辅助信息（M2 spec §媒体信息与浏览辅助信息）

引用 [M2 spec §媒体信息与浏览辅助信息（能力可用时）](../M2-local-scan/spec.md)。本 change 增加：`ffmpeg` 抽帧时同时把每帧时间戳写入 `asset.frame_timestamps`；抽帧数从固定 3 改为自适应。

#### Scenario: 抽帧产物含路径与时间戳
- **WHEN** 视频抽帧成功
- **THEN** `asset.frame_paths` 与 `asset.frame_timestamps` 同步回填，索引对齐、长度相等

### Requirement: segments 草稿由 M3 顺手产出（M3 spec §Q22）

引用 [M3 spec §Q22 segments 草稿由 M3 顺手产出](../M3-real-llm-analysis/spec.md)。本 change 对 Q22 的修订：

- 字段名从 `Asset.segments` 改为 `Asset.clip_suggestions`。
- 每段保留 9 个字段：`in_` / `out` / `role` / `reason` / `audio_strategy` / `subject_type` / `shot_scale` / `rating` / `tags`（M3 spec 原 Q22 只产出 5 个，本 change 让 prompt 同时产出 4 个 grilling Q4 保留字段）。
- 时间码字段升级为**严格校验**：原 Q22 "宽容校验、格式错丢弃整个列表"，本 change 改为"按段强制三条校验、不通过整段（非整列表）丢弃，并写素材级 warning"。

#### Scenario: 严格校验不影响主字段落盘
- **WHEN** 视频分析返回的 clip_suggestions 全部时间码不合法
- **THEN** `asset.clip_suggestions = []`、`analysis_status = "analyzed"`、`summary` / `tags` / `rating` 正常落盘（Q22 主字段保活语义保持）

## REMOVED Requirements

### Requirement: M3 spec §Q22 中"segments 字段缺失或格式错时整段丢弃为空列表"

**Reason**：Q22 原描述把整个 `segments` 列表作为丢弃粒度，过于粗。本 change 用更精细的"按段丢弃 + 写 warning"替代——已在上方 §MODIFIED §segments 草稿由 M3 顺手产出 的 Scenario 中重新表达。
**Migration**：实现时把 `_coerce_segments` 重命名为 `_coerce_clip_suggestions`，并将"丢弃整列表"逻辑改为"按段丢弃 + 追加素材级 warning"；M3 spec 原文不动（保持历史事实源），以本 spec MODIFIED 段为最新事实源。

## 安全与一致性约束

- 复用 M0/M2/M3 安全边界：M2 抽帧后的派生产物仍仅写入 `cache/`；M3 prompt 时间标注与日志均不含 API key、模型响应 `content` 字段；M3 严格校验是纯函数。
- 字段口径以 M0 + 本 spec MODIFIED 段为唯一来源。
- 删除/丢弃 clip_suggestion 段时只追加 `Asset.warnings`、不追加 `Asset.failures`（不是阻塞失败，是数据质量信号）。

## 测试策略

- **零 mock，沿用 M3 测试纪律**：所有新增测试遵循 M3 spec §Q1 / Q2 的"严格只打真模型、零 mock、缺 key 即失败"。
- **单元测试新增**（纯函数）：
  - `_compute_frame_count(duration)`：5 个边界（0/4.3/15/60/100/None）。
  - `_format_frame_timestamp(seconds)`：`10.5 → "00:10.5"`、`125.0 → "02:05.0"`。
  - `_build_user_content` 视频分支：含 N 张图 + N 个 text block 在前。
  - `_coerce_clip_suggestions`：全部 6 种校验失败分支（格式错/out<=in/越界/duration缺失仅前两条/全失败/部分失败）。
- **集成测试新增**（真打 Gemini）：
  - `test_video_analysis_emits_valid_timecodes` — 真喂 `IMG_4306.mov`，断言：① `asset.frame_timestamps` 长度匹配 frame_paths；② 落盘的所有 clip_suggestion 都通过校验（`0 <= in < out <= duration`）；③ `analysis_status = "analyzed"`。
  - 沿用现有 5 个真实视频 fixture（[M3 spec §Q16 / Q25](../M3-real-llm-analysis/spec.md)）。
- **回归测试**：现有 `tests/test_integration_m3.py` 中 `segments` 引用全部改 `clip_suggestions`；现有 `test_provider_emits_segments_for_video` 改名 + 增加时间码校验断言。
