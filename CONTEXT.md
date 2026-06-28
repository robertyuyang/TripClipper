# TripClipper 项目术语与领域语言

> 本文件是 TripClipper 跨模块共享的术语事实源。所有 spec / ADR / 代码注释 /
> 用户文案在引用以下术语时必须使用此处定义。术语新增或语义调整需同步更新本文。

## 三阶段产出模型（用户视角）

TripClipper 把"从一堆原始素材到一份可剪辑清单"分成三段连续阶段，每段对应不同的产出字段，不可互相替代：

### 1. 素材自身质量（Stage 2 / M3 产出）

- **`rating`**（1–5 整数）：素材**自身**的绝对画面质量评分。
  评分基准是「画面构图、主体清晰度、人物表情、光线、抖动、信息量」等**单素材内可判断**的维度。
  与其他素材**完全无关**——单独看一条素材就能给一个 rating。
  由 M3 真实模型分析得出，写入 `Asset.rating`。

- **关键纪律**：rating **不**因为"组内有更好的"而下调，**不**因为"已经被组主选了"而上调。
  即 12 条都值 5 星的海边日落都应该是 5 星，rating 字段不参与去重决策。

### 2. 雷同组内相对选择（M4 产出）

- **雷同素材组（Similar Group）**：一组在物理时间相邻、画面/主体相似、构图相近的素材集合。
  其作用是：①候选池去重的最小单位；②UI 展示时的折叠单位（review.html / Eagle 备注 / summary.md 都按组展示）。
  数据契约里以 `SimilarGroup` 表示，组 ID 写入每个组员的 `Asset.similar_group_id`。

- **`similar_selection`**（枚举：`primary` / `alternate` / `rejected` / `needs_review` / `none`）：素材在**所在雷同组内**的相对选择。
  - `primary`：组主选，候选池默认入选
  - `alternate`：组备选（仍然 4/5 星，仅为了去重而退居二线）
  - `rejected`：组内明显较差（构图破损/主体被遮挡/严重抖动）
  - `needs_review`：组级仲裁置信度不足，主选无法稳定决定
  - `none`：不在任何雷同组

- **`similar_rank`**（int）：组内顺序编号；`primary=1`，按 `alternate → rejected → needs_review` 递增。

- **`similar_reason`**（中文）：模型对该素材**为何被划入该 selection** 的相对判断（不是组总评）。

- **关键纪律**：组内选择**只在同组内有意义**，跨组比较无意义。两组的 primary 不是"全局最佳"，只是"各自组内最佳"。

### 3. 全局候选池入选状态（M4 产出）

- **默认剪辑候选池（Default Candidate Pool）**：项目级"打开 Eagle 时默认展示的剪辑筛选集合"。
  组成 = 所有非雷同素材 + 所有高置信组的 `primary_asset_id`，再做"主体 × 景别"基础平衡。

- **`edit_candidate_status`**（枚举：`default_selected` / `alternate` / `excluded` / `needs_review`）：素材在**全局候选池**的角色。
  - `default_selected`：默认入选（Eagle 主列表展示）
  - `alternate`：备选（Eagle 折叠在雷同组下展示）
  - `excluded`：不参与默认候选（rating 太低 / 组内 rejected / 平衡修剪命中）
  - `needs_review`：分析或仲裁置信度不足，需用户手动决定

- **`edit_candidate_priority`**（int）：候选池内排序权重；用于 UI 默认排序。

- **`edit_candidate_reason`**（中文）：该素材**为何获得当前 status** 的全局解释（"非雷同高星" / "海边日落组主选" / "为景别平衡入选 alternate"等）。

### 三者关系示例

> 海边日落连拍 12 条全是 5 星：
> - 12 条都 `rating=5`（M3 给的，单看每条都值 5）
> - M4 把它们聚成同一个 `SimilarGroup`，1 条 `similar_selection=primary`，11 条 `similar_selection=alternate`
> - 候选池里只有那 1 条 `primary` 是 `edit_candidate_status=default_selected`，其余 11 条 `edit_candidate_status=alternate`

这三个字段**正交**——任意一个都不能从其他两个推断。

## 阶段流水线（命令视角）

```
init → scan → sample → full → cluster → export → sync-eagle
 M1     M2     M3       M3      M4         M5       M6
```

- `init`（M1）：从 `project.yaml` 创建项目目录与 `cut_index.json` 骨架。
- `scan`（M2）：本地扫描素材文件，写入 `Asset` 基础字段、缩略图、关键帧。
- `sample`（M3）：分层抽样（默认 25 条）真实模型分析，验证设置。
- `full`（M3）：全量真实模型分析。
- `cluster`（**M4**）：本地启发式聚组 + 组级 LLM 仲裁 + 候选池生成。
- `export`（M5）：导出 review.html / CSV / summary.md。
- `sync-eagle`（M6）：dry-run 预览 / apply 写回 Eagle 备注。

`tripclipper run <slug>` 一键编排 scan → sample → full → cluster（M4 后扩展）。

## 关键架构决策（参见 [docs/adr/](./docs/adr/)）

- **ADR-001**：M4 雷同主选挑选采用「本地启发式聚组 + 组级 LLM 仲裁」组合方案。
- **ADR-002**：M4 默认候选池采用确定性后处理（零 LLM），不为候选池本身打模型。

## 数据契约口径

所有字段的官方定义在 [`docs/specs/M0-data-contract/spec.md`](./docs/specs/M0-data-contract/spec.md) 与 [`src/tripclipper/models.py`](./src/tripclipper/models.py)。
本文件只定义术语与跨模块共识，不重复定义字段类型/枚举值。
