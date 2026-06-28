# TripClipper Spec 工作区

本目录是 TripClipper MVP 规范驱动开发的**事实源**，用于跨会话协作。

## 背景

TripClipper MVP（见 [产品需求](../mvp-product-requirements.md) 与 [技术设计](../mvp-technical-design.md)）是一个从 0 到 1 的产品。整份 PRD 按依赖关系拆成 9 个需求模块（M0~M8），每个模块独立走一轮 Spec 流程（≈ 一个 OpenSpec change），并建议**一个模块一个会话**执行，避免上下文污染。

## 目录约定

每个模块一个目录，固定包含三件套：

```
docs/specs/
  README.md              # 本文件：模块索引与约定
  M0-data-contract/
    spec.md              # 需求规格：要做什么、字段口径、约束、验收口径
    check_list.md        # 验收清单：可逐项勾选的验收条件
    task_list.md         # 任务拆解：可执行的实现步骤
  M1-project-config/
  ...
```

## 跨会话使用规则

1. **新开会话做某模块时，先读本 README + 该模块 spec + 所有依赖模块的 spec**（尤其 M0 数据契约，所有模块都依赖它）。
2. 模块完成后，在下表更新状态，必要时回写 spec 反映实际实现（保持 spec 为事实源）。
3. 字段口径以 M0 `spec.md` 为唯一标准，其他模块不得各自重新定义。

## 模块索引

| 模块 | 名称 | 覆盖 FR / 章节 | 依赖 | 状态 |
| --- | --- | --- | --- | --- |
| M0 | 项目骨架与数据契约 | PRD 6.1/6.2/6.3、4.4；TD 4/7/12 | - | 已完成 |
| M1 | 项目创建与配置 | FR-1；TD 4 | M0 | 已完成 |
| M2 | 本地素材扫描（Stage 1） | FR-2；TD 5 | M0、M1 | 已完成 |
| M3 | 真实大模型分析引擎 | FR-3/FR-4/FR-5；TD 6/8 | M0、M2 | 已完成 |
| M4 | 雷同素材识别与候选池 | FR-6；TD 8 | M3 | 待开始 |
| M5 | 数据包导出与只读报告 | FR-7/FR-8；TD 9 | M3、M4 | 待开始 |
| M6 | Eagle 同步（预览+正式） | FR-9/FR-10；TD 10 | M5 | 待开始 |
| M7 | 本地启动页与状态面板 | PRD 5.2；TD 11 | M1~M6 | 待开始 |
| M8 | 错误记录与可观测性（横切） | FR-11；PRD 8 | 横切 | 待开始 |

## 建议执行顺序

主流程优先打通：**M0 → M1 → M2 → M3 → M4 → M5 → M6**，再用 M7 收口入口，M8 补横切的错误与可观测能力。

> 实际执行顺序追加 M5-early：**M3 → M5-early（HTML 验证）→ M4 → M5 完整版（CSV/MD）→ M6 → M7**。提前做 M5-early 是为了让后续模块完成后有低成本的视觉验证视图（详见 [`M5-early-html-report/spec.md`](./M5-early-html-report/spec.md)）。
