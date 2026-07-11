## ADDED Requirements

### Requirement: 剪映 draft 导出 API
系统 MUST 暴露一个聚焦的 exporter API，用于通过指定 export engine 将 `RoughCutPlan` 转换成剪映 draft content。

#### Scenario: 公共 exporter 符号可导入
- **GIVEN** `tripclipper.jianying` package
- **WHEN** consumer 导入 exporter API
- **THEN** `JianyingDraftExporter`、`JianyingDraftAdapter`、`AdapterCapabilities`、`DraftExportResult` 和 `DraftExportError` SHALL 可用。

#### Scenario: 默认 engine 导出 plan
- **GIVEN** 一个合法 `RoughCutPlan` 和可写 `output_dir`
- **WHEN** 调用 `JianyingDraftExporter.export(plan, output_dir)` 且未显式传入 engine
- **THEN** exporter SHALL 使用 `pyjianyingdraft` engine
- **AND** 返回的 `DraftExportResult` SHALL 包含 `engine`、`draft_content_path`、`media_paths` 和 `warnings`。

#### Scenario: 不支持的 engine 会被拒绝
- **GIVEN** 一个合法 `RoughCutPlan`
- **WHEN** 使用未知 engine 请求导出
- **THEN** export SHALL 以 `DraftExportError` 失败
- **AND** 不得写入任何剪映草稿库目录。

### Requirement: 导出副作用边界
Exporter MUST 只在请求的 `output_dir` 下写导出产物，并且 SHALL NOT 执行安装或 planning 工作。

#### Scenario: 输出被限制在 output_dir 内
- **GIVEN** 一个合法 `RoughCutPlan` 和 `output_dir`
- **WHEN** export 成功
- **THEN** exporter 创建的所有文件 SHALL 位于 `output_dir` 内
- **AND** `draft_content.json` SHALL 存在于 `output_dir` 下。

#### Scenario: 源输入不会被修改
- **GIVEN** 一个引用源媒体和 cut-index 文件的合法 `RoughCutPlan`
- **WHEN** export 成功
- **THEN** exporter SHALL NOT 修改输入 plan 对象
- **AND** SHALL NOT 修改被引用的源媒体文件
- **AND** SHALL NOT 修改被引用的 cut index。

#### Scenario: Export 不安装草稿
- **GIVEN** 一个合法 `RoughCutPlan`
- **WHEN** export 成功
- **THEN** exporter SHALL NOT 创建新的剪映草稿库项目目录
- **AND** SHALL NOT 调用 `Jianying10Installer.install`。

### Requirement: 解析 plan 媒体但不重新筛选
Exporter MUST 消费 `RoughCutPlan` 中已经选好的 timeline segments，并且 SHALL NOT 做二次粗剪筛选。

#### Scenario: Cut index 只用于路径解析和校验
- **GIVEN** 一个 `project.cut_index_path` 指向可读 cut index 的 plan
- **WHEN** export 解析媒体
- **THEN** exporter MAY 使用 cut index 解析 `asset_relative_path` 并校验媒体身份
- **AND** SHALL NOT 使用 cut index 新增、删除、重排或替换 timeline segments。

#### Scenario: Adapter 不读取 cut index 做选择
- **GIVEN** 一个包含已选 timeline segments 的 plan
- **WHEN** adapter 导出该 plan
- **THEN** adapter SHALL 消费传入的已选 segments
- **AND** SHALL NOT 读取 `cut_index.json` 来做候选过滤、选择、替换或排序。

#### Scenario: 必需媒体缺失时导出失败
- **GIVEN** 一个媒体 timeline segment 的源路径无法解析到可读文件
- **WHEN** export 运行
- **THEN** export SHALL 以 `DraftExportError` 失败
- **AND** error SHALL 标识无法解析的 segment 或媒体路径。

### Requirement: PyJianYingDraft adapter
系统 MUST 提供一个必需的 `pyjianyingdraft` adapter，将支持的 `RoughCutPlan` timeline segments 翻译成剪映 draft content。

#### Scenario: PyJianYingDraft 是必需依赖
- **GIVEN** 项目测试环境
- **WHEN** exporter 测试导入默认 adapter 依赖
- **THEN** 缺少 `pyJianYingDraft` SHALL 导致测试失败
- **AND** 该依赖 SHALL NOT 被当作 optional skip。

#### Scenario: 中间工作区默认保留
- **GIVEN** 一个合法 `RoughCutPlan` 和 `output_dir`
- **WHEN** `pyjianyingdraft` adapter 导出 plan
- **THEN** 它 MAY 创建 `output_dir/pyjianying_work/`
- **AND** 该中间工作区 SHALL 默认保留。

#### Scenario: 安全能力降级会被报告
- **GIVEN** 一个 adapter 无法完全表达但可以安全省略或简化的 plan feature
- **WHEN** export 在降级后成功
- **THEN** `DraftExportResult.warnings` SHALL 包含描述该不支持能力或简化行为的 warning。

### Requirement: 剪映 draft content 语义
Exporter MUST 生成与源 `RoughCutPlan` 用户可见 timeline 语义一致的剪映 draft content。

#### Scenario: Fixture export 与真实 draft 语义匹配
- **GIVEN** `tests/fixtures/roughcut/minimal_rough_cut_plan.json`
- **WHEN** 该 plan 通过 `pyjianyingdraft` 导出
- **THEN** 生成的 `draft_content.json` SHALL 与 `tests/fixtures/jianying/realistic_draft_content.json` 在语义上匹配
- **AND** 比较范围 SHALL 包括主视频顺序、source timeranges、target timeranges、BGM 时间和音量、图片覆盖时间、文本内容和时间。

#### Scenario: 不要求 draft 字节级一致
- **GIVEN** 生成的剪映 draft content
- **WHEN** 它与真实 draft fixture 比较
- **THEN** id、内部素材引用、字段顺序、时间戳、剪映版本字段和 pyJianYingDraft 辅助字段的差异 SHALL 被允许。

#### Scenario: Timeline track type 被映射
- **GIVEN** 一个包含 `video`、`audio`、`image` 和 `text` track type 的 plan timeline
- **WHEN** export 成功
- **THEN** 生成的 draft SHALL 为每种支持的 track type 包含对应的可见或可听剪映 timeline 内容。

### Requirement: 导出结果兼容 installer
导出的 draft content MUST 与剪映 10 installer API 兼容。

#### Scenario: 导出的 fixture draft 可以被安装
- **GIVEN** `tests/fixtures/roughcut/minimal_rough_cut_plan.json`
- **WHEN** 该 plan 被导出到临时输出目录
- **THEN** 生成的 `draft_content.json` SHALL 被 `Jianying10Installer` 使用 fixture 或 bundled template 输入接受
- **AND** installation SHALL 生成新的 draft directory，且安装阶段不需要 exporter 再做修改。
