# M0 项目骨架与数据契约 Spec

> 覆盖：PRD 6.1 / 6.2 / 6.3、4.4；TD 4 / 7 / 12
> 依赖：无（所有其他模块依赖本模块）
> 角色：M0 是整个 TripClipper MVP 的**地基**。它只定义"项目骨架 + 数据契约 + 安全边界"，不实现扫描、模型分析、导出、Eagle 等业务逻辑。

## Why

TripClipper 是从 0 到 1 的本地优先工具，`cut_index.json` 是唯一机器可读事实源，所有后续模块（M1~M8）都围绕它读写。如果没有先把项目骨架、配置口径、数据模型、字段枚举和安全边界一次性钉死，各模块会各自定义字段、口径漂移，导致导出、报告、Eagle 同步互相对不上。M0 把这些口径固定为代码层的单一来源。

## What Changes

- 新建 Python 项目骨架：`pyproject.toml`、包结构 `src/tripclipper/`、CLI 入口 `tripclipper`、项目 `README.md`。
- 定义 `project.yaml` 配置模型与加载/校验逻辑（必填字段、默认值、`editing_intent` 聚合、稳定 `project_slug` 生成）。
- 定义 `cut_index.json`（`schema_version = "0.2"`）的完整数据模型：`project`、`capabilities`、`analysis`、`assets`、`similar_groups`、`default_candidates`、`failures`、`warnings`。
- 定义全部字段枚举：`subject_type`、`people_presence`、`shot_scale`、`shot_function`、`similar_selection`、`edit_candidate_status`、`analysis_status`、`asset.type`。
- 实现 `cut_index.json` 的读写（序列化/反序列化 + schema 校验），并提供稳定 `asset_id` 生成工具。
- 实现项目目录管理：创建/定位 `projects/<project_slug>/` 及 `cache/{thumbnails,frames,transcripts}/`。
- 实现安全边界工具：密钥脱敏（`model_config_summary` 不含明文密钥）、原始素材路径只读约束、可撤销外部写入统一走 dry-run 约定（仅约定与工具，不实现 Eagle）。
- CLI 入口仅注册子命令骨架（`serve`/`analyze`/`export`/`sync-eagle`），命令体打印"未实现/由后续模块提供"占位，不实现业务逻辑。

不在 M0 范围（留给后续模块）：Stage 1 扫描（M2）、ffmpeg/ffprobe 集成（M2）、模型 provider 与 Stage 2 分析（M3）、雷同分组/候选池算法（M4）、导出器（M5）、Eagle（M6）、FastAPI 页（M7）、错误可观测面板（M8）。

## Impact

- 影响的能力：项目配置（M1）、扫描（M2）、分析（M3）、雷同/候选（M4）、导出（M5）、Eagle（M6）、本地页（M7）、可观测（M8）—— 全部消费 M0 定义的数据模型与目录约定。
- 影响的代码（新建）：
  - `pyproject.toml`、`README.md`
  - `src/tripclipper/__init__.py`
  - `src/tripclipper/cli.py`（子命令骨架）
  - `src/tripclipper/config.py`（`project.yaml` 模型、加载、校验、slug 生成、editing_intent 聚合）
  - `src/tripclipper/models.py`（`cut_index.json` 数据模型 + 枚举）
  - `src/tripclipper/cut_index.py`（读写、schema 校验、`asset_id` 生成）
  - `src/tripclipper/paths.py`（项目目录与 cache 目录管理）
  - `src/tripclipper/security.py`（密钥脱敏、只读约束工具）
  - `tests/test_config.py`、`tests/test_models.py`、`tests/test_cut_index.py`、`tests/test_paths.py`、`tests/test_security.py`

## 关键设计决策

- **数据建模库**：使用 Pydantic v2 定义 `project.yaml` 与 `cut_index.json` 模型。原因：后续 M3 需要对模型结构化输出做"本地校验后才写入"（TD 6），Pydantic 提供声明式校验、枚举约束、JSON 序列化，避免手写校验。
- **包布局**：采用 `src/` 布局（`src/tripclipper/`），CLI 通过 `[project.scripts]` 暴露 `tripclipper`。
- **schema_version**：固定常量 `SCHEMA_VERSION = "0.2"`，写入时落盘，读取时校验主版本兼容；不兼容时报清晰错误而非静默迁移。
- **asset_id 稳定性**：基于素材相对 `source_folder` 的相对路径做稳定哈希（如 `sha1(relative_path)[:12]` 加 `asset_` 前缀），保证同一文件多次扫描得到同一 ID（仅定义算法与工具函数，扫描在 M2 调用）。
- **project_slug 稳定性**：由 `project_name` 经确定性规范化（小写、空白/非字母数字转 `-`、去重连字符）生成；显式提供 `project_slug` 时以显式值为准。
- **密钥处理**：`project.yaml` 用 `model_config.api_key_env` 指向环境变量名，配置与 `cut_index.json` 中只保存 `api_key_env` 名称与 provider/模型名，绝不保存密钥明文。

## ADDED Requirements

### Requirement: 项目骨架可安装可运行
系统 SHALL 提供一个可安装的 Python 包 `tripclipper`，暴露 `tripclipper` CLI，且包含 `serve`/`analyze`/`export`/`sync-eagle` 子命令骨架。

#### Scenario: 安装后 CLI 可用
- **WHEN** 在干净环境执行 `pip install -e .` 后运行 `tripclipper --help`
- **THEN** 输出包含 `serve`、`analyze`、`export`、`sync-eagle` 四个子命令，进程退出码为 0

#### Scenario: 子命令骨架占位
- **WHEN** 运行任一子命令（如 `tripclipper export --project demo`）
- **THEN** 命令以清晰信息提示该能力由后续模块提供，不抛未捕获异常、不产生误导性结果

### Requirement: project.yaml 配置加载与校验
系统 SHALL 解析 `project.yaml`，校验必填字段 `project_name`、`source_folder`、`model_config`，应用建议字段默认值，并把 `output_style`/`target_length`/`audience`/`people_focus`/`audio_priority` 聚合为 `editing_intent`。

#### Scenario: 合法配置加载成功
- **WHEN** 传入包含 `project_name`、`source_folder`、`model_config` 的合法 `project.yaml`
- **THEN** 返回配置对象，`editing_intent` 含五个聚合字段，`eagle_sync` 默认 `enabled: true`、`mode: dry-run`

#### Scenario: 缺少必填字段报清晰错误
- **WHEN** `project.yaml` 缺少 `source_folder`
- **THEN** 抛出可读的配置错误，明确指出缺失字段，不产生部分结果

#### Scenario: 相对 source_folder 以配置文件目录为基准
- **WHEN** `source_folder` 为相对路径
- **THEN** 解析为相对 `project.yaml` 所在目录的绝对路径

#### Scenario: model_config 缺失允许保存但标记不可分析
- **WHEN** `model_config` 字段不完整（缺 `vision_model` 或 `api_key_env` 等）
- **THEN** 配置仍可被保存/加载，但模型配置标记为不可用，供后续 Stage 2 据此明确失败

### Requirement: 稳定标识生成
系统 SHALL 根据 `project_name` 生成确定性 `project_slug`，并提供根据素材相对路径生成确定性 `asset_id` 的工具。

#### Scenario: 同名项目得到同一 slug
- **WHEN** 对同一 `project_name`（如 `"2026 Team Event"`）多次生成 slug
- **THEN** 结果一致（如 `2026-team-event`）

#### Scenario: 同一文件得到同一 asset_id
- **WHEN** 对同一相对路径多次生成 `asset_id`
- **THEN** 结果一致，且不同相对路径得到不同 ID

### Requirement: cut_index.json 数据模型与读写
系统 SHALL 定义 `cut_index.json`（`schema_version = "0.2"`）的完整结构，提供读写与 schema 校验，且大型产物只用路径引用、不内嵌二进制或大段文本。

#### Scenario: 空项目可初始化并落盘
- **WHEN** 用合法配置初始化一个空 `cut_index`
- **THEN** 落盘的 JSON 含 `schema_version`、`project`、`capabilities`、`analysis`、`assets`、`similar_groups`、`default_candidates`、`failures`、`warnings` 顶层键，`assets` 等为空数组

#### Scenario: 往返序列化无损
- **WHEN** 写入再读回 `cut_index.json`
- **THEN** 读回的数据对象与写入前在字段与取值上一致

#### Scenario: 非法枚举值被拒绝
- **WHEN** 写入的 asset 含非法 `subject_type`（不在枚举内）
- **THEN** schema 校验失败并报清晰错误，不静默写入

#### Scenario: schema_version 不兼容报错
- **WHEN** 读取的文件 `schema_version` 与当前主版本不兼容
- **THEN** 报清晰错误，不静默迁移或损坏数据

### Requirement: 字段枚举口径单一来源
系统 SHALL 以代码层枚举固定下列取值，其他模块不得重新定义：
- `asset.type`：`video`、`image`、`audio`
- `analysis_status`：`scanned`、`analyzing`、`analyzed`、`analysis_failed`
- `subject_type`：`landscape`、`people`、`people_landscape`、`food`、`building`、`activity`、`object`、`other`
- `people_presence`：`none`、`single`、`multiple`、`small_group`、`crowd`
- `shot_scale`：`extreme_wide`、`wide`、`full`、`medium`、`close_up`、`extreme_close_up`
- `shot_function`：`establishing`、`highlight`、`transition`、`detail`、`reaction`、`dialogue`、`b_roll`、`other`
- `similar_selection`：`primary`、`alternate`、`rejected`、`needs_review`、`none`
- `edit_candidate_status`：`default_selected`、`alternate`、`excluded`、`needs_review`

#### Scenario: 枚举集中可被其他模块引用
- **WHEN** 其他模块需要某字段的合法取值
- **THEN** 能从 `tripclipper.models` 引用同一枚举定义，无需各自硬编码

### Requirement: 项目目录管理
系统 SHALL 在工作目录下管理 `projects/<project_slug>/` 及其 `cache/{thumbnails,frames,transcripts}/` 子目录，并能定位数据包文件路径。

#### Scenario: 创建项目目录结构
- **WHEN** 为某 slug 初始化项目目录
- **THEN** 创建 `projects/<slug>/cache/thumbnails`、`frames`、`transcripts`，并返回 `cut_index.json` 等产物的标准路径

#### Scenario: 重复初始化幂等
- **WHEN** 对已存在的项目目录再次初始化
- **THEN** 不报错、不清空已有内容

### Requirement: 安全边界
系统 SHALL 落实 PRD 4.4 与 TD 12 的安全约束：密钥不写入任何产物、原始素材路径只读、低可撤销外部写入走 dry-run 约定。

#### Scenario: 密钥不进入产物
- **WHEN** 由配置生成 `model_config_summary` 并写入 `cut_index.json`
- **THEN** 摘要只含 provider、模型名、`api_key_env` 名称，绝不含密钥明文；CSV/MD/HTML/日志同样不得含密钥（M0 提供脱敏工具，下游复用）

#### Scenario: 源目录只读约束
- **WHEN** 任何工具需要访问 `source_folder` 下的原始素材
- **THEN** 仅以只读方式引用路径，M0 提供的工具不提供删除/移动/覆盖源素材的能力
