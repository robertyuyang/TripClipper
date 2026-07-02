# ADR-004: M6 Eagle 同步设计为通用字段映射层（薄原则）

- 状态：已采纳（grilling 拍板于 2026-06-30）
- 关联：M6 spec、CONTEXT.md §全局候选池入选状态、PRD §FR-9/FR-10、TD §10
- 相关需求：PRD FR-9（[docs/mvp-product-requirements.md](../mvp-product-requirements.md)）；FR-10；TD 10

## 上下文

M6 Eagle 同步是 PRD §FR-9/FR-10 的兑现：把 cut_index 中每条 asset 的 rating、tag、similar_group_id、edit_candidate_status、edit_candidate_reason 等字段写入 Eagle 库，让用户在 Eagle 里基于 TripClipper 的分析结果做最终人工裁决。

PRD §FR-10 验收口径写：

> 成功素材在 Eagle 中具备 TripClipper 生成的标签、星级、雷同素材选择状态、剪辑候选状态和备注。

PRD 示例 JSON 还展示了"为雷同组创建子文件夹"的用法。grilling 阶段对这条做了反复推敲，发现以下张力：

1. **业务语义注入**：若 M6 在写 Eagle 时把 `edit_candidate_status:excluded` 翻译成中文 tag「建议删除」、把 `shot_function:highlight` 翻译成「高光」，等于 M6 在创造命名空间。一旦 M4 改字段名 / 加新字段，M6 必须跟着改，且翻译规则成为新的事实源。
2. **业务规则注入**：若 M6 实施"alternate 不进 Eagle / excluded 默认隐藏"等过滤，等于 M6 复刻了一份候选池策略——这本属 M4 职责。
3. **示例 ≠ 契约**：PRD §FR-10 的 JSON 示例（`folders_to_create: ["项目/高光"]`）只是数据形状演示，不是验收契约。验收文字仅要求"具备 ... 标签、星级、状态和备注"，没要求 folder 结构、tag 命名翻译、哪些状态进哪些不进。

可选路径：

- **路径 1 — 业务化 M6**：M6 内置一套"中文友好"tag 命名（建议删除/默认候选/...）和过滤策略（excluded 不同步 / 创建场景子 folder），按"用户视角的 Eagle 体验"组织。
- **路径 2 — 通用字段映射层**：M6 仅做"cut_index 字段 → Eagle 写入维度（rating/tag/note）"的字面映射，不发明命名、不做业务过滤、不建 folder。所有"什么算应删""什么是默认候选"由上游字段值决定。
- **路径 3 — 折中**：默认薄映射 + 提供少量内置语义快捷 tag（如 `建议删除`）作为便利层。

## 决策

**采用路径 2（通用字段映射层）**。

具体形态：

### 一、范围与原则
- M6 不发明字段、不创造 tag/folder 命名、不翻译枚举值
- M6 不做业务过滤；同步范围 = 所有 `analysis_status == analyzed` 的素材（含 default_selected / alternate / excluded / needs_review 全部四档）
- `analysis_status == scanned` 启动期阻断（提示先跑 analyze，可 `--skip-unanalyzed` 逃生）
- `analysis_status == analysis_failed` 软放行（带 `tc:analysis_status:analysis_failed` tag + note 区块写失败原因）

### 二、Eagle 版本与布局
- 仅支持 Eagle V2 Web API（≥ 4.0 Build 22），低版本启动期硬阻断
- 不建 folder（flat 布局），项目维度依靠 tag `tc:project:{slug}` 区分
- 通过 V2 `tagGroup` API 自动维护字段分组：每个 cut_index 字段对应一个 tag group，例如 group `tc:edit_candidate_status` 包含 `tc:edit_candidate_status:default_selected` / `:alternate` / `:excluded` / `:needs_review` 四个 tag

### 二·补 Smart Folder as user-facing view layer

[`eagle-smart-folders` spec](../specs/eagle-smart-folders/spec.md) 在
`sync-eagle --apply` 结束后自动维护一批 name 前缀 `TC · ` 的 Eagle
Smart Folder，作为“用户友好视图层”。Smart Folder 是 Eagle 侧保存的查询规则，
rule 全部由 `tc:*` tag 组合构成，本身不新造字段、不发明命名，也不是物理
folder，因此不与 §一 flat 布局决策冲突。

这兑现了本 ADR 退出条件中的第二条：当用户反馈“打开 Eagle 后总要花时间筛 /
配 smart folder 才能进入工作状态”时，用视图层增强补足体验，而不是把业务
语义下沉到 M6 的数据映射层。

### 三、tag 命名与字段映射
- 全局格式：`tc:{field}:{value}`，无翻译、无中文别名
- rating（int）→ Eagle 原生 rating
- 枚举/标量字段（含 `similar_group_id`）→ tag
- 单行/多行文本字段（`edit_candidate_reason` / `similar_group_reason` / `analysis_failure_reason`）→ note 区块
- 结构化字段（`clip_suggestions`）→ note 区块（按 priority 排序的 markdown 列表）
- skip 列表（不映射任何 Eagle 维度）：`asset_id` / `path` / `sha1` / `imported_at` / `analyzed_at` / `similar_group_confidence`
- 默认 `auto_map_unknown: true`：cut_index 中未在 mapping 声明的枚举/字符串字段，自动按 `tc:{field}:{value}` 产 tag；可通过 `--strict-mapping` 切换严格模式

### 四、默认 mapping 配置位置
- 内置默认 mapping：`src/tripclipper/templates/eagle_mapping.default.yaml`（随包发布）
- 项目级 override：在 `tripclipper.yaml` 中以 mapping 节点覆盖

### 五、note 模板
- 头部一行斜体：`_TripClipper · {project_slug} · synced {timestamp}_`
- 区块固定顺序：候选池理由 → 雷同组理由 → 建议剪辑片段 → 分析失败原因
- 空字段不渲染标题
- 区块标题用 `## markdown` 二级标题
- 时间码用反引号包裹（等宽 + 可复制）

### 六、二次同步
- 默认 update：每次 `sync-eagle --apply` 刷新所有同步过的 item 的 tag/rating/note，覆盖 Eagle 端手工修改
- `--skip` flag：跳过已同步 item（按 `eagle_sync_status == synced` 判断）
- `--reset`：把已同步 Eagle item 移到回收站、清 cut_index 的 `eagle_item_id`，下次重建（带二次确认）
- **不做 sha1 去重**：信任 cut_index 的 `eagle_item_id` 状态；首次同步前若用户已手工把素材拖进 Eagle，会出现重复 item。该问题在 [docs/todolist.md](../todolist.md) 中记为后续优化项
- 不做 stale 检测（不存字段 hash）

### 七、错误处理
- **启动期硬阻断（不写任何东西）**：Eagle 不可达 / 版本 < V2 / cut_index 校验失败 / scanned 素材存在
- **运行期容错**：单条 asset 失败 → 标 `eagle_sync_status: failed` 继续；tag group 维护失败 → warning 继续
- **运行期硬中止**：连续 5 条网络层失败 → 推断 Eagle 已断开，整体退出，已成功 item 保留 `synced` 状态
- 跑完写 `projects/<slug>/eagle_apply_result.json`（覆盖式，不保留历史）

## 理由

1. **PRD 验收口径与"业务化"无关**：FR-10 只要求 Eagle 中具备来自 cut_index 的字段表示，没要求"中文友好命名""场景 folder""按状态过滤"。把 PRD 示例 JSON 当成需求是过度解读。
2. **薄层的稳定性收益巨大**：上游加新字段（如未来 M4 增 `recommend_action` 或 `scene_cluster_id`），M6 默认 `auto_map_unknown` 模式下零代码改动即可在 Eagle 里出现新 tag group。业务化 M6 则需要手工补翻译表 + 决定它进 folder 还是 tag。
3. **职责清晰**：tag 命名一旦带翻译（`tc:excluded` vs `建议删除`），翻译表成为新的事实源，与 cut_index 字段、CONTEXT.md 术语形成三方约束，更新一处必须三处同步。薄映射只用 cut_index 字段值字面，事实源始终是 cut_index。
4. **Eagle 自身能力可承担"用户友好"**：Eagle 的 smart folder、starred tags、tag group 折叠这些客户端能力足以让用户基于 `tc:edit_candidate_status:excluded` 这类机器可读 tag 自定义"建议删除"视图。把命名翻译留给 Eagle 客户端 / 用户配置，比固化在 M6 代码更灵活。
5. **MVP 单人使用场景**：用户（项目当前唯一目标用户）已确认能接受 `tc:edit_candidate_status:excluded` 这类 tag 名 + 自行在 Eagle 中按 tag 筛选作为"应删素材"工作流。"中文友好命名"在多人 / 客户场景下才有真实价值，目前不存在。
6. **方案可逆**：未来若用户反馈 tag 名不友好，加翻译只是"在 default mapping yaml 加 `display_name` 字段 + 一个渲染器"，向后兼容；现在不做不影响后续追加。

## 后果

### 正面

- M6 实现 ≈ "load mapping → 遍历字段 → 写 Eagle 维度"三段式，无业务分支可测；测试用 Eagle V2 stub 即可
- 上游 M4 / M3 加字段对 M6 透明（默认 auto-map）
- 不引入"M6 specific 业务术语"——CONTEXT.md 不需要为 M6 增加新术语
- ADR / spec / 代码命名一致：cut_index 字段叫什么，Eagle tag 就叫什么

### 负面

- Eagle 标签面板里 tag 名不"中文友好"（`tc:edit_candidate_status:excluded` 而非 `建议删除`）；用户首次接触需要一次心智映射，理解"`tc:` 是 TripClipper 写入的 namespace"
- 用户期望"打开 Eagle 立刻看到清晰的 '建议删除' 大类"时，需要用 Eagle smart folder 自行配置一次（一次性配置，后续自动）
- 不做 sha1 去重 → 用户在 sync-eagle 之前手工把素材拖入 Eagle，会出现 Eagle 库中同文件的两条 item；该 known limitation 已记 todolist
- 默认 update 行为会覆盖用户在 Eagle 端手工修改的 rating/tag——这是文档化的预期行为，需要明确写入 CLI help

## 替代方案及拒绝原因

- **路径 1（业务化 M6）**：上述理由 1-3 全部反对；中文翻译表会成为第三个事实源；改字段名时三处同步成本高；MVP 单人场景下"中文友好"价值不足以抵消复杂度。
- **路径 3（折中：薄 + 少量便利 tag）**：grilling Q-A 多轮拍板拒绝。少量便利 tag（如 `建议删除`）一旦引入就要回答"为什么 needs_review 不也加便利 tag""为什么 alternate 不加"等问题；划线没有非任意性；"零便利 tag" 是唯一不靠主观判断的边界。
- **多 Eagle API 版本支持（V1 + V2）**：grilling 拍板拒绝。V1 不支持 tagGroup 程序化维护，会让 M6 长出两套写入路径。MVP 用户已确认 Eagle ≥ 4.0 Build 23。

## 退出条件

若未来出现以下任一情况，重新评估：

- TripClipper 进入多用户 / 客户场景，新用户反馈 `tc:edit_candidate_status:excluded` 这类 tag 名难理解
- 用户反馈"打开 Eagle 后总要花时间筛 / 配 smart folder 才能进入工作状态"，希望 M6 内置默认视图
- Eagle 客户端的 smart folder / tag group 能力出现重大变化，需要 M6 端配合调整命名

## 关联文档

- M6 spec：本 ADR 决定的形状会落到 [docs/specs/M6-eagle-sync/spec.md](../specs/M6-eagle-sync/spec.md)
- 默认 mapping 配置：[src/tripclipper/templates/eagle_mapping.default.yaml](../../src/tripclipper/templates/eagle_mapping.default.yaml)（实现时创建）
- 防重复导入优化：[docs/todolist.md §Eagle 同步防重复导入](../todolist.md)
