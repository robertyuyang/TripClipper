# Trustworthy Clip Timecodes 验收清单

## 如何手动验证本模块

> 本 change 没有独立 CLI 入口；验收靠：**重跑 demo 项目** + **检查 `cut_index.json` 字段** + **HTML 视觉核对** + **测试套件**。

```bash
# 0) 前置：ffmpeg/ffprobe 与 .env（TRIPCLIPPER_MODEL_API_KEY）就绪
export PATH="/opt/homebrew/bin:$PATH"
ffprobe -version && ffmpeg -version
cat .env | grep TRIPCLIPPER_MODEL_API_KEY   # 必须存在

# 1) 重新初始化 demo 项目（清除 0.2 的老 cut_index）
rm -rf projects/demo-scan
tripclipper init --config projects/demo-scan/project.yaml

# 2) 重跑全量分析
tripclipper run demo-scan --concurrency 5
# 期望：打印阶段摘要 + 全部 video asset 抽帧自适应

# 3) 检查 cut_index.json 字段
python -c "
import json
cut = json.load(open('projects/demo-scan/cut_index.json'))
assert cut['schema_version'] == '0.3', cut['schema_version']
for a in cut['assets']:
    if a['type'] != 'video' or a['analysis_status'] != 'analyzed':
        continue
    n_paths = len(a['frame_paths'])
    n_ts = len(a['frame_timestamps'])
    assert n_paths == n_ts, f'{a[\"asset_id\"]}: paths={n_paths} ts={n_ts}'
    duration = a['metadata'].get('duration')
    for cs in a.get('clip_suggestions', []):
        in_s = cs['in']
        out_s = cs['out']
        # 此处仅打印，逐项肉眼核对落 [0, duration] 范围
        print(a['asset_id'], in_s, '→', out_s, '| duration =', duration)
print('schema_version + frame_timestamps + clip_suggestions 校验通过')
"

# 4) 浏览器打开 review.html 核对 ClipSuggestion 渲染
open projects/demo-scan/review.html
# 重点核对：每个 asset 的 clip_suggestion 列时间码不出现 01:30:00（超 4s 视频）等明显错误

# 5) 跑测试全绿
pytest -q
```

**重点核对**：① `schema_version = "0.3"`；② 所有 video asset 的 `frame_timestamps` 长度 == `frame_paths` 长度；③ 每段 `clip_suggestion.in`/`out` 满足 `0 ≤ in < out ≤ duration`；④ `analyze` 日志 `logs/analyze-*.jsonl` 不含 API key 或 prompt 字面值；⑤ 若有段被严格校验丢弃，对应 asset 的 `warnings` 列表含 `stage="analyze"` 的非阻塞 WarningItem。

## M2 抽帧自适应化

- [x] `_compute_frame_count(None)` 返回 3
- [x] `_compute_frame_count(0)` 返回 3
- [x] `_compute_frame_count(4.3)` 返回 3（`round(4.3/5) = 1` → 下限保护到 3）
- [x] `_compute_frame_count(15)` 返回 3（`round(15/5) = 3`）
- [x] `_compute_frame_count(60)` 返回 12（`round(60/5) = 12`）
- [x] `_compute_frame_count(100)` 返回 12（`round(100/5) = 20` → 上限保护到 12）
- [x] `DJI_20260612134026_0001_D.MP4`（≈4.3s）抽 3 帧
- [x] `NO20250612-114146-064576F.mp4`（≈60s）抽 12 帧
- [x] 同一视频两次扫描 `frame_timestamps` 完全一致

## M2 时间戳写入 cut_index

- [x] `asset.frame_timestamps` 是浮点列表，单调递增
- [x] `len(asset.frame_paths) == len(asset.frame_timestamps)`
- [x] ffprobe 失败 / duration 缺失时 `frame_timestamps = []`（不报错）
- [x] M2 不抽帧场景（音频 / 缺 ffmpeg）`frame_timestamps = []`

## M3 prompt 时间标注

- [x] `_format_frame_timestamp(10.5) == "00:10.5"`
- [x] `_format_frame_timestamp(125.0) == "02:05.0"`
- [x] 视频 user content 中每张 image_url 之前有一个对应 text block
- [x] 文本格式严格匹配 `第 {i} 张关键帧 @ {MM:SS.S}`（i 从 1 起）
- [x] 缩略图前有 `"缩略图：素材封面"` text block（无时间标注）
- [x] 图片素材 user content 不含 `MM:SS.S` 标注
- [x] 音频素材 user content 无任何 image_url 与时间标注
- [x] system prompt 含时间码合法性约束段（包含「`0 <= in < out <= duration`」与「素材总时长」字面）

## M3 严格时间码校验

- [x] `_parse_timecode("00:30")` 解析为 30.0
- [x] `_parse_timecode("00:00:30.5")` 解析为 30.5
- [x] `_parse_timecode("30")` 解析为 30.0
- [x] `_parse_timecode("abc")` 返回 None
- [x] `_parse_timecode("-5")` 返回 None（非负约束）
- [x] 格式非法时该段被丢弃（其他段保留）
- [x] `out <= in` 时该段被丢弃
- [x] `in < 0` 或 `out > duration` 时该段被丢弃
- [x] 全部段被丢弃时 `asset.clip_suggestions = []`、`analysis_status = "analyzed"`
- [x] 全部段被丢弃时 `asset.warnings` 含 `stage="analyze"` / `blocking=False` 的 WarningItem
- [x] 主字段 `summary` / `tags` / `rating` 不受时间码校验失败影响

## M0 字段重命名 + SCHEMA 升版

- [x] `models.py` 中类名是 `ClipSuggestion`（不是 `Segment`）
- [x] `Asset.clip_suggestions` 字段存在、默认 `[]`
- [x] `Asset.frame_timestamps` 字段存在、默认 `[]`
- [x] `SCHEMA_VERSION == "0.3"`
- [x] 用 0.3 代码读 0.2 老 cut_index 报清晰错误
- [x] 错误消息含 `--stage full --force` 建议
- [x] 写入再读回 0.3 cut_index 数据无损

## ClipSuggestion 段级 4 字段

- [x] system prompt 含 `subject_type` / `shot_scale` / `rating` / `tags` 段级输出规约
- [x] 模型成功返回时段级 4 字段非空（验收时肉眼核对 demo-scan）
- [x] 段级非法枚举降级到 `None` 或默认值（沿用 M3 现有降级策略）
- [x] 段级降级不丢弃整段（只对应字段置 None）

## 下游字段重命名

- [x] [exporter.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/exporter.py) 中 `asset.segments` 引用全部改 `asset.clip_suggestions`
- [x] [review.html.tmpl](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/templates/review.html.tmpl) 中表头与 data-key 字段名同步
- [x] M4 [clusterer.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/clusterer.py) / [arbiter.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/arbiter.py) / [cluster_runner.py](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/cluster_runner.py) 引用同步
- [x] grep `\.segments\b` 在 `src/` 下零命中（语义已替换）

## 测试与脱敏

- [x] `pytest -q` 全绿（含 M3 真打模型集成测试）
- [x] 新增 6 个 `_compute_frame_count` 边界单测全绿
- [x] 新增 4 个 `_format_frame_timestamp` 单测全绿
- [x] 新增 6 种 `_coerce_clip_suggestions` 校验分支单测全绿
- [x] 新增视频分析"全部段满足校验"集成测试全绿（真打 Gemini）
- [x] `logs/analyze-*.jsonl` 仍不含 API key、`Authorization` header、prompt 字面值、模型响应 `content` 字段
- [x] `cut_index.json` 不含密钥明文（M0 安全边界保持）

## 事实源回写

- [x] [docs/specs/README.md](file:///Users/bytedance/Documents/TripClipper_Trae/docs/specs/README.md) 模块索引：`trustworthy-clip-timecodes` 状态改为「已完成」
- [x] 实现与本 spec 一致，无需回写偏差
- [x] M0 / M2 / M3 老 spec 原文不动（历史事实源），新事实以本 change 的 MODIFIED 段为准
