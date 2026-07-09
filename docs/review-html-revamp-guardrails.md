# review.html 改版保留清单

本文档沉淀当前 `review.html` 已具备、改版时应保留的功能要点。目标不是锁死现有视觉样式，而是保护页面的信息结构、交互能力、数据可达性。

适用范围：

- `src/tripclipper/exporter.py`
- `src/tripclipper/templates/review.html.tmpl`
- `tests/test_exporter.py`

## 1. 页面目标

`review.html` 是导出的离线审阅页。它必须在单个 HTML 中完成以下事情：

- 展示项目级摘要
- 展示相似组审阅入口
- 展示全部素材列表
- 支持按多维属性快速筛选
- 支持打开素材详情、缩略图和视频预览
- 支持从相似组快速定位到素材在主列表中的位置

改版可以改变布局、视觉风格、折叠方式，但不能牺牲以上职责。

## 2. 顶部 Header 必须保留的信息

Header 必须继续展示项目级基础信息：

- 项目名
- slug
- `source_folder`
- 模型提供方信息：`provider`、`vision_model`、`api_key_env`
- 分析信息：`analysis.stage`、`analysis.status`、开始/结束时间
- 素材总数
- 按素材类型聚合
- 按 `analysis_status` 聚合

Header 还必须保留 overview 摘要区：

- `rating` 分布
- 相似组汇总：组数、成员总数、待人工确认组数
- 候选池汇总：`default_selected` / `alternate` / `excluded` / `needs_review`
- session 汇总：session 总数；存在 unknown bucket 时显示 unknown 数量

异常/提示信息也必须保留：

- 未完成 `sample/full` 分析时，页面要有显式提示，说明分析字段可能为空
- `cut_index.failures` 非空时，页面要展示项目级 failures

## 3. 相似组区域必须保留的能力

相似组区域可以改版，但必须继续作为页面顶部的“去重审阅入口”，并保留：

- 无相似组时，该区域可整体消失，不留下空壳
- 有相似组时，必须展示组级摘要，而不是只在主列表里埋字段
- 顶层需要能收起/展开，避免大量相似组占满首屏
- 单组需要能收起/展开，避免大组成员一次性全铺开

每个相似组至少要保留这些信息：

- `similar_group_id`
- 置信度（若有）
- `basis`
- 是否 `needs_review`
- 主选/备选数量

每个组成员至少要保留这些信息：

- 缩略图
- 文件名
- 资产 id 尾部短标识
- `similar_selection`
- `rating`
- `similar_reason` 摘要

成员顺序要求：

- 继续按 `similar_rank` 排序，保证主选/备选阅读顺序稳定

跨区联动要求：

- 点击相似组成员，必须能定位到主列表对应素材
- 若素材位于折叠的 session 区块内，必须先展开该区块再滚动定位
- 定位后要有明显高亮反馈，帮助用户确认已跳到目标素材

## 4. 主列表/素材区必须保留的能力

主列表可以不是“单个超长表格”，但必须继续承担“全量素材浏览器”的角色。

### 4.1 分组方式

当前实现是按 session 分组展示。改版时必须保留以下语义：

- 已分配 session 的素材，要按 session 聚合展示
- 有时间信息的 session，要展示时间摘要
- `session_00_unknown` 要作为独立 bucket，且明确表现为“时间信息缺失”
- 没有任何 session 数据时，仍要有兜底区块承载素材，当前文案为“未分组素材”
- 兜底区块默认可见，保证无 session 项目也能直接使用

### 4.2 session 摘要信息

每个 session 区块至少要保留：

- `session_id`
- 起止时间，格式可调整，但要能看出时间范围
- 素材数量
- unknown / ungrouped 状态的显式标记

### 4.3 素材行字段

单条素材在主列表中必须继续可见以下信息：

- 缩略图
- 文件名
- 媒体信息：类型、时长、分辨率、codec、fps、体积、是否含音频
- `rating`
- `subject_type`
- `people_presence`
- `shot_scale`
- `shot_function`
- `tags`
- `summary`
- `clip_suggestions`
- `audio_strategy`
- 相似组信息
- 候选池状态
- `analysis_status`

说明：

- session 已升到分组层后，主列表里不必重复单独 session 列，但 session 语义不能丢
- 对字段名称是否继续用英文列名，改版可调整；字段本身必须可达

### 4.4 素材行的状态表达

不同分析状态要继续有明显区分：

- `analyzed`
- `scanned` / `analyzing`
- `analysis_failed`

并保留对应降级展示逻辑：

- `analyzed` 但没有 `summary` 时，要明确提示模型未生成 summary
- `scanned` / `analyzing` 时，不能空白；要用“待分析 + 扫描期可用信息”兜底
- `analysis_failed` 时，优先展示失败原因；没有原因也要明确是失败

## 5. 筛选能力必须保留

改版后必须还能对“全量素材”做统一筛选，而不是只筛当前展开区块。

必须保留的筛选项：

- 文本搜索：覆盖 `filename` / `relative_path` / `summary` / `tags`
- `subject_type`
- `shot_scale`
- `analysis_status`
- 相似组成员状态：全部 / 仅相似组成员 / 仅非相似组
- 候选池状态
- session

筛选行为要求：

- 筛选作用于所有素材行
- session 过滤选项要来自真实 `session` 数据，不是硬编码
- session 选项文案要能带出时间和素材数，便于识别
- 某个 session 区块在筛选后如果没有任何可见素材，应自动隐藏该区块
- 页面上要持续显示“当前显示条数 / 总条数”

## 6. 详情抽屉必须保留

点击素材行后，必须还能看到详情抽屉或等价详情面板。形式可改，但内容能力要保留：

- 打开/关闭单条素材详情
- 展示原始路径相关信息：`path`、`relative_path`
- 展示基础元数据：`type`、`size`、`modified_time`、`metadata`
- 展示缩略图/关键帧来源：`thumbnail_path`、`frame_paths`、`frame_timestamps`
- 展示 `clip_suggestions`
- 展示 `failures`、`warnings`

视频素材额外要求：

- 能直接打开原视频文件
- 能在页内预览播放视频，或提供等价能力

## 7. 缩略图/灯箱预览必须保留

缩略图相关交互必须保留：

- 主列表缩略图可点开大图/帧预览
- 相似组中的缩略图也可点开预览
- 若素材有多帧，预览层需要支持前后切换
- 若帧带时间戳，预览层要显示当前帧时间位置
- 预览层要能关闭，并支持键盘快捷键：
  - `Esc` 关闭
  - `←` / `→` 切换多帧

视频相关交互必须保留：

- 从预览层打开视频
- 在预览层内播放视频
- 预览层中图片区和视频区要共用统一的全屏覆盖交互模型，避免用户学习两套操作

## 8. 相似关系辅助感知必须保留

主列表中，相似关系不能只藏在文字里。至少要保留一种显式辅助感知：

- 悬停某条相似组素材时，高亮同组其他素材

如果未来换成交互更强的方案，也必须保证用户能快速看出“这条素材和哪些条目互相雷同”。

## 9. 离线导出约束必须保留

`review.html` 仍然必须保持离线可打开特性：

- 单文件 HTML 可直接打开
- 页面依赖内嵌 JSON 数据工作
- 不依赖在线接口才能完成核心浏览、筛选、详情、预览能力
- 本地文件通过 `file://` 可访问

同时要继续遵守当前脱敏边界：

- 导出到页面内的 `cut_index` 数据里，`project.model_config_summary` 需被清空

## 10. 改版时允许变化的部分

这些可以改：

- 视觉样式
- 卡片/表格/混合布局
- 相似组与 session 区块的具体折叠样式
- 列标题文案
- 详情面板是抽屉、侧边栏还是浮层

这些不应丢：

- 项目级摘要
- 相似组审阅入口
- 全量素材统一筛选
- session 维度浏览
- 素材详情可追溯
- 图片/视频预览
- 相似组到主列表定位联动
- 分析未完成、失败、unknown session 的降级表达

## 11. 验收建议

改版后，至少逐条验证以下场景：

1. 有多个相似组时，页面首屏不会被相似组完全占满
2. 相似组成员点击后，能展开对应 session 并定位到素材
3. session 很多、素材很多时，列表仍可快速浏览，筛选后空 session 会隐藏
4. 无 session 项目仍能正常浏览全部素材
5. `session_00_unknown` 会被单独识别，不与正常 session 混淆
6. `scanned` / `analysis_failed` 素材不会因为字段缺失而出现空白行
7. 图片、关键帧、视频都还能预览
8. 页面在脱网、本地双击打开场景下仍可使用

## 12. 代码锚点

后续改版优先对照这些实现入口：

- Header / overview：`src/tripclipper/exporter.py`
- 相似组渲染：`src/tripclipper/exporter.py`
- session 分组渲染：`src/tripclipper/exporter.py`
- 前端筛选、定位、抽屉、灯箱：`src/tripclipper/templates/review.html.tmpl`
- 回归测试：`tests/test_exporter.py`
