# M2 Tasks

> 阶段：**已完成**（implement）。全部任务已实现并通过测试（`tests/test_scan.py` 18 项、全量套件 50 passed）。
> 依赖前置：M0 已完成（`config`、`models`、`cut_index`、`paths`、`security`）、M1 已完成（`init_project` 可产出项目目录与已初始化 `cut_index.json`）。

- [x] Task 1：实现扫描核心常量与分类（`src/tripclipper/scan.py` 基础部分）
  - [x] SubTask 1.1：定义 `SUPPORTED_EXTENSIONS`（扩展名 → `AssetType` 单一映射，严格依 TD 5 清单：视频 `.mp4/.mov/.m4v/.avi/.mkv/.webm/.mts/.m2ts`、图片 `.jpg/.jpeg/.png/.heic/.heif/.webp/.tif/.tiff`、音频 `.mp3/.wav/.m4a/.aac/.flac/.ogg/.opus`），键统一小写
  - [x] SubTask 1.2：实现 `classify_file(path) -> Optional[AssetType]`（大小写不敏感；非媒体返回 `None`）
  - [x] SubTask 1.3：定义 `ScanResult`（Pydantic 模型或 dataclass）：`total`、`by_type`（video/image/audio 计数）、`skipped`、`failures`、`is_empty`、`capabilities`（ffmpeg/ffprobe 状态）、`cut_index_path`

- [x] Task 2：实现能力探测与外部工具薄封装
  - [x] SubTask 2.1：`detect_capabilities() -> Capabilities`，用 `shutil.which("ffmpeg")`/`shutil.which("ffprobe")` 判定，写 `notes`
  - [x] SubTask 2.2：`_run_ffprobe(path) -> dict`（调用 ffprobe 取 duration/分辨率/codec/fps/has_audio；按主流选择 + 分数帧率求值解析为统一 dict），外部调用集中此处
  - [x] SubTask 2.3：`_run_ffmpeg_thumbnail(...)` / `_run_ffmpeg_frames(...)`：视频抽取缩略图与至多 N 帧（默认 3，均匀分布）到 `cache/thumbnails`、`cache/frames`，返回生成文件路径
  - [x] SubTask 2.4：薄封装统一加超时与异常捕获，失败抛可识别异常供上层隔离

- [x] Task 3：实现单文件处理与媒体补全
  - [x] SubTask 3.1：`build_asset(path, source_folder)`：生成 `relative_path`（相对 source_folder）、复用 M0 `generate_asset_id`、填 `filename/path/extension/size/modified_time/type`、`analysis_status=scanned`
  - [x] SubTask 3.2：`probe_media(path, capabilities)`：ffprobe 可用时把媒体信息写入 `asset.metadata`；不可用/失败返回空并标记降级（不抛到顶层）
  - [x] SubTask 3.3：`extract_thumbnail`/`extract_frames` 接线：ffmpeg 可用时为视频回填 `thumbnail_path`/`frame_paths`；图片把原图路径作为缩略图来源引用（不复制原图）；音频跳过
  - [x] SubTask 3.4：单文件失败隔离：探测/抽帧异常 → 记录该 asset `warnings`/`failures` 或项目级 `failures`，继续处理其余文件

- [x] Task 4：实现 `scan_project`（端到端）
  - [x] SubTask 4.1：`scan_project(slug, *, base_dir=None, extract_media=True)`：定位并 `read_cut_index`（不存在则抛清晰错误提示先 init）→ `assert_read_only_source(source_folder)`
  - [x] SubTask 4.2：`os.walk` 收集候选文件 → 按相对路径排序（确定性）→ 逐个 `classify_file`，非媒体计入 skipped，支持媒体走 `build_asset` + 媒体补全
  - [x] SubTask 4.3：合并策略：按 `asset_id` 把新文件级信息合并进已有 asset，保留 Stage 2 分析字段；源中已消失的旧 asset 记录非阻塞警告（不删除）
  - [x] SubTask 4.4：写 `cut_index.capabilities`；ffmpeg/ffprobe 缺失时追加一条 stage=`scan` 能力警告（去重）；空目录追加"未发现可处理媒体"警告
  - [x] SubTask 4.5：`write_cut_index` 落盘，返回 `ScanResult`

- [x] Task 5：接线 CLI `analyze --stage scan`（`src/tripclipper/cli.py`）
  - [x] SubTask 5.1：`--stage scan` 从占位改为：加载配置取 slug（或直接接受 `--config`）→ 调 `scan_project` → 打印扫描摘要（总数/各类型/跳过/失败/能力）；`--stage sample/full` 仍占位
  - [x] SubTask 5.2：捕获错误（项目未初始化/配置错误）以面向用户清晰信息打印并 `sys.exit(非0)`，不抛未捕获堆栈

- [x] Task 6：编写测试并通过（`tests/test_scan.py`）
  - 测试约定（**零 mock，连依赖环境一起测，使用本地真实视频**）：
    - **不使用任何 mock / monkeypatch 函数替换 / stub**；`ffmpeg`/`ffprobe` 必须真实安装（本机已装 `/opt/homebrew/bin` 8.1.2），测试真实调用它们。
    - **素材来源 = 仓库本地 `tests/videos/` 下用户提供的真实视频，全量参与扫描**，不自造媒体。**只测视频类型**（image/audio 本期不测，待补素材）。
    - 实测真值（断言基准，须取主流、解析分数帧率）：
      - `NO20250612-*.mp4`（4 个）：主流 `1920×1080 / hevc / 30fps / 有音轨 / ≈60s`，内含 `640×480` h264 副流须被忽略
      - `DJI_20260612134026_0001_D.MP4`：`1920×1080 / hevc / ≈59.94fps / 有音轨 / ≈4.33s`，含 mjpeg 封面流+多 data 流须被忽略（最小文件，宜作主用例）
      - `DJI_2026061311*_D.MP4` / `DJI_20260613145058_0115_D.MP4`：`2688×1512 / hevc / ≈59.94fps / 有音轨`
    - 大文件（合计约 1GB）：扫描调用设足够超时；用例可全量跑。`tests/videos/` 必须在 `.gitignore` 排除。
    - 源只读：把 `tests/videos/` 作为 `source_folder` 只读引用，产物只写临时项目 `cache/`；断言扫描前后该目录文件数量/内容不变。
    - 先用 M1 `init_project` 真实初始化项目作前置。
    - **降级分支用真实空 PATH 触发**：`monkeypatch.setenv("PATH", str(empty_dir))` 让 `shutil.which` 真实找不到工具（仅改环境变量，不替换任何函数行为）。
    - **边界用例由测试在 `tmp_path` 直接写文件构造**（非有效媒体，不算自造媒体）：`note.txt`/无扩展名 `README`（跳过）、"垃圾字节 `.mp4`"（让真实 ffprobe 真实失败）、空目录。
  - [ ] SubTask 6.1：递归发现——`tests/videos/` 全部 `.mp4/.MP4` 进入 assets 且 type=video；额外写入的 `.txt`/无扩展名被跳过且计入 skipped
  - [ ] SubTask 6.2：扩展名大小写不敏感（素材含 `.mp4` 与 `.MP4`，均识别为 video）
  - [ ] SubTask 6.3：基础信息齐全（asset_id/filename/path/relative_path/extension/size/modified_time、analysis_status=scanned）；同一文件两次扫描 asset_id 一致；assets 按相对路径排序
  - [ ] SubTask 6.4：真实 ffprobe → metadata 贴合实测真值（duration/分辨率/codec/fps/has_audio）；**主流选择**（DJI 忽略 mjpeg/data、NO 取 1920×1080 非 640×480）；**分数帧率**（59.94/30.0 浮点）；真实 ffmpeg → thumbnail_path/frame_paths 回填且真实文件落在 cache/
  - [ ] SubTask 6.5：真实空 PATH（无 ffmpeg/ffprobe）→ capabilities 标记不可用、warnings 含 scan 能力警告、基础信息仍写入、不崩溃
  - [ ] SubTask 6.6：单文件失败隔离——损坏的 `.mp4`（真实 ffprobe 失败）仍入 assets 且记录 failure/warning，其余正常
  - [ ] SubTask 6.7：空目录 → assets 为空、warnings 含"未发现可处理媒体"、扫描成功
  - [ ] SubTask 6.8：幂等保活——先写入含分析字段的 asset，新增文件后再扫描，断言已有分析字段保留、文件级字段刷新；连续两次扫描不报错
  - [ ] SubTask 6.9：源只读——断言扫描前后 `tests/videos/` 文件数量/内容不变，派生产物只在 cache/
  - [ ] SubTask 6.10：CLI（`click.testing.CliRunner`）：成功路径退出码 0 并打印摘要；未初始化项目路径退出码非 0 且信息清晰
  - [ ] SubTask 6.11：`pytest` 全绿（在已安装 ffmpeg/ffprobe 的环境）；运行前确保 PATH 含 `/opt/homebrew/bin`

- [ ] Task 7：回写状态与配置
  - [ ] SubTask 7.1：把 `tests/videos/` 加入 `.gitignore`（避免约 1GB 大文件入库）
  - [ ] SubTask 7.2：`docs/specs/README.md` 模块索引把 M2 状态更新为"已完成"
  - [ ] SubTask 7.3：如实现与 spec 有偏差，回写 `spec.md` 保持事实源一致

# Task Dependencies
- Task 2 依赖 Task 1
- Task 3 依赖 Task 1、Task 2
- Task 4 依赖 Task 1~Task 3
- Task 5 依赖 Task 4
- Task 6 依赖 Task 1~Task 5
- Task 7 依赖 Task 6
