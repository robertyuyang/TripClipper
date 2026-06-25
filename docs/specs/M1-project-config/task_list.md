# M1 Tasks

> 阶段：实现阶段（apply）执行。当前为规格阶段，仅定义任务，未实现任何代码。
> 依赖前置：M0 已完成（`config`、`models`、`cut_index`、`paths`、`security`）。

- [x] Task 1：实现项目编排核心模块（`src/tripclipper/project.py`）
  - [x] SubTask 1.1：定义 `ProjectError(Exception)` 与 `ProjectSummary`（Pydantic 模型或 dataclass）：含 `project_name`、`project_slug`、`source_folder`、`source_folder_exists`、`editing_intent`、`model_config_summary`、`model_usable`、`project_dir`、`config_path`、`cut_index_path`、`warnings`
  - [x] SubTask 1.2：实现 `validate_source_folder(path)`，返回结构化结果（存在且为目录→可用；不存在/非目录→给出面向用户原因）
  - [x] SubTask 1.3：实现 `build_project_summary(config, *, base_dir=None)`，复用 `summarize_model_config` 与 `config.llm.is_usable()`，路径复用 `paths` 模块；摘要不含密钥
  - [x] SubTask 1.4：实现 `scaffold_config_file(path, *, project_name, source_folder, force=False)` 写出建议字段模板（`model_config` 用 `api_key_env`，不含密钥；`force=False` 且目标存在时报 `ProjectError`）

- [x] Task 2：实现 `init_project`（端到端创建/初始化）
  - [x] SubTask 2.1：`load_config(config_path)` → 校验 `source_folder`（缺失/非目录抛 `ProjectError`）→ `ensure_project_dirs(slug, base_dir)`
  - [x] SubTask 2.2：把传入 `project.yaml` 逐字复制到 `projects/<slug>/project.yaml`（不重新序列化，避免密钥/注释问题）；重设 `config.config_path` 指向项目目录副本
  - [x] SubTask 2.3：若 `cut_index.json` 不存在 → `init_cut_index` 落盘；若已存在 → `read_cut_index` 后仅刷新 `project` 块（`updated_at`、`editing_intent`、`model_config_summary`、`eagle_sync`、`source_folder`、`config_path`），保留 `assets`/`analysis` 等
  - [x] SubTask 2.4：模型不可用时向 `cut_index.json.warnings` 追加一条非阻塞 `WarningItem`（stage=`config`，说明模型配置不完整、Stage 2 暂不可成功），去重避免重复初始化堆积
  - [x] SubTask 2.5：返回 `ProjectSummary`

- [x] Task 3：接线 CLI `init` 子命令（`src/tripclipper/cli.py`）
  - [x] SubTask 3.1：新增 `tripclipper init`：`--config` 初始化项目并打印摘要；`--scaffold <path>` + `--project-name` + `--source-folder` 生成模板；可选 `--base-dir`、`--force`
  - [x] SubTask 3.2：捕获 `ProjectError`/`ConfigError`，以面向用户的清晰信息打印并 `sys.exit(非0)`，不抛未捕获堆栈；摘要打印不含密钥

- [x] Task 4：编写测试并通过（`tests/test_project.py`）
  - 测试输入约定：全部用**合成数据**，在 `tmp_path` 中现写 `project.yaml` 字符串 + 用 `mkdir()` 造空 `source_folder` 目录；不放真实素材、不调用真实大模型、不写入真实密钥（密钥仅以 `api_key_env` 名称出现，安全断言用假串如 `"secret123"` 验证不泄露）。沿用 M0 的 `_write_yaml` + `tmp_path` 风格。
  - [x] SubTask 4.1：合法配置创建项目成功，目录与 `cut_index.json` 落盘，`project` 块字段齐全
  - [x] SubTask 4.2：摘要含 `model_usable`/`source_folder_exists`，且不含密钥（断言密钥值不出现在摘要/落盘文件文本中）
  - [x] SubTask 4.3：`source_folder` 不存在 / 指向文件 → 抛 `ProjectError`
  - [x] SubTask 4.4：模型配置不完整仍创建成功，`model_usable=False` 且 `warnings` 含非阻塞配置警告
  - [x] SubTask 4.5：重复初始化幂等——先写入若干 `assets`/`analysis`，改配置后再初始化，断言已有结果保留、`updated_at`/`editing_intent` 刷新
  - [x] SubTask 4.6：`scaffold_config_file` 生成的模板可被 `load_config` 解析，且不含密钥明文
  - [x] SubTask 4.7：CLI `init` 经 `click.testing.CliRunner`：成功路径退出码 0 并打印摘要；素材目录缺失路径退出码非 0 且信息清晰
  - [x] SubTask 4.8：`pytest` 全绿

- [x] Task 5：回写状态
  - [x] SubTask 5.1：`docs/specs/README.md` 模块索引把 M1 状态更新为"已完成"
  - [x] SubTask 5.2：如实现与 spec 有偏差，回写 `spec.md` 保持事实源一致

# Task Dependencies
- Task 2 依赖 Task 1
- Task 3 依赖 Task 1、Task 2
- Task 4 依赖 Task 1~Task 3
- Task 5 依赖 Task 4
