# M0 验收清单

## 如何手动验证本模块

> M0 是项目骨架 + 数据契约，没有页面，验收靠：干净安装 + CLI 骨架占位 + 数据契约单测。

```bash
# 1) 干净环境安装（含开发依赖）
pip install -e ".[dev]"

# 2) CLI 骨架可用（退出码 0，应含 init/serve/analyze/export/sync-eagle）
tripclipper --help
tripclipper serve            # 打印占位信息，不抛异常
tripclipper analyze          # 打印占位信息，不抛异常

# 3) 数据契约相关单测全绿
pytest -q tests/test_models.py tests/test_cut_index.py tests/test_paths.py tests/test_security.py tests/test_config.py
```

**重点核对**：`tripclipper --help` 列出全部子命令；占位子命令不崩溃；空项目落盘的 `cut_index.json` 含八个顶层键 + `schema_version="0.2"`；`model_config_summary` 无密钥明文。

## 项目骨架
- [x] `pip install -e .` 在干净环境安装成功
- [x] `tripclipper --help` 退出码 0，输出含 `serve`/`analyze`/`export`/`sync-eagle`
- [x] 各子命令运行时给出"由后续模块提供"的清晰占位，不抛未捕获异常

## 配置（project.yaml）
- [x] 合法配置加载成功，返回配置对象
- [x] `editing_intent` 正确聚合 `output_style`/`target_length`/`audience`/`people_focus`/`audio_priority`
- [x] `eagle_sync` 默认 `enabled: true`、`mode: dry-run`；`sample_size` 默认 25
- [x] 缺少 `project_name`/`source_folder`/`model_config` 任一时报清晰错误，不产生部分结果
- [x] 相对 `source_folder` 解析为相对 `project.yaml` 目录的绝对路径
- [x] `model_config` 不完整时仍可加载，并标记为不可用（不崩溃）

## 稳定标识
- [x] 同一 `project_name` 多次生成 `project_slug` 结果一致
- [x] 同一相对路径多次生成 `asset_id` 结果一致，不同路径结果不同

## cut_index.json
- [x] 空项目初始化后落盘 JSON 含全部八个顶层键 + `schema_version`
- [x] `schema_version` 落盘为 `"0.2"`
- [x] 写入再读回数据无损（往返一致）
- [x] 非法枚举值（如非法 `subject_type`）被 schema 校验拒绝并报清晰错误
- [x] `schema_version` 主版本不兼容时读取报清晰错误，不静默迁移
- [x] `cut_index.json` 不内嵌图片/视频/音频/大段转写，仅路径引用

## 字段枚举
- [x] `asset.type`/`analysis_status`/`subject_type`/`people_presence`/`shot_scale`/`shot_function`/`similar_selection`/`edit_candidate_status` 取值与 spec 一致
- [x] 枚举集中定义于 `tripclipper.models`，可被其他模块引用

## 项目目录管理
- [x] 初始化创建 `projects/<slug>/cache/{thumbnails,frames,transcripts}`
- [x] 返回 `cut_index.json` 等产物的标准路径
- [x] 对已存在目录重复初始化幂等，不清空已有内容

## 安全边界
- [x] `model_config_summary` 只含 provider/模型名/`api_key_env` 名称，无密钥明文
- [x] 提供可供下游复用的脱敏工具
- [x] 源目录访问工具仅只读引用，不提供删除/移动/覆盖能力

## 测试
- [x] `pytest` 全部用例通过

## 事实源回写
- [x] `docs/specs/README.md` 中 M0 状态更新为已完成
