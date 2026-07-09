# TripClipper 粗剪与剪映草稿生成技术文档

日期：2026-07-09

配套设计文档：

```text
docs/superpowers/specs/2026-07-09-rough-cut-draft-generation-design.md
```

## 1. 代码结构

新增模块：

```text
src/tripclipper/roughcut/
  models.py
  planner.py
  validator.py
  io.py

src/tripclipper/jianying/
  models.py
  draft_exporter.py
  installer.py
  adapters/
    base.py
    pyjianyingdraft.py
    vectcutapi.py
```

原则：

- `src/tripclipper/models.py` 继续只管 `cut_index.json`。
- 粗剪计划模型放在 `roughcut.models`。
- 剪映导出和安装模型放在 `jianying.models`。

## 2. 路径约定

项目产物：

```text
projects/<slug>/
  rough_cut_plan.json
  exports/
    roughcut/
      rough_cut_plan.md
      rough_cut_plan.csv
    jianying/<draft_id>/
      draft_content.json
      draft_meta_info.json
      install_report.json
```

剪映 10 默认草稿库：

```text
~/Movies/JianyingPro/User Data/Projects/com.lveditor.draft
```

`exports/jianying/<draft_id>/` 只保存中间产物和报告；最终草稿目录写入剪映草稿库下的新目录。

## 3. `RoughCutPlan` 最小 schema

第一版 schema 只表达剪辑计划，不表达剪映文件结构。

顶层字段：

```text
schema_version
project
intent
source_snapshot
timeline
text_overlays
bgm
transitions
unused_assets
warnings
created_at
```

关键字段：

- `schema_version`: 独立版本号，第一版为 `0.1`。
- `project`: `project_slug`、`cut_index_path`、`project_config_path`。
- `intent`: `target_duration_sec`、`output_style`、`audience`、`people_focus`、`audio_priority`。
- `source_snapshot`: 输入素材数、候选池数、雷同组数。
- `timeline`: 粗剪片段列表。

片段字段：

```text
segment_id
asset_id
asset_path
asset_relative_path
asset_type
source_range
timeline_range
track_type
track_index
audio_mode
reason
source_candidate_status
selection_override_reason
tags
```

时间统一用秒：

```text
source_range.start_sec
source_range.end_sec
timeline_range.start_sec
timeline_range.end_sec
```

校验规则：

- `asset_id` 必须能在 `cut_index.json` 找到。
- planner 生成计划时，`asset_path` 必须存在。
- exporter 消费计划时，优先用当前 `cut_index.json` 和 `asset_relative_path` 重新解析路径，失败再回退 `asset_path`。
- 视频和音频必须有 `source_range`，图片可以没有。
- `timeline_range.end_sec > timeline_range.start_sec`。
- 同一主视频轨上的片段不能重叠。
- 默认不允许使用 `excluded` 素材；如果使用，必须有 `selection_override_reason`。

## 4. Planner 契约

接口：

```text
RoughCutPlanner.plan(request) -> RoughCutPlan
```

请求字段：

```text
slug
base_dir
target_duration_sec
max_segments
include_alternates
allow_needs_review
```

第一版启发式策略：

1. 读取 `cut_index.json`。
2. 优先选择 `edit_candidate_status=default_selected`。
3. 按 `edit_candidate_priority` 升序、`rating` 降序排序。
4. 优先使用 `clip_suggestions`。
5. 默认不选 `needs_review` 和 `excluded`。
6. 默认候选不足时，可按参数补充 `alternate`。

LLM planner 后续可以替换选择策略，但输出必须通过同一 schema 校验。

## 5. Exporter 契约

接口：

```text
JianyingDraftExporter.export(plan, output_dir, engine) -> DraftExportResult
```

输出：

```text
engine
draft_content_path
draft_meta_info_path
media_paths
warnings
```

约束：

- exporter 只写 `output_dir`。
- exporter 不写剪映草稿库。
- adapter 不读取 `cut_index.json` 做二次筛选。
- adapter 能力不足时，要在 `warnings` 中说明降级，例如不支持转场或文本样式。

默认 engine：

```text
pyjianyingdraft
```

`vectcutapi` 后置实现。

## 6. Installer 契约

接口：

```text
Jianying10Installer.install(request) -> DraftInstallResult
```

请求字段：

```text
draft_content_path
draft_name
jianying_library_dir
template_dir
asset_mode: copy | hardlink
```

结果字段：

```text
draft_dir
timeline_id
asset_count
written_files
validations
warnings
```

### 6.1 安装前检查

安装前检查默认每次 install 都执行。检查：

- `draft_content_path` 存在。
- `jianying_library_dir` 存在。
- `template_dir` 包含必要模板文件。
- 目标草稿目录不存在。
- 素材文件可读。
- `hardlink` 模式在当前文件系统可用。

检查失败时不创建草稿目录，并把失败原因写入安装报告。

### 6.2 草稿写入规则

每次安装：

- 创建唯一草稿目录。
- 生成新的 `timeline_id`。
- 从模板复制草稿外壳。
- 把素材复制或硬链接到草稿内 `assets/`。
- 重写 `draft_content.json` 里的素材路径。

至少重写：

```text
materials.videos[].path
materials.videos[].remote_url
materials.audios[].path
materials.audios[].remote_url
materials.images[].path
materials.images[].remote_url
```

### 6.3 剪映 10 关键文件

安装器必须写入并保持内容一致：

```text
draft_content.json
draft_content.json.bak
template-2.tmp
Timelines/<timeline_id>/draft_content.json
Timelines/<timeline_id>/draft_content.json.bak
Timelines/<timeline_id>/template.tmp
Timelines/<timeline_id>/template-2.tmp
```

还需要更新模板外壳中的：

```text
project.json
timeline_layout.json
draft_meta_info.json
```

## 7. CLI

```bash
tripclipper roughcut plan <slug> --target-duration 90
tripclipper jianying export <slug> --engine pyjianyingdraft
tripclipper jianying install --draft-content <path> --name <draft_name>
tripclipper jianying create <slug> --target-duration 90 --engine pyjianyingdraft
```

`create` 等价于：

```text
roughcut plan -> jianying export -> jianying install
```

任一阶段失败时停止，并保留前一阶段成功产物。

## 8. 错误处理

建议异常：

```text
RoughCutValidationError
DraftExportError
DraftInstallError
```

CLI 规则：

- 用户输入错误退出码为 2。
- 业务失败退出码为 1。
- 不打印裸堆栈。
- 错误信息要说明失败阶段和建议动作。
- 安装失败时清理本次创建的不完整草稿目录。
- 保留 `draft_content.json` 和 `install_report.json` 便于重试。

## 9. 测试重点

`RoughCutPlan`：

- 合法计划可读写。
- 非法时间范围失败。
- 缺失 asset 失败。
- timeline 重叠失败。
- `excluded` 无 override reason 失败。

planner：

- 默认只选 `default_selected`。
- 默认不选 `needs_review` 和 `excluded`。
- 每个片段有 reason。
- 总时长接近目标时长。

exporter：

- 同一 plan 输出稳定。
- 不修改源素材。
- 不重新筛选素材。
- adapter 降级写入 warnings。

installer：

- 安装前检查失败时不写草稿目录。
- 写入 7 个关键文件。
- 替换新 `timeline_id`。
- 素材路径全部存在。
- 旧路径和临时路径不再出现在草稿 JSON 中。

人工冒烟：

- 剪映 10 能看到新草稿。
- 打开不丢素材。
- 时间线顺序正确。
- 保存后再次打开可用。

## 10. 依赖策略

- `pyJianYingDraft` 作为可选依赖或运行时探测，不进入核心依赖。
- `VectCutAPI` 第一版不做必需依赖。
- 缺少 adapter 依赖时，CLI 给出明确安装提示。
