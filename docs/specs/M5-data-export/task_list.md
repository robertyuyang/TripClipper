# Tasks — M5 数据包导出与报告补全

> 阶段：实施前的有序工作清单。每项任务对应 [spec.md](spec.md) 中的一个或一组 Requirement。
> 实施纪律：与 M3/M4/M5-early 一致——纯函数单测 + demo-scan 端到端用真 cut_index.json 断言；CLI stdout 用 `CliRunner` 捕获断言；视觉部分由用户亲自 `open` 确认。

## Task 列表

- [x] Task 1：纯函数 `_compute_overview_counts(cut_index)` 提取聚合数据（spec ADDED §「review.html 头部 SHALL 渲染项目级总览条」共享逻辑）
  - [x] SubTask 1.1：在 [exporter.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/exporter.py) 顶部新增 `@dataclass(frozen=True) class OverviewCounts`，字段：
        `rating_distribution: dict[int | None, int]`（key 为 1~5 或 None；保证 6 个 key 全在，缺者补 0）、
        `similar_group_count: int`、`similar_member_count: int`、`similar_needs_review_count: int`、
        `candidate_counts: dict[str, int]`（key 为 `default_selected` / `alternate` / `excluded` / `needs_review`；保证 4 个 key 全在）、
        `total_assets: int`、`counts_by_type: dict[str, int]`、`counts_by_status: dict[str, int]`。
  - [x] SubTask 1.2：新增 `_compute_overview_counts(cut_index: CutIndex) -> OverviewCounts` 纯函数。
        遍历 `cut_index.assets` 累计：rating 分布（按 `asset.rating`，None 归 None 桶）、按 `asset.type` 计数、按 `asset.analysis_status` 计数、按 `asset.edit_candidate_status` 计数（None 不计入）。
        遍历 `cut_index.similar_groups` 累计：组数、成员总数（`len(group.asset_ids)`）、待人工确认组数（`group.needs_review == True`）。
  - [x] SubTask 1.3：单测 `test_compute_overview_counts_*`（4 用例）：
        - 完整数据（spec ADDED §「完整数据」场景）：rating=[5,5,4,4,4,3,2,None,None,None]、1 组 3 成员 0 待确认、候选池 default×6/alternate×3/excluded×0/needs_review×1 → 断言每个字段精确值
        - 空 similar_groups → `similar_group_count=0`，rating 分布不变
        - 所有 `edit_candidate_status=None` → `candidate_counts` 四个 key 全为 0
        - 空 assets 列表 → 所有计数为 0、rating 分布 6 个 key 全为 0

- [x] Task 2：纯函数 `_render_overview_section(counts: OverviewCounts) -> str`（spec ADDED §「review.html 头部 SHALL 渲染项目级总览条」）
  - [x] SubTask 2.1：新增函数，返回 `<div class="overview">...</div>` HTML 字符串。
        包含三个 `<div class="overview-row">`：
        - rating 分布行：始终渲染，文本 `★5 ×N · ★4 ×N · ★3 ×N · ★2 ×N · ★1 ×N · 未评级 ×N`
        - 相似组聚合行：仅 `similar_group_count > 0` 时渲染，文本 `相似组 N 个（共 M 条；K 条待人工确认）`
        - 候选池聚合行：仅四个 candidate count 之和 > 0 时渲染，文本 `候选池：default_selected ×N · alternate ×N · excluded ×N · needs_review ×N`
  - [x] SubTask 2.2：单测 `test_render_overview_section_*`（4 用例）：
        - 完整数据 → HTML 含三行三组期望文本（与 spec §「完整数据」场景断言字面一致）
        - 无相似组 → 输出不含 `相似组` 字面
        - 无候选池（candidate 全 None）→ 输出不含 `候选池：` 字面
        - 全空（0 素材）→ 仅 rating 分布行存在且每项均 `×0`

- [x] Task 3：把总览条拼入 `_render_project_header`（spec ADDED §「review.html 头部 SHALL 渲染项目级总览条」）
  - [x] SubTask 3.1：修改 [_render_project_header](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/exporter.py#L578-L652)：在现有 `<dl>` 与 `notice_html` 之间插入 `_render_overview_section(_compute_overview_counts(cut_index))` 的输出。
  - [x] SubTask 3.2：既有 `test_render_project_header_*` 单测在断言原 `<dl>` 内容不变的基础上，新增「输出含 `.overview` class」断言。

- [x] Task 4：纯函数 `copy_cut_index(slug, *, base_dir=None) -> Path`（spec ADDED §「cut_index 副本 SHALL 与活动文件解耦且脱敏」）
  - [x] SubTask 4.1：新增 [paths.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/paths.py) 中 `exported_cut_index_path(slug, base_dir) -> Path`，返回 `exports_dir(slug, base_dir) / "cut_index.json"`；加入 `__all__`；docstring 顶部布局图同步追加这一行（与 `review.html` 同级在 `exports/` 下）。
  - [x] SubTask 4.2：新增 [exporter.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/exporter.py) 中 `copy_cut_index(slug, *, base_dir=None) -> Path`。
        实现：调 `read_cut_index(slug, base_dir)` 拿 `CutIndex` → 调既有 [`_dump_cut_index_json`](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/exporter.py#L655-L665) 拿 JSON 文本（沿用同一脱敏边界）→ `exports_dir(slug, base_dir).mkdir(parents=True, exist_ok=True)` → 写入 `exported_cut_index_path(slug, base_dir)` → 返回 Path。
        错误：项目不存在 → 抛 `ExportError`；IO 失败 → 抛 `ExportError`。
  - [x] SubTask 4.3：单测 `test_copy_cut_index_*`（4 用例）：
        - 正常路径：写入文件存在、内容 valid JSON、`json.loads(...)["project"]["model_config_summary"] == {}`
        - 副本独立：先调 `copy_cut_index`，再用 `write_cut_index` 修改活动 cut_index（如增删一条 asset），断言副本 mtime/SHA 不变
        - 不存在 slug → 抛 `ExportError`
        - 脱敏：构造 `model_config_summary={"provider": "openrouter", "secret": "DUMMY"}` → 副本 JSON 中该字典为 `{}`

- [x] Task 5：纯函数 `_summarise_for_stdout(cut_index: CutIndex) -> str`（spec ADDED §「`tripclipper export` SHALL 在 stdout 打印项目级聚合摘要」）
  - [x] SubTask 5.1：新增函数，消费 `_compute_overview_counts` 的输出（**与 review.html 总览条共用**，保证 spec §「摘要数据与 review.html 总览条一致」场景）。
        返回 multi-line 字符串：
        ```
        📊 项目「{project_name}」总览
          素材总数：N（video=N, image=N）
          分析状态：analyzed=N, scanned=N, analysis_failed=N
          rating 分布：★5 ×N · ★4 ×N · ★3 ×N · ★2 ×N · ★1 ×N · 未评级 ×N
          相似组：N 个（共 M 条；K 条待人工确认）  ← 仅有组时
          候选池：default_selected ×N · alternate ×N · excluded ×N · needs_review ×N  ← 仅有候选池时
        ```
        `project_name` 取 `cut_index.project.project_name`，缺则用 `cut_index.project.project_slug`。
  - [x] SubTask 5.2：单测 `test_summarise_for_stdout_*`（3 用例）：
        - 完整数据 → 6 行（标题 + 5 明细），相似组与候选池行均出现，数字与 spec §「完整数据」场景一致
        - 无相似组 → 5 行（少了相似组行），其他不变
        - 全 None 候选池 + 无相似组 → 4 行（仅标题 + 总数 + 分析状态 + rating）

- [x] Task 6：修改 CLI [export 命令](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/cli.py#L470-L504)（spec MODIFIED §「`tripclipper export <slug>` 命令面板」）
  - [x] SubTask 6.1：删除 `@click.option("--html/--no-html", ...)`；删除函数内 `if not html_flag: ... sys.exit(2)` 块。
  - [x] SubTask 6.2：新增 `@click.option("--cut-index-only/--no-cut-index-only", "cut_index_only", default=False, show_default=True, help="仅生成 cut_index 副本，跳过 review.html。")`。
  - [x] SubTask 6.3：函数体重构为：
        ```python
        try:
            cut_index_copy_path = copy_cut_index(slug, base_dir=base_dir)
            click.echo(f"已生成 cut_index 副本: {cut_index_copy_path}")
            if not cut_index_only:
                html_path = render_review_html(slug, base_dir=base_dir)
                click.echo(f"已生成 review.html: {html_path}")
            cut_index = read_cut_index(slug, base_dir)
            click.echo("")
            click.echo(_summarise_for_stdout(cut_index))
            if open_flag and not cut_index_only:
                webbrowser.open(f"file://{html_path}")
            elif open_flag and cut_index_only:
                click.echo("--open 与 --cut-index-only 冲突，跳过打开。", err=True)
        except ExportError as exc:
            click.echo(f"导出失败：{exc}", err=True)
            sys.exit(1)
        ```
  - [x] SubTask 6.4：在 [cli.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/cli.py) 顶部 import 补 `copy_cut_index, _summarise_for_stdout` 与 `read_cut_index`（若未 import）。

- [x] Task 7：CSS 新增 `.overview` / `.overview-row`（spec §What Changes 第 2 条）
  - [x] SubTask 7.1：在 [review.html.tmpl](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/templates/review.html.tmpl) `</style>` 之前追加：
        ```css
        .overview { margin: 6px 0 10px; padding: 8px 12px; background: #f5f9ff; border-left: 3px solid #2a5db0; border-radius: 3px; }
        .overview-row { font-size: 13px; line-height: 1.7; color: #2b3340; }
        .overview-row + .overview-row { margin-top: 2px; }
        ```
  - [x] SubTask 7.2：模板**无**新增占位符（总览条由 `_render_project_header` 拼入 `__PROJECT_HEADER_HTML__`）。

- [x] Task 8：删除 paths.py 死代码（spec ADDED §「paths.py SHALL 移除未使用的 CSV/MD 路径辅助」）
  - [x] SubTask 8.1：删除 [paths.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/paths.py) 中 `assets_csv_path` / `segments_csv_path` / `summary_md_path` 三个函数定义。
  - [x] SubTask 8.2：删除三者在 `__all__` 中的条目。
  - [x] SubTask 8.3：删除 docstring 顶部布局示意里的 `assets.csv` / `segments.csv` / `summary.md` 三行。
  - [x] SubTask 8.4：grep `assets_csv_path|segments_csv_path|summary_md_path` 在 `src/` 与 `tests/` 必须无匹配；若有则修。
  - [x] SubTask 8.5：单测 `test_paths_csv_md_helpers_removed`：`with pytest.raises(ImportError): from tripclipper.paths import assets_csv_path`。

- [x] Task 9：端到端 demo-scan 渲染断言（[test_exporter.py](file:///Users/bytedance/Documents/TripClipper_Trae/tests/test_exporter.py)）
  - [x] SubTask 9.1：新增 `test_render_demo_scan_includes_overview_section`：用 `Path("projects/demo-scan/cut_index.json")` 真数据渲染，断言：
        - HTML 含 `class="overview"` 至少 1 处
        - HTML 含 `★5 ×` 字面（rating 分布行始终在）
        - 由于 demo-scan 有 group_1 → 含 `相似组 1 个` 字面
        - 由于 demo-scan 有候选池数据 → 含 `候选池：default_selected ×` 字面
  - [x] SubTask 9.2：新增 `test_render_no_groups_omits_overview_similar_row`：手工构造 `CutIndex(similar_groups=[], ...)`，渲染输出含 `.overview`，但**不含** `相似组` 字面。
  - [x] SubTask 9.3：新增 `test_copy_cut_index_demo_scan_end_to_end`：用 demo-scan 真项目（tmp_path 拷一份），调 `copy_cut_index` → 读副本 → `json.loads()["project"]["model_config_summary"]` 为 `{}`、`len(...["assets"])` 与原值一致。

- [x] Task 10：CLI 端到端（[test_cli_export.py](file:///Users/bytedance/Documents/TripClipper_Trae/tests/test_cli_export.py)）
  - [x] SubTask 10.1：移除既有 `test_export_no_html_*` 类用例（或断言 `--no-html` 不再是合法 flag，触发 click usage error）。
  - [x] SubTask 10.2：新增 `test_export_writes_both_files_and_prints_summary`：跑 `runner.invoke(main, ["export", slug])`，断言：
        - exit_code == 0
        - `exports/review.html` 与 `exports/cut_index.json` 都存在
        - stdout 含 `已生成 cut_index 副本:` 与 `已生成 review.html:` 两行
        - stdout 含 `📊 项目「...」总览` 字面
        - stdout 含 `rating 分布：★5 ×` 字面
  - [x] SubTask 10.3：新增 `test_export_cut_index_only`：跑 `runner.invoke(main, ["export", slug, "--cut-index-only"])`：
        - exit_code == 0
        - `exports/cut_index.json` 存在
        - `exports/review.html` **不存在**（或 mtime 早于本次调用，若是先前测试残留）
        - stdout 不含 `已生成 review.html:` 行
        - stdout 仍含 `📊 项目「...」总览` 字面
  - [x] SubTask 10.4：新增 `test_export_open_with_cut_index_only_warns`：跑 `runner.invoke(main, ["export", slug, "--cut-index-only", "--open"])`：
        - exit_code == 0
        - stderr 含 `--open 与 --cut-index-only 冲突` 字面（webbrowser.open 不被调用——可用 monkeypatch 断言未调用）

- [x] Task 11：文档更新
  - [x] SubTask 11.1：[docs/specs/README.md](file:///Users/bytedance/Documents/TripClipper_Trae/docs/specs/README.md) 模块索引中 M5 行状态由「待开始」改为「定稿（待用户审）」；spec 完成审阅、check_list 全部勾选后再改为「已完成」。
  - [x] SubTask 11.2：本 spec 目录沿用三件套 spec.md / task_list.md / check_list.md，无需额外 README。
  - [x] SubTask 11.3：更新 [exporter.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/exporter.py) 文件头 module docstring：把第 1-2 行的「M5-early」字样升级为「M5」；新增一段说明 `copy_cut_index` 与 `_summarise_for_stdout` 的职能。

- [ ] Task 12：人工视觉验收
  - [ ] SubTask 12.1：跑 `.venv/bin/tripclipper export demo-scan --open`，肉眼核对：
        - 浏览器打开 review.html，原有 `<dl>` 之后出现一块浅蓝底总览条
        - 总览条三行：rating 分布、相似组（demo-scan 1 组 3 成员）、候选池（default + alternate 计数）
        - 终端打印 `📊 项目「demo-scan」总览` 标题与至少 5 行明细
  - [ ] SubTask 12.2：跑 `.venv/bin/tripclipper export demo-scan --cut-index-only`：
        - 终端只打印 `已生成 cut_index 副本: ...` + 摘要，没有 review.html 行
        - `ls projects/demo-scan/exports/` 含 `cut_index.json`
  - [ ] SubTask 12.3：验证副本与活动文件解耦：
        - `.venv/bin/tripclipper export demo-scan`
        - `sha256sum projects/demo-scan/cut_index.json projects/demo-scan/exports/cut_index.json` 记录两个 SHA
        - `.venv/bin/tripclipper analyze --stage sample demo-scan --force`
        - 再 `sha256sum` 比较：第一个变了，第二个保持原值
  - [ ] SubTask 12.4：验证脱敏：`grep -F "$TRIPCLIPPER_MODEL_API_KEY" projects/demo-scan/exports/cut_index.json` 返回空；`jq '.project.model_config_summary' projects/demo-scan/exports/cut_index.json` 输出 `{}`
  - 用户主导，不写自动化。

## Task Dependencies

- Task 2 依赖 Task 1（消费 `OverviewCounts`）。
- Task 3 依赖 Task 2。
- Task 5 依赖 Task 1（共用聚合函数）。
- Task 6 依赖 Task 4 + Task 5（CLI 调两个函数）。
- Task 7 与 Task 1-6 可并行（CSS 与 Python 互不依赖）。
- Task 8 与 Task 1-7 可并行（独立的死代码清理）。
- Task 9 依赖 Task 1-4 + Task 7。
- Task 10 依赖 Task 1-7 全部完成。
- Task 11 可在任何时候做。
- Task 12 依赖 1-11 全部完成。
