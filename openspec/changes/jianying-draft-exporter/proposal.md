## 为什么

TripClipper 已经有稳定的 `RoughCutPlan` 契约，也有独立的剪映 10 安装路径，但中间还缺少把粗剪计划转换成剪映 `draft_content.json` 的桥接层。本变更补上第一条可用的 plan-to-draft 导出主链路，同时继续保持边界：只有 installer 可以写入剪映草稿库。

## 变更内容

- 新增 `JianyingDraftExporter` API，消费已校验的 `RoughCutPlan`，并把剪映导出产物写入调用方指定的 `output_dir`。
- 新增 `JianyingDraftAdapter` 抽象，第一版必须提供基于 `pyJianYingDraft` 的实现。
- 新增导出结果和错误模型，包括 `engine`、`draft_content_path`、可选 `draft_meta_info_path`、已解析媒体路径和能力降级 warning。
- 将 `pyJianYingDraft` 作为第一版默认导出路径的核心依赖，而不是 optional 或 best-effort 集成。
- 当 adapter 需要 pyJianYingDraft 中间工作区时，默认保留 `output_dir/pyjianying_work/` 便于调试。
- 新增语义回归测试，将 fixture plan 生成的 draft 与 `tests/fixtures/jianying/realistic_draft_content.json` 做语义比较。
- 新增集成风格测试，证明导出的 `draft_content.json` 可以被 `Jianying10Installer` 消费。
- 不实现启发式 planner、LLM planner、`VectCutAPI` 导出、CLI 编排，也不把导出产物安装进真实剪映草稿库。

## 能力

### 新增能力

- `jianying-draft-export`：通过默认 `pyjianyingdraft` engine，把 `RoughCutPlan` 导出为剪映 draft content。

### 修改能力

- 无。

## 影响范围

- 新增 `src/tripclipper/jianying/` 下的 exporter 和 adapter 模块。
- 修改 `src/tripclipper/jianying/models.py` 和 package exports，暴露 draft export 结果与错误模型。
- 将 `pyJianYingDraft` 加入核心项目依赖。
- 新增 `tests/test_jianying_exporter.py` 和 `tests/test_jianying_pyjianyingdraft_adapter.py`。
- 依赖 R1 rough-cut plan contract 和 R2 Jianying installer API。
