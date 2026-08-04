# 多轮片段选片 Agent 设计

## 状态

本设计已完成方案讨论，等待用户复核。

本设计覆盖独立的片段级选片 Agent，不修改现有正式素材分析 Prompt、评分 Prompt、`cut_index.json` Schema、`clip_suggestions` 写入逻辑或 Roughcut 流程。

## 背景

现有流程主要依赖单次素材分析产生的 `rating`、摘要、关键帧和 `clip_suggestions`。它适合形成稳定的素材索引，但不能充分解决任务级选片：

- 同一素材在 60 秒轻松视频和 3 分钟叙事视频中的价值不同；
- 单次均匀抽帧可能遗漏短暂但高价值的片段；
- 高星素材可能高度重复，低星素材也可能承担唯一叙事作用；
- 用户可能提出开头形式、人物重点、景别搭配等自然语言要求；
- 模型需要按需多次查看素材，而不是只做一次判断。

因此固定评分和任务选片解耦：

- `rating` 表达素材自身相对稳定的可见价值；
- 选片结果表达片段在某次视频任务中的作用、稀缺性、替代关系和优先级。

## 目标

建立一个受控但具有自主搜索能力的选片 Agent：

1. 读取现有 `cut_index.json`，不重复全量分析所有原始视频；
2. 由 LLM 自主决定何时、对哪个素材、在哪个时间范围追加取帧；
3. 根据用户自然语言要求和实际素材，动态建立内容分类；
4. 在项目范围内比较片段，输出主选、备选和待人工复核候选；
5. 将当前状态与运行历史分开保存；
6. 支持程序中断后从已保存状态继续；
7. 到候选池为止，不决定最终剪辑顺序。

## 非目标

- 不修改正式评分或素材分析 Prompt；
- 不重新设计或验证五档评分量表；
- 不把新发现写回 `cut_index.json` 或原有 `clip_suggestions`；
- 不输出最终时间线、精确剪点、音乐卡点或转场；
- 不实现 DeerFlow App；
- 不实现多 Agent 评审；
- 不计算金额预算或 Codex 套餐剩余额度；
- 本期不做新旧选片方案的效果对比验证。

## 总体架构

```text
TripClipper CLI / API
        ↓
SelectionRunner
        ↓
DeerFlow Harness
        ↓
Selection Agent
        ↓
Python Tools
        ↓
SelectionValidator
        ↓
SelectionStore
```

职责边界：

- TripClipper 是产品入口和任务编排层；
- `SelectionRunner` 负责任务目录、输入快照、启动、恢复和重走；
- DeerFlow Harness 负责模型循环、Tool Call、上下文管理和递归上限；
- Selection Agent 自主决定查看、分类、比较和何时请求完成；
- Python Tools 提供受控查询和状态修改；
- `SelectionValidator` 检查确定性规则；
- `SelectionStore` 保存状态和事件，不做审美判断。

DeerFlow 只作为嵌入式 Harness，不拥有用户入口、状态格式、完成规则或项目生命周期。

## Python 与 DeerFlow 依赖

TripClipper 运行环境升级到 Python 3.12 或更高版本。

DeerFlow Harness 当前从 DeerFlow 仓库源码引入。依赖必须固定到实施时通过完整测试的 Git commit，禁止跟随 `main` 分支浮动。未来独立 PyPI 包稳定后，再评估切换到正式版本号。

模型使用 DeerFlow 的 `CodexChatModel`，读取本机 `~/.codex/auth.json`。不要求新增 OpenAI API Key。

## 目录命名

文档与 Python 包统一使用 `clip_selection`：

```text
docs/clip_selection/
src/tripclipper/clip_selection/
```

Python 包不能使用 `clip-selection`，因此不在不同目录间混用连字符和下划线。

项目级运行数据仍使用复数目录 `selections`，表示一个项目可以有多个选片任务。

## 用户输入与任务目录

用户提供一个位于任意位置的 Markdown 文件。文件名就是用户给出的任务名称，文件内容使用自由自然语言，不要求 JSON 或固定表单。

示例：

```markdown
# 暑假漂流轻松版

做一个 60 秒左右、轻松有趣的旅行视频。
开头使用最有冲击力的漂流镜头。
中间避免连续出现相似机位，全景、中景和近景尽量穿插。
重点保留人物真实互动和意外反应。
```

入口：

```bash
tripclipper select 26shidu ~/Desktop/暑假漂流轻松版.md
```

首次运行时，Runner 创建：

```text
projects/26shidu/selections/
├── shared_frames/
└── 暑假漂流轻松版/
    ├── brief.md
    ├── state.json
    └── events.jsonl
```

- `brief.md` 是外部输入文件的任务内快照；
- `state.json` 保存当前有效状态；
- `events.jsonl` 保存追加式运行历史；
- `shared_frames/` 保存所有选片任务可复用的追加帧。

任务名称禁止包含路径分隔符。首次运行后，恢复使用任务目录内的 `brief.md`。`--restart` 时重新复制外部 Markdown，并重建状态和事件文件。

## Brief 进入 Agent 的方式

Runner 读取任务目录内的 `brief.md`，将完整原文放入初始用户消息。Agent 不通过 Shell 或通用文件工具读取外部路径，也不获得任意文件访问权限。

不把用户要求强行拆成大量 JSON 字段。开头形式、节奏、景别搭配、人物偏好等继续以自然语言提供给 LLM。

目标时长是完成检查需要的唯一固定数值：

- Brief 能识别出明确时长时使用该时长；
- 未写或无法识别时默认 60 秒。

Runner 使用一个最小的确定性时长解析器处理常见的秒、分钟、`s` 和 `min` 表达，不增加单独的 LLM 调用或 `selection_duration_set` Tool。不能解析的表达直接使用默认值。其他用户要求不做程序解析，完整交给 Selection Agent。

## Agent 指令结构

运行指令分三层：

```text
system.md   固定运行边界
SKILL.md    选片专业方法
brief.md    本次用户目标
```

代码包内结构：

```text
src/tripclipper/clip_selection/
├── prompts/
│   └── system.md
└── skills/
    ├── public/
    └── custom/
        └── clip_selection/
            ├── SKILL.md
            └── references/
                ├── discovery.md
                ├── comparison.md
                ├── uncertainty_review.md
                └── convergence.md
```

`system.md` 始终加载，只规定：

- Agent 身份和任务边界；
- 只能使用注册的选片 Tools；
- 不能直接写 `state.json`；
- 状态变化必须通过 Tool；
- 完成必须调用 `selection_finish_request`；
- 必须使用 `clip_selection` Skill。

`SKILL.md` 保存选片总方法，并按需引用：

- `discovery.md`：全量发现和意外高价值片段；
- `comparison.md`：同类比较、主备和替代性；
- `uncertainty_review.md`：不确定但值得人工查看的片段；
- `convergence.md`：完成请求前的最终检查。

这些文件不是多个固定阶段 Prompt，也不规定 Tool 调用顺序。Agent 在一个连续循环中自主使用方法。

Runner 将包内 `skills/` 配置为 DeerFlow 的自定义 Skills 路径，并只允许当前 Agent 使用 `clip_selection`。目录保留 DeerFlow 要求的 `public/` 和 `custom/` 两层；本项目 Skill 位于 `custom/clip_selection/`。

`AGENTS.md` 不用于运行时选片规则。它面向在代码仓库中工作的编码 Agent，不能替代 DeerFlow 的运行时 system prompt 或选片 Skill。

## `cut_index.json` 的使用方式

Runner 在 Python 进程中读取并解析完整 `cut_index.json`。完整文件不进入 LLM 上下文。

Agent 通过分页和按需 Tool 获取局部信息：

- `asset_list` 返回一页精简素材摘要；
- `asset_get` 返回单个素材完整索引信息；
- `asset_frames_sample` 返回指定时间范围内的多张采样帧。

初始上下文只包含 Brief、项目标识、素材数量、当前状态摘要和 Tool 描述。大量素材数据保留在 Python 内存中。

选片 Agent 只读 `cut_index.json`。星级是参考信号，不是候选准入条件。

## Tool 契约

第一版注册以下 Tool：

```text
asset_list
asset_get
asset_frames_sample

selection_categories_save
selection_candidate_add
selection_candidate_update
selection_candidate_remove
selection_finish_request
```

### `asset_list`

分页列出素材的精简信息，包括 `asset_id`、时长、摘要、星级和已有建议概况。Runner 自动记录已经返回的分页位置。

### `asset_get`

读取一个素材的完整索引信息，包括摘要、星级、`clip_suggestions`、已有帧和时间戳。

### `asset_frames_sample`

参数至少包括：

```json
{
  "asset_id": "asset-1",
  "start_sec": 12,
  "end_sec": 24,
  "count": 3
}
```

Tool 从指定时间范围返回多张采样帧。优先复用已有帧；数量不足时从原视频追加抽取，并写入 `selections/shared_frames/`。它只提供观察证据，不创建候选 Clip。

### `selection_categories_save`

保存当前选片任务的完整内容分类列表。Tool 修改内存状态，经 Validator 检查后，由 Store 保存整个 `state.json`，不创建单独分类文件。

### 候选 Tool

- `selection_candidate_add`：新增候选，由代码生成 `candidate_id`；
- `selection_candidate_update`：修改状态、分类、范围、理由或替代关系；
- `selection_candidate_remove`：从当前候选池移除，删除原因写入事件历史。

被其他候选引用时不能直接删除，必须先修改替代关系。

### `selection_finish_request`

表示 Agent 请求结束，不保证成功。Validator 返回 `accepted` 或阻塞原因。检查通过后状态立即变为 `completed`，不要求第二次完成请求。

## Tool 注册

SelectionRunner 为每个任务创建绑定当前项目、Store、Validator 和共享帧目录的 Python Tool。Tools 直接传入 DeerFlow `create_deerflow_agent(tools=...)`。

不使用 MCP、CLI Tool 包装、全局任务变量或 DeerFlow App。每个任务持有独立 Tool 实例，避免状态串线。

## 当前状态与运行历史

### `state.json`

`state.json` 只保存当前有效事实，不保存完整模型对话和所有 Tool 历史。

建议结构：

```json
{
  "schema_version": 1,
  "task_name": "暑假漂流轻松版",
  "status": "running",
  "target_duration_sec": 60,
  "categories": [],
  "asset_progress": {
    "listed_pages": [],
    "opened_asset_ids": [],
    "sampled_ranges": []
  },
  "candidates": [],
  "unresolved": []
}
```

不保存 Brief 或 `cut_index` 哈希。恢复时直接使用任务目录内当前 Brief、项目当前 `cut_index.json` 和现有状态。

状态只使用：

```text
running
incomplete
completed
```

恢复 `incomplete` 任务时先改回 `running`。`completed` 状态默认只读，只有 `--restart` 才能重走。

### `events.jsonl`

`events.jsonl` 追加记录：

- 任务启动、恢复、重走和结束；
- Tool 名称和结构化参数；
- Validator 接受或拒绝；
- 候选移除原因；
- 运行错误；
- 可获得的 token 用量、模型调用次数和运行时间。

不保存每轮完整 LLM 输入输出。每轮输入通常包含前文，完整保存会产生大量重复。恢复不依赖事件日志。

## 分类结构

分类由 Agent 根据 Brief 和实际素材动态建立，不使用固定枚举。

```json
{
  "category_id": "category-001",
  "name": "漂流高潮",
  "required": true,
  "purpose": "提供开头吸引力和主要高潮",
  "missing_reason": null
}
```

- `category_id` 由代码生成；
- 一个候选可以属于零个、一个或多个分类；
- 分类改名不改变引用；
- 必要分类没有合适候选时必须填写 `missing_reason`；
- 分类列表不能退化成每个片段一个分类。

## 候选结构

```json
{
  "candidate_id": "candidate-001",
  "asset_id": "asset-1",
  "start_sec": 12.0,
  "end_sec": 18.5,
  "status": "primary",
  "category_ids": ["category-001"],
  "recommended_use": "适合作为开头或漂流高潮",
  "reason": "水花冲击明显，人物表情清楚；同类镜头中冲击最强",
  "alternative_to_ids": [],
  "review_reason": null
}
```

状态只保留：

```text
primary
alternate
needs_review
```

不在当前候选池保存 `excluded`。淘汰通过 `selection_candidate_remove` 完成，原因进入 `events.jsonl`。

字段规则：

- `recommended_use` 可选，供下游理解建议用途；
- `reason` 必填，合并可见证据和选择理由；
- `review_reason` 只在 `needs_review` 时必填，说明哪里不确定；
- `alternative_to_ids` 保存明确替代关系；
- 候选和分类 ID 都由代码生成，不由 LLM 自行编造。

## `needs_review`

`needs_review` 用于保存模型无法可靠确认，但可能有趣、稀有或不可替代的片段。

第一版不设固定数量上限。固定 `5` 个没有充分依据，也不能适配不同时长和素材规模。

每个 `needs_review` 必须同时说明：

- 为什么值得保留；
- 具体无法确认什么；
- 人工应重点查看什么。

明显重复的待复核项必须合并或移除。用户在 Brief 中明确要求上限时，才采用该上限。

## SelectionValidator

`SelectionValidator` 是普通代码，不调用 LLM、不保存文件。它提供两类检查：

```text
validate_change
validate_completion
```

代码可以检查：

- `asset_id` 存在；
- 时间范围合法且不超过素材时长；
- 分类引用和候选引用存在；
- 状态枚举和必填字段合法；
- 必要分类有主选，或明确记录缺失；
- 主选时间范围按并集计算后满足容量；
- 不存在高优先级未解决问题；
- 输出符合 Schema。

代码不能可靠判断：

- 片段是否有趣；
- 分类是否审美合理；
- 证据描述是否准确；
- 镜头搭配是否好；
- 片段是否真的不可替代。

这些判断由 LLM 完成，Validator 只检查结构和可确定事实。

## 容量与完成条件

设目标时长为 `T`。第一版保留 50% 主选容量余量：

```text
T <= 主选片段可用总时长 <= 1.5T
```

同一候选属于多个分类时只计算一次；同一素材内重叠的主选范围按时间并集计算。`alternate` 和 `needs_review` 不计入主选容量。

完成条件：

1. 所有素材分页都通过 `asset_list` 展示给 Agent；
2. 每个必要分类都有主选，或明确记录缺失；
3. 候选引用、时间范围和替代关系合法；
4. 主选容量位于 `T` 至 `1.5T`；
5. 不存在高优先级未解决问题；
6. 所有 `needs_review` 有完整理由；
7. 状态通过 Schema 和业务检查。

Agent 调用一次 `selection_finish_request`。检查通过立即完成；检查失败返回 blockers，Agent 继续自主工作。

完成前的同类比较、重复清理和最终审视写入 Skill，不编码成固定步骤或双阶段状态机。

## SelectionStore

`SelectionStore` 是普通 Python 持久化代码，不是 LLM。

状态修改流程：

```text
LLM 调用 Tool
Tool 构造内存状态变化
SelectionValidator 校验
SelectionStore 保存
Tool 返回结果
```

`state.json` 使用临时文件原子替换：

1. 完整内容写入 `state.json.tmp`；
2. 写成功后通过同文件系统重命名替换 `state.json`；
3. 临时写入失败时，旧 `state.json` 保持完整。

第一版不实现文件锁、并发写控制、状态 revision 或额外 `fsync`。每个选片任务只允许一个 Runner 写自己的状态文件。

## 启动、恢复与重走

代码保持两条分支：

```python
if restart or not state_path.exists():
    state = create_initial_state()
else:
    state = store.load()
```

默认行为：

- 没有 `state.json`：创建新任务状态；
- 有未完成状态：从状态继续；
- 已完成状态：直接返回现有结果，不启动 Agent。

强制重走：

```bash
tripclipper select 26shidu ~/Desktop/暑假漂流轻松版.md --restart
```

`--restart` 重新复制 Brief，重建 `state.json`，清空旧 `events.jsonl`。第一版不自动归档旧状态，不实现版本管理。

恢复不会恢复 LLM 隐藏思考或完整对话。Runner 使用 `brief.md`、当前 `cut_index.json` 和 `state.json` 创建新的 Agent 上下文。可以承接：

- 已建立分类；
- 当前候选池及理由；
- 已列出、打开和采样的素材范围；
- 已抽取共享帧；
- 未解决问题。

## DeerFlow 运行限制

不设计金额预算。系统没有模型实时价格、Codex 套餐剩余额度或准确收费信息。

DeerFlow `recursion_limit` 只作为防止无限循环的安全上限。它限制 LangGraph 执行步数，不等于金额预算，也不等于精确 LLM 轮数。

TripClipper 不再实现独立的 `max_rounds`、`max_frame_requests` 或 `max_review_clips`。

命中 `recursion_limit` 时，Runner 保留当前状态并标记 `incomplete`。下次启动可以继续。

## 错误处理

第一版只保留必要处理：

- Tool 参数错误：返回 Agent，继续运行；
- Validator 拒绝：返回 blockers，继续运行；
- 抽帧失败：返回 Agent，允许换范围或跳过；
- 模型或 DeerFlow 异常：保留状态并标记 `incomplete`；
- 命中递归限制：标记 `incomplete`；
- Store 写入失败：立即停止，保留旧状态；
- `state.json` 无法解析：停止，不自动修复或覆盖；
- Codex 未登录：启动前报错；
- Brief、`cut_index.json` 或原视频不存在：返回明确错误。

TripClipper 不额外实现模型重试系统，使用 DeerFlow 或模型 Provider 的现有能力。

## 输出边界

`state.json` 在 `status = completed` 后直接作为候选池输出。下游读取：

- 分类；
- `primary`、`alternate`、`needs_review` 候选；
- 建议用途；
- 理由；
- 替代关系。

输出不包含最终剪辑顺序。选片 Agent 负责“有哪些可用片段”，后续剪辑 Agent 负责“怎样排列片段”。

## 代码影响面

新增：

```text
src/tripclipper/clip_selection/
├── prompts/system.md
├── skills/public/
├── skills/custom/clip_selection/SKILL.md
├── skills/custom/clip_selection/references/discovery.md
├── skills/custom/clip_selection/references/comparison.md
├── skills/custom/clip_selection/references/uncertainty_review.md
├── skills/custom/clip_selection/references/convergence.md
├── models.py
├── runner.py
├── agent.py
├── asset_tools.py
├── selection_tools.py
├── validator.py
├── store.py
└── frames.py
```

修改：

- `pyproject.toml`：Python 改为 `>=3.12`，固定 DeerFlow Git commit；
- `src/tripclipper/cli.py`：新增 `tripclipper select`；
- `src/tripclipper/paths.py`：新增选片任务和共享帧路径函数。

复用但不修改数据契约：

- `cut_index.py`；
- 现有素材模型；
- 现有 ffmpeg 抽帧能力；
- Codex 登录态。

明确不改：

- `src/tripclipper/provider.py` 正式素材分析 Prompt；
- `src/tripclipper/arbiter.py` 现有仲裁 Prompt；
- `cut_index.json` Schema；
- 星级和 `clip_suggestions`；
- Roughcut。

旧的 `experiments/clip_selection/` 自研 Harness 已移除。新实现直接落在正式 Python 包中，避免长期维护两套运行框架。

## 实现期测试范围

本期不做选片质量验证，但代码实现仍需要单元测试：

- Store 原子写入和损坏状态处理；
- Validator 合法与非法状态变化；
- Tool 参数和状态修改；
- 分页读取 `cut_index`；
- 共享帧复用；
- 新建、恢复、完成和 `--restart`；
- DeerFlow 异常和递归限制处理。

真实 LLM 不进入单元测试。使用假模型或脚本化 Tool Call 测试状态流转。

## TODO

以下内容明确延期，不进入第一版：

- 新旧选片方案真实项目对比和人工盲评；
- 高价值片段发现率、无用候选比例和运行消耗统计；
- 五档星级区分度的独立设计与验证；
- 双阶段完成检查和候选结构稳定性检测；
- 独立复核 Agent；
- 根据目标时长动态限制人工复核负担；
- 金额预算和 Codex 套餐额度感知；
- 多任务并发写锁和状态 revision；
- DeerFlow 正式 PyPI 包发布后的依赖迁移；
- 将新发现晋升回固定素材分析层。
