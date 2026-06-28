# M5-early 验收清单

## 如何手动验证本模块

> M5-early 是早期裁剪版的 HTML 验证报告，验收靠：CLI `export` + 浏览器打开 review.html + 肉眼检查缩略图与字段对应关系。前置需 M3 已跑过（cut_index 有分析字段）；可用 demo-scan 项目或临时构造的 cut_index。

```bash
# 0) 前置：跑过 M3 的 sample 或 full
tripclipper init --config ./project.yaml
tripclipper analyze --stage scan --config ./project.yaml
tripclipper analyze <slug> --stage sample --concurrency 5

# 1) 生成 review.html
tripclipper export <slug> --html
# 打印：「已生成 review.html: <绝对路径>」，退出码 0

# 2) 用浏览器打开（或 --open 自动打开）
tripclipper export <slug> --html --open

# 3) 肉眼验收（这是本模块的核心验收）
# 在浏览器中确认：
#   - 缩略图正常显示（每行一张 80px 高的 jpg）
#   - 每行 summary 与缩略图画面一致 ← M3 模型质量的视觉验证
#   - 星级、subject_type、shot_scale、shot_function 与画面主观判断匹配
#   - 表头点击能升降排序、三个 <select> 能筛选、搜索框能搜出含关键词的行
#   - 点击任一行能展开抽屉看到完整 metadata、segments、frame_paths 全图
#   - similar_group / edit_candidate_status 两列固定显示「（待 M4）」
#   - 失败素材行红色高亮（row-failed），summary 列显示失败原因（截 80 字符）
#   - 头部信息块展示项目名、source_folder、provider、vision_model、api_key_env（不含密钥值）
#   - 头部 analysis 状态摘要（stage / status / started_at / finished_at / error_summary）

# 4) 安全验收：密钥脱敏
grep -F "$TRIPCLIPPER_MODEL_API_KEY" projects/<slug>/exports/review.html
# → 应返回空（密钥不出现在 HTML 中）
grep -F "Authorization" projects/<slug>/exports/review.html
# → 应返回空
grep -F "model_config" projects/<slug>/exports/review.html
# → 应返回空（__JSON_DATA__ 已删除 model_config 字段）

# 5) 失败路径：未初始化
tripclipper export not-exist-slug --html
# → 退出码非 0，stderr 含「尚未初始化」，不抛裸堆栈

# 6) 失败路径：--no-html
tripclipper export <slug> --no-html
# → 退出码 2，stderr 含「M5-early 当前只支持 HTML 导出」

# 7) 测试全绿
pytest -q tests/test_exporter.py tests/test_cli_export.py
pytest -q tests/test_integration_m3.py    # 末尾追加部分应通过
```

**重点核对**：缩略图 file URI 路径正确指向 `projects/<slug>/cache/thumbnails/`；每个 `<tr>` 的 `data-asset-id`/`data-subject-type`/`data-shot-scale`/`data-status` 属性齐全（供 JS 筛选使用）；M4 字段的占位文本在 M4 完成后才能替换为真实数据，本模块不考虑；HTML 严格只读（无 `<form>`、无 `fetch`/`XHR`），所有交互在 DOM 内完成；密钥/Authorization/model_config 均不出现在 HTML 中。

## CLI 命令形态
- [ ] `tripclipper export <slug> --html` 工作（默认就是 `--html`）
- [ ] `tripclipper export <slug> --html --open` 工作（成功后调 `webbrowser.open`）
- [ ] `tripclipper export <slug> --no-html` 退出码 2，stderr 含「M5-early 当前只支持 HTML 导出」
- [ ] 未初始化项目执行 `export` → 退出码非 0、stderr 含「尚未初始化」、不抛裸堆栈
- [ ] CLI 错误兜底：`ExportError` 一律 `click.echo(..., err=True)` + `sys.exit(1)`，不抛裸堆栈

## 文件路径与忽略项
- [ ] `paths.exports_dir(slug, base_dir)` 返回 `<base_dir>/projects/<slug>/exports/`
- [ ] `paths.review_html_path(slug, base_dir)` 返回 `<base_dir>/projects/<slug>/exports/review.html`
- [ ] `render_review_html` 调用时自动 `mkdir(parents=True, exist_ok=True)` 创建 exports 目录
- [ ] `.gitignore` 含 `projects/*/exports/`

## HTML 视图：项目头部信息块
- [ ] 展示项目名、slug、source_folder（HTML 转义生效）
- [ ] 展示模型配置摘要：provider / vision_model / api_key_env（**不**展示密钥值）
- [ ] 展示 analysis 状态：stage / status / started_at / finished_at / error_summary
- [ ] 展示素材计数：总数 / video / image / audio / analyzed / scanned / analysis_failed
- [ ] 展示项目级 failures 列表，每条一行 `[stage] target: reason`
- [ ] `cut_index.analysis is None` 或 `analysis.status != "completed"` 时显示「尚未运行 sample/full 分析」提示

## HTML 视图：素材表格 15 列
- [ ] 列序：缩略图 / 文件名 / 类型+时长 / 星级 / subject_type / people_presence / shot_scale / shot_function / tags / summary / segments / audio_strategy / similar_group / edit_candidate_status / analysis_status
- [ ] 缩略图：`<img src="file:///abs/path/to/thumb.jpg">` 80px 高
- [ ] 缩略图缺失时显示 `[无缩略图]` 灰色占位
- [ ] 时长格式：mm:ss（`metadata.duration_seconds` 取整）；缺失时显示 ""
- [ ] 星级：`★★★☆☆` 字符渲染（rating=3 时 3 实心 + 2 空心）；rating=None 时显示 ""
- [ ] tags 截断到 5 个，`tag1, tag2, ... (+3)` 提示总数
- [ ] summary 截断到 80 字符
- [ ] segments 多段以 `<div class="segment">` 分隔；空时显示「（无）」
- [ ] similar_group / edit_candidate_status 两列固定显示「（待 M4）」（M4 完成后切换为真实数据渲染）
- [ ] analysis_status 彩标：analyzed=绿、scanned=黄、analysis_failed=红、其他=灰

## HTML 视图：行高亮与降级
- [ ] `analysis_status="analyzed"` 行无特殊高亮
- [ ] `analysis_status="scanned"` 行 CSS class 含 `row-pending`（淡黄背景）
- [ ] `analysis_status="analysis_failed"` 行 CSS class 含 `row-failed`（淡红背景）
- [ ] `analysis_failed` 素材的 summary 列显示 `failures[-1].reason` 截断 80 字符
- [ ] `analyzed` 素材且 `summary` 为空时显示「（模型未生成 summary）」
- [ ] `scanned` 素材的 summary 列显示「（待分析）」

## HTML 视图：交互能力
- [ ] 表头每列点击可排序（首次升序、再次降序、第三次恢复原始顺序）
- [ ] subject_type 筛选 `<select>`：列出所有出现过的值 + "全部"
- [ ] shot_scale 筛选 `<select>`：列出所有出现过的值 + "全部"
- [ ] analysis_status 筛选 `<select>`：列出 analyzed/scanned/analysis_failed/全部
- [ ] 顶部搜索框：模糊匹配 filename / summary / tags（任一字段命中即显示）
- [ ] 多筛选条件 AND 组合（select 与 select、select 与搜索框）
- [ ] 行点击展开抽屉，显示完整 metadata、segments、frame_paths（含全图）
- [ ] 抽屉内 frame_paths 用 `<img src="file:///...">` 渲染
- [ ] JS 严格只读：无 `fetch` / `XMLHttpRequest` / `<form action>`、无 DOM 修改 cut_index 的能力

## 安全：密钥与敏感配置脱敏
- [ ] `__JSON_DATA__` 序列化前删除 `cut_index.project.model_config` 整段（用 `model_copy(deep=True)` 在副本上删，不污染原对象）
- [ ] HTML 文本（grep `os.environ[api_key_env]` 的值）应返回空
- [ ] HTML 文本（grep "Authorization"）应返回空
- [ ] HTML 文本（grep "model_config"）应返回空
- [ ] 项目头部信息块只展示 `api_key_env`（环境变量名），**不**展示其值
- [ ] `__JSON_DATA__` 嵌入 HTML 时 `</script>` 替换为 `<\/script>`（防脚本注入）

## 严格只读
- [ ] HTML 不含 `<form>` 元素
- [ ] HTML 不含任何 `fetch(...)` / `XMLHttpRequest` 调用
- [ ] HTML 不含任何修改本地文件的能力（按设计就不可能，但需自查模板）
- [ ] 所有交互（排序/筛选/搜索/抽屉）在 DOM 内完成

## graceful degrade（M4 字段尚未实现）
- [ ] `similar_group_id` 列文本固定显示「（待 M4）」
- [ ] `edit_candidate_status` 列文本固定显示「（待 M4）」
- [ ] M4 完成后只需替换 `_asset_to_row` 中两个分支，不动模板列结构、不动 CSS、不动 JS

## 与 M5 完整版的前向兼容
- [ ] `exporter.render_review_html` 函数签名稳定（M5 完整版不重写）
- [ ] 模板 3 个占位符 (`__PROJECT_HEADER_HTML__` / `__TABLE_ROWS_HTML__` / `__JSON_DATA__`) 名称稳定
- [ ] CLI 命令 `tripclipper export <slug> --html` 不变；M5 完整版只新增 flag

## 测试与回写
- [ ] `tests/test_exporter.py` 全部用例通过（12 个 SubTask 6.x 全覆盖）
- [ ] `tests/test_cli_export.py` 全部用例通过
- [ ] `tests/test_integration_m3.py` 末尾追加部分通过（render_review_html 端到端）
- [ ] Unit 测试不调 `Provider.analyze`，不构造伪造分析结果
- [ ] `docs/specs/README.md` 模块索引追加 M5-early 行；状态从"待开始"→"已完成"
- [ ] `docs/specs/README.md` "建议执行顺序"段追加说明
- [ ] `pytest -q` 全绿
