# TripClipper 待办点子（TODO List）

> 这份文档用来随手记录脑子里冒出来、但还没有正式立项的功能想法。
> 想到就先写下来，后续再决定归到哪个版本或是否成立独立 spec。
> 与 [future-version-requirements.md](./future-version-requirements.md) 的关系：
> 那份是已经梳理过的版本路线图；这份是更早期、未分类的灵感池。

## 候选功能

### 场景聚类

- 想法：把已经扫描/分析过的素材，按"场景"自动聚成几组，方便后续审核和粗剪挑选。
- 可能的聚类维度：
  - 视觉相似度（同一地点、同一镜头机位、同一光线条件）
  - 时间相近（同一时间段连续拍摄的素材大概率属于同一场景）
  - 地点信息（如果有 GPS / EXIF）
  - 模型分析得到的标签和场景描述
- 期望产出：
  - 每个素材带上 `scene_cluster_id`，写回 `cut_index.json`
  - 在 review 页面/导出里能按场景分组浏览
  - 支持人工合并、拆分场景
- 待确认：
  - 用什么算法（embedding + 聚类，还是基于规则）
  - 离线跑还是分析时顺便产出
  - 是否需要跨项目共享场景定义

### Eagle 同步防重复导入（sha1 去重）

- 背景：M6 `sync-eagle` 当前实现走"信任 cut_index"路径——若 `cut_index.eagle_item_id` 非空走 update，否则直接 `addFromPath` 创建新 item。
- 已知风险：在以下场景会让 Eagle 库里出现同一文件的多条 item：
  - 用户在跑 TripClipper 之前手工把素材拖进了 Eagle，cut_index 不知道这些 item 已存在。
  - cut_index.json 损坏 / 删除 / 重建，导致已有的 `eagle_item_id` 全部丢失，再次同步会全员 re-import。
  - 多个 TripClipper 项目共用同一 Eagle 库，且素材文件路径有重叠。
  - 用户搬移项目目录，cut_index 里的绝对路径变化但 sha1 不变。
- 想法：在 `sync-eagle` 写入前增加一道 sha1（或 path）匹配步骤——若 Eagle 库中已存在同 sha1 的 item，把它的 id 回写进 `cut_index.eagle_item_id` 后走 update 路径，不再 `addFromPath`。
- 期望产出：
  - 同一文件在 Eagle 库里最多一条 item，无论 cut_index 状态如何。
  - 跨项目、用户手工导入、目录迁移等场景都能自动 link 而非重复导入。
  - 失败情况（Eagle V2 不支持 sha1 lookup 时）能优雅降级到 path lookup。
- 待确认：
  - Eagle V2 Web API 是否支持按 sha1 / 路径批量查询 item（待 spec 阶段实测确认 API 形式）。
  - N 条素材每条多一次 GET 是否需要批量化（V2 一般支持 POST 带数组批量查）。
  - cut_index 里命中 sha1 但 path 不一致时（用户搬过目录）的处理：以 sha1 为准 link 还是提示用户。

### 统一参数输入，统一参数重跑

- 想法：把一次项目运行涉及的所有可调参数（扫描、采样、模型、prompt、导出选项等）收敛成一份统一的"运行参数"对象，整个流水线都从它读取；同一份参数可以用来一键重跑。
- 期望产出：
  - 一份单一来源的参数文件，例如 `project.yaml` 或 `run_params.json`，覆盖：
    - 扫描参数（路径、扩展名白名单、采样帧率等）
    - 模型参数（provider、model、温度、并发、超时、重试）
    - prompt 参数（系统/用户 prompt 模板、版本号）
    - 分析参数（采样策略、是否启用音频、是否启用 OCR 等）
    - 导出参数（哪些导出物、HTML 主题、CSV 字段）
  - CLI/API 全部走"先解析参数 → 再执行"的路径，避免参数散落在命令行 flag 和代码默认值里。
  - 每次运行把使用过的完整参数快照写到产物目录，例如 `run_params.snapshot.json`。
  - 提供 `tripclipper rerun <project>` 或类似命令，直接读取上次快照重新执行，无需手敲参数。
- 价值：
  - 复现性：任何一次运行都可以用同一份参数原样再跑。
  - 可对比：不同参数版本的结果可以横向比较。
  - 易迁移：参数文件可以连同数据包一起复制到另一台机器继续跑。
- 待确认：
  - 参数文件格式（YAML / JSON / TOML）
  - 参数 schema 校验方式（pydantic 还是 JSON Schema）
  - CLI flag 和参数文件冲突时的优先级规则
  - 是否支持参数继承/覆盖（base + override）

### 人声识别与转写

- 想法：在素材分析阶段识别人声片段，并对可识别的人声内容做自动转写，作为后续检索、粗剪和摘要的基础数据。
- 期望产出：
  - 为视频或音频素材新增人声相关元数据，例如是否有人声、起止时间、说话片段数
  - 生成逐段转写文本，并写回 `cut_index.json` 或独立的转写产物文件
  - 支持按关键词搜索素材里的口播内容，例如人名、地点、台词、讲解词
  - 在 review 页面展示转写文本，并支持按时间戳定位回原素材
- 待确认：
  - 识别范围是只做中文普通话，还是要兼容方言 / 英文 / 中英混说
  - 走本地 ASR 还是云端语音识别服务
  - 转写粒度是整段文本、句子级，还是词级时间戳
  - 背景音乐、环境噪音、多人同时说话时的处理策略

### 增加运行时日志

- 想法：为扫描、分析、导出、同步等长链路任务补齐运行时日志，便于排查失败原因、观察进度，并为后续性能优化提供依据。
- 期望产出：
  - 关键阶段输出结构化日志，例如任务开始、输入参数摘要、阶段切换、耗时、失败原因、重试情况
  - 支持按项目或按运行批次落盘，例如写入 `logs/` 目录下的独立日志文件
  - CLI 在终端保留简洁进度信息，详细内容进入文件日志，避免刷屏
  - 出错时能快速定位到具体素材、具体阶段、具体异常，而不是只看到顶层报错
- 待确认：
  - 日志格式用纯文本、JSON Lines，还是两者同时提供
  - 默认日志级别是 `info` 还是 `debug`，以及是否支持命令行覆盖
  - 是否需要引入统一的 run_id，把一次运行内的所有日志串起来
  - 敏感信息（路径、token、prompt、模型返回）需要脱敏到什么程度

### 合并 `.env`

- 想法：把当前分散的环境变量配置收敛起来，减少 `.env`、`.env.local`、shell 导出变量等多处维护带来的混乱和遗漏。
- 期望产出：
  - 明确一套统一的环境变量加载规则，例如基础配置、项目覆盖、本地私有配置各自的优先级
  - 减少重复定义的 key，避免同一个变量在多个 `.env` 文件里值不一致
  - 提供一份清晰的 `.env.example` 或等价模板，说明每个变量的用途和必填性
  - 启动时输出缺失或冲突配置的提示，降低环境问题排查成本
- 待确认：
  - 是真正合并成单一 `.env`，还是保留分层文件但统一加载逻辑
  - 当前有哪些变量已经重复、冲突或失效，是否需要先做一次清点
  - 配置优先级规则是 `shell > .env.local > .env > 默认值`，还是别的顺序
  - 是否要把项目级配置和全局工具级配置彻底分开

### Session 切分的时间字段升级（EXIF / creation_time）

- 背景：`sync-eagle --split-by-session`（按行程/活动把素材归入 Eagle 子 folder 的功能）当前只用 `Asset.modified_time`（来自文件系统 `st_mtime`）判定素材的时间归属并切分 session。选择 mtime 是为了实现最简、零改动 scan 逻辑。
- 已知风险：mtime 只在"从相机/SD 卡直接导入的原始文件"上等于拍摄时刻。以下场景会让切分明显失真：
  - 从 iCloud / Google Photos / 微信 / AirDrop 下载的素材，mtime = 下载时刻
  - 经 `cp` / `rsync` 复制且未保留 mtime 的素材
  - 用户手工整理时被 touch 过的素材
- 已在 demo-scan 上验证：当前 9 个视频（DJI 无人机 + 行车记录仪 + iPhone 直连导入）mtime 与视频内嵌 `format.tags.creation_time` 相差 ≤ 60 秒，两种时间源在 gap=2h 阈值下切出的 session 完全一致。→ 现有实现在"直连导入"场景下够用。
- 想法：扫描期由 ffprobe 顺手读视频 `format.tags.creation_time`、由 Pillow / piexif 读图片 EXIF `DateTimeOriginal`，写入 `Asset.metadata['captured_at']`；session 切分优先用它，缺失回落 `modified_time`。
- 期望产出：
  - `Asset.metadata['captured_at']`（ISO 8601，UTC 归一化）新字段
  - session 切分 helper 优先读该字段，缺失才回落 `modified_time`
  - 已下载 / 转发的混合素材也能切出正确 session
- 待确认：
  - 图片 EXIF 读取要不要新增依赖（Pillow vs piexif vs 纯 ffprobe）
  - 是否需要一次性 backfill 已有项目的 cut_index（还是等下一次 scan 顺手补）
  - `captured_at` 的时区归一化策略（EXIF `DateTimeOriginal` 没有内嵌时区信息）

### Session 切分升级：用大模型辅助识别行程

- 背景：`sync-eagle --split-by-session` 首版只用"相邻素材时间间隔 ≥ 阈值"这一条规则来切段——纯启发式，不理解内容。
- 已知局限：
  - 同一活动中间因等光/换机位停拍超过阈值 → 被错误切开
  - 两个连续但内容完全不同的活动（比如吃完午饭立刻去下一个景点）→ 被错误合并
  - session folder 只能起 `session_01_2026-06-15_09-30` 这种时间戳名字，没有"海边 / 游戏 / 晚餐"的语义命名
- 想法：在时间切分的初稿上叠一层大模型判断——把每个候选 session 的关键帧（或缩略图）+ 已分析出的 `subject_type` / `scene` / `summary` 喂给 vision/text 模型，让它：
  - 判断"是否应该把相邻两个 session 合并"或"是否应该把一个 session 里的内容再切开"
  - 为每个 session 生成人类可读的短名（"海边散步" / "室内桌游"）
  - 输出置信度，低置信度回落到纯时间切分结果
- 期望产出：
  - `session_{NN}_{起始时间}_{语义名}` 的 folder 命名
  - session 合并/拆分建议写进 cut_index（新字段 `sessions[]` 或复用 `similar_groups` 结构）
  - dry-run 里展示"启发式切出 N 段 → 模型建议合并/拆分为 M 段"的对比
- 待确认：
  - 走 vision 模型（吃缩略图）还是 text 模型（吃已有的 subject/summary 描述）
  - 单次 prompt 的 session 上限（一次输入所有 session 还是滑窗）
  - 是否引入独立的 `analysis_stage = session`，与 `sample` / `full` / `cluster` 并列
  - 用户否决模型建议的入口（人工强制切分 / 合并 API）

### Session 切分升级：project.yaml 预声明行程作为强 hint

- 背景：用户往往拍摄前就知道"这次出行有哪几段行程"（酒店 → 海边 → 午饭 → 游戏场 → 晚宴），完全靠事后启发式或模型推断反而绕远。让用户在 `project.yaml` 里预声明行程边界，产品体验最直接。
- 想法：在 `project.yaml` 新增一节 `trips:`，用户预先写清每段行程的名称与时间窗（或起止时间戳），切分时把它当强 hint：
  ```yaml
  trips:
    - name: 海边散步
      start: 2026-06-15T09:00
      end:   2026-06-15T12:00
    - name: 桌游店
      start: 2026-06-15T14:00
      end:   2026-06-15T18:30
    - name: 晚宴
      start: 2026-06-15T19:30
  ```
- 期望产出：
  - 素材按 `modified_time`（或未来的 `captured_at`）落入声明的时间窗
  - session folder 直接使用 `trips[].name` 命名，而非 `session_01_...` 时间戳
  - 时间窗之外的素材归入 `session_unassigned` 或按启发式补切
  - 未声明 `trips:` 时回落到当前启发式切分行为
- 待确认：
  - 时间窗允许开区间/闭区间的写法（只写 start 不写 end 的最后一段如何处理）
  - 用户声明行程与启发式切分冲突时的优先级（默认应"用户声明 > 启发式"）
  - 是否允许行程时间窗重叠（同一素材可能属于两段）
  - 与前一条"大模型辅助切分"的叠加顺序：`用户声明 > 大模型 > 启发式` ？
