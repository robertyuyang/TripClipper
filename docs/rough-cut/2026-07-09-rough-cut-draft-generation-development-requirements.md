# 粗剪与剪映草稿生成实现计划

> **给智能体执行者：** 必须使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans` 按任务逐项实现。本计划使用复选框（`- [ ]`）跟踪步骤。

**目标：** 把粗剪与剪映草稿生成拆成多个可独立执行的开发需求，每个需求都可以在一个新的 Codex 对话中单独完成。

**架构：** 中心契约是 `rough_cut_plan.json`。开发顺序从可复用 fixture 和 schema 开始，然后做剪映安装器，再做草稿导出器，再做粗剪规划器，最后做 CLI 编排。每个需求都必须产出可测试的软件，并在进入下一个需求前提交。

**技术栈：** Python 3.10+、Pydantic v2、Click、pytest、标准库 `json`/`pathlib`/`shutil`、必需 `pyJianYingDraft` adapter；第一轮不要求 `VectCutAPI` 依赖。

## 全局约束

- 来源 spec：`docs/rough-cut/2026-07-09-rough-cut-draft-generation-design.md` 和 `docs/rough-cut/2026-07-09-rough-cut-draft-generation-technical.md`。
- 不修改、移动、覆盖原始素材文件。
- 除了创建一个唯一命名的新草稿目录，不写入用户已有剪映草稿目录。
- `install/create` 默认执行安装前检查；检查失败时停止，不创建草稿目录。
- `rough_cut_plan.json` 只表达剪辑意图和时间线计划，不表达剪映文件结构。
- `JianyingDraftExporter` 可以读取 `cut_index.json` 做路径解析和校验，但不允许做二次素材筛选。
- `Jianying10Installer` 不理解素材内容，不改变剪辑顺序。
- `pyJianYingDraft` 是 R3 默认且必需的导出依赖；`VectCutAPIAdapter` 是后续可选工作，不能阻塞第一条可用主链路。
- 本轮 grilling 修订只覆盖 R0-R3；R4-R6 保留原方向，后续单独审。
- 保持改动聚焦。忽略无关未跟踪文件，例如 `docs/review-html-*.md`。

---

## 使用方式

每个需求开一个新的对话。新对话直接复制该需求下方的“对话启动语”。除非某个需求明确依赖前面需求，否则不要在同一对话里顺手实现后续需求。

推荐顺序：

```text
R0 fixture 包
R1 RoughCutPlan schema
R2 Jianying10Installer
R3 JianyingDraftExporter + PyJianYingDraftAdapter
R4 启发式 RoughCutPlanner
R5 CLI 编排
R6 可选 adapter 和 LLM planner
```

产品运行顺序是 `planner -> exporter -> installer`，但开发顺序故意不同。先验证稳定契约和剪映落盘行为，再增加自动规划能力。

## 共享文件地图

按需求逐步创建这些目录和文件：

```text
src/tripclipper/roughcut/
  __init__.py
  models.py
  io.py
  validator.py
  planner.py

src/tripclipper/jianying/
  __init__.py
  models.py
  draft_exporter.py
  installer.py
  paths.py
  adapters/
    __init__.py
    base.py
    pyjianyingdraft.py
    vectcutapi.py

tests/fixtures/roughcut/
tests/fixtures/jianying/
```

后续可能修改的既有文件：

```text
src/tripclipper/cli.py
src/tripclipper/paths.py
pyproject.toml
```

---

### 需求 R0：Fixture 包与校验样本

**目标：** 创建本地 fixture 集，让后续需求不依赖真实用户项目也能测试，并保留用户提供的 legacy rough cut / realistic draft 成对样本作为 R3 语义回归基准。

**依赖：** 仅依赖当前 spec。

**文件：**
- 创建：`tests/fixtures/roughcut/minimal_rough_cut_plan.json`
- 创建：`tests/fixtures/roughcut/minimal_cut_index.json`
- 创建：`tests/fixtures/roughcut/legacy_eval_rough_cut_source.json`
- 创建：`tests/fixtures/jianying/realistic_draft_content.json`
- 创建：`tests/fixtures/jianying/minimal_template_draft/`
- 创建：`tests/fixtures/media/`
- 测试：`tests/test_roughcut_fixture_contract.py`

**产出：**
- 小型媒体 fixture 文件，或在测试中用标准库生成的 dummy 文件。
- 一个最小 `cut_index.json`，至少包含两个视频素材、一张图片素材和一条音频素材。
- 一个符合 R1 契约、引用 fixture 素材的最小 `rough_cut_plan.json`，包含 video、image、audio、text 多轨样例。
- 用户提供的旧 rough cut 输入样本，保存为 `legacy_eval_rough_cut_source.json`，路径需要相对化或改写到 fixture 媒体；它只作为构造和语义比较参考，不作为正式 schema fixture。
- 用户提供的真实剪映 `draft_content.json`，保存为 `realistic_draft_content.json`，路径需要相对化或改写到 fixture 媒体。
- 一个自动测试用的最小剪映模板草稿目录 `minimal_template_draft/`，包含 installer 需要的模板外壳文件。

**验收标准：**
- `pytest tests/test_roughcut_fixture_contract.py -v` 通过。
- fixture 路径尽量相对仓库或 pytest 临时目录。
- fixture 不引用 `/Users/bytedance/...` 绝对路径。
- fixture plan 使用 float 秒表示时间范围。
- fixture plan 的 `timeline` 覆盖 `track_type=video|image|audio|text`。
- fixture plan 中 video/audio 有 `source_range`，image/text 没有 `source_range`。
- fixture plan 中媒体 segment 使用 `asset_id + asset_relative_path` 作为主身份，`asset_path` 只做快照兜底。
- fixture draft content 包含后续 installer 可重写的真实媒体引用。
- `minimal_template_draft/` 能支持 R2 自动测试复制外壳、写 7 个关键文件、更新 `project.json`、`timeline_layout.json`、`draft_meta_info.json`。

**不做：**
- 不实现 schema 模型。
- 不实现 exporter。
- 不实现 installer。
- 不实现 legacy rough cut 到正式 `RoughCutPlan` 的通用转换工具。

**建议步骤：**

- [ ] 在 `tests/fixtures/` 下创建 fixture 目录。
- [ ] 添加可安全提交的小型媒体占位文件，或在测试里用标准库写入生成。
- [ ] 添加 `minimal_cut_index.json`，包含 `schema_version`、`project`、`assets`、`default_candidates`，以及无关顶层字段的空数组。
- [ ] 复制用户提供的 `projects/demo-scan/exports/rough_cut_plan.json` 为 `legacy_eval_rough_cut_source.json`，并把其中媒体路径改写到 fixture 媒体路径。
- [ ] 复制用户提供的 `projects/demo-scan/exports/draft_content.json` 为 `realistic_draft_content.json`，并把其中媒体路径改写到 fixture 媒体路径。
- [ ] 基于 legacy rough cut / realistic draft 成对样本，手工构造符合 R1 契约的 `minimal_rough_cut_plan.json`，不实现通用转换器。
- [ ] 添加最小 `minimal_template_draft/` 骨架，包含 `project.json`、`timeline_layout.json`、`draft_meta_info.json` 和 `Timelines/`。
- [ ] 添加测试，加载每个 JSON fixture，并断言必要顶层键存在、路径不含 `/Users/bytedance/`。
- [ ] 运行 `pytest tests/test_roughcut_fixture_contract.py -v`。
- [ ] 提交：`test: add rough cut draft fixtures`。

**对话启动语：**

```text
按 docs/rough-cut/2026-07-09-rough-cut-draft-generation-development-requirements.md 的需求 R0 实现 fixture 包。只做 R0，不实现 schema/exporter/installer/planner。完成后运行 R0 验收测试并提交。
```

---

### 需求 R1：RoughCutPlan Schema、IO 与 Validator

**目标：** 定义稳定的 `rough_cut_plan.json` 契约和本地校验工具。

**依赖：** R0 fixture 包。

**文件：**
- 创建：`src/tripclipper/roughcut/__init__.py`
- 创建：`src/tripclipper/roughcut/models.py`
- 创建：`src/tripclipper/roughcut/io.py`
- 创建：`src/tripclipper/roughcut/validator.py`
- 测试：`tests/test_roughcut_models.py`
- 测试：`tests/test_roughcut_validator.py`

**接口：**
- 产出：`ROUGH_CUT_PLAN_SCHEMA_VERSION = "0.1"`。
- 产出：`TimeRange`、`RoughCutProjectRef`、`RoughCutIntent`、`RoughCutSourceSnapshot`、`RoughCutSegment`、`TextOverlay`、`TransitionPlan`、`UnusedAsset`、`PlanWarning`、`RoughCutPlan`。
- 产出：`read_rough_cut_plan(path) -> RoughCutPlan`。
- 产出：`write_rough_cut_plan(path, plan) -> None`。
- 产出：`validate_rough_cut_plan(plan, cut_index) -> None`。
- 产出：`RoughCutValidationError`。

**验收标准：**
- `pytest tests/test_roughcut_models.py tests/test_roughcut_validator.py -v` 通过。
- 合法 fixture plan 往返读写无数据丢失。
- 非法时间范围失败。
- 根据 `cut_index.json` 校验时，缺失 asset id 失败。
- 同一 `(track_type, track_index)` 内 timeline 重叠失败，不同轨道重叠允许。
- `candidate_status_snapshot="excluded"` 且缺少 `selection_override_reason` 时失败。
- `candidate_status_snapshot` 复用 `EditCandidateStatus`，表示生成计划时 `cut_index.assets[*].edit_candidate_status` 的快照。
- `asset_id + asset_relative_path` 是素材主身份；`asset_path` 只做路径快照和兜底。
- video/audio segment 必须有 `source_range`；image/text segment 必须没有 `source_range`。
- text segment 必须有 `text_overlay`；非 text segment 不允许有 `text_overlay`。
- 顶层字段不包含 `text_overlays`、`bgm`、`transitions`；文本、BGM、转场都在 `timeline` segment 内表达。
- `unused_assets` 字段保留，但允许为空，不要求覆盖所有未用素材。

**不做：**
- 不从 `cut_index.json` 生成 plan。
- 不导出剪映 `draft_content.json`。
- 不安装剪映草稿。

**建议步骤：**

- [ ] 添加基于 `tests/fixtures/roughcut/minimal_rough_cut_plan.json` 的失败版模型往返测试。
- [ ] 添加非法时间范围、缺失 asset id、同轨重叠、excluded 无原因的失败版 validator 测试。
- [ ] 添加 source_range 规则测试：video/audio 必须有；image/text 必须没有。
- [ ] 添加 text_overlay 规则测试：text 必须有；非 text 不能有。
- [ ] 在 `src/tripclipper/roughcut/models.py` 实现 Pydantic 模型。
- [ ] 在 `src/tripclipper/roughcut/io.py` 实现 JSON 读写 helper。
- [ ] 在 `src/tripclipper/roughcut/validator.py` 实现校验。
- [ ] 在 `src/tripclipper/roughcut/__init__.py` 导出公共名称。
- [ ] 运行 `pytest tests/test_roughcut_models.py tests/test_roughcut_validator.py -v`。
- [ ] 运行 `pytest tests/test_models.py tests/test_cut_index.py -v`，确认核心模型无回归。
- [ ] 提交：`feat: add rough cut plan schema`。

**对话启动语：**

```text
按 docs/rough-cut/2026-07-09-rough-cut-draft-generation-development-requirements.md 的需求 R1 实现 RoughCutPlan schema/io/validator。只做 R1。依赖 R0 fixture。完成后运行 R1 验收测试并提交。
```

---

### 需求 R2：Jianying10Installer

**目标：** 把已有 `draft_content.json` 安全、可重复地安装成一个新的剪映 10 草稿目录。

**依赖：** R0 fixture 包。

**文件：**
- 创建：`src/tripclipper/jianying/__init__.py`
- 创建：`src/tripclipper/jianying/models.py`
- 创建：`src/tripclipper/jianying/paths.py`
- 创建：`src/tripclipper/jianying/installer.py`
- 测试：`tests/test_jianying_installer.py`

**接口：**
- 产出：`DraftInstallRequest`。
- 产出：`InstallValidationItem`。
- 产出：`DraftInstallResult`。
- 产出：`DraftInstallError`。
- 产出：`Jianying10Installer.install(request: DraftInstallRequest) -> DraftInstallResult`。

**验收标准：**
- `pytest tests/test_jianying_installer.py -v` 通过。
- installer 拒绝缺失 `draft_content_path`、缺失模板目录、缺失草稿库目录、不可读媒体。
- installer 使用 `minimal_template_draft/` 复制剪映模板外壳，不从零生成剪映外壳。
- installer 创建唯一草稿目录，目录名格式为 `tc-<draft_name_slug>-<YYYYMMDD-HHMMSS>-<random6>`。
- installer 生成新的 `timeline_id = uuid.uuid4().hex`，每次安装不同。
- installer 第一版只支持 copy，把媒体复制到草稿本地 `assets/`；不实现 hardlink。
- installer 至少重写这些明确媒体字段中的路径：
  - `materials.videos[].path`
  - `materials.audios[].path`
  - `materials.images[].path`
- 如果上述对象存在 `remote_url`，也需要处理；fixture 中没有该字段时不强制造出。
- installer 不递归改写所有 `*_path` 字段。
- installer 写入并保持内容一致的 7 个关键文件：
  - `draft_content.json`
  - `draft_content.json.bak`
  - `template-2.tmp`
  - `Timelines/<timeline_id>/draft_content.json`
  - `Timelines/<timeline_id>/draft_content.json.bak`
  - `Timelines/<timeline_id>/template.tmp`
  - `Timelines/<timeline_id>/template-2.tmp`
- installer 更新 `project.json`、`timeline_layout.json` 和 `draft_meta_info.json`。
- installer 把 `install_report.json` 写在输入 `draft_content.json` 同目录，不写进剪映草稿目录。
- 目录创建后发生失败时，installer 清理本次不完整草稿目录，并留下安装报告。

**不做：**
- 不生成 `draft_content.json`。
- 不解析 `rough_cut_plan.json`。
- 不调用 `pyJianYingDraft`。
- 不打开或自动操作剪映 UI。
- 不实现 hardlink。

**人工验收：**
- 使用真实剪映 10 模板目录和已知可用的 `draft_content.json`。
- 先安装到临时剪映草稿库副本。
- fixture 测试通过后，再安装到真实剪映草稿库。
- 打开剪映 10，确认新草稿出现、可打开、媒体不丢失、保存后可再次打开。

**建议步骤：**

- [ ] 添加安装前检查失败的测试。
- [ ] 添加安装到 pytest 临时草稿库目录的成功测试。
- [ ] 添加媒体路径重写测试。
- [ ] 添加 `materials.videos[].type="photo"` 图片素材路径重写测试。
- [ ] 添加 7 个关键文件写入测试。
- [ ] 添加写入失败时清理不完整草稿目录的测试。
- [ ] 添加安装报告写在 `draft_content.json` 同目录的测试。
- [ ] 添加每次安装生成不同 `timeline_id` 和唯一 `tc-...` 草稿目录名的测试。
- [ ] 在 `src/tripclipper/jianying/models.py` 实现请求/结果模型。
- [ ] 在 `src/tripclipper/jianying/paths.py` 实现路径 helper。
- [ ] 在 `src/tripclipper/jianying/installer.py` 实现 installer。
- [ ] 在 `src/tripclipper/jianying/__init__.py` 导出公共名称。
- [ ] 运行 `pytest tests/test_jianying_installer.py -v`。
- [ ] 提交：`feat: add jianying draft installer`。

**对话启动语：**

```text
按 docs/rough-cut/2026-07-09-rough-cut-draft-generation-development-requirements.md 的需求 R2 实现 Jianying10Installer。只做 R2。输入是已有 draft_content.json fixture，不实现 exporter/planner/CLI。完成后运行 R2 验收测试并提交。
```

---

### 需求 R3：JianyingDraftExporter 与 PyJianYingDraftAdapter

**目标：** 把符合 R1 契约的 `rough_cut_plan.json` 转成新的 `draft_content.json`，并验证 installer 能安装它。

**依赖：** R1 RoughCutPlan schema 和 R2 Jianying10Installer。

**文件：**
- 创建：`src/tripclipper/jianying/draft_exporter.py`
- 创建：`src/tripclipper/jianying/adapters/__init__.py`
- 创建：`src/tripclipper/jianying/adapters/base.py`
- 创建：`src/tripclipper/jianying/adapters/pyjianyingdraft.py`
- 修改：`src/tripclipper/jianying/models.py`
- 修改：`pyproject.toml`
- 测试：`tests/test_jianying_exporter.py`
- 测试：`tests/test_jianying_pyjianyingdraft_adapter.py`

**接口：**
- 消费：`RoughCutPlan`。
- 产出：`DraftExportResult`。
- 产出：`JianyingDraftExporter.export(plan, output_dir, engine="pyjianyingdraft") -> DraftExportResult`。
- 产出：`JianyingDraftAdapter.export(plan, output_dir) -> DraftExportResult`。
- 产出：`AdapterCapabilities`。
- 产出：`DraftExportError`。

**验收标准：**
- `pytest tests/test_jianying_exporter.py tests/test_jianying_pyjianyingdraft_adapter.py -v` 通过。
- exporter 只写 `output_dir` 内部。
- exporter 可以在 `output_dir/pyjianying_work/` 下创建 pyJianYingDraft 中间草稿目录，并默认保留。
- exporter 不写真实剪映草稿库。
- exporter 不修改源素材，也不修改输入 plan。
- `pyJianYingDraft` 是核心强依赖，不做 optional/lazy skip；依赖缺失时测试应失败。
- exporter 可以读取 `plan.project.cut_index_path` 只用于路径解析和校验；adapter 不读取 `cut_index.json` 做二次素材筛选。
- export result 包含 `engine`、`draft_content_path`、可选 `draft_meta_info_path`、`media_paths`、`warnings`。
- 对可安全降级的不支持能力写入 `warnings`。
- fixture plan 生成的 `draft_content.json` 可以交给 R2 installer 测试消费。
- fixture plan 生成的 `draft_content.json` 需要和 `tests/fixtures/jianying/realistic_draft_content.json` 做语义比较：
  - 主视频轨素材顺序一致。
  - 每个主视频片段的 `source_timerange` 和 `target_timerange` 近似一致，允许秒到微秒转换的取整误差。
  - BGM audio track 存在，起点、时长、音量近似一致。
  - 图片覆盖轨存在，素材和时间范围近似一致。
  - text track 存在，文本内容和时间范围近似一致。
  - 不要求 id、内部素材引用、字段顺序、时间戳、剪映版本字段或 pyJianYingDraft 自动生成的辅助字段一致。

**不做：**
- 不实现启发式 planning。
- 不实现 LLM planning。
- 不实现 `VectCutAPIAdapter`。
- 不添加最终 CLI 编排。
- 不把 `draft_content.json` 安装进真实剪映草稿库；安装仍由 R2 Jianying10Installer 负责。

**人工验收：**

```text
minimal_rough_cut_plan.json
  -> JianyingDraftExporter
  -> generated draft_content.json
  -> Jianying10Installer
  -> 剪映 10 打开新草稿
```

生成的 draft 不需要和 `realistic_draft_content.json` 字节级一致。只验证语义一致：媒体数量、顺序、近似 source range、timeline 顺序、文本覆盖、BGM 处理、可安装性。

**建议步骤：**

- [ ] 添加使用 `minimal_rough_cut_plan.json` 的失败版 exporter 测试。
- [ ] 添加 exporter 不写 `output_dir` 外部的测试。
- [ ] 添加 adapter 不读取 `cut_index.json` 做二次筛选的测试。
- [ ] 添加 adapter capability warning 测试。
- [ ] 添加 pyJianYingDraft 强依赖导入测试。
- [ ] 添加 `pyjianying_work/` 默认保留测试。
- [ ] 添加和 `realistic_draft_content.json` 的语义比较测试。
- [ ] 添加集成风格测试：把 fixture plan 导出到临时输出目录，再把生成的 `draft_content.json` 交给 installer fixture。
- [ ] 实现 adapter protocol 和 capability model。
- [ ] 实现 `DraftExportResult` 和 `DraftExportError`。
- [ ] 实现 exporter engine dispatch。
- [ ] 实现 `PyJianYingDraftAdapter`，使用 `pyJianYingDraft` 生成中间草稿，再整理出标准 `draft_content.json`。
- [ ] 把 `pyJianYingDraft` 加入核心依赖。
- [ ] 运行 `pytest tests/test_jianying_exporter.py tests/test_jianying_pyjianyingdraft_adapter.py tests/test_jianying_installer.py -v`。
- [ ] 提交：`feat: add jianying draft exporter`。

**对话启动语：**

```text
按 docs/rough-cut/2026-07-09-rough-cut-draft-generation-development-requirements.md 的需求 R3 实现 JianyingDraftExporter + PyJianYingDraftAdapter。只做 R3。依赖 R1/R2。完成后验证“minimal_rough_cut_plan.json -> exporter -> semantic comparison -> installer”链路并提交。
```

---

> **R0-R3 grilling 修订边界：** 上方 R0-R3 已按本轮 grilling 决策修订。下方 R4-R6 保留原计划方向，尚未经过本轮 R0-R3 决策同等深度的 grilling；实现前建议单独复审。

### 需求 R4：启发式 RoughCutPlanner

**目标：** 不使用 LLM，从真实 `cut_index.json` 和项目意图生成第一版 `rough_cut_plan.json`。

**依赖：** R1 RoughCutPlan schema。

**文件：**
- 创建：`src/tripclipper/roughcut/planner.py`
- 修改：`src/tripclipper/roughcut/__init__.py`
- 测试：`tests/test_roughcut_planner.py`

**接口：**
- 消费：`read_cut_index(path) -> CutIndex`。
- 消费：`RoughCutPlan`、`RoughCutIntent`、`RoughCutSegment`。
- 产出：`RoughCutPlanRequest`。
- 产出：`HeuristicRoughCutPlanner.plan(request: RoughCutPlanRequest) -> RoughCutPlan`。

**验收标准：**
- `pytest tests/test_roughcut_planner.py tests/test_roughcut_validator.py -v` 通过。
- planner 默认选择 `edit_candidate_status=default_selected`。
- planner 默认排除 `needs_review` 和 `excluded`。
- planner 只在配置允许或默认候选不足时补充 `alternate`。
- planner 优先使用 `clip_suggestions`。
- planner 生成的每个 segment 都有 `reason`。
- planner 输出能通过 `validate_rough_cut_plan`。
- timeline 总时长接近 `target_duration_sec`，且不超过目标时长多于一个已选片段时长。

**不做：**
- 不调用 LLM。
- 不导出 `draft_content.json`。
- 不安装剪映草稿。
- 不实现最终 CLI 编排。

**建议步骤：**

- [ ] 添加默认候选选择测试。
- [ ] 添加默认跳过 `needs_review` 和 `excluded` 的测试。
- [ ] 添加 `include_alternates=True` 测试。
- [ ] 添加 `clip_suggestions` 转成 `source_range` 的测试。
- [ ] 添加每个 segment 都有非空 `reason` 的测试。
- [ ] 实现 `RoughCutPlanRequest`。
- [ ] 实现 `HeuristicRoughCutPlanner`。
- [ ] 运行 `pytest tests/test_roughcut_planner.py tests/test_roughcut_validator.py -v`。
- [ ] 提交：`feat: add heuristic rough cut planner`。

**对话启动语：**

```text
按 docs/rough-cut/2026-07-09-rough-cut-draft-generation-development-requirements.md 的需求 R4 实现启发式 RoughCutPlanner。只做 R4，不做 LLM/exporter/installer/CLI 串联。完成后运行 R4 验收测试并提交。
```

---

### 需求 R5：CLI 命令与端到端编排

**目标：** 通过清晰的 Click 命令暴露粗剪与剪映链路，并提供一键 `jianying create`。

**依赖：** R1、R2、R3、R4。

**文件：**
- 修改：`src/tripclipper/cli.py`
- 修改：`src/tripclipper/paths.py`
- 测试：`tests/test_cli_roughcut.py`
- 测试：`tests/test_cli_jianying.py`

**接口：**
- 消费：`HeuristicRoughCutPlanner.plan`。
- 消费：`write_rough_cut_plan`。
- 消费：`JianyingDraftExporter.export`。
- 消费：`Jianying10Installer.install`。
- 产出：`tripclipper roughcut plan <slug> --target-duration 90`。
- 产出：`tripclipper jianying export <slug> --engine pyjianyingdraft`。
- 产出：`tripclipper jianying install --draft-content <path> --name <draft_name>`。
- 产出：`tripclipper jianying create <slug> --target-duration 90 --engine pyjianyingdraft`。

**验收标准：**
- `pytest tests/test_cli_roughcut.py tests/test_cli_jianying.py -v` 通过。
- `roughcut plan` 写入 `projects/<slug>/rough_cut_plan.json`。
- `jianying export` 写入 `projects/<slug>/exports/jianying/<draft_id>/draft_content.json`。
- `jianying install` 安装已有 `draft_content.json` 并报告新草稿目录。
- `jianying create` 执行 `plan -> export -> install`。
- 任一阶段失败时停止，并保留前面阶段已成功产物。
- CLI 错误遵循现有风格：不打印裸堆栈；用户输入错误退出码 2；业务失败退出码 1。

**不做：**
- 不添加 LLM planner。
- 不添加 `VectCutAPIAdapter`。
- 不添加 UI。

**建议步骤：**

- [ ] 添加 `roughcut plan` 的失败版 CLI 测试。
- [ ] 添加 `jianying export` 的失败版 CLI 测试。
- [ ] 添加 `jianying install` 的失败版 CLI 测试。
- [ ] 添加 `jianying create` 在 export 失败后停止的测试。
- [ ] 在 `src/tripclipper/cli.py` 添加 roughcut 和 jianying Click command group。
- [ ] 在 `src/tripclipper/paths.py` 添加 roughcut 与 jianying export 产物路径 helper。
- [ ] 按现有 CLI 约定接好错误处理。
- [ ] 运行 `pytest tests/test_cli_roughcut.py tests/test_cli_jianying.py -v`。
- [ ] 运行 `pytest tests/test_cli_export.py tests/test_project.py tests/test_paths.py -v` 做相邻 CLI/path 回归检查。
- [ ] 提交：`feat: add rough cut jianying cli`。

**对话启动语：**

```text
按 docs/rough-cut/2026-07-09-rough-cut-draft-generation-development-requirements.md 的需求 R5 实现 CLI 命令和 create 串联。只做 R5。依赖 R1-R4 已完成。完成后运行 R5 验收测试并提交。
```

---

### 需求 R6：可选 LLM Planner 与 VectCutAPIAdapter

**目标：** 主链路稳定后，再添加可选的增强规划和备用草稿导出路径。

**依赖：** R1-R5。

**文件：**
- 修改：`src/tripclipper/roughcut/planner.py`
- 创建：`src/tripclipper/roughcut/llm_planner.py`
- 修改：`src/tripclipper/jianying/adapters/vectcutapi.py`
- 测试：`tests/test_roughcut_llm_planner.py`
- 测试：`tests/test_jianying_vectcutapi_adapter.py`

**接口：**
- 消费：`RoughCutPlan` schema 和 validator。
- 产出：可选 planner engine，例如 `--planner heuristic|llm`。
- 产出：可选 export engine：`--engine vectcutapi`。

**验收标准：**
- LLM planner 输出必须通过 `validate_rough_cut_plan`。
- LLM planner 失败时不能写入非法 plan 文件。
- VectCutAPI adapter 必须消费和 PyJianYingDraftAdapter 相同的 `RoughCutPlan`。
- VectCutAPI adapter 不允许复制粗剪业务逻辑。
- 可选依赖缺失时给出清楚 CLI 错误。

**不做：**
- 启发式 planner 和端到端 create 稳定前，不把 LLM planner 设为默认。
- 不让 VectCutAPI 成为必需依赖。

**建议步骤：**

- [ ] 添加 fake provider 返回合法 JSON 的 LLM planner 测试。
- [ ] 添加 LLM 返回非法 JSON 时不写 plan 文件的测试。
- [ ] 在显式 planner 选项后实现 `LLMRoughCutPlanner`。
- [ ] 用 fake client 添加 VectCutAPI adapter 测试。
- [ ] 实现作为 `RoughCutPlan` 薄翻译层的 `VectCutAPIAdapter`。
- [ ] 运行 `pytest tests/test_roughcut_llm_planner.py tests/test_jianying_vectcutapi_adapter.py -v`。
- [ ] 提交：`feat: add optional rough cut engines`。

**对话启动语：**

```text
按 docs/rough-cut/2026-07-09-rough-cut-draft-generation-development-requirements.md 的需求 R6 实现可选 LLM planner 和 VectCutAPIAdapter。只做 R6。依赖 R1-R5 已完成。不要改变默认主链路。
```

---

## 最终集成检查

只在 R1-R5 都完成后运行：

- [ ] `pytest -q`
- [ ] 用 fixture 项目生成 plan：`tripclipper roughcut plan <slug> --target-duration 90`。
- [ ] 导出 plan：`tripclipper jianying export <slug> --engine pyjianyingdraft`。
- [ ] 把生成的 `draft_content.json` 安装到临时剪映草稿库副本。
- [ ] 人工打开剪映 10，确认新草稿出现、可打开、媒体不丢失、保存后可再次打开。

最终预期链路：

```text
cut_index.json + project.yaml
  -> tripclipper roughcut plan
  -> rough_cut_plan.json
  -> tripclipper jianying export
  -> draft_content.json
  -> tripclipper jianying install
  -> 剪映 10 打开新草稿
```

## Grilling 决策记录（R0-R3 only）

| 编号 | 范围 | 决策 |
| --- | --- | --- |
| G1 | R0 Fixture 包 | 保留用户提供的旧 rough cut / realistic draft 成对样本，分别命名为 `legacy_eval_rough_cut_source.json` 和 `realistic_draft_content.json`。 |
| G2 | R0 Fixture 包 | R0 执行者基于成对样本构造正式 `minimal_rough_cut_plan.json`，不实现通用转换工具，也不要求用户手写。 |
| G3 | R0 Fixture 包 | `draft_content.json` 使用用户提供的真实复杂样本，不再额外手写 `minimal_draft_content.json`。 |
| G4 | R0 Fixture 包 | 自动测试使用 `minimal_template_draft/`；真实剪映 10 空草稿模板只用于人工验收。 |
| G5 | R1 RoughCutPlan Schema | 顶层保留 `timeline`，删除顶层 `text_overlays`、`bgm`、`transitions`；文本、BGM、转场都在 timeline segment 内表达。 |
| G6 | R1 RoughCutPlan Schema | 第一版支持多轨，并校验每个 `(track_type, track_index)` 内不重叠。 |
| G7 | R1 RoughCutPlan Schema | 图片轨在 plan 中使用 `track_type="image"`，导出时映射到剪映内部结构。 |
| G8 | R1 RoughCutPlan Schema | `source_candidate_status` 改名为 `candidate_status_snapshot`，表示 `edit_candidate_status` 快照，只用于审阅、解释和校验。 |
| G9 | R1 RoughCutPlan Schema | `asset_id + asset_relative_path` 是素材主身份；`asset_path` 是路径快照和兜底。 |
| G10 | R1 RoughCutPlan Schema | 时间统一用 float 秒；video/audio 必须有 `source_range`，image/text 必须没有 `source_range`。 |
| G11 | R1 RoughCutPlan Schema | `unused_assets` 保留但允许为空，不要求覆盖所有未用素材。 |
| G12 | R2 Jianying10Installer | installer 依赖模板草稿目录，复制模板外壳再写入内容，不从零生成剪映外壳。 |
| G13 | R2 Jianying10Installer | 第一版只支持 copy，不实现 hardlink。 |
| G14 | R2 Jianying10Installer | 安装报告写在输入 `draft_content.json` 同目录，不写入剪映草稿目录。 |
| G15 | R2 Jianying10Installer | 新剪映草稿目录名使用 `tc-<draft_name_slug>-<YYYYMMDD-HHMMSS>-<random6>`。 |
| G16 | R2 Jianying10Installer | 每次安装生成新的 `timeline_id = uuid.uuid4().hex`。 |
| G17 | R3 JianyingDraftExporter | `pyJianYingDraft` 是核心强依赖；`VectCutAPIAdapter` 后置到 R6。 |
| G18 | R3 JianyingDraftExporter | exporter 可在 `output_dir/pyjianying_work/` 创建中间草稿目录，并默认保留；不得写真实剪映草稿库。 |
| G19 | R3 JianyingDraftExporter | R3 输出与 `realistic_draft_content.json` 做语义比较，不做字节级比较。 |
| G20 | R0-R3 范围 | 本轮修订只覆盖 R0-R3；R4-R6 后续单独 grilling。 |

## 自审记录

- Spec 覆盖：R1 覆盖 `RoughCutPlan`；R2 覆盖 `Jianying10Installer`；R3 覆盖 `JianyingDraftExporter`；R4 覆盖 `RoughCutPlanner`；R5 覆盖 CLI；R6 覆盖可选 LLM/VectCutAPI。
- 范围拆分：每个需求都有独立测试文件、文件边界、依赖和对话启动语。
- 安装检查策略：`install/create` 使用内置检查，不增加单独的用户预览模式。
- 依赖策略：`pyJianYingDraft` 是 R3 强依赖；`VectCutAPIAdapter` 保持后续可选。
