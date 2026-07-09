# TripClipper 粗剪与剪映草稿生成设计文档

日期：2026-07-09

## 1. 结论

原草案的三段式设计方向正确：`RoughCutPlanner` 决定剪什么，`JianyingDraftExporter` 把计划翻译为剪映草稿内容，`Jianying10Installer` 负责让剪映 10 稳定识别草稿。这个边界值得保留。

需要调整的是文档层次和契约清晰度。原草案把产品决策、模块职责、剪映 10 文件经验、CLI 命名和实现顺序放在同一份文档里，读起来可用，但实现时容易把“粗剪方案”和“剪映草稿落盘”耦合在一起。本轮设计把它拆成两份文档：

- 设计文档：说明目标、用户流程、模块边界、产物、阶段策略和验收标准。
- 技术文档：说明数据模型、接口、路径、CLI、剪映 10 安装不变量、错误处理和测试策略。

核心原则是：`rough_cut_plan.json` 是稳定中心契约，剪映草稿只是一个导出落地器。剪映导出失败时，粗剪计划仍然应该独立有用、可审、可改、可重跑。

## 2. 背景

TripClipper 已完成素材筛选能力，现有流水线能从原始素材生成 `cut_index.json`，并通过分析、雷同组仲裁和默认候选池得到适合进入剪辑决策的素材集合。下一步能力是从“筛选好的素材”进入“可执行的粗剪方案”，再进一步生成剪映 10 可打开的草稿副本。

现有领域语言里已经明确三类字段的边界：

- `rating` 表示素材自身质量。
- `similar_selection` 表示雷同组内相对选择。
- `edit_candidate_status` 表示全局候选池角色。

粗剪阶段必须消费这些既有语义，而不是重新发明筛选规则。它可以根据成片目标进一步取舍、排序和裁切，但必须保留选择理由，便于用户理解和人工修正。

## 3. 目标

本阶段要交付两层价值：

1. 生成一个可审阅的粗剪计划：
   - 从 `cut_index.json` 和 `project.yaml` 的剪辑意图出发。
   - 选择素材、片段范围、时间线顺序和声音策略。
   - 输出 `rough_cut_plan.json`，并能导出给人看的计划说明。

2. 生成一个剪映 10 可打开的草稿：
   - 把 `rough_cut_plan.json` 翻译成 `draft_content.json`。
   - 安装为一个新的剪映草稿目录。
   - 保证不修改原始素材，不覆盖用户现有剪映项目。

第一版优先保证“单方案、基础时间线、稳定打开”。复杂特效、多方案比较、自动成片和完整字幕工作流不进入第一版。

## 4. 非目标

- 不生成最终视频文件。
- 不操控剪映 UI。
- 不原地修改用户已有剪映草稿。
- 不修改、移动、覆盖原始素材。
- 不做完整调色、复杂转场、复杂音频混音。
- 不在 `JianyingDraftExporter` 或 adapter 内做 LLM 粗剪决策。
- 不让 `pyJianYingDraft` 和 `VectCutAPI` 各自维护不同业务逻辑。

## 5. 推荐方案

本设计比较三种方案：

### 5.1 方案 A：只做粗剪计划，不生成剪映草稿

优点：

- 实现风险最低。
- 与 TripClipper 当前“剪辑前整理工具”的定位最一致。
- 产物稳定、可审、可手工使用。

缺点：

- 用户仍然需要手动把素材拖入剪映。
- 已验证的剪映 10 草稿经验没有沉淀到产品能力中。

### 5.2 方案 B：粗剪计划加剪映导出，但剪映导出作为独立落地器

优点：

- 粗剪计划本身有稳定价值。
- 剪映导出失败不会破坏主产物。
- 模块边界清楚，便于测试和替换 adapter。
- 能把已验证的剪映 10 文件规则固化为安装器契约。

缺点：

- 需要同时维护计划 schema、草稿导出和安装器三层契约。
- 第一版必须克制功能范围，避免把剪映草稿结构研究扩大成独立大项目。

### 5.3 方案 C：直接从 `cut_index.json` 生成剪映草稿

优点：

- 表面链路短。
- Demo 速度可能最快。

缺点：

- 粗剪决策不可审，难以手改和重跑。
- adapter 容易复制业务逻辑。
- 剪映文件结构变化会污染上游剪辑决策。
- 后续支持 CapCut、EDL、CSV 或其他导出格式时需要重做。

### 5.4 本设计选择

选择方案 B。它保留原草案三模块结构，但把 `rough_cut_plan.json` 提升为中心契约。实现顺序先固化最小计划 schema，再尽快处理风险最高的 `Jianying10Installer`。产品上不把剪映草稿当作唯一成果。

## 6. 用户流程

### 6.1 最小成功流程

```text
已有项目 cut_index.json + project.yaml
  -> tripclipper roughcut plan <slug>
  -> projects/<slug>/rough_cut_plan.json
  -> tripclipper jianying create <slug>
  -> projects/<slug>/exports/jianying/<draft_id>/
  -> 剪映 10 草稿库中新草稿
```

用户得到：

- 一个可读、可修改、可重跑的 `rough_cut_plan.json`。
- 一个新建的剪映 10 草稿。
- 一份导出报告，说明用了哪些素材、哪些素材未使用、安装路径和校验结果。

### 6.2 分步调试流程

```text
tripclipper roughcut plan <slug>
tripclipper jianying export <slug> --plan projects/<slug>/rough_cut_plan.json
tripclipper jianying install --draft-content <path> --name <draft_name>
```

分步命令用于定位问题：

- `plan` 失败：问题在输入数据、剪辑意图或 LLM 输出校验。
- `export` 失败：问题在计划到 `draft_content.json` 的翻译。
- `install` 失败：问题在剪映 10 草稿目录、素材落盘或文件一致性。

## 7. 模块边界

### 7.1 `RoughCutPlanner`

职责：生成粗剪计划。

输入：

- `projects/<slug>/cut_index.json`
- `projects/<slug>/project.yaml`
- 命令行覆盖参数，例如目标时长、风格、声音偏好

输出：

- `projects/<slug>/rough_cut_plan.json`

它决定：

- 选用哪些素材。
- 每条素材取哪个片段。
- 片段顺序和预计时长。
- 哪些片段保留原声、静音或压低。
- 标题、标签、字幕占位和 BGM 意图。
- 未使用关键素材的原因。

它不做：

- 不写剪映草稿。
- 不调用 `pyJianYingDraft` 或 `VectCutAPI`。
- 不复制素材。
- 不修改 `cut_index.json`。

第一版可以先支持启发式计划器，再接入 LLM 计划器。无论计划来源是什么，输出都必须通过同一个 `RoughCutPlan` schema 校验。

### 7.2 `JianyingDraftExporter`

职责：把 `rough_cut_plan.json` 翻译为剪映草稿内容。

输入：

- `rough_cut_plan.json`
- 导出配置，例如 `engine=pyjianyingdraft`

输出：

- `draft_content.json`
- 可选 `draft_meta_info.json`
- `DraftExportResult`

它负责：

- 创建基础时间线。
- 添加视频、图片、音频、文本轨。
- 表达片段裁切、排序、静音、BGM、标题和基础转场。
- 记录 adapter 能力不足导致的降级。

它不做：

- 不重新筛选素材。
- 不调用 LLM。
- 不写剪映草稿库目录。
- 不处理剪映 10 多镜像文件一致性。

第一版默认 adapter 是 `PyJianYingDraftAdapter`。`VectCutAPIAdapter` 后置为兼容性对照和备用实现。

### 7.3 `Jianying10Installer`

职责：把 exporter 产出的剪映草稿内容安装为剪映 10 可打开的新草稿。

输入：

- `draft_content.json`
- `draft_name`
- 剪映草稿库路径
- 剪映 10 模板草稿目录
- 素材处理模式：`copy` 或 `hardlink`

输出：

- 新草稿目录。
- 安装报告。
- 校验结果。

它负责：

- 创建唯一草稿目录。
- 生成新的 `timeline_id`。
- 从模板复制草稿外壳。
- 复制或硬链接素材到草稿内 `assets/`。
- 重写 `draft_content.json` 中素材路径。
- 同步写入剪映 10 需要的多个镜像文件。
- 校验草稿目录内部不再引用临时路径或旧草稿路径。

它不做：

- 不理解素材内容。
- 不改变剪辑顺序。
- 不调用 adapter。
- 不操控剪映 UI。

## 8. 数据产物

### 8.1 `cut_index.json`

已有事实源。粗剪阶段只读取它，不写回。

粗剪优先消费：

- `default_candidates`
- `assets[].edit_candidate_status`
- `assets[].edit_candidate_priority`
- `assets[].clip_suggestions`
- `assets[].audio_strategy`
- `assets[].rating`
- `assets[].subject_type`
- `assets[].shot_scale`
- `assets[].shot_function`
- `assets[].tags`
- `similar_groups`
- `sessions`

### 8.2 `rough_cut_plan.json`

新的中心契约。它表达剪辑计划，不表达剪映文件结构。

必须具备：

- 项目和计划元信息。
- 输入快照摘要。
- 目标成片参数。
- 时间线片段列表。
- 每个片段的 source range 和 timeline range。
- 素材引用和选择理由。
- 音频策略。
- 文本和标题元素。
- BGM 策略。
- 导出提示和兼容性约束。

### 8.3 `draft_content.json`

由 `JianyingDraftExporter` 生成。它是剪映草稿内容，但不是完整剪映 10 草稿目录。

### 8.4 剪映 10 草稿目录

由 `Jianying10Installer` 生成。它是最终可被剪映桌面端识别的草稿副本。

## 9. 原草案需要修正的点

### 9.1 `rough_cut_plan.json` 需要成为强 schema

原草案只描述“必须包含什么”，还没有明确 schema、校验规则和失败行为。实现时必须用 Pydantic 模型作为代码单一来源，否则 LLM 输出、手写 JSON 和 adapter 消费会很快漂移。

### 9.2 installer 应该有 dry-run 和 preflight

剪映草稿库是用户真实应用目录。即使安装器只创建新草稿，也需要在写入前检查：

- 剪映草稿库路径存在。
- 模板草稿目录完整。
- 目标草稿目录不存在。
- 所有素材源文件可读。
- `copy` 或 `hardlink` 模式可用。

第一版 `create` 命令可以默认真正安装，但 `install` 命令必须支持 `--dry-run` 便于调试。

### 9.3 adapter 能力差异需要显式记录

不同第三方 API 对文本、转场、静音、BGM 和素材路径字段的支持程度不同。adapter 不能悄悄丢功能，必须在 `DraftExportResult.warnings` 中记录降级。

### 9.4 `engine=both` 不应是一线用户功能

对照模式适合作为开发验证能力，但不适合作为第一版主流程。第一版用户命令应保持单 engine，开发测试可以保留 internal compare 命令或测试夹具。

### 9.5 剪映缓存不能作为验收依据

原草案已经指出剪映缓存可能显示旧路径。技术验收必须以草稿目录内 JSON 文件和素材文件存在性为准，人工打开剪映只作为最终冒烟测试。

## 10. 实施阶段

### Phase 1：固化 `RoughCutPlan` schema

先定义中心契约和校验器。用手写计划 fixture 验证 schema 能表达视频、图片、BGM、标题、文本占位和基础转场。

完成标准：

- `rough_cut_plan.json` 可读写。
- 无效时间码、缺失素材、重叠片段能被清楚拒绝。
- 手写计划能作为 exporter 输入。

### Phase 2：实现 `Jianying10Installer`

先固化已验证的剪映 10 落盘规则。安装器可以消费已有 `draft_content.json` fixture，不依赖 planner。

完成标准：

- 生成唯一草稿目录。
- 写入剪映 10 关键镜像文件。
- 素材路径全部重写到草稿内 assets。
- 安装报告能说明每项校验结果。

### Phase 3：实现 `JianyingDraftExporter` 和 `PyJianYingDraftAdapter`

把手写 `rough_cut_plan.json` 翻译成 `draft_content.json`。

完成标准：

- 同一计划重复导出结果稳定。
- exporter 不修改计划和源素材。
- installer 安装后剪映可打开。

### Phase 4：实现 `RoughCutPlanner`

接入真实 `cut_index.json`。第一版允许启发式 planner 先落地，LLM planner 接在同一 schema 后面。

完成标准：

- 从默认候选池生成一个连贯计划。
- 总时长接近目标时长。
- 每个片段都有选择理由。
- 计划可人工修改后继续导出。

### Phase 5：后置 `VectCutAPIAdapter`

作为兼容性对照和备用 adapter，不进入第一版主路径。

完成标准：

- 消费同一个 `RoughCutPlan`。
- 输出经过同一个 installer。
- 差异来自 API 表达能力，而不是业务逻辑分叉。

## 11. 验收标准

### 自动验收

- `RoughCutPlan` schema 能校验合法计划并拒绝非法计划。
- planner 不选择 `edit_candidate_status=excluded` 的素材，除非计划里写明人工覆盖原因。
- timeline 片段不重叠，总时长与目标时长误差在配置阈值内。
- exporter 输出的 material 和 segment 引用一致。
- installer 写入的剪映 10 镜像文件内容一致。
- 安装后的草稿目录中素材引用全部存在。
- 原始素材没有被修改。

### 人工验收

- 剪映 10 能看到新草稿。
- 打开草稿不丢素材。
- 主时间线顺序与 `rough_cut_plan.json` 一致。
- 视频、图片、BGM 和文本占位可见。
- 草稿保存后仍可再次打开。

## 12. 成功后的用户体验

用户完成素材筛选后，可以运行一次命令得到一个粗剪草稿。草稿不是最终成片，而是已经把“选哪些、怎么排、哪里保留原声、哪里放标题”准备好的可编辑起点。

如果剪映草稿生成失败，用户仍然能拿到 `rough_cut_plan.json`，并可用它人工剪辑或等待修复后重跑导出。这是 TripClipper 从素材整理进入粗剪副驾的关键安全边界。
