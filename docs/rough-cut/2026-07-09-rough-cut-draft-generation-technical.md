# TripClipper 粗剪与剪映草稿生成技术文档

日期：2026-07-09

> **本轮修订范围：** 本次 grilling 只确认并修订 R0（Fixture 包）、R1（RoughCutPlan Schema）、R2（Jianying10Installer）、R3（JianyingDraftExporter + PyJianYingDraftAdapter）。本文中涉及 R4-R6 的内容保留原技术方向，后续实现前需要单独复审。

配套设计文档：

```text
docs/rough-cut/2026-07-09-rough-cut-draft-generation-design.md
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
      pyjianying_work/
```

剪映 10 默认草稿库：

```text
~/Movies/JianyingPro/User Data/Projects/com.lveditor.draft
```

`exports/jianying/<draft_id>/` 只保存中间产物和报告；最终草稿目录写入剪映草稿库下的新目录。

`draft_id` 采用：

```text
tc-<slug>-<YYYYMMDD-HHMMSS>-<random6>
```

同一次导出的 `draft_id` 默认也作为安装到剪映草稿库时的新草稿目录名前缀，便于从 TripClipper 导出记录追踪到剪映草稿。

## 3. `RoughCutPlan` 最小 schema

第一版 schema 只表达剪辑计划，不表达剪映文件结构。

顶层字段：

```text
schema_version
project
intent
source_snapshot
timeline
unused_assets
warnings
created_at
```

关键字段：

- `schema_version`: 独立版本号，第一版为 `0.1`。
- `project`: `project_slug`、`cut_index_path`、`project_config_path`。
- `intent`: `target_duration_sec`、`output_style`、`audience`、`people_focus`、`audio_priority`。
- `source_snapshot`: 输入素材数、候选池数、雷同组数。
- `timeline`: 粗剪时间线元素列表。所有视频、图片、音频、文本都作为 timeline item 表达，不再使用顶层 `text_overlays`、`bgm` 或 `transitions` 字段。

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
volume
text_overlay
transition_in
transition_out
reason
candidate_status_snapshot
selection_override_reason
tags
```

时间统一用 float 秒：

```text
source_range.start_sec
source_range.end_sec
timeline_range.start_sec
timeline_range.end_sec
```

`track_type` 第一版取值：

```text
video
audio
image
text
```

时间线以 `(track_type, track_index)` 表示一条具体轨道。不同轨道之间允许重叠；同一轨道内不允许重叠。图片在 `rough_cut_plan.json` 中使用 `track_type="image"`，导出到剪映/pyJianYingDraft 时再映射到剪映内部的图片或视频素材结构。

校验规则：

- `asset_id` 必须能在 `cut_index.json` 找到。
- planner 生成计划时，`asset_path` 必须存在。
- exporter 消费计划时，优先用当前 `cut_index.json` 和 `asset_relative_path` 重新解析路径，失败再回退 `asset_path`。
- `asset_id + asset_relative_path` 是素材主身份；`asset_path` 是生成计划时的路径快照和兜底。
- 视频和音频必须有 `source_range`。
- 图片和文本必须没有 `source_range`。
- 视频、音频、图片必须有 `asset_id`、`asset_relative_path`、`asset_path`。
- 文本不需要素材身份字段，但必须有 `text_overlay`。
- `timeline_range.end_sec > timeline_range.start_sec`。
- 每个 `(track_type, track_index)` 轨道内的 `timeline_range` 不能重叠。
- 默认不允许使用 `excluded` 素材；如果使用，必须有 `selection_override_reason`。
- `candidate_status_snapshot` 是生成计划时 `cut_index.assets[*].edit_candidate_status` 的快照，取值复用 `EditCandidateStatus`；它只用于审阅、解释和校验，不用于 exporter 二次筛选。
- `unused_assets` 保留，但第一版允许为空，不要求覆盖所有未用素材；后续 planner 只记录值得解释的未用素材。

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
- exporter 可以读取 `plan.project.cut_index_path` 只用于路径解析和校验；adapter 不读取 `cut_index.json` 做二次素材筛选。
- pyJianYingDraft 可以在 `output_dir/pyjianying_work/` 下创建中间草稿目录；该目录默认保留用于调试。
- adapter 能力不足时，要在 `warnings` 中说明降级，例如不支持转场或文本样式。

默认 engine：

```text
pyjianyingdraft
```

`vectcutapi` 后置实现。

R3 自动验收需要用 fixture 中的正式 `minimal_rough_cut_plan.json` 生成新的 `draft_content.json`，并与真实 `realistic_draft_content.json` 做语义比较。比较范围包括主视频轨素材顺序、`source_timerange`、`target_timerange`、BGM 轨、图片覆盖轨、文本轨内容与时间范围；不要求 id、字段顺序、时间戳、剪映版本字段或 pyJianYingDraft 自动生成的辅助字段字节级一致。

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
asset_mode: copy
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

检查失败时不创建草稿目录，并把失败原因写入安装报告。

### 6.2 草稿写入规则

每次安装：

- 创建唯一草稿目录。
- 生成新的 `timeline_id = uuid.uuid4().hex`。
- 从模板复制草稿外壳。
- 把素材复制到草稿内 `assets/`。第一版只支持 `copy`，不实现 hardlink。
- 重写 `draft_content.json` 里的素材路径。
- `install_report.json` 写到 `draft_content.json` 同目录，不写进剪映草稿目录。
- 新草稿目录名采用 `tc-<draft_name_slug>-<YYYYMMDD-HHMMSS>-<random6>`，最多重试 5 次，不覆盖已有目录。

素材收集和路径重写规则：

```text
materials.videos[].path
materials.audios[].path
materials.images[].path
```

如果上述对象存在 `remote_url`，也需要处理；fixture 中没有该字段时不强制造出。素材收集以明确媒体字段中的实际 `path` 是否存在为准，不递归改写所有 `*_path` 字段；`algorithm_artifact_path`、`static_cover_image_path`、`source_feature_path` 等第一版不碰。

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

所有引用旧 timeline id 的位置都必须替换为新 `timeline_id`。

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
- 同一 `(track_type, track_index)` 内重叠失败，不同轨道重叠允许。
- 只有 video/audio 允许并要求 `source_range`；image/text 不允许 `source_range`。
- 文本 segment 必须有 `text_overlay`，非文本 segment 不允许 `text_overlay`。

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
- pyJianYingDraft 生成的 draft 与真实 fixture 做语义比较。

installer：

- 安装前检查失败时不写草稿目录。
- 写入 7 个关键文件。
- 替换新 `timeline_id`。
- 素材路径全部存在。
- 旧路径和临时路径不再出现在草稿 JSON 中。
- `install_report.json` 保留在 `draft_content.json` 同目录。
- 每次安装生成唯一 `tc-...` 草稿目录。

人工冒烟：

- 剪映 10 能看到新草稿。
- 打开不丢素材。
- 时间线顺序正确。
- 保存后再次打开可用。

## 10. 依赖策略

- `pyJianYingDraft` 是第一版 R3 默认且必需的导出依赖，应进入核心依赖。
- `VectCutAPI` 第一版不做必需依赖，作为 R6 后续可选 adapter。

## 11. R0-R3 Grilling Amendments

本节只归档本轮 grilling 对 R0-R3 的修订范围：

- R0 Fixture 包。
- R1 RoughCutPlan Schema / IO / Validator。
- R2 Jianying10Installer。
- R3 JianyingDraftExporter + pyJianYingDraft adapter。

R4-R6 不在本轮修订范围内，后续如需调整 planner、CLI 或 VectCutAPI adapter，应单独 grilling。
