# M2 验收清单

## 如何手动验证本模块

> M2 是本地素材扫描（Stage 1），没有页面，验收靠：CLI 扫描 + 检查 `cut_index.json.assets` 与 `cache/` 产物 + 真实集成测试。前置需 `ffmpeg`/`ffprobe`（本机在 `/opt/homebrew/bin`），并先用 M1 初始化项目。

```bash
# 0) 确保 ffmpeg/ffprobe 可用
export PATH="/opt/homebrew/bin:$PATH"
ffprobe -version && ffmpeg -version

# 1) 先初始化项目（M1），再执行 Stage 1 扫描
tripclipper init --config ./project.yaml
tripclipper analyze --stage scan --config ./project.yaml
# 打印：发现总数 / 各类型计数 / 跳过 / 失败 / ffmpeg·ffprobe 能力，退出码 0

# 2) 检查扫描产物
cat projects/<slug>/cut_index.json        # assets 被填充，含基础信息与 metadata
ls projects/<slug>/cache/thumbnails/      # 视频缩略图
ls projects/<slug>/cache/frames/          # 关键帧

# 3) 幂等：再扫一次，结果稳定、asset_id 不变、顺序一致
tripclipper analyze --stage scan --config ./project.yaml

# 4) 失败路径：未初始化项目时退出码非 0、提示先 init、不抛堆栈
tripclipper analyze --stage scan --config <未初始化项目的配置>

# 5) 真实集成测试全绿（零 mock，真实调用 ffprobe/ffmpeg，需 tests/videos/ 素材）
pytest -q tests/test_scan.py
```

**重点核对**：每个 asset 含 `asset_id/filename/path/relative_path/extension/size/modified_time`，`analysis_status=scanned`；多流文件取主视频流（忽略 mjpeg 封面流/data 流）；分数帧率求值为浮点；派生产物只写入 `cache/`、源目录零改动；缺工具时降级记 `warnings` 不崩溃；空目录给"未发现可处理媒体"提示。

## 递归发现与类型识别
- [x] `source_folder`（含子目录）下的支持媒体（视频/图片/音频）进入 `cut_index.json.assets`，`type` 正确
- [x] 非媒体文件（`.txt`/`.docx`/无扩展名等）不进入 `assets`，并计入扫描摘要 skipped
- [x] 扩展名大小写不敏感（`.MP4`/`.JPG` 等被正确识别）
- [x] 支持类型清单与 TD 5 一致（视频/图片/音频三类扩展名齐全）

## 基础文件信息与稳定标识
- [x] 每个 asset 含 `asset_id`/`filename`/`path`/`relative_path`/`extension`/`size`/`modified_time`
- [x] 初始 `analysis_status` 为 `scanned`
- [x] 同一文件多次扫描 `asset_id` 一致（复用 M0 `generate_asset_id`）
- [x] `assets` 按相对路径排序，多次扫描顺序与结果稳定可复现

## 媒体信息与浏览辅助信息（能力可用时）
- [x] `ffprobe` 可用时 `asset.metadata` 含 duration/分辨率/codec/fps/has_audio
- [x] 多流文件取**主视频流**：DJI 文件忽略 mjpeg 封面流与 data 流；NO 系列取 1920×1080 主流而非 640×480 副流
- [x] 分数帧率 `avg_frame_rate`（如 60000/1001、30/1）求值为浮点（≈59.94、30.0）
- [x] `ffmpeg` 可用时视频生成缩略图与关键帧，`thumbnail_path`/`frame_paths` 被回填
- [x] 所有派生产物仅写入项目 `cache/`（thumbnails/frames），源目录不被修改

## 优雅降级与失败隔离
- [x] `ffmpeg`/`ffprobe` 缺失时 `capabilities` 标记不可用、`warnings` 含 stage=`scan` 能力警告，基础信息仍写入，不崩溃
- [x] 单个文件探测/抽帧失败被记录到该 asset 或项目 `warnings`/`failures`，其余文件正常完成

## 空目录
- [x] `source_folder` 无支持媒体时 `assets` 为空、`warnings` 含"未发现可处理媒体"、扫描成功结束

## 幂等与可重入
- [x] 含已有 Stage 2 分析字段的 asset，新增文件后再扫描，分析字段保留、文件级字段刷新
- [x] 连续两次扫描均成功、不抛异常、`asset_id` 稳定、顺序一致
- [x] 能力/空目录警告重复扫描不重复堆积

## CLI 入口
- [x] `tripclipper analyze --stage scan --config <合法配置>` 退出码 0 并打印发现总数/各类型/跳过/失败/能力
- [x] 对未初始化项目执行扫描时退出码非 0、信息清晰（提示先 init）、不抛未捕获堆栈

## 安全与一致性
- [x] `source_folder` 仅只读引用，扫描前后源目录文件未被删除/移动/覆盖
- [x] 任何摘要/日志不含密钥明文
- [x] M2 未重新定义任何 M0 字段或枚举

## 测试与回写
- [x] `tests/test_scan.py` 全部用例通过，`pytest` 全绿（PATH 含 `/opt/homebrew/bin`）
- [x] 测试**零 mock**：不替换任何函数/stub，使用 `tests/videos/` 本地真实视频全量跑，真实调用 ffprobe/ffmpeg
- [x] 媒体断言贴合实测真值（NO 系列 1920×1080/hevc/30fps/有音轨/≈60s；DJI 系列 1920×1080 或 2688×1512/hevc/≈59.94fps/有音轨）
- [x] 降级用例通过真实空 `PATH`（真实无 ffmpeg/ffprobe 环境）触发，而非伪造函数返回
- [x] 单文件失败用例通过真实损坏 `.mp4` 让真实 ffprobe 失败触发
- [x] `tests/videos/` 已加入 `.gitignore`（约 1GB 大文件不入库）
- [x] `docs/specs/README.md` 中 M2 状态更新为已完成
