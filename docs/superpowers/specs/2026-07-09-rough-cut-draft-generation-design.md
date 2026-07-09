# TripClipper 粗剪与剪映草稿生成设计文档

日期：2026-07-09

## 1. 结论

原草案方向是对的：保留三段式链路。

```text
cut_index.json + project.yaml
  -> RoughCutPlanner
  -> rough_cut_plan.json
  -> JianyingDraftExporter
  -> draft_content.json
  -> Jianying10Installer
  -> 剪映 10 新草稿
```

需要收紧的是边界：`rough_cut_plan.json` 是中心契约，剪映草稿只是一个导出落地器。也就是说，粗剪计划必须独立有用；剪映导出失败时，用户仍然能拿计划人工剪或后续重试。

## 2. 为什么这样设计

TripClipper 已经完成素材筛选，现有事实源是 `cut_index.json`。粗剪阶段应该消费既有筛选语义，而不是重新发明一套判断：

- `rating`：素材自身质量。
- `similar_selection`：雷同组内相对选择。
- `edit_candidate_status`：全局候选池角色。

因此粗剪做的是“从候选素材里组织成片段和顺序”，不是重新筛选素材。

## 3. 目标与非目标

目标：

- 生成一个可审、可改、可重跑的 `rough_cut_plan.json`。
- 生成一个剪映 10 可打开的新草稿。
- 不修改原始素材，不覆盖用户已有剪映项目。

第一版只保证：

- 单个粗剪方案。
- 基础视频/图片/BGM/文本占位。
- 基础时间线顺序和裁切。
- 剪映 10 能打开草稿。

非目标：

- 不生成最终视频。
- 不操控剪映 UI。
- 不做复杂转场、调色、混音、完整字幕工作流。
- 不让 adapter 各自做粗剪业务逻辑。

## 4. 三个模块

### 4.1 `RoughCutPlanner`

职责：决定剪什么。

输入：

- `cut_index.json`
- `project.yaml`
- 目标时长、风格、声音偏好等参数

输出：

- `rough_cut_plan.json`

它决定：

- 使用哪些素材。
- 每条素材取哪个片段。
- 片段顺序和时长。
- 哪些片段保留原声、静音或作为 BGM 下方素材。
- 标题、标签、文本占位和 BGM 意图。
- 为什么使用或跳过关键素材。

它不做：

- 不写剪映草稿。
- 不调用 `pyJianYingDraft` 或 `VectCutAPI`。
- 不复制素材。
- 不修改 `cut_index.json`。

第一版可以先实现启发式 planner，后续再接 LLM planner。两者都必须输出同一个 `RoughCutPlan` schema。

### 4.2 `JianyingDraftExporter`

职责：把 `rough_cut_plan.json` 翻译成剪映草稿内容。

输入：

- `rough_cut_plan.json`
- adapter 配置，例如 `pyjianyingdraft`

输出：

- `draft_content.json`
- 可选 `draft_meta_info.json`

它不做：

- 不筛选素材。
- 不调用 LLM。
- 不写剪映草稿库。
- 不处理剪映 10 多镜像文件同步。

默认 adapter 用 `PyJianYingDraftAdapter`。`VectCutAPIAdapter` 后置为备选和兼容性对照。

### 4.3 `Jianying10Installer`

职责：把 exporter 产物安装成剪映 10 可识别的新草稿。

输入：

- `draft_content.json`
- 草稿名称
- 剪映草稿库路径
- 剪映 10 模板草稿目录
- 素材模式：`copy` 或 `hardlink`

它负责：

- 创建唯一新草稿目录。
- 生成新的 `timeline_id`。
- 从模板复制草稿外壳。
- 复制或硬链接素材到草稿内 `assets/`。
- 重写素材路径。
- 写入剪映 10 需要的关键镜像文件。
- 校验草稿目录可被剪映识别。

它不做：

- 不改变剪辑顺序。
- 不理解素材内容。
- 不调用 adapter。
- 不操控剪映 UI。

## 5. Dry-run 和 Preflight 是什么

这两个词只应该出现在 `Jianying10Installer` 这一环。

`preflight` 是安装前体检：在真正写入剪映草稿库之前，检查模板目录、剪映草稿库、素材文件、目标目录名和硬链接能力是否可用。

`dry-run` 是只做体检和生成报告，不真正创建剪映草稿目录。

有没有必要？有，但只在安装器里必要。原因是 installer 会写用户真实的剪映草稿库，即使它只创建新草稿，也可能遇到路径错、模板不完整、素材丢失、硬链接不可用等问题。提前检查能避免写出半个坏草稿。

需要简化的地方：

- `plan` 不需要 dry-run，它本来只写 TripClipper 项目产物。
- `export` 不需要 dry-run，它只写中间目录。
- `install` 支持 `--dry-run`，默认执行 preflight。
- `create` 可以默认直接安装，失败时保留前一步产物和错误报告。

## 6. 命令形态

分步命令：

```bash
tripclipper roughcut plan <slug> --target-duration 90
tripclipper jianying export <slug> --engine pyjianyingdraft
tripclipper jianying install --draft-content <path> --name <draft_name>
```

一键命令：

```bash
tripclipper jianying create <slug> --target-duration 90 --engine pyjianyingdraft
```

一键命令等价于：

```text
plan -> export -> install
```

任一阶段失败时停止，并保留前一阶段成功产物。

## 7. 实施顺序

1. 定义 `RoughCutPlan` schema 和校验。
2. 实现 `Jianying10Installer`，固化剪映 10 落盘规则。
3. 实现 `JianyingDraftExporter` 和 `PyJianYingDraftAdapter`。
4. 实现启发式 `RoughCutPlanner`。
5. 后置接入 LLM planner 和 `VectCutAPIAdapter`。

## 8. 验收标准

自动验收：

- `rough_cut_plan.json` 可校验、可读写。
- planner 默认只用 `default_selected`，不误用 `excluded`。
- exporter 不修改源素材，不重新筛选素材。
- installer 写入的剪映关键镜像文件一致。
- 草稿内素材路径全部存在。

人工验收：

- 剪映 10 能看到新草稿。
- 打开草稿不丢素材。
- 时间线顺序与 `rough_cut_plan.json` 一致。
- 视频、图片、BGM 和文本占位可见。
- 保存后再次打开仍可用。
