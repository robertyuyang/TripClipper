# TripClipper 粗剪与剪映草稿生成技术文档

日期：2026-07-09

## 1. 技术目标

本技术文档定义粗剪计划和剪映 10 草稿生成的实现契约。它配套设计文档：

```text
docs/superpowers/specs/2026-07-09-rough-cut-draft-generation-design.md
```

技术目标：

- 用 Pydantic 模型固定 `rough_cut_plan.json` schema。
- 用清晰模块接口隔离 planner、exporter、adapter 和 installer。
- 用文件级不变量固化剪映 10 草稿安装规则。
- 让每一层都可独立测试、独立重跑、独立定位错误。

## 2. 代码结构

建议新增模块：

```text
src/tripclipper/roughcut/
  __init__.py
  models.py
  planner.py
  validator.py
  io.py

src/tripclipper/jianying/
  __init__.py
  draft_exporter.py
  installer.py
  models.py
  paths.py
  adapters/
    __init__.py
    base.py
    pyjianyingdraft.py
    vectcutapi.py
```

建议新增测试：

```text
tests/test_roughcut_models.py
tests/test_roughcut_planner.py
tests/test_jianying_exporter.py
tests/test_jianying_installer.py
tests/fixtures/roughcut/
tests/fixtures/jianying/
```

`src/tripclipper/models.py` 继续作为 `cut_index.json` 的事实源。粗剪模型不要塞进 `models.py`，避免把项目索引模型和下游计划模型混在一起。

## 3. 路径约定

项目产物路径：

```text
projects/<slug>/
  cut_index.json
  project.yaml
  rough_cut_plan.json
  exports/
    roughcut/
      rough_cut_plan.md
      rough_cut_plan.csv
    jianying/
      <draft_id>/
        draft_content.json
        draft_meta_info.json
        install_report.json
        staging/
```

剪映 10 默认草稿库路径：

```text
~/Movies/JianyingPro/User Data/Projects/com.lveditor.draft
```

安装器写入的是剪映草稿库下的新目录，不写入 `projects/<slug>/exports/jianying/<draft_id>/` 作为最终草稿。`exports/jianying/<draft_id>/` 只保存中间产物和报告。

## 4. `RoughCutPlan` schema

### 4.1 顶层模型

建议模型：

```python
class RoughCutPlan(BaseModel):
    schema_version: str
    project: RoughCutProjectRef
    intent: RoughCutIntent
    source_snapshot: RoughCutSourceSnapshot
    timeline: list[RoughCutSegment]
    text_overlays: list[TextOverlay] = Field(default_factory=list)
    bgm: BgmPlan | None = None
    transitions: list[TransitionPlan] = Field(default_factory=list)
    unused_assets: list[UnusedAsset] = Field(default_factory=list)
    warnings: list[PlanWarning] = Field(default_factory=list)
    created_at: str
```

第一版 `schema_version` 使用独立版本号：

```text
rough_cut_plan_schema_version = "0.1"
```

它不复用 `cut_index.json` 的 `SCHEMA_VERSION`，因为两个文件的生命周期不同。

### 4.2 项目引用

```python
class RoughCutProjectRef(BaseModel):
    project_slug: str
    project_name: str | None = None
    cut_index_path: str
    project_config_path: str | None = None
```

`cut_index_path` 和 `project_config_path` 保存生成计划时解析到的路径。消费方优先使用当前 CLI 的 `<slug> + --base-dir` 重新定位项目文件，定位失败时再回退到计划内路径。这样项目搬移后仍可通过 `--base-dir` 继续导出。

### 4.3 剪辑意图

```python
class RoughCutIntent(BaseModel):
    target_duration_sec: float
    output_style: str | None = None
    audience: str | None = None
    people_focus: str | None = None
    audio_priority: str | None = None
    language: str = "zh-CN"
```

`target_duration_sec` 是必填数值。`project.yaml` 中 `target_length` 可以是自然语言，planner 负责解析为秒数。如果无法解析，CLI 要求用户通过 `--target-duration` 提供明确秒数。

### 4.4 输入快照

```python
class RoughCutSourceSnapshot(BaseModel):
    cut_index_schema_version: str
    asset_count: int
    default_candidate_count: int
    similar_group_count: int
    source_folder: str | None = None
```

输入快照用于排查“计划是基于哪批输入生成的”。它不是完整拷贝，不能替代 `cut_index.json`。

### 4.5 时间表示

所有内部计算使用秒，JSON 中也保存秒。显示层可以再格式化为 `HH:MM:SS.mmm`。

```python
class TimeRange(BaseModel):
    start_sec: float
    end_sec: float
```

校验规则：

- `start_sec >= 0`
- `end_sec > start_sec`
- 第一版最小片段长度为 0.5 秒
- timeline 范围不得重叠

### 4.6 时间线片段

```python
class RoughCutSegment(BaseModel):
    segment_id: str
    asset_id: str
    asset_path: str
    asset_relative_path: str | None = None
    asset_type: Literal["video", "image", "audio"]
    source_range: TimeRange | None = None
    timeline_range: TimeRange
    track_type: Literal["main_video", "overlay", "audio"]
    track_index: int = 0
    audio_mode: Literal["keep", "mute", "duck", "replace"] = "keep"
    playback_speed: float = 1.0
    role: str | None = None
    reason: str
    source_candidate_status: str | None = None
    source_rating: int | None = None
    selection_override_reason: str | None = None
    tags: list[str] = Field(default_factory=list)
```

规则：

- planner 生成计划时，`asset_path` 必须指向现有文件。
- exporter 消费计划时，优先用当前 `cut_index.json` 的 `asset_id` 或 `asset_relative_path` 重新解析素材路径；解析失败时再使用 `asset_path`。
- `asset_id` 必须能在 `cut_index.json` 找到。
- `asset_type=image` 时 `source_range` 可以为空。
- `asset_type=video` 或 `audio` 时 `source_range` 必须存在。
- `track_type=main_video` 的片段在同一 track 上不得重叠。
- `playback_speed` 第一版只允许 `1.0`，字段保留给后续版本。
- `source_candidate_status=excluded` 时必须提供 `selection_override_reason`。

### 4.7 文本元素

```python
class TextOverlay(BaseModel):
    text_id: str
    text: str
    timeline_range: TimeRange
    kind: Literal["title", "caption", "label"]
    position: Literal["top", "center", "bottom"] = "bottom"
    style: dict[str, Any] = Field(default_factory=dict)
```

第一版 style 只作为 adapter hint，不保证所有字段都能落到剪映。adapter 不支持的样式必须记录 warning。

### 4.8 BGM

```python
class BgmPlan(BaseModel):
    mode: Literal["none", "file", "placeholder"] = "none"
    path: str | None = None
    volume: float = 0.35
    start_sec: float = 0
```

第一版不做自动找音乐。`mode=placeholder` 表示在计划中保留 BGM 意图，但 exporter 不创建真实音频轨。

### 4.9 转场

```python
class TransitionPlan(BaseModel):
    transition_id: str
    before_segment_id: str
    after_segment_id: str
    kind: Literal["cut", "crossfade"] = "cut"
    duration_sec: float = 0
```

第一版默认只保证硬切。`crossfade` 作为 best-effort 导出，adapter 不支持时降级为 `cut` 并记录 warning。

### 4.10 辅助模型

```python
class UnusedAsset(BaseModel):
    asset_id: str
    reason: str


class PlanWarning(BaseModel):
    code: str
    message: str
    target: str | None = None
```

`UnusedAsset` 只记录粗剪阶段主动解释的未使用素材，不要求覆盖 `cut_index.json` 中所有未入选素材。

## 5. Planner 契约

### 5.1 接口

```python
class RoughCutPlanner(Protocol):
    def plan(self, request: RoughCutPlanRequest) -> RoughCutPlan:
        ...
```

```python
class RoughCutPlanRequest(BaseModel):
    slug: str
    base_dir: str | None = None
    target_duration_sec: float
    max_segments: int | None = None
    include_alternates: bool = False
    allow_needs_review: bool = False
```

### 5.2 第一版选择策略

第一版支持启发式 planner，作为 LLM planner 前置稳定基线：

1. 读取 `cut_index.json`。
2. 优先选择 `edit_candidate_status=default_selected`。
3. 按 `edit_candidate_priority` 升序、`rating` 降序排序。
4. 优先使用 `clip_suggestions`，没有建议时对视频取开头可用片段，对图片给默认展示时长。
5. 在目标时长内尽量平衡 `shot_function` 和 `shot_scale`。
6. `alternate` 只有在 `include_alternates=True` 或默认候选不足时进入。
7. `needs_review` 默认不进入，除非 `allow_needs_review=True`。
8. `excluded` 默认不进入。

LLM planner 后续可以替换第 3 到第 5 步，但不得绕过 schema 校验。

### 5.3 计划校验

`validate_rough_cut_plan(plan, cut_index)` 负责：

- 检查 asset 存在。
- 检查文件路径存在。
- 检查 source range 合法。
- 检查 timeline 不重叠。
- 检查目标时长误差。
- 检查 `excluded` 使用必须有 `selection_override_reason`。
- 检查 BGM 文件存在。

校验失败抛出 `RoughCutValidationError`，错误里包含字段路径和面向用户的说明。

## 6. Exporter 契约

### 6.1 接口

```python
class JianyingDraftExporter:
    def export(
        self,
        plan: RoughCutPlan,
        output_dir: Path,
        engine: str = "pyjianyingdraft",
    ) -> DraftExportResult:
        ...
```

```python
class DraftExportResult(BaseModel):
    engine: str
    draft_content_path: str
    draft_meta_info_path: str | None = None
    media_paths: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
```

Exporter 只写 `output_dir`，不写剪映草稿库。

### 6.2 Adapter 接口

```python
class JianyingDraftAdapter(Protocol):
    engine_name: str

    def export(self, plan: RoughCutPlan, output_dir: Path) -> DraftExportResult:
        ...
```

adapter 必须消费同一个 `RoughCutPlan`。adapter 内禁止读取 `cut_index.json` 重新做素材筛选。

### 6.3 Adapter 能力矩阵

每个 adapter 提供能力声明：

```python
class AdapterCapabilities(BaseModel):
    video_segments: bool
    image_segments: bool
    audio_segments: bool
    text_overlays: bool
    bgm: bool
    mute_video_audio: bool
    crossfade: bool
```

Exporter 在导出前比较 plan 和 capability：

- 不支持但可降级：继续导出并记录 warning。
- 不支持且不可降级：抛出 `DraftExportError`。

## 7. Installer 契约

### 7.1 接口

```python
class Jianying10Installer:
    def install(self, request: DraftInstallRequest) -> DraftInstallResult:
        ...
```

```python
class DraftInstallRequest(BaseModel):
    draft_content_path: str
    draft_name: str
    jianying_library_dir: str
    template_dir: str
    asset_mode: Literal["copy", "hardlink"] = "copy"
    dry_run: bool = False
```

```python
class DraftInstallResult(BaseModel):
    draft_dir: str
    timeline_id: str
    asset_count: int
    written_files: list[str] = Field(default_factory=list)
    validations: list[InstallValidationItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
```

```python
class InstallValidationItem(BaseModel):
    name: str
    passed: bool
    message: str
```

### 7.2 Preflight

安装前检查：

- `draft_content_path` 是文件。
- `jianying_library_dir` 是目录。
- `template_dir` 是目录。
- 模板目录包含 `project.json`、`timeline_layout.json`、`draft_meta_info.json` 和 `Timelines/`。
- `draft_name` 可用于文件名。
- 目标草稿目录不存在。
- `draft_content.json` 中引用的媒体文件可读。
- `hardlink` 模式在当前文件系统可用；不可用时失败，不自动转 copy，除非用户显式设置 `copy`。

`dry_run=True` 时只做 preflight 和计划报告，不创建草稿目录。

### 7.3 草稿目录创建

目标目录名：

```text
<safe_draft_name>_<YYYYMMDD_HHMMSS>_<short_uuid>
```

每次安装生成新的 `timeline_id`。旧草稿名和旧 `timeline_id` 不复用。

### 7.4 素材落盘

草稿内素材目录：

```text
assets/
  video/
  audio/
  image/
  assets_relink_all/
```

规则：

- 视频进入 `assets/video/`。
- 音频进入 `assets/audio/`。
- 图片进入 `assets/image/`。
- `assets_relink_all/` 放置所有素材的扁平辅助链接或副本。
- 文件名冲突时添加 asset id 或短 hash。
- 素材复制或硬链接失败时安装失败，并清理本次创建的不完整草稿目录。

### 7.5 路径重写

安装器必须把 `draft_content.json` 中的媒体路径重写到草稿内 assets。

至少覆盖：

```text
materials.videos[].path
materials.videos[].remote_url
materials.audios[].path
materials.audios[].remote_url
materials.images[].path
materials.images[].remote_url
```

如果 adapter 输出中还存在其他 source 字段，安装器需要通过结构化路径访问方式处理，不能用纯字符串全局替换。

### 7.6 剪映 10 关键镜像文件

安装器必须写入并保持一致：

```text
draft_content.json
draft_content.json.bak
template-2.tmp
Timelines/<timeline_id>/draft_content.json
Timelines/<timeline_id>/draft_content.json.bak
Timelines/<timeline_id>/template.tmp
Timelines/<timeline_id>/template-2.tmp
```

一致性规则：

- 这些文件中的草稿内容 JSON 必须一致。
- 文件内 timeline id 必须使用新 `timeline_id`。
- 顶层和 `Timelines/<timeline_id>/` 下内容保持同步。

### 7.7 其他文件更新

安装器还需要更新模板外壳里的：

```text
project.json
timeline_layout.json
draft_meta_info.json
```

规则：

- 草稿名称使用用户提供的 `draft_name`。
- timeline 引用使用新 `timeline_id`。
- 创建时间和更新时间使用当前时间。
- 不保留模板草稿旧路径。

### 7.8 安装后校验

安装后必须检查：

- 7 个关键镜像文件存在。
- 7 个关键镜像文件内容一致。
- 新 `timeline_id` 出现在所有必要位置。
- 旧 `timeline_id` 不再出现在草稿目录内 JSON 文件中。
- 所有素材路径存在。
- 草稿目录内 JSON 文件不引用 exporter 临时目录。
- 草稿目录内 JSON 文件不引用模板草稿路径。
- 原始素材文件未被修改。

校验结果写入：

```text
projects/<slug>/exports/jianying/<draft_id>/install_report.json
```

## 8. CLI 设计

### 8.1 粗剪命令

```bash
tripclipper roughcut plan <slug> \
  --base-dir <dir> \
  --target-duration 90 \
  --max-segments 24 \
  --include-alternates \
  --allow-needs-review
```

输出：

```text
projects/<slug>/rough_cut_plan.json
projects/<slug>/exports/roughcut/rough_cut_plan.md
projects/<slug>/exports/roughcut/rough_cut_plan.csv
```

### 8.2 剪映导出命令

```bash
tripclipper jianying export <slug> \
  --plan projects/<slug>/rough_cut_plan.json \
  --engine pyjianyingdraft
```

输出：

```text
projects/<slug>/exports/jianying/<draft_id>/draft_content.json
projects/<slug>/exports/jianying/<draft_id>/draft_meta_info.json
```

### 8.3 剪映安装命令

```bash
tripclipper jianying install \
  --draft-content <path> \
  --name <draft_name> \
  --library-dir "$HOME/Movies/JianyingPro/User Data/Projects/com.lveditor.draft" \
  --template-dir <template_dir> \
  --asset-mode copy \
  --dry-run
```

### 8.4 一键创建命令

```bash
tripclipper jianying create <slug> \
  --target-duration 90 \
  --engine pyjianyingdraft \
  --library-dir "$HOME/Movies/JianyingPro/User Data/Projects/com.lveditor.draft" \
  --template-dir <template_dir> \
  --asset-mode copy
```

一键命令等价于：

```text
roughcut plan -> jianying export -> jianying install
```

任一阶段失败时停止，并保留前一阶段成功产物。

## 9. 错误处理

新增异常类型：

```python
class RoughCutError(Exception): ...
class RoughCutValidationError(RoughCutError): ...
class DraftExportError(Exception): ...
class DraftInstallError(Exception): ...
class DraftPreflightError(DraftInstallError): ...
```

CLI 规则：

- 用户输入错误退出码为 2。
- 业务失败退出码为 1。
- 不向用户打印裸堆栈。
- 错误文案包含失败阶段、失败对象和建议动作。
- 任何路径或配置输出不得泄露密钥。

安装器写入草稿目录失败时：

- 清理本次创建的不完整目录。
- 保留 `exports/jianying/<draft_id>/install_report.json`，记录失败位置。
- 不清理 `draft_content.json`，便于重试。

## 10. 测试策略

### 10.1 RoughCutPlan 模型测试

覆盖：

- 合法计划往返序列化。
- 缺失 asset id 失败。
- source range 反向失败。
- timeline 重叠失败。
- 图片无 source range 合法。
- 视频无 source range 失败。
- `excluded` 素材无 `selection_override_reason` 失败。

### 10.2 Planner 测试

使用小型 `cut_index.json` fixture：

- 只选择默认候选。
- 目标时长不足时截断。
- 默认不选择 `needs_review`。
- `include_alternates=True` 时允许 alternate。
- 每个 segment 有 reason。

### 10.3 Exporter 测试

使用手写 `rough_cut_plan.json` fixture：

- adapter 收到同一 plan。
- 输出路径在 `output_dir` 内。
- 不修改源素材。
- 不修改 plan 文件。
- capability 不支持时产生 warning 或失败。

### 10.4 Installer 单元测试

使用剪映 10 模板 fixture 和小型 `draft_content.json` fixture：

- dry-run 不写目标草稿目录。
- copy 模式复制素材。
- hardlink 模式创建硬链接。
- 生成唯一草稿目录。
- 写入 7 个关键文件。
- 替换 timeline id。
- 路径重写覆盖 path 和 remote_url。
- 旧路径命中为 0。
- 安装失败时清理不完整目录。

### 10.5 手工冒烟测试

在真实剪映 10 环境执行：

1. 准备一个包含 2 个视频、1 张图片、1 个 BGM 的计划。
2. 导出 `draft_content.json`。
3. 安装为新草稿。
4. 打开剪映 10。
5. 确认新草稿可见、可打开、素材不丢失、时间线顺序正确。
6. 保存后退出，再次打开确认草稿仍可用。

## 11. 依赖策略

第一版新增第三方依赖要谨慎。

建议：

- `pyJianYingDraft` 不直接加入核心依赖，先放在可选依赖组或运行时探测。
- `VectCutAPI` 不进入第一版必需依赖。
- 没有安装 adapter 依赖时，CLI 报清楚错误并提示安装方式。

`pyproject.toml` 可后续增加：

```toml
[project.optional-dependencies]
jianying = ["pyJianYingDraft"]
```

具体包名以实测可安装名称为准，技术实现前需要用本地环境验证。

## 12. 风险与约束

### 12.1 剪映 10 草稿格式不稳定

应对：

- installer 的镜像文件规则写成测试。
- 模板草稿作为 fixture 版本化管理。
- 安装报告记录剪映模板来源和时间。

### 12.2 第三方 adapter API 漂移

应对：

- adapter 最薄化，只做 plan 到 API 的翻译。
- exporter 通过 `DraftExportResult` 和 capability 矩阵统一处理差异。
- 主业务测试尽量使用 fake adapter。

### 12.3 LLM 输出不稳定

应对：

- LLM planner 输出必须经过 Pydantic 校验。
- 失败时不写入计划文件。
- 第一版保留启发式 planner 作为稳定基线。

### 12.4 文件路径和权限问题

应对：

- 所有路径在执行前 expanduser 和 resolve。
- 写入剪映草稿库前 preflight。
- `hardlink` 不可用时明确失败。
- 默认推荐 `copy` 模式。

### 12.5 剪映缓存误导

应对：

- 验收以草稿目录 JSON 和素材文件为准。
- 人工打开剪映只验证最终可用性。
- 安装报告保留旧路径扫描结果。

## 13. 实现顺序

1. 新增 `roughcut.models` 和 schema 测试。
2. 新增 `roughcut.io`、`roughcut.validator`。
3. 新增启发式 `RoughCutPlanner`。
4. 新增 `jianying.models` 和 fake adapter 测试。
5. 新增 `Jianying10Installer` 和模板 fixture 测试。
6. 接入 `PyJianYingDraftAdapter`。
7. 增加 CLI 命令。
8. 用真实剪映 10 做手工冒烟。
9. 后置接入 `VectCutAPIAdapter`。

## 14. 完成定义

本阶段完成时必须满足：

- `tripclipper roughcut plan <slug>` 能生成合法 `rough_cut_plan.json`。
- `tripclipper jianying export <slug>` 能从该计划生成 `draft_content.json`。
- `tripclipper jianying install` 能安装新剪映 10 草稿并输出报告。
- 失败时能定位到 plan、export 或 install 的具体阶段。
- 自动测试覆盖 schema、planner、exporter 和 installer 的核心不变量。
- 真实剪映 10 冒烟测试通过。
