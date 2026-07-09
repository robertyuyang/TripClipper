# review.html 最小保留规格

本文档定义 `review.html` 改版时必须保留的功能要素。
目标：允许改布局、改视觉、改交互样式；不丢页面职责。

参考：

- [review-html-revamp-guardrails.md](file:///Users/bytedance/Documents/TripClipper_Trae/docs/review-html-revamp-guardrails.md)
- [review.html.tmpl](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/templates/review.html.tmpl)

## 1. 页面定位

`review.html` 是离线审阅页。必须继续承担 4 件事：

1. 展示项目级概览
2. 展示相似组审阅入口
3. 展示全部素材并支持筛选
4. 展示素材详情与预览

## 2. 改版可变项

这些可以改：

- 视觉风格
- 排版布局
- 表格或卡片形式
- 折叠方式
- 文案中英文

## 3. 改版不可丢项

### 3.1 Header

必须保留：

- 项目基础信息：项目名、slug、`source_folder`
- 分析信息：`analysis.stage`、`analysis.status`、时间信息
- 素材聚合：总数、类型计数、`analysis_status` 计数
- overview 摘要：
  - `rating` 分布
  - 相似组汇总
  - 候选池汇总
  - session 汇总
- notice / failures 提示

### 3.2 相似组区域

必须保留：

- 有相似组时，页面顶部存在独立相似组审阅入口
- 无相似组时，可整体不显示
- 每组至少可见：
  - `similar_group_id`
  - `confidence`
  - `basis`
  - `needs_review`
- 每个成员至少可见：
  - 缩略图
  - 文件名
  - `similar_selection`
  - `rating`
  - `similar_reason`
- 成员按 `similar_rank` 稳定排序
- 点击组成员，能定位到主列表对应素材，并有高亮反馈

### 3.3 素材区

必须保留：

- 页面能浏览全部素材，不可只剩局部视图
- session 语义保留：
  - 正常 session 分组
  - `session_00_unknown`
  - 无 session 数据时有兜底区
- 单条素材至少可达这些信息：
  - 缩略图
  - 文件名
  - 媒体信息
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

### 3.4 状态降级

必须保留：

- `analyzed`、`scanned/analyzing`、`analysis_failed` 有明确区分
- `summary` 缺失时有显式兜底文案
- 失败素材优先显示失败原因
- 未分析素材不能空白

### 3.5 筛选

必须保留统一筛选能力，且作用于全部素材：

- 文本搜索：`filename` / `relative_path` / `summary` / `tags`
- `subject_type`
- `shot_scale`
- `analysis_status`
- 相似组成员筛选
- 候选池状态筛选
- session 筛选
- 当前显示条数 / 总条数

### 3.6 详情

点击素材后，必须还能打开详情面板或等价视图。至少保留：

- `path` / `relative_path`
- `metadata`
- `thumbnail_path`
- `frame_paths`
- `frame_timestamps`
- `clip_suggestions`
- `failures`
- `warnings`

视频素材还必须保留：

- 打开原视频
- 页内播放或等价预览

### 3.7 预览

必须保留：

- 缩略图点开大图/关键帧预览
- 相似组中的缩略图也可预览
- 多帧可切换
- 有时间戳时显示时间位置
- 可关闭

### 3.8 离线约束

必须保留：

- 单文件 HTML 可直接打开
- 核心能力不依赖网络请求
- 页面依赖内嵌 JSON 工作
- 保持当前脱敏边界，不暴露敏感配置或密钥

## 4. 一句话验收

只要改版后用户仍能：

1. 看项目概览
2. 按相似组找素材
3. 按多维条件筛全部素材
4. 打开素材详情和预览
5. 在离线 HTML 中完成上述操作

则视为满足本规格。
