# TripClipper

TripClipper 是一个本地优先的 Python 工具，用来扫描素材目录、分析素材、规划粗剪结果，并以 `cut_index.json` 作为唯一的机器可读事实源。

## 当前状态

当前仓库已经打通了从本地项目初始化到 Eagle 同步的完整 CLI 流程：

- 项目初始化
- 本地素材扫描
- sample / full 分析
- 聚类
- 导出 review 页面
- `sync-eagle` 同步到 Eagle

本地 FastAPI 页面 `serve` 目前仍是占位实现。

## 安装

```bash
# 仅运行时依赖
pip install -e .

# 带开发依赖（pytest）
pip install -e ".[dev]"
```

## 运行前要求

TripClipper 现在对本地媒体工具是严格要求：

- `scan` / `run` 默认要求 `ffmpeg` 和 `ffprobe` 都可用
- 如果任一工具不可用，`tripclipper analyze --stage scan` 和 `tripclipper run` 会直接失败
- 不再静默降级成“没有缩略图也继续跑”

在 macOS 上通常直接安装 Homebrew 版本即可：

```bash
brew install ffmpeg
```

## 常用素材流程

### 1. 用已有 `project.yaml` 初始化项目

```bash
tripclipper init --config path/to/project.yaml
```

### 2. 生成新的 `project.yaml` 模板

```bash
tripclipper init \
  --scaffold ./project.demo.yaml \
  --project-name "Demo Project" \
  --source-folder /absolute/path/to/raw-media
```

### 3. 一条命令跑完整流程

```bash
tripclipper run <slug>
```

当前 `run` 的实际行为：

- 依次执行 `scan -> sample -> full -> cluster -> export`
- 产物输出到 `projects/<slug>/exports/`
- 结束后自动打开 `review.html`

### 4. 手动分阶段运行

```bash
tripclipper analyze --stage scan --config path/to/project.yaml
tripclipper analyze <slug> --stage sample
tripclipper analyze <slug> --stage full
tripclipper analyze <slug> --stage cluster
tripclipper export <slug>
```

一些常用变体：

```bash
# scan 时跳过缩略图 / 关键帧抽取
tripclipper analyze --stage scan --config path/to/project.yaml --no-extract-media

# full 时强制重跑已经 analyzed 的素材
tripclipper analyze <slug> --stage full --force

# 控制 sample / full 阶段并发度
tripclipper analyze <slug> --stage sample --concurrency 3
tripclipper analyze <slug> --stage full --concurrency 3

# 在 sample 后暂停，人工看一眼再继续
tripclipper run <slug> --pause-after sample
```

### 5. 只导出 review 相关产物

```bash
tripclipper export <slug>
tripclipper export <slug> --cut-index-only
```

### 6. 同步到 Eagle

```bash
# 只预览，不写入
tripclipper sync-eagle <slug> --dry-run

# 真正写入 Eagle
tripclipper sync-eagle <slug> --apply

# 增量同步：跳过已经 synced 的素材
tripclipper sync-eagle <slug> --apply --skip

# 仅重试上次失败的素材
tripclipper sync-eagle <slug> --apply --retry-failed

# 跳过未分析素材，而不是启动时报错阻断
tripclipper sync-eagle <slug> --apply --skip-unanalyzed

# 先把已同步 Eagle item 移到回收站，再重建
tripclipper sync-eagle <slug> --apply --reset

# 同上，但跳过二次确认
tripclipper sync-eagle <slug> --apply --reset --yes

# 禁止未声明字段自动映射为 tag
tripclipper sync-eagle <slug> --apply --strict-mapping

# 跳过 smart folder 维护
tripclipper sync-eagle <slug> --apply --no-smart-folders

# 限定必须写入某个 Eagle 库，防止误写
tripclipper sync-eagle <slug> --apply \
  --library-path /Users/you/Pictures/MyLibrary.library
```

## CLI 参数总览

全局帮助：

```bash
tripclipper --help
tripclipper --version
```

### `tripclipper init`

创建 / 初始化项目，或生成新的 `project.yaml` 模板。

```bash
tripclipper init [OPTIONS]
```

参数：

- `--config TEXT`：已有 `project.yaml` 路径
- `--scaffold TEXT`：生成新的 `project.yaml` 模板到该路径
- `--project-name TEXT`：项目名；搭配 `--scaffold` 时必填
- `--source-folder TEXT`：素材目录；搭配 `--scaffold` 时必填
- `--base-dir TEXT`：覆盖项目根目录基准
- `--force / --no-force`：目标已存在时是否覆盖

### `tripclipper analyze`

手动运行某一个阶段。

```bash
tripclipper analyze [OPTIONS] [SLUG]
```

参数：

- `--config TEXT`：`project.yaml` 路径，主要用于 `--stage scan`
- `--base-dir TEXT`：覆盖项目根目录基准
- `--stage [scan|sample|full|cluster]`：指定阶段
- `--no-extract-media / --extract-media`：在 `scan` 阶段跳过或启用缩略图 / 关键帧抽取
- `--force / --no-force`：在 `full` 阶段是否强制重跑已分析素材
- `--concurrency INTEGER`：sample / full 并发数，默认 `5`

示例：

```bash
tripclipper analyze --stage scan --config path/to/project.yaml
tripclipper analyze demo-scan --stage sample
tripclipper analyze demo-scan --stage full --force --concurrency 3
tripclipper analyze demo-scan --stage cluster
```

### `tripclipper run`

一键跑通本地常规流程。

```bash
tripclipper run [OPTIONS] SLUG
```

参数：

- `--base-dir TEXT`：覆盖项目根目录基准
- `--pause-after [sample]`：在 sample 后暂停，等待回车再继续
- `--concurrency INTEGER`：sample / full 并发数，默认 `5`

### `tripclipper export`

生成 review 相关派生产物。

```bash
tripclipper export [OPTIONS] SLUG
```

参数：

- `--base-dir TEXT`：覆盖项目根目录基准
- `--cut-index-only / --no-cut-index-only`：仅复制 `cut_index.json`，跳过 `review.html`

行为说明：

- 默认会生成并自动打开 `review.html`
- 产物写入 `projects/<slug>/exports/`

### `tripclipper sync-eagle`

预览或执行 Eagle 同步。

```bash
tripclipper sync-eagle [OPTIONS] SLUG
```

参数：

- `--base-dir TEXT`：覆盖项目根目录基准
- `--apply / --dry-run`：执行写入或仅预览；默认 `--dry-run`
- `--skip`：跳过已经标记为 `synced` 的素材
- `--reset`：把已同步 Eagle item 移到回收站，并清除 `eagle_item_id`
- `--retry-failed`：仅处理上次标记为 `failed` 的素材
- `--skip-unanalyzed`：跳过 `scanned` 素材，而不是启动时报错阻断
- `--strict-mapping`：禁用 `auto_map_unknown`
- `--no-smart-folders`：跳过 smart folder 维护
- `--library-path TEXT`：要求 Eagle 当前打开指定 `.library`
- `--yes`：跳过 `--reset` 时的二次确认

### `tripclipper serve`

启动本地 FastAPI 页面。目前仍是占位实现。

```bash
tripclipper serve [OPTIONS]
```

参数：

- `--host TEXT`：绑定地址，默认 `127.0.0.1`
- `--port INTEGER`：端口，默认 `8765`

## Eagle 库路径门禁

`sync-eagle` 支持限制“只能写入指定 Eagle 库”，避免误同步到错误库。

可以把期望库路径放进 `project.yaml`：

```yaml
eagle_sync:
  api_base_url: http://localhost:41595
  library_path: /Users/you/Pictures/MyLibrary.library
```

也可以在命令行直接传：

```bash
tripclipper sync-eagle <slug> --apply \
  --library-path /Users/you/Pictures/MyLibrary.library
```

优先级如下：

1. `--library-path`
2. `project.yaml.eagle_sync.library_path`
3. 都未设置：不做库路径门禁

## 开发

```bash
pytest -q
```
