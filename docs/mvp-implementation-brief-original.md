# TripClipper MVP 实施简报

## 1. 背景

TripClipper 是一个本地运行的剪辑准备 Agent，面向旅行、团队活动、聚会、会议等素材整理场景。第一版不是自动剪辑软件，也不负责生成最终成片，而是把原始素材整理到“可剪”的状态：

- 扫描本地素材文件夹。
- 分析视频、图片和音频。
- 生成标签、星级、镜头说明、推荐 timecode 和声音建议。
- 导出可迁移的数据包。
- 将素材级结果同步到 Eagle，作为第一版审核和浏览 UI。

原始需求文档路径：

```text
/Users/bytedance/Documents/New project/travel-material-agent-requirements.md
```

当前仓库路径：

```text
/Users/bytedance/Documents/TripClipper
```

当前仓库一开始基本为空项目，后续实现应以本文档作为第一版 MVP 的执行依据。

## 2. MVP 已定取舍

MVP 需要实现一个本地 FastAPI 启动页，同时保留可复用的 CLI/API 核心逻辑。

已确定的方向：

- 本地入口：`tripclipper serve`。
- UI 形态：FastAPI 简单本地页面，不做完整审核工作台。
- 项目输入：`project.yaml`。
- 存储方式：JSON 文件包，不上 SQLite。
- 分析流程：两阶段分析。
- 模型能力：云模型可配置，同时必须提供 mock provider，保证无 API key 时也能跑通链路。
- Eagle 定位：素材级 UI 和同步适配器，不是唯一事实源。
- 片段输出：第一版只输出 timecode，不裁切视频片段。
- 素材处理：只引用原始路径，不复制、不移动、不删除、不覆盖源素材。

第一版不做：

- 不做完整 Web 审核/编辑工作台。
- 不修改剪映/CapCut 项目。
- 不自动生成最终成片。
- 不在 Eagle 内强行做片段级对象。
- 不引入 SQLite，除非后续编辑历史和复杂筛选需求明确需要。

## 3. 项目输入

每个项目通过 `project.yaml` 配置。

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
  provider: "mock"
  vision_model: ""
  transcription_model: ""
  text_model: ""
eagle_sync:
  enabled: true
  mode: "dry-run"
```

`output_style`、`target_length`、`audience`、`people_focus`、`audio_priority` 这些剪辑意图字段都是每个项目的输入参数，不能写死在产品逻辑里。

## 4. 命令入口

核心命令：

```bash
tripclipper serve
tripclipper analyze --config project.yaml --stage scan
tripclipper analyze --config project.yaml --stage sample
tripclipper analyze --config project.yaml --stage full
tripclipper export --project <project_slug>
tripclipper sync-eagle --project <project_slug> --dry-run
tripclipper sync-eagle --project <project_slug> --apply
```

`tripclipper serve` 启动一个本地页面，用于常见工作流：

- 创建或选择项目配置。
- 启动 Stage 1 扫描。
- 启动 Stage 2 样本分析。
- 启动 Stage 2 全量分析。
- 导出报告。
- 执行 Eagle dry-run。
- 执行 Eagle apply。
- 展示任务日志、处理计数和失败列表。

这个页面是启动器和状态面板，不是完整素材审核编辑器。

## 5. 两阶段分析

### Stage 1：本地扫描

Stage 1 应该便宜、稳定、确定性强，并且尽量只依赖本地能力。

职责：

- 递归扫描支持的媒体文件。
- 识别视频、图片和音频类型。
- 生成稳定的 `asset_id`。
- 提取基础文件信息：文件名、路径、大小、修改时间、扩展名。
- 在 `ffprobe` 可用时提取时长、分辨率、编码、fps、是否有音频等信息。
- 在 `ffmpeg` 可用时抽取缩略图和关键帧。
- 当 `ffmpeg` 或 `ffprobe` 缺失时记录能力警告，而不是让流程崩溃。
- 单个文件失败时继续处理剩余文件。

Stage 1 不能依赖模型 API key。

### Stage 2：模型分析

Stage 2 使用模型能力，但模型 provider 必须可替换。

职责：

- 生成中文素材说明。
- 生成内容标签、用途标签、声音标签、质量标签。
- 生成 1-5 星评分。
- 推荐可用 timecode。
- 推荐片段用途，例如开头、高光、转场、B-roll、同期声、收尾。
- 推荐声音策略，例如保留人声、保留环境声、静音、待人工确认。

Stage 2 应先跑 20-30 个素材的样本分析。样本结果确认后，再执行全量分析。

第一版必须实现 mock provider，保证没有模型 API key 时也能跑通完整流程。

## 6. 标准数据包

项目输出目录建议如下：

```text
projects/<project_slug>/
  project.yaml
  cut_index.json
  assets.csv
  segments.csv
  summary.md
  review.html
  cache/
    thumbnails/
    frames/
    transcripts/
```

### `cut_index.json`

机器可读事实源。

应保存：

- 项目信息和剪辑意图。
- 素材元数据。
- 分析状态。
- 标签、星级、说明、场景或分类。
- 推荐可用片段。
- 声音建议。
- 缩略图、关键帧、转写文本路径。
- Eagle item id 和同步状态。
- 失败信息和警告信息。

`cut_index.json` 不能内嵌图片、视频或大段转写文本。大型产物必须用路径引用。

### `assets.csv`

给人和表格工具看的素材级导出。

建议列：

- `asset_id`
- `file`
- `path`
- `type`
- `duration`
- `rating`
- `scene`
- `tags`
- `summary`
- `audio_suggestion`
- `analysis_status`
- `eagle_item_id`

### `segments.csv`

给剪辑时使用的片段级导出。

建议列：

- `asset_id`
- `file`
- `path`
- `in`
- `out`
- `role`
- `rating`
- `reason`
- `audio_strategy`
- `tags`

### `summary.md`

给人看的项目总结。

应包含：

- 项目概览。
- 推荐粗剪结构。
- 高分素材。
- 高光候选。
- 可用同期声/原声候选。
- 开头、转场、收尾候选。
- 低质量或废片候选。
- 失败和警告摘要。

### `review.html`

本地静态报告。

应展示：

- 可用时展示素材缩略图。
- 文件名和路径。
- 星级、标签和说明。
- 推荐片段和理由。
- 声音策略。
- 原始媒体路径或链接。

v1 中 `review.html` 是只读报告，不承担编辑功能。

## 7. Eagle 同步

Eagle 是第一版素材级审核和管理适配器。

必须满足：

- 支持 dry-run 和 apply。
- dry-run 展示计划创建的文件夹、标签、星级和备注。
- apply 在可行时创建项目文件夹和场景文件夹。
- apply 保守地导入或同步素材。
- apply 写入素材级标签、星级和备注。
- 备注只追加或更新 `TripClipper` 管理区块。
- 不覆盖用户已有备注和标签。
- 绝不删除、移动或修改原始素材文件。
- Eagle 未启动或 API 不可用时，本地导出仍然必须成功。

Eagle 备注中的管理区块应有清晰边界，例如：

```text
<!-- TripClipper:start -->
镜头说明：...

推荐片段：
- 00:08-00:15：人物互动，高光，保留原声。
- 00:31-00:36：转场，可静音。

声音建议：...
Agent 评分：5 星。
<!-- TripClipper:end -->
```

## 8. 实现优先级

按以下顺序实现：

1. Python 项目骨架：`pyproject.toml`、README、包结构、CLI 入口。
2. `project.yaml` 读取和项目目录管理。
3. Stage 1 扫描：素材发现、稳定 `asset_id`、元数据、可选 ffmpeg/ffprobe 集成、优雅降级。
4. Mock Stage 2 provider：说明、标签、星级、可用片段、声音策略。
5. 导出器：`cut_index.json`、`assets.csv`、`segments.csv`、`summary.md`、`review.html`。
6. Eagle dry-run 计划生成。
7. 保守版 Eagle apply。
8. FastAPI 本地启动页。
9. 基础测试：配置、扫描、导出、mock 分析、Eagle 备注区块替换。

## 9. 验收标准

MVP 满足以下条件即可验收：

- `tripclipper serve` 可以启动本地页面。
- 示例 `project.yaml` 可以跑完整流程。
- 没有模型 API key 时，mock provider 可以跑通。
- 缺少 `ffmpeg` 或 `ffprobe` 时流程不崩溃，只记录能力缺失。
- 项目能导出 `cut_index.json`、`assets.csv`、`segments.csv`、`summary.md`、`review.html`。
- Eagle 不可用时，不影响本地数据包导出。
- Eagle sync dry-run 可用。
- Eagle apply 不覆盖用户已有内容，只更新 `TripClipper` 管理区块。
- 工具不删除、不移动、不修改原始素材。

## 10. 建议的 Goal 提示词

新开实现线程时，可以直接使用这段提示词：

```text
请进入 Goal 模式，并按以下文档实现 TripClipper MVP：
/Users/bytedance/Documents/TripClipper/docs/mvp-implementation-brief.md

请先读取文档，再从 Python 项目骨架开始，依次实现 CLI、项目配置、Stage 1 扫描、mock Stage 2 分析、可迁移导出、Eagle dry-run/apply，以及 FastAPI 本地启动页。

第一版必须安全：不删除、不移动、不覆盖原始素材；ffmpeg、模型、Eagle 失败时都不能阻塞本地数据包导出；没有模型 API key 时，mock provider 也要能跑通完整链路。
```
