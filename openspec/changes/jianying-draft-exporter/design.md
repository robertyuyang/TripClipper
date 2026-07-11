## 背景

R0/R1 已经建立了可移植 fixture 和 `RoughCutPlan` schema，并把它作为粗剪意图的中心契约。R2 隔离了剪映安装行为：它消费一个已有的 `draft_content.json`，把媒体复制到新草稿本地 `assets/` 目录，并写入剪映 10 草稿外壳。R3 缺的就是这两个契约之间的桥。

Exporter 必须把 timeline 意图翻译成剪映 draft content，但不能变成 planner 或 installer。它可以从 `plan.project.cut_index_path` 读取 cut index 来解析和校验媒体路径，但不能重新解释候选状态、重排素材，也不能决定哪些片段应该进入剪辑。默认导出 engine 是 `pyjianyingdraft`；`VectCutAPI` 保留到后续 R6。

## 目标 / 非目标

**目标：**

- 暴露 `JianyingDraftExporter.export(plan, output_dir, engine="pyjianyingdraft")`。
- 新增 `JianyingDraftAdapter` interface 和 `PyJianYingDraftAdapter` 实现。
- 新增 `DraftExportResult`、`AdapterCapabilities` 和 `DraftExportError` 模型。
- 只在 `output_dir` 内写导出产物，包括 `draft_content.json` 和可选的 `draft_meta_info.json`。
- 默认保留 `output_dir/pyjianying_work/`，方便调试 pyJianYingDraft 的中间输出。
- 生成与真实剪映 draft fixture 在语义上等价的 fixture draft content。
- 证明导出的 `draft_content.json` 可以被 `Jianying10Installer` 消费。

**非目标：**

- 不实现启发式 planner 或 LLM planner。
- 不实现 `VectCutAPIAdapter`。
- 不新增 CLI 命令或端到端 `create` 编排。
- 不写真实剪映草稿库。
- 不把默认导出路径所需的 `pyJianYingDraft` 做成 optional。

## 决策

### Exporter dispatch 保持很薄

`JianyingDraftExporter` 负责解析 engine、保证输出范围只在 `output_dir` 内，并把具体 draft 构造交给 adapter。这样 engine 相关知识不会散落到 orchestration 类里，后续新增 optional adapter 时也不需要复制公共 API。

备选方案：把所有 pyJianYingDraft 调用都直接放进 `JianyingDraftExporter`。这会让 R3 略简单，但 R6 接入 VectCutAPI 时会更痛，要么复制 orchestration 行为，要么再重构。

### `pyJianYingDraft` 是核心依赖

R3 将 `pyJianYingDraft` 作为必需依赖，并加入核心依赖列表。测试环境缺少该依赖时应该失败，而不是静默 skip exporter 测试。

备选方案：使用 optional import，缺失时 skip 或 warning。这样会削弱第一条可用主链路，因为 CI 可能在没有验证默认 engine 的情况下通过。

### 解析媒体路径，但不重新筛选媒体

Exporter 可以读取 `plan.project.cut_index_path` 指向的 cut index，用来解析 `asset_relative_path` 和校验身份；必要时回退到 `asset_path`。Adapter 接收的是已经选好的 timeline segments，不能读取 `cut_index.json` 来过滤、替换、排序或补充素材。

备选方案：让 adapter 自己读 cut index。这样会模糊 planner 和 exporter 的边界，也会让不同 engine 的行为更难比较。

### 不支持的 adapter 能力用 warning 表达

Adapter 暴露 `AdapterCapabilities`，对可以安全降级的能力返回 warnings，例如不支持某些转场细节或文本样式细节。必需媒体缺失、时间范围无法表达等问题仍然是 export error。

备选方案：任何装饰性能力不支持都直接失败。这样第一版 exporter 会过脆，即使生成的 draft 在用户可见语义上仍然可用，也会被阻断。

### 用语义回归，不做字节级 draft 比较

剪映 draft JSON 会包含 id、时间戳、版本元数据和 pyJianYingDraft 自动生成的辅助字段，这些字段可以合法变化。测试应该比较用户可见语义：主视频顺序、source/target timerange、BGM 时间和音量、图片覆盖时间、文本内容和时间。

备选方案：生成 JSON 与 fixture 做字节级比较。这样会过拟合 pyJianYingDraft 内部字段，遇到无害元数据变化也会失败。

## 风险 / 取舍

- `pyJianYingDraft` API 可能和预期不同 -> 把调用隔离在 `PyJianYingDraftAdapter` 内，测试钉住 TripClipper 语义而不是每个生成字段。
- 语义比较 helper 可能漏掉剪映结构问题 -> 增加 installer 兼容性测试，并保留 `pyjianying_work/` 方便人工检查。
- 部分 plan feature 可能无法完整映射到 pyJianYingDraft -> 对安全降级写 warnings，只对必需媒体或时间表达失败抛 hard error。
- fixture 相对路径解析可能有歧义 -> 失败前按 repo root、当前工作目录、plan/cut-index 上下文做归一化解析。

## 迁移计划

本变更新增能力，不迁移现有用户数据。实现时先添加失败版 exporter/adapter 测试，再实现模型和 engine dispatch，再实现 pyJianYingDraft adapter，最后补上语义比较和 installer 集成测试。已有 R0/R1/R2 测试应保持通过。

## 未决问题

- 实现前需要确认 `pyJianYingDraft` 的准确 package 名和 import path，再固定 `pyproject.toml` 中的依赖写法。
- 第一版 adapter 的文本样式和图片覆盖映射，可能需要根据 pyJianYingDraft 实际输出做 fixture-driven 微调。
