# M1 验收清单

## 如何手动验证本模块

> M1 是项目创建与配置，没有页面，验收靠：CLI 建项目 + 检查落盘的 `cut_index.json` + 单测。

```bash
# 1) 生成一个 project.yaml 模板（不含密钥，使用 api_key_env）
tripclipper init --scaffold ./project.yaml \
  --project-name "Demo" --source-folder /path/to/media

# 2) 用配置初始化项目（退出码 0，打印项目名/slug/素材目录/模型可用性摘要）
tripclipper init --config ./project.yaml

# 3) 检查产物：项目目录、缓存子目录、配置副本与 cut_index.json
ls projects/<slug>/                      # 应有 project.yaml 副本与 cut_index.json
ls projects/<slug>/cache/                # 应有 thumbnails/frames/transcripts
cat projects/<slug>/cut_index.json       # project 节点字段齐全、无密钥明文

# 4) 失败路径：source_folder 不存在时退出码非 0、信息清晰、不抛堆栈
tripclipper init --config <source_folder缺失的配置>

# 5) 单测全绿
pytest -q tests/test_project.py
```

**重点核对**：`cut_index.json.project` 含 `project_name/project_slug/source_folder/config_path/editing_intent/model_config_summary/eagle_sync/created_at/updated_at`；摘要含 `model_usable` 与 `source_folder_exists`；任何输出与落盘都无密钥明文；重复初始化幂等、不清空已有内容。

## 项目创建与初始化
- [x] 合法配置执行初始化后，创建 `projects/<slug>/` 与 `cache/{thumbnails,frames,transcripts}/`
- [x] 项目目录内生成 `project.yaml` 副本与 `cut_index.json`
- [x] `cut_index.json.project` 含 `project_name`/`project_slug`/`source_folder`/`config_path`/`editing_intent`/`model_config_summary`/`eagle_sync`/`created_at`/`updated_at`
- [x] `config_path` 指向项目目录内的规范副本
- [x] 新建项目的 `assets`/`similar_groups`/`default_candidates`/`failures` 为空数组

## 配置摘要
- [x] 摘要含 `model_usable`（布尔）与 `source_folder_exists`（布尔）
- [x] 摘要的模型配置部分仅含 provider/模型名/`api_key_env` 名称/language/sample_size 等非密钥字段
- [x] 摘要、打印输出与落盘 `cut_index.json` 均不含密钥明文

## 素材目录校验
- [x] `source_folder` 不存在时抛 `ProjectError`，信息面向用户并提示修正
- [x] `source_folder` 指向文件而非目录时抛 `ProjectError`，说明不是目录
- [x] 校验失败时不写入误导性素材结果

## 模型配置不完整
- [x] `model_config` 不完整时项目仍创建成功
- [x] 摘要 `model_usable=False`
- [x] `cut_index.json.warnings` 含一条非阻塞警告，说明模型配置不完整、Stage 2 暂不可成功

## 幂等与可重入
- [x] 含已有 `assets`/`analysis` 的项目，修改配置后重新初始化，已有内容保留
- [x] 重新初始化刷新 `project.editing_intent` 与 `updated_at`
- [x] 连续两次初始化均成功、不抛异常、不清空已有内容
- [x] 重复初始化不重复堆积同一条模型配置警告

## CLI 入口
- [x] `tripclipper init --config <合法配置>` 退出码 0 并打印含项目名/slug/素材目录/模型可用性的摘要
- [x] `tripclipper init --config <source_folder 缺失>` 退出码非 0，信息清晰，不抛未捕获堆栈
- [x] `tripclipper init --scaffold <path> --project-name X --source-folder <dir>` 生成可被 `load_config` 解析的模板，`model_config` 用 `api_key_env`、不含密钥

## 安全与一致性
- [x] `source_folder` 仅只读引用，未删除/移动/覆盖源素材
- [x] M1 未重新定义任何 M0 字段或枚举

## 测试与回写
- [x] `tests/test_project.py` 全部用例通过，`pytest` 全绿
- [x] `docs/specs/README.md` 中 M1 状态更新为已完成
