## 1. 依赖门禁与测试脚手架

- [x] 1.1 确认 R1/R2 前置 API 可导入：`RoughCutPlan`、`read_rough_cut_plan`、`validate_rough_cut_plan`、`Jianying10Installer` 和 installer models。
- [x] 1.2 验证 `pyJianYingDraft` 的 package 名和 import path，并记录需要写入 `pyproject.toml` 的准确依赖字符串。
- [x] 1.3 添加失败版公共 API 测试，覆盖 `JianyingDraftExporter`、`JianyingDraftAdapter`、`AdapterCapabilities`、`DraftExportResult` 和 `DraftExportError`。
- [x] 1.4 添加失败版 exporter dispatch 测试，覆盖默认 `pyjianyingdraft` engine 和未知 engine 的 `DraftExportError`。
- [x] 1.5 添加失败版副作用边界测试，证明 export 只写 `output_dir`、不修改输入 plan、不修改源媒体或 cut index，也不调用 `Jianying10Installer.install`。

## 2. 导出语义测试

- [x] 2.1 添加失败版媒体解析测试，覆盖基于 cut index 的路径解析、回退到 `asset_path`，以及必需媒体不可读时的清晰 `DraftExportError`。
- [x] 2.2 添加失败版 adapter 边界测试，证明 adapter 消费已选 timeline segments，不读取 `cut_index.json` 做过滤、替换或排序。
- [x] 2.3 添加失败版 pyJianYingDraft 依赖测试，确保默认 adapter 依赖缺失时失败而不是 skip。
- [x] 2.4 添加失败版 `pyjianying_work/` 保留测试和 adapter capability warning 测试。
- [x] 2.5 添加剪映 draft content 语义比较 helper：主视频顺序、source timeranges、target timeranges、BGM 时间和音量、图片覆盖时间、文本内容和时间。
- [x] 2.6 添加失败版 fixture 回归测试，比较 `minimal_rough_cut_plan.json` 导出结果与 `realistic_draft_content.json` 的语义。
- [x] 2.7 添加失败版集成风格测试：导出 fixture plan，并把生成的 `draft_content.json` 交给 `Jianying10Installer` 和 fixture 或 bundled template 输入。

## 3. Exporter 模型与公共 API

- [x] 3.1 在 `src/tripclipper/jianying/models.py` 添加 `DraftExportResult`、`DraftExportError` 和 `AdapterCapabilities`。
- [x] 3.2 创建 `src/tripclipper/jianying/adapters/base.py`，定义 `JianyingDraftAdapter` interface。
- [x] 3.3 创建 `src/tripclipper/jianying/draft_exporter.py`，实现薄 engine dispatch 和输出边界检查。
- [x] 3.4 在 exporter 中实现媒体路径解析：`plan.project.cut_index_path` 只用于身份和路径校验，并保持 plan 中的 timeline 顺序。
- [x] 3.5 更新 `src/tripclipper/jianying/__init__.py` 和 adapter package exports，暴露新的公共 API。

## 4. PyJianYingDraft Adapter

- [x] 4.1 在确认准确 package 名后，将 `pyJianYingDraft` 加入核心项目依赖。
- [x] 4.2 创建 `src/tripclipper/jianying/adapters/pyjianyingdraft.py`，实现必需 import path，不使用 optional lazy-skip。
- [x] 4.3 将 `RoughCutPlan` video segments 映射到剪映主视频 materials/tracks，并保留 source 和 target timeranges。
- [x] 4.4 将 audio/BGM segments、image overlay segments 和 text overlay segments 映射进生成 draft，并保留时间、音量和文本语义。
- [x] 4.5 对安全的不支持能力输出 result warnings，例如 transition 或 style 降级。
- [x] 4.6 在 `output_dir` 下写入 `draft_content.json`、可选 `draft_meta_info.json`，并保留 `pyjianying_work/` 产物。

## 5. 验证

- [x] 5.1 运行 `pytest tests/test_jianying_exporter.py tests/test_jianying_pyjianyingdraft_adapter.py -v`。
- [x] 5.2 运行 `pytest tests/test_jianying_installer.py -v`，确认 installer 兼容性未回归。
- [x] 5.3 运行相邻 rough-cut contract 回归：`pytest tests/test_roughcut_fixture_contract.py tests/test_roughcut_models.py tests/test_roughcut_validator.py -v`。
- [x] 5.4 手动或通过集成测试验证 fixture 链路：`minimal_rough_cut_plan.json -> JianyingDraftExporter -> semantic comparison -> Jianying10Installer`。
