# TripClipper

TripClipper 是一个本地优先的 Python 素材整理与粗剪工具。它可以扫描、分析、筛选原始素材，并以 `cut_index.json` 作为统一的数据源。

## 当前状态

目前已经打通从项目创建、素材扫描、AI 分析、智能选片、结果导出到 Eagle 同步的完整 CLI 流程。自动粗剪与剪映草稿能力已提供 Python API；本地启动页 `serve` 仍是占位功能。

## 已实现功能

### 1. 项目管理

- **项目创建**：从配置文件初始化项目，或生成新的项目模板。
- **剪辑目标设置**：配置成片风格、目标时长、受众和人物偏好。
- **本地安全管理**：所有结果保存在本地，不修改、移动或重命名原始素材。

### 2. 素材整理

- **素材扫描**：自动发现项目中的视频、图片和音频素材。
- **基础信息提取**：识别素材时长、画面规格、音轨等信息，并为视频生成预览图。
- **增量更新**：重复扫描时保留已有分析结果，只合并新增或变化的素材。
- **拍摄时段分组**：按拍摄时间自动划分 session，方便按行程或场景整理素材。

### 3. AI 素材分析

- **内容理解**：生成素材摘要、中文短标题、标签、评分和镜头信息。
- **可用片段推荐**：标记值得保留的片段及其时间范围。
- **语音识别**：判断视频中的人声质量，生成带时间码的原语言转写。
- **批量分析**：支持抽样分析、全量分析、断点续跑和强制重新分析。

### 4. 智能选片

- **雷同素材识别**：自动找出内容相近或重复拍摄的素材。
- **组内优选**：在相似素材中标记首选、备选和淘汰项，并给出判断理由。
- **候选池生成**：综合评分和内容分布，生成默认剪辑候选池。
- **人工复核提示**：将低置信度结果单独标记，避免直接替用户做不可靠的决定。

### 5. 结果查看与导出

- **可视化复核**：通过 `review.html` 查看素材预览、分析结果、语音转写和选片结论。
- **分时段浏览**：按 session 查看素材，快速理解一次拍摄中的不同阶段。
- **数据导出**：导出 `cut_index.json` 和 `assets.csv`，便于归档或继续处理。

### 6. Eagle 素材库同步

- **同步预览与执行**：写入 Eagle 前可先预览同步结果。
- **智能命名与标注**：同步素材名称、评分、标签、描述和语音信息。
- **双视图目录整理**：同一素材同时保留原始来源目录和拍摄批次目录，不会重复导入文件。
- **幂等增量同步**：重复同步会复用现有项目目录，并支持跳过已同步素材、重试失败项和重建同步结果。
- **智能分类维护**：维护 TripClipper 专用标签组和 Smart Folder。
- **素材库保护**：可校验当前 Eagle 素材库，降低误写风险。

### 7. 自动粗剪

- **初版时间线生成**：从候选池和推荐片段中生成第一版粗剪计划。
- **目标时长控制**：按项目目标时长选择和排列素材。
- **可追溯选片**：保留每段素材的来源、候选状态和入选理由。

> 自动粗剪目前通过 Python API 使用，尚未接入 CLI。

### 8. 剪映草稿生成

- **草稿导出**：将粗剪计划转换为包含视频、音频、图片和文字轨的剪映草稿。
- **草稿安装**：把生成结果安装到剪映 10 草稿目录，并复制所需媒体。
- **安全回滚**：安装失败时清理不完整草稿，避免污染现有项目。

> 剪映草稿导出与安装目前通过 Python API 使用，尚未接入 CLI。

## 安装

```bash
# 仅安装运行依赖
pip install -e .

# 同时安装开发依赖
pip install -e ".[dev]"
```

## 使用 CLI

`tripclipper` 命令通常安装在项目自己的虚拟环境中，而不是系统全局环境。

可以选择以下任一方式运行：

```bash
# 方式一：激活虚拟环境
source .venv/bin/activate
tripclipper --help
```

```bash
# 方式二：直接调用虚拟环境中的命令
.venv/bin/tripclipper --help
```

如果还没有 `.venv`，可以先创建并安装项目：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## 运行要求

素材扫描与完整流程依赖以下本地工具：

- `ffmpeg`
- `ffprobe`

如果缺少任一工具，`scan` 和 `run` 会直接停止并提示错误。在 macOS 上可以通过 Homebrew 安装：

```bash
brew install ffmpeg
```

## 常用流程

### 1. 使用已有配置创建项目

```bash
tripclipper init --config path/to/project.yaml
```

### 2. 生成项目配置模板

```bash
tripclipper init \
  --scaffold ./project.demo.yaml \
  --project-name "Demo Project" \
  --source-folder /absolute/path/to/raw-media
```

`project.yaml` 可以配置剪辑目标，例如成片风格和目标时长：

```yaml
output_style: "travel vlog"
target_length: "120s"
```

`target_length` 支持秒数或时间码格式；未填写时，自动粗剪默认以 90 秒为目标。

### 3. 一键运行完整流程

```bash
tripclipper run <slug>
```

`run` 会：

- 依次执行 `scan → sample → full → cluster → export`
- 将结果写入 `projects/<slug>/exports/`
- 完成后自动打开 `review.html`

### 4. 分阶段运行

```bash
tripclipper analyze --stage scan --config path/to/project.yaml
tripclipper analyze <slug> --stage sample
tripclipper analyze <slug> --stage full
tripclipper analyze <slug> --stage cluster
tripclipper export <slug>
```

常用选项：

```bash
# 扫描时跳过缩略图与关键帧提取
tripclipper analyze --stage scan --config path/to/project.yaml --no-extract-media

# 重新分析已完成素材
tripclipper analyze <slug> --stage full --force

# 控制分析并发数
tripclipper analyze <slug> --stage sample --concurrency 3
tripclipper analyze <slug> --stage full --concurrency 3

# sample 完成后暂停，人工确认后继续
tripclipper run <slug> --pause-after sample
```

### 5. 导出复核结果

```bash
tripclipper export <slug>
tripclipper export <slug> --cut-index-only
```

默认生成 `cut_index.json`、`assets.csv` 和 `review.html`。使用 `--cut-index-only` 时仍会生成前两项，但跳过 `review.html`。

### 6. 同步到 Eagle

```bash
# 仅预览，不写入 Eagle
tripclipper sync-eagle <slug> --dry-run

# 正式写入
tripclipper sync-eagle <slug> --apply

# 跳过已同步素材
tripclipper sync-eagle <slug> --apply --skip

# 仅重试失败素材
tripclipper sync-eagle <slug> --apply --retry-failed

# 跳过尚未分析的素材
tripclipper sync-eagle <slug> --apply --skip-unanalyzed

# 将已同步项目移入 Eagle 回收站后重建
tripclipper sync-eagle <slug> --apply --reset

# 重建时跳过二次确认
tripclipper sync-eagle <slug> --apply --reset --yes

# 禁止未声明字段自动映射为标签
tripclipper sync-eagle <slug> --apply --strict-mapping

# 跳过 Smart Folder 维护
tripclipper sync-eagle <slug> --apply --no-smart-folders

# 限定目标 Eagle 素材库
tripclipper sync-eagle <slug> --apply \
  --library-path /Users/you/Pictures/MyLibrary.library
```

## CLI 参数说明

查看帮助和版本：

```bash
tripclipper --help
tripclipper --version
```

### `tripclipper init`

创建或初始化项目，也可以生成新的 `project.yaml` 模板。

```bash
tripclipper init [OPTIONS]
```

参数：

- `--config TEXT`：已有 `project.yaml` 的路径
- `--scaffold TEXT`：生成新配置模板的目标路径
- `--project-name TEXT`：项目名称；与 `--scaffold` 一起使用
- `--source-folder TEXT`：原始素材目录；与 `--scaffold` 一起使用
- `--base-dir TEXT`：自定义项目根目录
- `--force / --no-force`：目标已存在时是否覆盖

### `tripclipper analyze`

手动运行指定分析阶段。

```bash
tripclipper analyze [OPTIONS] [SLUG]
```

参数：

- `--config TEXT`：`project.yaml` 路径，主要用于 `scan`
- `--base-dir TEXT`：自定义项目根目录
- `--stage [scan|sample|full|cluster]`：选择处理阶段
- `--no-extract-media / --extract-media`：是否提取缩略图和关键帧
- `--force / --no-force`：是否重新分析已完成素材
- `--concurrency INTEGER`：sample/full 并发数，默认 `5`

示例：

```bash
tripclipper analyze --stage scan --config path/to/project.yaml
tripclipper analyze demo-scan --stage sample
tripclipper analyze demo-scan --stage full --force --concurrency 3
tripclipper analyze demo-scan --stage cluster
```

### `tripclipper run`

一键执行常规素材处理流程。

```bash
tripclipper run [OPTIONS] SLUG
```

参数：

- `--base-dir TEXT`：自定义项目根目录
- `--pause-after [sample]`：sample 完成后暂停，按回车继续
- `--concurrency INTEGER`：sample/full 并发数，默认 `5`

### `tripclipper export`

生成可视化复核和数据导出文件。

```bash
tripclipper export [OPTIONS] SLUG
```

参数：

- `--base-dir TEXT`：自定义项目根目录
- `--cut-index-only / --no-cut-index-only`：生成 `cut_index.json` 和 `assets.csv`，跳过 `review.html`

默认行为：

- 生成并自动打开 `review.html`
- 所有导出文件写入 `projects/<slug>/exports/`

### `tripclipper sync-eagle`

预览或执行 Eagle 同步。

```bash
tripclipper sync-eagle [OPTIONS] SLUG
```

参数：

- `--base-dir TEXT`：自定义项目根目录
- `--apply / --dry-run`：正式执行或仅预览；默认 `--dry-run`
- `--skip`：跳过已同步素材
- `--reset`：将已同步 Eagle item 移入回收站并清除同步状态
- `--retry-failed`：仅处理上次同步失败的素材
- `--skip-unanalyzed`：跳过尚未完成分析的素材
- `--strict-mapping`：关闭未知字段自动映射
- `--no-smart-folders`：跳过 Smart Folder 维护
- `--library-path TEXT`：要求 Eagle 当前打开指定素材库
- `--yes`：执行 `--reset` 时跳过二次确认

### `tripclipper serve`

启动本地页面。当前仍为占位功能。

```bash
tripclipper serve [OPTIONS]
```

参数：

- `--host TEXT`：监听地址，默认 `127.0.0.1`
- `--port INTEGER`：监听端口，默认 `8765`

## Eagle 素材库保护

`sync-eagle` 可以校验当前打开的 Eagle 素材库，防止误写。

可以在 `project.yaml` 中配置目标素材库：

```yaml
eagle_sync:
  api_base_url: http://localhost:41595
  library_path: /Users/you/Pictures/MyLibrary.library
```

也可以通过命令行指定：

```bash
tripclipper sync-eagle <slug> --apply --library-path /Users/you/Pictures/MyLibrary.library
```

配置优先级：

1. `--library-path`
2. `project.yaml.eagle_sync.library_path`
3. 未配置：不启用素材库路径校验

## 开发与测试

```bash
pytest -q
```
