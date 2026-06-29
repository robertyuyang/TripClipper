# Trustworthy Clip Timecodes Tasks

> 阶段：**已完成**。本 change 已落实 [trustworthy-clip-timecodes/spec.md](./spec.md) 的实施。
> 依赖前置：M0 / M2 / M3 / M4 / M5-early 已完成。
> 拍板决策：[ADR-003](../../adr/ADR-003-frame-timestamp-annotation.md)。

## 任务清单

- [x] **Task 1**：M0 数据契约升版（[src/tripclipper/models.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/models.py)）
  - [x] SubTask 1.1：把 `Segment` 类名改为 `ClipSuggestion`；保持 9 个字段（`in_` / `out` / `role` / `reason` / `audio_strategy` / `subject_type` / `shot_scale` / `rating` / `tags`），保留 `alias="in"` for `in_`
  - [x] SubTask 1.2：把 `Asset.segments` 字段名改为 `Asset.clip_suggestions`（仍 `default_factory=list`）
  - [x] SubTask 1.3：在 `Asset.frame_paths` 旁并列新增 `frame_timestamps: list[float] = Field(default_factory=list)`，docstring 说明索引与 `frame_paths` 一一对应
  - [x] SubTask 1.4：`SCHEMA_VERSION` 常量值由 `"0.2"` 改为 `"0.3"`
  - [x] SubTask 1.5：检查 `src/tripclipper/cut_index.py` 的 schema 校验：版本不匹配时报错信息加一句「建议执行 `tripclipper analyze <slug> --stage full --force` 重新分析」
  - [x] SubTask 1.6：更新 [tests/test_models.py](file:///Users/bytedance/Documents/TripClipper_Trae/tests/test_models.py)：`Segment` 引用全部改 `ClipSuggestion`、`asset.segments` 改 `asset.clip_suggestions`、`SCHEMA_VERSION` 断言改 `"0.3"`、新增 `frame_timestamps` 默认值与并列写入断言

- [x] **Task 2**：M2 抽帧自适应化 + 时间戳写入（[src/tripclipper/scan.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/scan.py)）
  - [x] SubTask 2.1：新增纯函数 `_compute_frame_count(duration: float | None) -> int`：`duration is None` 时返回 3；否则 `max(3, min(12, round(duration / 5)))`
  - [x] SubTask 2.2：删除 `_MAX_FRAMES = 3` 常量
  - [x] SubTask 2.3：改造 `_run_ffmpeg_frames()` 返回类型从 `list[Path]` 改为 `list[tuple[Path, float]]`（路径 + 时间戳并列）
  - [x] SubTask 2.4：`scan_project` 主逻辑：抽帧后把 `frames` 解构为 `frame_paths` 与 `frame_timestamps` 两个列表，分别写入 `asset.frame_paths` 与 `asset.frame_timestamps`
  - [x] SubTask 2.5：处理 duration 不可用分支：`asset.metadata.duration is None` 时 `_compute_frame_count(None) → 3`，且时间戳列表仍按均匀切分给值（非 None）；ffprobe 完全失败导致 metadata 为空时，跳过抽帧 + `frame_timestamps = []`
  - [x] SubTask 2.6：更新 [tests/test_scan.py](file:///Users/bytedance/Documents/TripClipper_Trae/tests/test_scan.py)

- [x] **Task 3**：M3 prompt 时间标注 + 字段重命名 + 4 段级字段（[src/tripclipper/provider.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/provider.py)）
  - [x] SubTask 3.1：删除 `_MAX_FRAMES_FOR_PROMPT = 3`；`_build_user_content` 改为消费 `len(asset.frame_paths)`
  - [x] SubTask 3.2：在 `_build_user_content` 中：缩略图前插 `text("缩略图：素材封面")`；每张 frame 前按索引插 `text(f"第 {i+1} 张关键帧 @ {_format_frame_timestamp(asset.frame_timestamps[i])}")`
  - [x] SubTask 3.3：新增纯函数 `_format_frame_timestamp(seconds: float) -> str`
  - [x] SubTask 3.4：更新 `_SYSTEM_PROMPT` 常量（字段名 / 4 段级字段 / 时间码约束段）
  - [x] SubTask 3.5：`_coerce_segments` 改名 `_coerce_clip_suggestions`，实现三条校验（格式 / 顺序 / 边界）+ 收集 dropped
  - [x] SubTask 3.6：`apply_analysis` 把被丢弃的段写入 `asset.warnings`，`stage="analyze"`, `blocking=False`
  - [x] SubTask 3.7：调用方处理：`asset.clip_suggestions = ` 校验通过的段；即使全部丢弃，`asset.analysis_status` 仍转 `analyzed`
  - [x] SubTask 3.8：更新 [tests/test_provider.py](file:///Users/bytedance/Documents/TripClipper_Trae/tests/test_provider.py) 单元测试
  - [x] SubTask 3.9：更新 [tests/test_integration_m3.py](file:///Users/bytedance/Documents/TripClipper_Trae/tests/test_integration_m3.py)

- [x] **Task 4**：下游模块字段重命名（语义不变）
  - [x] SubTask 4.1：[src/tripclipper/exporter.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/exporter.py)：HTML 渲染中 `asset.segments` 引用改 `asset.clip_suggestions`
  - [x] SubTask 4.2：[src/tripclipper/clusterer.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/clusterer.py) / [arbiter.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/arbiter.py) / [cluster_runner.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/cluster_runner.py)：grep 无 `segments` 残留
  - [x] SubTask 4.3：[src/tripclipper/templates/review.html.tmpl](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/templates/review.html.tmpl)：`th data-key="segments"` 改 `clip_suggestions`、drawer JSON 字段同步
  - [x] SubTask 4.4：[tests/test_exporter.py](file:///Users/bytedance/Documents/TripClipper_Trae/tests/test_exporter.py)、[tests/test_cli_export.py](file:///Users/bytedance/Documents/TripClipper_Trae/tests/test_cli_export.py)、[tests/test_integration_m3.py](file:///Users/bytedance/Documents/TripClipper_Trae/tests/test_integration_m3.py)：现有 `segments` 引用全改 `clip_suggestions`
  - [x] SubTask 4.5：清理 `projects/demo-scan/cut_index.json`，已执行 `tripclipper run demo-scan --concurrency 5` 重跑

- [x] **Task 5**：端到端验证 + 回写
  - [x] SubTask 5.1：跑 `pytest -q`，全绿（288 passed，含 integration_m3/m4 真打）
  - [x] SubTask 5.2：跑 demo 项目：`tripclipper run demo-scan --concurrency 5`，检查 `cut_index.json`：
    - `schema_version = "0.3"` ✓
    - 所有 video asset 的 `frame_timestamps` 非空、长度匹配 `frame_paths`、单调递增 ✓
    - 所有 `clip_suggestions[*].in` / `out` 落在 `[0, asset.metadata.duration]` 内、`out > in` ✓
  - [x] SubTask 5.3：浏览器打开 `projects/demo-scan/review.html`（cut_index drawer 中含 `clip_suggestions` / `frame_timestamps` 字段渲染）
  - [x] SubTask 5.4：[docs/specs/README.md](file:///Users/bytedance/Documents/TripClipper_Trae/docs/specs/README.md) 模块索引：`trustworthy-clip-timecodes` 状态改为「已完成」
  - [x] SubTask 5.5：实现与 spec 一致，无需回写偏差

## 任务依赖

- Task 2 / Task 3 都依赖 Task 1（模型类型 + SCHEMA_VERSION 落地）
- Task 3 依赖 Task 2（M3 prompt 消费 `frame_timestamps`，M2 必须先写入）
- Task 4 依赖 Task 1（字段名重命名后下游引用才能编译过）
- Task 5 依赖 Task 1~4

## 关键实现注意

- **Pydantic 字段重命名**：`Asset.segments` → `Asset.clip_suggestions` 是 BREAKING；不需要 alias 兼容旧字段（SCHEMA_VERSION 升版已经表达不向下兼容）。
- **`_parse_timecode` 容错**：模型可能返回 `"30"` / `"30.5"` / `"00:30"` / `"00:00:30.5"` 等多种格式，统一解析为非负秒数浮点；解析失败返回 `None` 由调用方丢弃该段。
- **N 帧上限 12 注意 base64 体积**：若实际跑下来某些素材 prompt 超长导致 API 报错，作为 ADR-003 §退出条件第 1 条评估触发点。
- **零 mock 纪律**：测试新增的所有 `_parse_timecode` / `_coerce_clip_suggestions` 都是纯函数单测，喂手工字符串测纯解析，**不**算 mock 模型（与 M3 spec §Q17 解释一致）。
