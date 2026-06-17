# TripClipper 技术设计文档

## 1. 文档定位

本文档定义 TripClipper 当前版本的技术实现方案。产品目标、用户场景、范围边界和验收标准见产品需求文档。

技术方向是：本地 FastAPI 启动页作为轻量入口，CLI/API 核心逻辑可复用，项目状态保存在可迁移 JSON 文件包中，Eagle 只是可选适配器。

## 2. 架构原则

- 本地优先：核心数据保存在当前仓库工作目录下的 `projects/<project_slug>/`。
- 可迁移事实源：`cut_index.json` 是机器可读事实源，Eagle 和 HTML/CSV/Markdown 都是派生产物或适配器。
- 真实模型分析：Stage 2 必须调用真实大模型能力；模型配置缺失或调用失败时不得生成替代性假结果。
- 可替换模型接入：模型调用通过 provider 边界实现，但 provider 必须连接真实模型服务。
- 保守写入：不删除、不移动、不修改原始素材，只引用路径并生成缓存/导出文件。
- 简单存储：当前版本使用 JSON 文件包，不引入复杂项目数据库。
- 可恢复执行：扫描、样本分析、全量分析、导出和 Eagle 同步应可重复执行，失败记录必须可追踪。

## 3. 运行入口

CLI 命令：

```bash
tripclipper serve
tripclipper serve --host 127.0.0.1 --port 8765
tripclipper analyze --config project.yaml --stage scan
tripclipper analyze --config project.yaml --stage sample
tripclipper analyze --config project.yaml --stage full
tripclipper export --project <project_slug>
tripclipper sync-eagle --project <project_slug> --dry-run
tripclipper sync-eagle --project <project_slug> --apply
```

`tripclipper serve` 启动本地 FastAPI 页面，用于常见工作流：

- 创建 `project.yaml`。
- 启动 Stage 1 扫描。
- 启动 Stage 2 样本分析。
- 启动 Stage 2 全量分析。
- 导出报告。
- 执行 Eagle dry-run 或 apply。
- 展示项目列表、任务日志、处理进度、失败列表和下一步建议。

## 4. 配置设计

项目配置文件为 `project.yaml`。

必填字段：

- `project_name`
- `source_folder`
- `model_config`

建议字段：

```yaml
project_name: "2026 Team Event"
source_folder: "/path/to/source/media"
output_style: "activity_recap"
target_length: "3min"
audience: "internal_team"
people_focus: "high"
audio_priority: "high"
model_config:
  provider: "openai_compatible"
  base_url: "https://api.example.com/v1"
  api_key_env: "TRIPCLIPPER_MODEL_API_KEY"
  vision_model: "vision-model-name"
  text_model: "text-model-name"
  transcription_model: "audio-model-name"
  language: "zh-CN"
  sample_size: 25
eagle_sync:
  enabled: true
  mode: "dry-run"
  base_url: "http://127.0.0.1:41595/api"
```

实现要求：

- 相对 `source_folder` 应解析为相对 `project.yaml` 所在目录。
- 未指定 `project_slug` 时，由 `project_name` 生成稳定 slug。
- `model_config` 必须能解析出真实模型访问配置；缺失时允许保存配置，但 Stage 2 必须失败并提示用户修正。
- `api_key_env` 用于从环境变量读取密钥；不得把密钥写入 `cut_index.json`、导出表格或报告。
- `eagle_sync` 默认 `enabled: true`、`mode: dry-run`。
- `output_style`、`target_length`、`audience`、`people_focus`、`audio_priority` 通过 `editing_intent` 聚合，供模型分析、默认候选池和导出器使用。

## 5. Stage 1 本地扫描

Stage 1 应便宜、稳定、确定性强，并且不依赖模型访问配置。

职责：

- 递归扫描支持的媒体文件。
- 识别视频、图片和音频类型。
- 生成稳定的 `asset_id`。
- 提取基础文件信息：文件名、路径、相对路径、大小、修改时间、扩展名。
- 在 `ffprobe` 可用时提取时长、分辨率、编码、fps、是否有音频。
- 在 `ffmpeg` 可用时抽取缩略图和关键帧。
- 当 `ffmpeg` 或 `ffprobe` 缺失时记录能力警告，而不是让流程崩溃。
- 单个文件失败时继续处理剩余文件。

支持的文件类型：

- 视频：`.mp4`、`.mov`、`.m4v`、`.avi`、`.mkv`、`.webm`、`.mts`、`.m2ts`
- 图片：`.jpg`、`.jpeg`、`.png`、`.heic`、`.heif`、`.webp`、`.tif`、`.tiff`
- 音频：`.mp3`、`.wav`、`.m4a`、`.aac`、`.flac`、`.ogg`、`.opus`

Stage 1 输出写入 `cut_index.json`，素材初始 `analysis_status` 为 `scanned`。

## 6. Stage 2 真实模型分析

Stage 2 使用真实大模型能力，分为样本分析和全量分析。

职责：

- 生成中文素材说明。
- 生成内容标签、用途标签、声音标签和质量标签。
- 生成 1-5 星评分。
- 推荐可用 timecode。
- 推荐片段用途，例如开头、高光、转场、B-roll、同期声、收尾。
- 推荐声音策略，例如保留人声、保留环境声、静音、待人工确认。
- 输出主体类型、主要主体、人物存在状态、景别和镜头功能。
- 识别雷同素材组，并生成组内主选、备选、不推荐或待人工确认状态。
- 生成去重后的默认剪辑候选状态和候选理由。

样本分析：

- `sample` 阶段默认处理 20-30 个素材，配置默认值为 25。
- 样本选择应覆盖不同素材类型、时间分布、文件夹分布和画面差异，避免只取同一类素材。
- 样本分析结果写回 `cut_index.json`，并可被导出器和本地报告展示。

全量分析：

- `full` 阶段处理全部待分析素材。
- 已有有效分析结果的素材应支持跳过或重新分析，入口层必须给出清晰提示。
- 模型服务中断时保留已完成素材结果，未完成素材记录失败原因。

模型调用边界：

- provider 接口输入为项目剪辑意图、素材元数据、缩略图/关键帧路径、可选音频/转写路径。
- provider 输出必须是结构化 JSON，并通过本地校验后写入 `cut_index.json`。
- 模型输出无法解析、字段缺失或类型不合法时，该素材标记为 `analysis_failed`，不得写入假结果。
- 模型配置缺失、密钥缺失、鉴权失败或服务不可用时，Stage 2 整体或相关素材失败；本地扫描和已有导出仍可使用。

## 7. 数据包结构

项目输出目录：

```text
projects/<project_slug>/
  project.yaml
  cut_index.json
  assets.csv
  segments.csv
  summary.md
  review.html
  eagle_dry_run.json
  eagle_apply_result.json
  cache/
    thumbnails/
    frames/
    transcripts/
```

`cut_index.json` 顶层结构：

```json
{
  "schema_version": "0.2",
  "project": {},
  "capabilities": {},
  "analysis": {},
  "assets": [],
  "similar_groups": [],
  "default_candidates": [],
  "failures": [],
  "warnings": []
}
```

`project` 保存：

- `project_name`
- `project_slug`
- `source_folder`
- `config_path`
- `editing_intent`
- `model_config_summary`
- `eagle_sync`
- `created_at`
- `updated_at`

`analysis` 保存：

- `provider`
- `vision_model`
- `text_model`
- `transcription_model`
- `stage`
- `sample_size`
- `started_at`
- `finished_at`
- `status`
- `error_summary`

`asset` 保存：

- `asset_id`、`file`、`filename`
- `path`、`relative_path`
- `type`、`extension`
- `size`、`modified_time`
- `metadata`
- `thumbnail_path`、`frame_paths`、`transcript_path`
- `analysis_status`
- `scene`、`summary`、`tags`、`rating`
- `subject_type`、`primary_subject`、`people_presence`
- `shot_scale`、`shot_function`
- `segments`
- `audio_suggestion`、`audio_strategy`
- `similar_group_id`、`similar_selection`、`similar_rank`、`similar_reason`
- `edit_candidate_status`、`edit_candidate_priority`、`edit_candidate_reason`
- `eagle_item_id`、`eagle_sync_status`
- `warnings`、`failures`

字段枚举：

- `subject_type`：`landscape`、`people`、`people_landscape`、`food`、`building`、`activity`、`object`、`other`
- `people_presence`：`none`、`single`、`multiple`、`small_group`、`crowd`
- `shot_scale`：`extreme_wide`、`wide`、`full`、`medium`、`close_up`、`extreme_close_up`
- `shot_function`：`establishing`、`highlight`、`transition`、`detail`、`reaction`、`dialogue`、`b_roll`、`other`
- `similar_selection`：`primary`、`alternate`、`rejected`、`needs_review`、`none`
- `edit_candidate_status`：`default_selected`、`alternate`、`excluded`、`needs_review`

`segment` 保存：

- `in`
- `out`
- `role`
- `subject_type`
- `shot_scale`
- `rating`
- `reason`
- `audio_strategy`
- `tags`

`similar_group` 保存：

- `similar_group_id`
- `asset_ids`
- `basis`
- `primary_asset_id`
- `alternate_asset_ids`
- `rejected_asset_ids`
- `default_candidate_asset_id`
- `confidence`
- `needs_review`
- `reason`

`default_candidates` 保存去重后的默认剪辑候选池：

- `asset_id`
- `priority`
- `role`
- `reason`
- `similar_group_id`
- `subject_type`
- `shot_scale`

`cut_index.json` 不能内嵌图片、视频、音频或大段转写文本。大型产物必须用路径引用。

## 8. 分析后处理

模型完成素材级分析后，需要执行本地后处理，保证结果可筛选、可导出、可同步。

画面类型与景别：

- 以模型结构化输出为准。
- 缺失字段应进入素材级 warning，并标记为 `other` 或 `needs_review`。
- 当素材存在多个明显片段时，素材级字段保存主导画面，片段级字段可保存局部景别。

雷同素材组：

- 依据模型输出、文件时间邻近性、视觉摘要、标签、主体、景别和推荐片段进行分组。
- 每个高置信雷同组最多一个 `primary`。
- 备选素材保留原始星级，不因去重降低评分。
- 置信度不足时标记为 `needs_review`，不得强行选择主选。

默认剪辑候选池：

- 包含高价值非雷同素材，以及每个高置信雷同组的主选素材。
- 同组高星备选素材默认标记为 `alternate`，不进入默认主候选列表。
- 同组不推荐素材标记为 `excluded`。
- 待人工确认素材进入待确认列表，不混入默认主候选列表。
- 候选池应利用主体类型和景别做基础平衡，避免可选素材充足时全是人物近景或全是风景空镜。

## 9. 导出器设计

导出命令从 `cut_index.json` 生成派生产物。

`assets.csv` 列：

- `asset_id`
- `file`
- `path`
- `type`
- `duration`
- `rating`
- `scene`
- `subject_type`
- `primary_subject`
- `people_presence`
- `shot_scale`
- `shot_function`
- `tags`
- `summary`
- `similar_group_id`
- `similar_selection`
- `similar_rank`
- `similar_reason`
- `edit_candidate_status`
- `edit_candidate_priority`
- `edit_candidate_reason`
- `audio_suggestion`
- `analysis_status`
- `eagle_item_id`
- `eagle_sync_status`

`segments.csv` 列：

- `asset_id`
- `file`
- `path`
- `in`
- `out`
- `role`
- `subject_type`
- `shot_scale`
- `rating`
- `reason`
- `audio_strategy`
- `tags`

`summary.md` 应包含：

- 项目概览。
- 推荐粗剪结构。
- 景别和主体覆盖情况。
- 去重后的默认剪辑候选清单。
- 高分素材。
- 高光候选。
- 雷同素材主选建议。
- 可用同期声或原声候选。
- 开头、转场、收尾候选。
- 低质量或废片候选。
- 失败和警告摘要。

`review.html` 是只读本地报告，应展示：

- 缩略图、文件名、路径。
- 星级、标签、说明。
- 主体类型、人物存在状态、景别、镜头功能。
- 雷同素材组、组内选择状态、选择理由。
- 剪辑候选状态、候选优先级、候选理由。
- 推荐片段、声音策略和原始媒体链接。

默认视图应突出展示 `default_selected` 素材；`alternate` 和 `excluded` 素材应可在雷同组内展开查看。

## 10. Eagle 适配器设计

Eagle 是可选适配器，不是事实源。

dry-run：

- 读取 `cut_index.json`。
- 生成项目文件夹和场景文件夹计划。
- 生成每个素材的目标 folder、tags、rating、note。
- note 预览必须包含主体类型、景别、镜头功能、雷同素材状态、剪辑候选状态和推荐理由。
- 写入 `eagle_dry_run.json`。

apply：

- 默认连接 `http://127.0.0.1:41595/api`，可通过 `eagle_sync.base_url` 或 `EAGLE_API_URL` 覆盖。
- Eagle API 不可用时，写入 warning 和跳过状态，不阻塞本地数据包。
- 可行时创建项目文件夹和场景文件夹。
- 对已有素材按路径匹配并更新，找不到时从原始路径导入。
- 更新备注时只替换 `TripClipper` 管理区块。
- 更新标签时合并新增标签，不清空用户已有标签。
- apply 结果写入 `eagle_apply_result.json`，并回写 `cut_index.json` 的 `eagle_item_id` 和 `eagle_sync_status`。

建议写入标签：

- `TripClipper`
- 主体类型，例如 `人物加风景`
- 景别，例如 `中景`
- 镜头功能，例如 `高光`
- 候选状态，例如 `默认候选`、`备选候选`
- 雷同组状态，例如 `雷同组主选`、`雷同组备选`

管理区块边界：

```text
<!-- TripClipper:start -->
...
<!-- TripClipper:end -->
```

## 11. FastAPI 本地页

本地页是 launcher/status panel，不是完整审核工作台。

接口建议：

- `GET /`：渲染本地页面。
- `POST /create-config`：创建 `project.yaml`。
- `POST /scan`：运行 Stage 1。
- `POST /analyze`：运行 Stage 2 sample 或 full。
- `POST /export`：生成导出物。
- `POST /sync-eagle`：执行 dry-run 或 apply。
- `GET /api/status`：返回项目列表、最近任务日志和失败列表。

页面状态应展示：

- 项目配置摘要。
- 模型配置是否完整，但不展示密钥明文。
- 扫描、样本分析、全量分析、导出、Eagle 同步状态。
- 素材数量、成功数量、失败数量、待人工确认数量。
- 下一步建议。

任务日志当前版本可以保存在进程内存中。长期运行历史留给后续版本。

## 12. 错误处理和安全

- 配置错误应返回清晰错误信息。
- `source_folder` 不存在或不是目录时记录失败，不应生成误导性素材结果。
- `ffmpeg`、`ffprobe`、Eagle API 缺失不能阻塞本地数据包导出。
- 模型配置缺失或模型调用失败时，Stage 2 必须失败并记录原因，不得伪造分析结果。
- 单个素材扫描、缩略图生成、关键帧生成或模型分析失败时，应记录到该素材或项目 warnings/failures。
- 原始素材路径只读使用，工具不得删除、移动、复制或覆盖源素材。
- 所有可撤销性较低的外部写入都应先支持 dry-run。
- 密钥不得写入 `cut_index.json`、CSV、Markdown、HTML、Eagle note 或任务日志。

## 13. 实现优先级

按以下顺序实现：

1. Python 项目骨架：`pyproject.toml`、README、包结构、CLI 入口。
2. `project.yaml` 读取、模型配置校验和项目目录管理。
3. Stage 1 扫描：素材发现、稳定 `asset_id`、元数据、可选 ffmpeg/ffprobe 集成、优雅降级。
4. 真实模型 provider：视觉理解、文本生成、可选音频理解，输出结构化 JSON。
5. Stage 2 样本分析和全量分析：写入说明、标签、星级、主体类型、景别、推荐片段和声音策略。
6. 分析后处理：雷同素材组、组内选择状态、默认剪辑候选池。
7. 导出器：`cut_index.json`、`assets.csv`、`segments.csv`、`summary.md`、`review.html`。
8. Eagle dry-run 计划生成。
9. 保守版 Eagle apply。
10. FastAPI 本地启动页。
11. 基础测试：配置、扫描、真实模型 provider 边界、结构化输出校验、导出、Eagle 备注区块替换。

## 14. 工程验收

工程层面至少验证：

- 配置读取、默认值和模型配置校验。
- 稳定 `project_slug` 和 `asset_id`。
- Stage 1 能发现支持的媒体并跳过非媒体文件。
- 模型配置缺失时 Stage 2 明确失败，且不写入假分析结果。
- Stage 2 成功素材能写入说明、标签、星级、主体类型、人物存在状态、景别、镜头功能、推荐片段和声音策略。
- 雷同素材组能标记主选、备选、不推荐或待人工确认。
- 同组高星备选素材不进入默认主候选列表，但保留原星级。
- 默认剪辑候选池包含雷同组主选和非雷同高价值素材。
- 导出器能生成全部目标文件，并包含主体类型、景别、雷同组和剪辑候选状态字段。
- Eagle dry-run 不依赖 Eagle 运行。
- Eagle apply 不覆盖用户已有备注和标签，只更新 `TripClipper` 管理区块。
- 缺少可选本地媒体能力时不会导致核心流程崩溃。
