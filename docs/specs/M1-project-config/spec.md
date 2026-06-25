# M1 项目创建与配置 Spec

> 覆盖：PRD FR-1、PRD 5.1（步骤 1-2）、9.1（创建项目）；TD 4 / 7 / 13(#2)
> 依赖：M0（数据契约、`load_config`、`ProjectConfig`、`init_cut_index`、目录管理、脱敏工具）
> 角色：M1 是把 M0 的"数据契约 + 配置加载"组装成**用户可用的"创建/初始化项目"能力**的编排层。它不实现扫描（M2）、模型分析（M3）、导出（M5）、Eagle（M6）、FastAPI 页（M7）。

## Why

M0 已经能解析与校验 `project.yaml` 并定义 `cut_index.json` 数据模型，但还没有任何用户可触发的"把一个素材整理任务保存为独立项目"的入口。FR-1 要求用户能：创建项目、看到配置摘要、在素材目录不存在时被明确提示修正、在模型配置不完整时仍可保存项目（但 Stage 2 不可成功）、修改配置后重新执行后续流程。M1 把这些固化为一套**可复用的核心函数 + 一个 CLI 入口**，供后续 CLI 流程与 M7 的 FastAPI 页共同消费（架构原则：CLI/API 核心逻辑可复用）。

## What Changes

- 新增核心模块 `src/tripclipper/project.py`，提供：
  - `validate_source_folder(path)`：判断素材目录是否存在且为目录，返回结构化结果（是否可用 + 原因）。
  - `build_project_summary(config, *, base_dir=None)`：由 `ProjectConfig` 生成**不含密钥**的项目配置摘要对象 `ProjectSummary`，含模型配置可用性、素材目录是否存在、项目目录与产物标准路径。
  - `init_project(config_path, *, base_dir=None, force=False)`：端到端"创建/初始化项目"。加载配置 → 校验素材目录 → 生成 slug → 幂等创建项目目录 → 把 `project.yaml` 落到项目目录（规范位置）→ 初始化或更新 `cut_index.json` 的 `project` 块 → 返回 `ProjectSummary`。
  - `scaffold_config_file(path, *, project_name, source_folder, force=False)`：在指定路径写出一份带建议字段的 `project.yaml` 模板，便于用户从零"创建"配置（不含任何密钥明文，`model_config` 用 `api_key_env` 指向环境变量名）。
- 新增 CLI 子命令 `tripclipper init`（接线到 `init_project` / `scaffold_config_file`），创建/初始化项目并打印配置摘要；错误以面向用户的清晰信息呈现并以非 0 退出码结束。
- 行为约束：
  - **素材目录不存在或不可访问** → `init_project` 抛出清晰的 `ProjectError`，提示用户修正，不产生误导性项目结果（TD 12）。
  - **模型配置不完整** → 项目仍可创建/保存，`ProjectSummary.model_usable=False`，并在 `cut_index.json.warnings` 写入一条非阻塞警告，明确"Stage 2 暂不可执行成功"。
  - **重复初始化幂等**：对已存在的项目再次 `init`，不清空已有 `assets`/`analysis`/`similar_groups` 等结果，仅刷新 `project` 块并更新 `updated_at`；未加 `force` 时不覆盖已存在产物中的素材数据。
  - **不修改原始素材**：仅以只读方式引用 `source_folder`（复用 M0 安全边界）。

不在 M1 范围（留给后续模块）：Stage 1 扫描与 ffmpeg/ffprobe（M2）、模型 provider 与 Stage 2（M3）、雷同/候选（M4）、导出器（M5）、Eagle（M6）、FastAPI `POST /create-config` 与状态面板（M7）。

## Impact

- 影响的能力：扫描（M2）、分析（M3）、导出（M5）、Eagle（M6）、本地页（M7）都将以 M1 创建出的项目目录与初始化好的 `cut_index.json` 为起点。
- 影响的代码：
  - 新增 `src/tripclipper/project.py`
  - 修改 `src/tripclipper/cli.py`（新增 `init` 子命令）
  - 新增 `tests/test_project.py`
  - 回写 `docs/specs/README.md` 模块状态
- 不改动 M0 的数据契约与字段口径（无 BREAKING）。

## 关键设计决策

- **复用而非重定义**：`init_project` 直接调用 M0 的 `load_config`、`generate_project_slug`、`ensure_project_dirs`、`init_cut_index`、`read_cut_index`/`write_cut_index`、`summarize_model_config`，不重复实现校验或字段口径。
- **project.yaml 规范位置**：项目的事实配置落在 `projects/<slug>/project.yaml`（TD 7）。当用户传入的配置文件不在项目目录内时，以**逐字复制**（不重新序列化）方式落入项目目录，避免丢失注释/字段顺序，也避免把环境变量解析后的密钥写入文件。`cut_index.json.project.config_path` 指向项目目录内的规范副本。
- **摘要不含密钥**：`ProjectSummary` 与其打印输出只暴露 provider / base_url / 各 model 名 / `api_key_env` 名称 / language / sample_size（复用 `summarize_model_config`），绝不含密钥明文。
- **幂等与可重入**：再次 `init` 时读回已存在的 `cut_index.json`，只更新 `project` 块（含 `updated_at`、`editing_intent`、`model_config_summary`、`eagle_sync`、`source_folder`、`config_path`），保留 `assets`/`analysis`/`similar_groups`/`default_candidates`/`failures` 既有内容，满足 FR-1"修改配置后重新执行后续流程"。
- **目录基准可注入**：`init_project` 接受可选 `base_dir`（默认 `<cwd>/projects`），便于测试与多工作区，沿用 M0 `paths` 模块的 `base_dir` 约定。

## ADDED Requirements

### Requirement: 项目创建与初始化
系统 SHALL 提供从 `project.yaml` 创建/初始化项目的能力：加载并校验配置、生成稳定 `project_slug`、幂等创建 `projects/<slug>/` 与 `cache/{thumbnails,frames,transcripts}/`、把配置落到项目目录规范位置、初始化 `cut_index.json`，并返回不含密钥的配置摘要。

#### Scenario: 合法配置创建项目成功
- **WHEN** 用包含 `project_name`、`source_folder`（存在的目录）、`model_config` 的合法 `project.yaml` 执行初始化
- **THEN** 创建 `projects/<slug>/`、`cache/{thumbnails,frames,transcripts}/`、项目目录内 `project.yaml` 副本与 `cut_index.json`；返回的摘要含项目名、slug、素材目录、editing_intent、模型配置摘要、模型可用性、各产物标准路径

#### Scenario: 初始化后落盘的 cut_index 含完整 project 块
- **WHEN** 初始化完成后读取 `projects/<slug>/cut_index.json`
- **THEN** `project` 块含 `project_name`、`project_slug`、`source_folder`、`config_path`（指向项目目录内副本）、`editing_intent`、`model_config_summary`、`eagle_sync`、`created_at`、`updated_at`；`assets` 等为空数组

### Requirement: 配置摘要可见且不含密钥
系统 SHALL 生成并展示项目配置摘要，包含模型配置是否可用、素材目录是否存在；摘要与其打印输出绝不包含密钥明文。

#### Scenario: 摘要展示模型可用性与目录状态
- **WHEN** 为一个已加载的合法配置构建摘要
- **THEN** 摘要含 `model_usable`（布尔）与 `source_folder_exists`（布尔），模型配置摘要仅含 provider/模型名/`api_key_env` 名称等非密钥字段

#### Scenario: 摘要不泄露密钥
- **WHEN** `project.yaml` 的 `model_config` 通过 `api_key_env` 指向密钥环境变量
- **THEN** 摘要、打印输出与落盘 `cut_index.json` 均只含 `api_key_env` 名称，不含密钥值

### Requirement: 素材目录校验
系统 SHALL 在创建/初始化项目时校验 `source_folder` 是否存在且为目录；不存在或不可访问时给出面向用户的清晰错误并提示修正，不生成误导性项目结果。

#### Scenario: 素材目录不存在报清晰错误
- **WHEN** `source_folder` 指向不存在的路径执行初始化
- **THEN** 抛出可读的 `ProjectError`，明确指出目录不存在并提示用户修正；不写入误导性素材结果

#### Scenario: source_folder 指向文件而非目录报错
- **WHEN** `source_folder` 指向一个文件
- **THEN** 抛出可读的 `ProjectError`，说明该路径不是目录

### Requirement: 模型配置不完整仍可保存项目
系统 SHALL 在 `model_config` 不完整时仍允许创建/保存项目，但明确标记模型不可用，使 Stage 2 不能被视为可成功执行。

#### Scenario: 模型配置缺失仍能创建项目
- **WHEN** `project.yaml` 的 `model_config` 缺少 `vision_model`/`api_key_env` 等关键字段，但 `project_name`、`source_folder` 合法
- **THEN** 项目仍被创建并初始化 `cut_index.json`；摘要 `model_usable=False`；`cut_index.json.warnings` 含一条非阻塞警告，说明模型配置不完整、Stage 2 暂不可执行成功

### Requirement: 重复初始化幂等且不破坏已有结果
系统 SHALL 支持对已存在项目重复初始化以反映配置修改；重复初始化不得清空已有的素材与分析结果。

#### Scenario: 修改配置后重新初始化保留已有素材
- **WHEN** 已存在含若干 `assets` 与 `analysis` 的项目，修改 `project.yaml`（如改 `target_length`）后再次初始化
- **THEN** `cut_index.json` 的 `assets`/`analysis` 等既有内容保留；`project.editing_intent` 与 `updated_at` 被刷新

#### Scenario: 重复初始化不报错
- **WHEN** 对同一项目连续两次初始化
- **THEN** 两次均成功、不抛异常、不清空已有内容

### Requirement: CLI 创建/初始化入口
系统 SHALL 提供 `tripclipper init` 子命令，从配置创建/初始化项目并打印配置摘要；同时支持生成一份 `project.yaml` 模板用于从零创建。

#### Scenario: init 初始化并打印摘要
- **WHEN** 运行 `tripclipper init --config <合法 project.yaml>`
- **THEN** 完成初始化，stdout 打印含项目名、slug、素材目录、模型可用性的配置摘要，退出码为 0

#### Scenario: init 在素材目录缺失时清晰失败
- **WHEN** 运行 `tripclipper init --config <source_folder 不存在的 project.yaml>`
- **THEN** stderr/stdout 给出面向用户的清晰错误并提示修正，退出码非 0，不抛未捕获堆栈

#### Scenario: init 生成配置模板
- **WHEN** 运行 `tripclipper init --scaffold <目标路径> --project-name "X" --source-folder <dir>`
- **THEN** 在目标路径写出含建议字段的 `project.yaml` 模板，`model_config` 以 `api_key_env` 指向环境变量名、不含密钥明文，退出码为 0

## 安全与一致性约束

- 复用 M0 安全边界：`source_folder` 只读引用；摘要与产物均经脱敏，密钥不入任何文件或日志。
- 字段口径以 M0 `models.py` / `config.py` 为唯一来源，M1 不重新定义任何字段或枚举。
