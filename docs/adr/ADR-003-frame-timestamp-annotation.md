# ADR-003: M3 视频 segments 时间码靠"M2 自适应抽帧+写时间戳 + M3 prompt 时间标注 + 严格校验"落地

- 状态：已采纳（grilling 拍板于 2026-06-29）
- 关联：[trustworthy-clip-timecodes/spec.md](../specs/trustworthy-clip-timecodes/spec.md)、[M2 spec](../specs/M2-local-scan/spec.md)、[M3 spec](../specs/M3-real-llm-analysis/spec.md)、[CONTEXT.md](../../CONTEXT.md)
- 相关需求：PRD FR-3 / FR-4（[mvp-product-requirements.md](../mvp-product-requirements.md)）；TD 6
- 取代关系：补充而非取代 M3 spec §Q22「segments 草稿由 M3 顺手产出」

## 上下文

M3 让视觉模型一次调用顺手产出 `Asset.segments`（高光片段，每段含 `in_`/`out` 时间码、`role`、`reason`、`audio_strategy`）。当前实现里：

- **M2** 在视频 1/4、1/2、3/4 时长处抽 **3 张匿名关键帧**，路径写入 `asset.frame_paths`，**时间戳算完即扔**（[scan.py L294-L342](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/scan.py#L294-L342)）。
- **M3** 把视频缩略图 + 至多 3 张关键帧 base64 拼进 vision API 的 `image_url` 多模态消息，**没有附任何时间戳文本标注**（[provider.py L358-L399](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/provider.py#L358-L399)）。Prompt 让模型按 `HH:MM:SS` 输出 `in`/`out`，**模型实际上凭空猜**——它看到的是 3 张匿名图，不知道每张图对应整段视频的哪个时间点。
- **M3 parser**（`_coerce_segments`，[provider.py L473-L509](file:///Users/bytedance/Documents/TripClipper_Trae/src/tripclipper/provider.py#L473-L509)）只做了字段宽容校验，**不验证时间码合法性**——格式错、`out<in`、超 `duration` 都会原样落盘。

后果：`cut_index.json.assets[*].segments[*].in_`/`out` 是不可信字段；M4/M5 任何消费 segments 时间码做对照/导出/Eagle 同步的下游都会拿到错数据，无可观测信号告诉用户"这条数据有问题"。

可选路径：

- **路径 1 — 同一次调用塞时间戳上下文**：M2 抽帧数从 3 张提到自适应（按 `duration` 按比例选 N 帧，封顶 12），把每帧的时间戳跟路径并列写进 `cut_index`；M3 给模型的多模态消息里在每张 `image_url` 前面插一个 text block「第 N 张关键帧 @ MM:SS.S」，prompt 加约束「`in`/`out` 必须接近这些时间点且落在 `[0, duration]` 内」；M3 parser 升级为严格校验：格式可解析 + `out>in` + 落在 `[0, duration]`。
- **路径 2 — per-segment 二次调用**：M3 第一次调用让模型先输出"几段、对应大致区间"的语义意图（不要时间码），M3 围绕区间在源视频上现抽窄窗口的密集帧再调一次让模型精确定位时间码。
- **路径 3 — 升级到能读视频流的多模态模型**：换 `gemini-2.5-pro-video` / `gemini-3.0-video` 这种能直接消费视频流的 vision model，时间戳由模型从视频本身读出。
- **路径 4 — 不动**：保留现状，prompt 里加一句"模型自报可信度"，让用户自己看 segments 时间码可信不可信。

## 决策

**采用路径 1**（M2 自适应抽帧+写时间戳 + M3 prompt 时间标注 + M3 严格校验）。

具体形态：

- **M2 抽帧数自适应**：`frame_count = max(3, min(12, round(duration / 5)))`，`duration` 不可用（`ffprobe` 失败 / 音频/图片）时退化为 3 帧。下限 3 保证短视频仍能多角度采样；上限 12 控制 base64 体积（gemini 多模态消息成本随帧数线性涨）；步长 5 秒/帧是 cherryin 通道 Gemini 3.5 flash 在 30-60s 真实素材上的经验值。
- **M2 写时间戳**：`Asset.frame_timestamps: list[float]`，与 `frame_paths` 索引一一对应、长度相等；时间单位秒，浮点；写入 `cut_index.json` 作为新字段。
- **M3 prompt 时间标注**：构造 user content 时，对每张 `image_url` 前插一个 text block，文案模板：`第 {i} 张关键帧 @ {MM:SS.S}`（`MM:SS.S` 由 `frame_timestamps[i]` 用秒级精度格式化）。Prompt 显式约束：「输出的 `in`/`out` 必须落在 `[0, duration]` 区间内，且应贴近上述时间标注的视觉证据；如视觉证据不足以确定高光段则不输出该 segment」。
- **M3 严格校验**：`_coerce_segments` 升级为 `_coerce_clip_suggestions`，对每段 ClipSuggestion 强制三条校验——① `in`/`out` 必须匹配 `^\d{1,2}:\d{2}:\d{2}(\.\d+)?$` 或纯秒数浮点；② `out > in`；③ `0 ≤ in < out ≤ duration`（`duration` 缺失时校验①②）。任一条不过则**整段丢弃**（不污染 Asset），其他通过校验的 segments 正常落盘，主字段 `summary`/`tags`/`rating` 等不受影响。
- **命名重构**：把 `Segment` / `Asset.segments` 重命名为 `ClipSuggestion` / `Asset.clip_suggestions`，对齐 PRD 用语（segments 在 video 领域常指"任意时间区间"，clip suggestion 在剪辑场景明确表达"高光片段建议"）；`SCHEMA_VERSION` 由 `0.2` 升至 `0.3`（BREAKING）。
- **删 4 个 dead field**：原 `Segment` 上的 `subject_type`/`shot_scale`/`rating`/`tags` 当前 prompt 不让模型出、永远是空——保留还是删除走过 grilling Q4 单独决策：**保留**这 4 个字段并让 prompt 同时产出（赋予 segment 级的主体类型/景别/星级/标签语义，区别于 asset 级的全段统计）。

## 理由

1. **路径 2（per-segment 二次调用）成本翻倍且收益有限**：每条素材至少 2 次模型调用，token 与 latency 双倍；而 cherryin 通道 Gemini 3.5 flash 在「已知整段 duration + N 张带时间戳的关键帧」前提下，足以把 in/out 时间码定位到 5 秒级精度——这已经是 M4 雷同分组所需的精度上限（M4 不依赖秒级精度做雷同识别）。
2. **路径 3（升级到读视频流的多模态模型）依赖外部不可控因素**：cherryin 转发的 Gemini 3.5 flash 当前**不**支持直接消费视频流，要换成支持视频流的模型需要切 base_url 或换 provider；且视频流模型 token 成本约高 5-10 倍。Spec 阶段不能假设外部供应商通道可用性，本机演进必须在「现有 vision API + base64 image_url」的能力范围内闭环。
3. **路径 4（不动）违反 PRD §2「禁止伪造分析结果」**：现状 segments 的 in/out 是模型在缺失上下文下的硬编生成结果，写进 `cut_index.json` 后下游无法区分"这是真的高光起止"还是"模型瞎填"。即使加 confidence 字段，confidence 本身也是同一次模型调用产出的、不可信的元数据。
4. **路径 1 的"喂时间戳"成本可控**：每张关键帧前面的 text block 字面字符串约 30 token，N≤12 帧总成本 ≤360 prompt token，与单张 base64 关键帧约 400-800 token 比可以忽略；严格校验是纯函数，零运行时成本；自适应抽帧改的是 M2 而非 M3，不增加每次模型调用本身的请求规模。
5. **路径 1 的"严格校验"提供可观测信号**：当模型时间码失败时，segments 数被 `_coerce_clip_suggestions` 丢弃，下游看到的是「这条视频成功 analyzed，但 clip_suggestions 为空」——这是一个**显式信号**，跟"模型瞎填一个貌似合法的时间码"在语义上完全不同，M5 HTML 可观测面板和 M8 错误记录可以据此做监控。
6. **命名重构现在做最便宜**：M3 已完成、M4 已完成但 folder-as-project 重构未做（处于暂存状态），M5 完整版/M6 Eagle/M7 启动页都未开工——下游对 `segments` 字段的消费面只在 M5-early 的 review.html 渲染 + M4 内部参考；现在做重命名 + SCHEMA_VERSION bump 影响面是最小的窗口；继续往后做完 M5/M6 再改要同步迁移更多文件 + 真实用户的 cut_index.json 数据迁移。
7. **保留 4 个 dead field + prompt 产出**：grilling 过程中先选"删掉"再改"保留"，最终保留的理由是——asset 级已经有 `subject_type`/`shot_scale`/`rating` 描述"这段视频整体什么主体、什么景别、几星"，但**单条 segment** 可能跨越多个景别（远景拉到特写的运镜）、单条 segment 可能从风景切到人物（subject_type 不一致），让模型对每段 ClipSuggestion 独立标注这 4 个字段，给 M5 报告和 M6 Eagle tag 提供更精细的剪辑维度，且边际成本极低（同一次调用顺手出）。

## 后果

### 正面

- `cut_index.json.assets[*].clip_suggestions[*].in`/`out` 字段从"不可信"变为"严格校验后落盘"，下游 M4/M5/M6 可信引用。
- 时间标注 text block 让模型有了可对照的视觉证据，定性上 in/out 偏差从"全凭语义"收窄到"对照可见的 12 帧"。
- 严格校验把"模型瞎填"变成"段被丢弃"，给可观测面板提供显式信号。
- ClipSuggestion 命名让代码意图更直接（`asset.clip_suggestions` 比 `asset.segments` 在剪辑工具上下文里更准确）。
- 4 个 segment 级字段补回，M5/M6 可以输出"段级景别/主体"维度的报告，而不仅是"asset 级一刀切"。

### 负面

- **SCHEMA_VERSION 0.2 → 0.3 是 BREAKING**：用户现有 `cut_index.json` 在新代码上读会报"schema 不兼容"，需要：① 实现阶段提供一次性迁移工具（`tripclipper migrate-schema --from 0.2 --to 0.3`）把 `segments` 改名为 `clip_suggestions`、补 `frame_timestamps: []`；② 或要求用户对项目执行 `--force` 重新 scan + analyze（cheapest，但要消耗模型 API 配额）。本 ADR 选 **②**，因为：M2 重新抽帧本身就是这次改动的必要步骤（要从 3 帧改到自适应、要写时间戳），即使保留 schema 兼容也不能复用旧 frame_paths；M3 重新分析才能消费 frame_timestamps 重新校验时间码。提供迁移工具反而误导用户认为"不重跑也能用上时间码可信化"。
- **M2 抽帧上限 12 增加 cache/frames 体积**：每个 30s 视频从 3 帧涨到 6 帧、60s 视频从 3 帧涨到 12 帧；按 5 个真实样本估算，cache 体积约增加 3-4 倍（每帧 100-300KB JPEG）。可接受——`cache/` 已在 `.gitignore`，且本地工具的磁盘成本可忽略。
- **M3 每次调用 prompt token 增加 ~360**：N=12 帧时增加 360 token、N=3 帧时增加 90 token，cherryin Gemini 3.5 flash 按 1M input token / $0.075 计，单条素材成本增加约 $0.000027（30 分之一美分），可忽略。
- **保留 4 个 dead field 让 prompt 复杂度增加**：每段 ClipSuggestion 要求模型同时产出 6 个字段（`in`/`out`/`role`/`reason`/`subject_type`/`shot_scale`/`rating`/`tags`/`audio_strategy`）会让模型在小段内做更多分类判断，可能让原本主字段（summary/tags/rating）质量下降。需要在 grilling Q4 退出条件里盯紧：若新 prompt 让 asset 级 rating 分布漂移明显，考虑回退到删除这 4 个字段。

## 替代方案及拒绝原因

- **路径 2（per-segment 二次调用）**：见理由 1。成本翻倍、latency 翻倍、收益（更精确时间码）在 5 秒级精度已经能由路径 1 提供；MVP 阶段不优化 sub-5s 的时间码精度。
- **路径 3（升级到读视频流的多模态模型）**：见理由 2。依赖外部 provider 通道升级，超出本仓 spec 阶段可控范围。若未来 cherryin / 其他通道开放 Gemini-Video 或 GPT-4o-Video，作为路径 3 的强需求触发点。
- **路径 4（不动）**：见理由 3。违反 PRD §2 禁止伪造分析结果。

## 退出条件

若未来真实素材上出现以下任一情况，重新评估：

- 路径 1 校验后**整体素材 clip_suggestions 丢弃率 > 30%**：说明模型在带时间戳的情况下仍频繁产生越界/格式错时间码，路径 1 假设失效，触发路径 2 评估。
- **5 秒级精度不够**：M5/M6 用户反馈"剪辑 in/out 在 ±5s 偏差内不可用、需要 ±1s 精度"，触发路径 2 或路径 3 评估。
- **ClipSuggestion 4 字段（subject_type/shot_scale/rating/tags）让 asset 级 rating 分布漂移明显**：触发删除这 4 字段的回退评估（保持 segment 只含 in/out/role/reason/audio_strategy）。
- **cherryin / 主通道开放视频流模型**：触发路径 3 评估，权衡 token 成本 vs 时间码精度提升。
