# M0 Tasks

> 阶段：实现阶段（apply）执行。当前为规格阶段，仅定义任务，未实现任何代码。

- [x] Task 1：搭建 Python 项目骨架
  - [x] SubTask 1.1：创建 `pyproject.toml`（项目元信息、依赖 `pydantic>=2`、`pyyaml`、`click` 或 `typer`、开发依赖 `pytest`；`[project.scripts]` 暴露 `tripclipper`）
  - [x] SubTask 1.2：创建 `src/tripclipper/__init__.py`（含 `__version__` 与 `SCHEMA_VERSION = "0.2"`）
  - [x] SubTask 1.3：创建项目根 `README.md`（安装、基本 CLI 用法）
  - [x] SubTask 1.4：`pip install -e .` 可成功安装，`tripclipper --help` 可运行

- [x] Task 2：实现 CLI 子命令骨架（`src/tripclipper/cli.py`）
  - [x] SubTask 2.1：注册 `serve`/`analyze`/`export`/`sync-eagle` 四个子命令及其主要参数（与 TD 3 入口一致）
  - [x] SubTask 2.2：命令体打印"该能力由后续模块提供"占位，退出码正常，不抛未捕获异常

- [x] Task 3：定义字段枚举与数据模型（`src/tripclipper/models.py`）
  - [x] SubTask 3.1：定义枚举 `AssetType`、`AnalysisStatus`、`SubjectType`、`PeoplePresence`、`ShotScale`、`ShotFunction`、`SimilarSelection`、`EditCandidateStatus`
  - [x] SubTask 3.2：定义 `Segment`、`Asset`、`SimilarGroup`、`DefaultCandidate`、`Failure`、`Warning`、`ProjectInfo`、`Capabilities`、`AnalysisInfo` 模型（字段与 TD 7 对齐；警告模型类名用 `WarningItem` 规避内置 `Warning`）
  - [x] SubTask 3.3：定义顶层 `CutIndex` 模型（含 `schema_version`、八大块）

- [x] Task 4：实现 project.yaml 配置（`src/tripclipper/config.py`）
  - [x] SubTask 4.1：定义 `ModelConfig`、`EagleSync`、`EditingIntent`、`ProjectConfig` 模型，必填校验与建议字段默认值（`eagle_sync.enabled=true`、`mode=dry-run`、`sample_size=25`）
  - [x] SubTask 4.2：实现 `load_config(path)`：解析 YAML、相对 `source_folder` 以配置目录为基准解析、缺失必填字段报清晰错误
  - [x] SubTask 4.3：实现 `editing_intent` 聚合与 `model_config` 可用性判断（不完整时标记不可用而非崩溃；字段名 `llm` + alias `model_config` 规避 Pydantic 保留名）
  - [x] SubTask 4.4：实现确定性 `generate_project_slug(project_name)`

- [x] Task 5：实现 cut_index 读写与稳定 ID（`src/tripclipper/cut_index.py`）
  - [x] SubTask 5.1：实现 `init_cut_index(config)` 生成空 `CutIndex`（含 `model_config_summary` 脱敏摘要）
  - [x] SubTask 5.2：实现 `write_cut_index(path, cut_index)` 与 `read_cut_index(path)`，含 schema 校验与 `schema_version` 主版本兼容检查
  - [x] SubTask 5.3：实现 `generate_asset_id(relative_path)` 确定性哈希

- [x] Task 6：实现项目目录管理（`src/tripclipper/paths.py`）
  - [x] SubTask 6.1：实现 `project_dir(slug)`、`cut_index_path(slug)` 等标准路径定位
  - [x] SubTask 6.2：实现 `ensure_project_dirs(slug)` 幂等创建 `cache/{thumbnails,frames,transcripts}`

- [x] Task 7：实现安全边界工具（`src/tripclipper/security.py`）
  - [x] SubTask 7.1：实现 `summarize_model_config(model_config)` 输出脱敏摘要（无密钥明文）
  - [x] SubTask 7.2：实现 `redact_secrets(text)` 兜底脱敏工具，供下游产物写入前复用
  - [x] SubTask 7.3：约定源目录只读访问工具（只读引用，不暴露删除/移动/覆盖能力）

- [x] Task 8：编写测试并通过
  - [x] SubTask 8.1：`tests/test_config.py`（加载、默认值、相对路径、缺失字段、slug 稳定）
  - [x] SubTask 8.2：`tests/test_models.py`（枚举约束、非法枚举被拒）
  - [x] SubTask 8.3：`tests/test_cut_index.py`（初始化、往返序列化、schema_version 不兼容、asset_id 稳定）
  - [x] SubTask 8.4：`tests/test_paths.py`（目录创建、幂等）
  - [x] SubTask 8.5：`tests/test_security.py`（密钥不入摘要、脱敏工具）
  - [x] SubTask 8.6：`pytest` 全绿（19 passed）

- [x] Task 9：回写状态
  - [x] SubTask 9.1：在 `docs/specs/README.md` 模块索引表把 M0 状态更新为"已完成"
  - [x] SubTask 9.2：如实现与 spec 有偏差，回写 `spec.md` 保持事实源一致（无功能性偏差，无需回写）

# Task Dependencies
- Task 2 依赖 Task 1
- Task 3 是 Task 4、Task 5 的基础
- Task 4 依赖 Task 3、Task 7（脱敏摘要）
- Task 5 依赖 Task 3、Task 4、Task 6、Task 7
- Task 8 依赖 Task 2~Task 7
- Task 9 依赖 Task 8
