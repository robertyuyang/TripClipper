# M2 本地素材扫描（Stage 1） Spec

> 覆盖：PRD FR-2、PRD 5.1（步骤 3）、9.1（执行扫描）；TD 5 / 13(#3) / 12
> 依赖：M0（`models`、`cut_index`、`paths`、`security`、`config`）、M1（`init_project` 产出的项目目录与已初始化的 `cut_index.json`）
> 角色：M2 是 Stage 1 **本地素材扫描**层。它把 `source_folder` 下的原始素材发现、分类、生成稳定 `asset_id`、提取基础文件信息与（可用时的）媒体信息/浏览辅助信息，写入 `cut_index.json`。它**不依赖任何模型访问配置**，不实现 Stage 2 分析（M3）、雷同/候选（M4）、导出（M5）、Eagle（M6）、FastAPI 页（M7）。

## Why

M1 已经能创建项目并初始化 `cut_index.json`，但 `assets` 仍是空数组——用户还无法知道素材目录里到底有哪些可处理媒体、哪些文件无法处理。FR-2 要求一个**便宜、稳定、确定性强、且不依赖模型配置**的本地扫描：递归发现支持的视频/图片/音频，生成稳定 `asset_id`，提取基础文件信息，并在 `ffprobe`/`ffmpeg` 可用时补充媒体信息与缩略图/关键帧；任一文件或外部工具失败都不得中断整体扫描，而是降级并记录到 `warnings`/`failures`。M2 把这套扫描固化为**可复用核心函数 + 一个 CLI 入口**（`tripclipper analyze --stage scan`），供后续 CLI 流程与 M7 的 `POST /scan` 共同消费。

## What Changes

- 新增核心模块 `src/tripclipper/scan.py`，提供：
  - `SUPPORTED_EXTENSIONS`：扩展名 → `AssetType` 的单一映射（取值严格依 TD 5 的支持类型清单），大小写不敏感。
  - `classify_file(path)`：按扩展名判定为 `video`/`image`/`audio` 或 `None`（非媒体）。
  - `detect_capabilities()`：通过 `shutil.which` 探测 `ffmpeg`/`ffprobe` 是否可用，返回 M0 的 `Capabilities`（含 `ffmpeg`/`ffprobe` 布尔与说明 `notes`）。
  - `probe_media(path)`：在 `ffprobe` 可用时返回媒体信息（`duration`、`width`/`height`、`codec`、`fps`、`has_audio`）并写入 `asset.metadata`；不可用或失败时返回空并记录降级。**解析规则**（由真实素材验证得出，见下文）：① 分辨率/编码取**主视频流**——在 `codec_type=video` 的流中按像素面积最大者选主，**忽略** `data` 流与 mjpeg 封面/缩略流（DJI/行车记录仪文件常含副流）；② `fps` 解析 `avg_frame_rate` 的 `num/den` 分数并求值为浮点（如 `60000/1001`→59.94、`30/1`→30.0），`den=0` 时记为 0/缺省；③ `has_audio` 以"存在 `codec_type=audio` 流"判定；④ `duration` 取 `format.duration`（秒，浮点）。
  - `extract_thumbnail(...)` / `extract_frames(...)`：在 `ffmpeg` 可用时为视频抽取缩略图与若干关键帧到 `cache/thumbnails`、`cache/frames`，回填 `asset.thumbnail_path`、`asset.frame_paths`；图片可直接把自身路径作为缩略图来源（不复制原图，仅引用）。
  - `scan_project(slug, *, base_dir=None, extract_media=True)`：端到端扫描。读回项目 `cut_index.json` → 只读递归遍历 `source_folder` → 分类、生成 `asset_id`、提取基础信息 →（能力可用且 `extract_media=True` 时）补媒体信息与缩略图/关键帧 → 合并进 `cut_index`（保留已有分析结果）→ 落盘 → 返回 `ScanResult` 摘要。
  - `ScanResult`：扫描结果摘要（发现总数、各类型计数、跳过的非媒体数、失败数、能力状态、是否为空目录）。
- 修改 `src/tripclipper/cli.py`：把 `analyze --stage scan` 从占位接线到 `scan_project`，打印扫描摘要；错误以面向用户的清晰信息呈现并以非 0 退出码结束。`--stage sample/full` 仍为占位（M3）。
- 行为约束：
  - **递归扫描 + 确定性**：按相对 `source_folder` 的相对路径**排序**遍历，保证多次扫描得到稳定、可复现的顺序与结果。
  - **类型识别**：仅支持文件进入 `assets`；非媒体文件被跳过且**不**进入 `assets`，计入 `ScanResult.skipped`。
  - **稳定 `asset_id`**：复用 M0 `generate_asset_id(relative_path)`，同一文件多次扫描得到同一 ID。
  - **优雅降级**：`ffmpeg`/`ffprobe` 缺失时记录一条能力警告（`cut_index.json.warnings`，stage=`scan`），跳过媒体信息/缩略图，**不**让流程崩溃；基础文件信息仍写入。
  - **单文件失败隔离**：单个文件的探测/抽帧失败只记录到该 asset 的 `warnings`/`failures` 或项目级 `failures`，继续处理其余文件。
  - **空目录提示**：`source_folder` 下无任何支持媒体时，写入一条面向用户的非阻塞警告（"未发现可处理媒体"），`assets` 保持为空，不报错。
  - **幂等可重入**：重复扫描刷新文件级字段（size/modified_time/metadata/缩略图等），但对 `asset_id` 匹配的已有 asset **保留**其 Stage 2 分析字段（summary/tags/rating/subject_type/segments 等）；初始 `analysis_status` 为 `scanned`，已 `analyzed` 的素材不被回退。
  - **源目录只读**：仅以只读方式读取 `source_folder`，不删除/移动/覆盖任何原始素材（复用 M0 安全边界）；所有派生产物只落到项目 `cache/` 下。
  - **不依赖模型配置**：扫描与模型配置无关；即使 `model_usable=False` 也能成功扫描。

不在 M2 范围（留给后续模块）：模型 provider 与 Stage 2 样本/全量分析（M3）、雷同分组与候选池（M4）、CSV/MD/HTML 导出（M5）、Eagle（M6）、FastAPI `POST /scan` 与状态面板（M7）、转写（transcripts，Stage 2 范畴）。

## Impact

- 影响的能力：分析（M3）、雷同/候选（M4）、导出（M5）、Eagle（M6）、本地页（M7）都以 M2 扫描出的 `assets`（含基础信息、稳定 ID、可选媒体信息与缩略图/关键帧路径）为起点。
- 影响的代码：
  - 新增 `src/tripclipper/scan.py`
  - 修改 `src/tripclipper/cli.py`（`analyze --stage scan` 接线）
  - 新增 `tests/test_scan.py`
  - 回写 `docs/specs/README.md` 模块状态（M2 → 已完成）
- 不改动 M0 的数据契约与字段口径，不新增枚举（复用 `AssetType`、`AnalysisStatus`、`Capabilities`、`Asset`、`WarningItem`、`Failure`）；无 **BREAKING**。

## 关键设计决策

- **复用而非重定义**：`asset_id` 用 M0 `generate_asset_id`；目录/缓存路径用 M0 `paths`（`thumbnails_dir`/`frames_dir`/`cut_index_path`）；读写用 M0 `read_cut_index`/`write_cut_index`；能力状态用 M0 `Capabilities`；只读约束用 M0 `assert_read_only_source`。M2 不重新定义任何字段或枚举。
- **测试策略：零 mock 的真实集成测试**。本模块测试**不使用任何 mock / monkeypatch 函数替换 / stub**。`ffprobe`/`ffmpeg` 必须真实安装并被真实调用。**素材来源是仓库本地 `tests/videos/` 下用户提供的真实视频**（8 个，含 DJI 多流文件与行车记录仪主/副流文件），全量参与扫描，真实跑 `_run_ffprobe`/`_run_ffmpeg_*` 验证 `metadata` 解析（主流选择、分数帧率、has_audio、duration）与缩略图/关键帧产物。本期**只测视频类型**（image/audio 待补素材）。因此 **ffmpeg/ffprobe 是本模块测试的硬依赖**（开发与 CI 环境都必须安装），不再提供"无外部依赖也能跑测"的退路，也不再有 `skipif` 跳过。`tests/videos/` 已加入 `.gitignore`（约 1GB，不入库）；运行测试前确保 `PATH` 含 `/opt/homebrew/bin`（本机 ffmpeg/ffprobe 8.1.2 所在）。需要叠加非媒体/损坏文件的边界用例，在 `tmp_path` 下新建源目录并用 **symlink** 指向真实视频（避免拷贝大文件、保持 `tests/videos/` 只读），再写入合成的非媒体/垃圾字节文件。
- **降级分支也用真实环境，不用 mock**：要验证"工具缺失时优雅降级"，通过**真实地构造一个不含 ffmpeg/ffprobe 的环境**来触发——即在子测试中把 `PATH` 临时指向一个空目录（`monkeypatch.setenv("PATH", <空目录>)` 只改环境变量、不替换任何函数行为），让 `shutil.which` 真实地找不到工具。这测的是真实的"无依赖环境"，而非伪造函数返回值。
- **外部调用仍收口到薄封装**（`_run_ffprobe`、`_run_ffmpeg_thumbnail`、`_run_ffmpeg_frames`、`detect_capabilities`）：这样做是为了实现内聚与可读性（统一超时/异常处理），**不是**为了便于 mock。
- **确定性遍历**：用 `os.walk` 收集后按相对路径排序，再统一处理，避免文件系统返回顺序差异导致的非确定性，满足 TD"Stage 1 应优先保证稳定和确定性"。
- **缩略图策略**：视频用 `ffmpeg` 在固定时间点（如中点或 1s）截一张缩略图，关键帧抽取数量受一个小常量上限约束（默认 3，仅取均匀分布的几帧），避免大目录产生海量派生文件；图片不复制原图，仅把原图路径作为 `thumbnail_path` 来源引用（保持源只读、不放大缓存体积）；音频无缩略图。
- **合并与保活**：再次扫描时按 `asset_id` 把新发现的文件级信息合并进已有 asset，保留 Stage 2 已写入的分析字段；源目录中已消失的旧 asset 不强行删除，而是记录一条非阻塞警告（提示文件已不在源目录），由后续模块/用户决定处理，避免误删分析结果。
- **base_dir 可注入**：`scan_project` 接受可选 `base_dir`（默认 `<cwd>/projects`），沿用 M0/M1 约定，便于测试与多工作区。

## ADDED Requirements

### Requirement: 递归发现与类型识别
系统 SHALL 递归扫描项目的 `source_folder`，按扩展名（大小写不敏感）将文件识别为 `video`/`image`/`audio`；仅支持媒体进入 `cut_index.json.assets`，非媒体文件被跳过且不进入 `assets`。

#### Scenario: 支持的媒体进入素材索引
- **WHEN** `source_folder`（含子目录）下存在 `.mp4`、`.jpg`、`.mp3` 等支持类型文件并执行扫描
- **THEN** 这些文件作为 `asset` 进入 `cut_index.json.assets`，`type` 分别为 `video`/`image`/`audio`，`analysis_status` 为 `scanned`

#### Scenario: 非媒体文件被跳过
- **WHEN** `source_folder` 下存在 `.txt`、`.docx`、无扩展名等非媒体文件
- **THEN** 这些文件不进入 `assets`，并计入扫描摘要的跳过计数

#### Scenario: 扩展名大小写不敏感
- **WHEN** 存在 `.MP4`、`.JPG` 等大写扩展名文件
- **THEN** 仍被正确识别为对应媒体类型并进入 `assets`

### Requirement: 基础文件信息与稳定标识
系统 SHALL 为每个媒体文件生成稳定 `asset_id`，并提取基础文件信息：`filename`、`path`、`relative_path`、`extension`、`size`、`modified_time`。

#### Scenario: 基础信息齐全
- **WHEN** 扫描一个媒体文件
- **THEN** 对应 asset 含 `asset_id`、`filename`、`path`（绝对路径）、`relative_path`（相对 `source_folder`）、`extension`、`size`（字节）、`modified_time`（ISO 时间），`analysis_status` 为 `scanned`

#### Scenario: 同一文件得到同一 asset_id
- **WHEN** 对同一文件多次扫描
- **THEN** 其 `asset_id` 保持一致（复用 M0 `generate_asset_id(relative_path)`）

#### Scenario: 遍历顺序确定
- **WHEN** 对同一目录多次扫描
- **THEN** `assets` 按相对路径排序，顺序与结果稳定可复现

### Requirement: 媒体信息与浏览辅助信息（能力可用时）
系统 SHALL 在 `ffprobe` 可用时提取媒体信息（时长、分辨率、编码、fps、是否有音频）写入 `asset.metadata`；在 `ffmpeg` 可用时为视频抽取缩略图与关键帧，回填 `thumbnail_path` 与 `frame_paths`。

#### Scenario: ffprobe 可用时补充媒体信息
- **WHEN** `ffprobe` 可用且扫描一个视频
- **THEN** 该 asset 的 `metadata` 含 `duration`、`width`/`height`、`codec`、`fps`、`has_audio` 等字段

#### Scenario: 多流文件取主视频流
- **WHEN** 扫描一个含多条视频流的文件（如 DJI 文件含 `mjpeg` 封面流 + `data` 流，或行车记录仪文件含 `1920×1080` 主流与 `640×480` 副流）
- **THEN** `metadata.width`/`height`/`codec` 取**主视频流**（像素面积最大的 `video` 流），忽略 `data` 流与 mjpeg 封面/缩略流

#### Scenario: 分数帧率解析为浮点
- **WHEN** 视频的 `avg_frame_rate` 为分数（如 `60000/1001` 或 `30/1`）
- **THEN** `metadata.fps` 为求值后的浮点（≈59.94 或 30.0），而非原始分数字符串

#### Scenario: ffmpeg 可用时生成缩略图与关键帧
- **WHEN** `ffmpeg` 可用且扫描一个视频
- **THEN** 在 `cache/thumbnails`、`cache/frames` 生成派生文件，`thumbnail_path` 与 `frame_paths` 被回填为这些文件路径

#### Scenario: 派生产物只落在 cache，不触碰源
- **WHEN** 生成缩略图/关键帧
- **THEN** 所有派生文件仅写入项目 `cache/` 子目录，`source_folder` 下的原始素材不被修改/移动/删除

### Requirement: 缺失外部工具时优雅降级
系统 SHALL 在 `ffmpeg` 或 `ffprobe` 缺失时记录能力警告并跳过相应步骤，而不是让扫描崩溃；基础文件信息仍须写入。

#### Scenario: 工具缺失记录能力警告且不崩溃
- **WHEN** `ffmpeg`/`ffprobe` 均不可用时执行扫描
- **THEN** `cut_index.json.capabilities` 标记对应能力为不可用，`warnings` 含一条 stage=`scan` 的能力警告；`assets` 仍含全部基础文件信息，进程不抛未捕获异常

### Requirement: 单文件失败隔离
系统 SHALL 保证单个文件的媒体探测或缩略图/关键帧抽取失败不中断整体扫描，而是记录到该 asset 或项目的 `warnings`/`failures` 并继续。

#### Scenario: 某文件探测失败不影响其余
- **WHEN** 扫描过程中某个文件的 `ffprobe`/`ffmpeg` 处理抛错或超时
- **THEN** 该文件仍以基础信息进入 `assets`（媒体信息缺省），并记录一条失败/警告；其余文件正常完成扫描

### Requirement: 空目录提示
系统 SHALL 在 `source_folder` 下无任何支持媒体时给出面向用户的清晰提示，不报错。

#### Scenario: 空目录提示未发现可处理媒体
- **WHEN** `source_folder` 存在但其中无任何支持类型媒体
- **THEN** `assets` 为空，`cut_index.json.warnings` 含一条"未发现可处理媒体"的非阻塞警告，扫描以成功状态结束

### Requirement: 幂等可重入且不破坏已有分析
系统 SHALL 支持重复扫描以反映源目录变化；重复扫描刷新文件级信息但不得清空 `asset_id` 匹配素材的已有 Stage 2 分析结果。

#### Scenario: 重复扫描保留已有分析
- **WHEN** 已有若干 asset 含 Stage 2 分析字段（如 `summary`/`tags`/`rating`），源目录新增一个文件后再次扫描
- **THEN** 新文件作为新 asset 加入；已有 asset 的分析字段保留，仅文件级字段（size/modified_time/metadata 等）被刷新

#### Scenario: 重复扫描不报错
- **WHEN** 对同一项目连续两次扫描
- **THEN** 两次均成功、不抛异常、`asset_id` 稳定、顺序一致

### Requirement: CLI 扫描入口
系统 SHALL 提供 `tripclipper analyze --stage scan --config <project.yaml>`（或按 slug）执行 Stage 1 扫描并打印扫描摘要；错误以面向用户清晰信息呈现并以非 0 退出码结束。

#### Scenario: scan 执行并打印摘要
- **WHEN** 运行 `tripclipper analyze --stage scan --config <合法 project.yaml>`
- **THEN** 完成扫描，stdout 打印发现总数、各类型计数、跳过数、失败数与能力状态，退出码为 0

#### Scenario: scan 在项目未初始化时清晰失败
- **WHEN** 对一个不存在 `cut_index.json` 的项目运行扫描
- **THEN** 给出面向用户的清晰错误（提示先 `init`），退出码非 0，不抛未捕获堆栈

## 安全与一致性约束

- 复用 M0 安全边界：`source_folder` 只读引用；密钥与扫描无关，任何摘要/日志均不含密钥明文。
- 字段口径以 M0 `models.py` 为唯一来源，M2 不重新定义任何字段或枚举。
- 派生产物（缩略图/关键帧）只写入项目 `cache/`，不污染源目录。
