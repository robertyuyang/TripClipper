# ADR-001: M4 雷同主选挑选采用「本地启发式聚组 + 组级 LLM 仲裁」组合方案

- 状态：已采纳（grilling 拍板于 2026-06-28）
- 关联：M4 spec §雷同分组、CONTEXT.md §雷同素材组
- 相关需求：PRD FR-6（[docs/mvp-product-requirements.md L734-L780](../mvp-product-requirements.md)）；TD 8

## 上下文

M3 已经为每条素材产出 `rating` / `summary` / `tags` / `subject_type` / `primary_subject`
 / `shot_scale` / `shot_function` / `audio_strategy` 等字段。M4 要在这些字段之上完成两件事：
**①把雷同素材聚成组**；**②为每组挑出"主选"**。PRD FR-6 把主选判断维度列得很全：
画面稳定性、构图、主体清晰度、人物表情、动作完整度、光线曝光、遮挡、模糊、抖动、声音可用性、信息量、剪辑意图。

可选路径：

- **路径 A — 纯本地启发式**：用 M3 已有字段做规则聚类，主选直接按 `rating` desc。
  零额外 LLM 调用，但 FR-6 列的 10+ 主选维度里**纯规则只覆盖 `rating` 一项**，
  其余维度（构图/表情/光线/抖动）M3 没单独写字段，规则拿不到信号。
- **路径 B — 本地聚组 + 组级 LLM 仲裁**：本地启发式先聚出候选组（>1 个素材的组），
  每组发一次额外 LLM 调用，把该组缩略图打包丢给视觉模型，让它直接判定 primary/alternate/rejected。
- **路径 C — 嵌入向量 + 聚类**：用 embedding 模型把 `summary` + `tags` 算向量做 HAC/DBSCAN。
  引入新模型类别、聚类调参复杂，且仍不覆盖"画面稳定性"等图像维度。

## 决策

**采用路径 B**。

具体形态：
- 本地启发式聚组：双轨规则——「modified_time ≤60s + subject_type 一致」**或**
  「subject_type + shot_scale 一致且 (`primary_subject` 2-gram Jaccard ≥0.6 或 tags Jaccard ≥0.5)」。
  传递性走并查集（A 与 B 相似、B 与 C 相似 → A、B、C 同组）。
- 组级 LLM 仲裁：单组最多 12 条素材入仲裁（超过取 rating Top12，其余按 rating 标 alternate）；
  每条只送缩略图；模型一次返回 `primary_asset_id` / `alternate_asset_ids` / `rejected_asset_ids` /
  `confidence` / `basis` / `reason`；`confidence<0.6` 时整组标 `needs_review`。
- 仲裁失败处理：与 M3 同纪律——可重试错误重试一次（指数退避），仍失败则整组 `needs_review`、
  `arbitration_failures += 1`，**其他组继续**。
- `editing_intent` 不在本地后处理时手工加权，而是在 Arbiter system prompt 中拼接传给 LLM。

## 理由

1. **FR-6 主选判断维度覆盖**：路径 A 只覆盖 `rating` 1 个维度，路径 B 通过缩略图覆盖
   画面稳定性、构图、主体清晰度、表情、光线、遮挡 6 个维度（抖动仅在缩略图上无法判定，作为已知近似）。
2. **与 M3 纪律一致**：M3 立下"严格只打真模型、不许伪造分析结果"。如果 M4 用规则伪造主选挑选理由
   （比如 "组内 rating 最高且 modified_time 最早"），与 M3 立的纪律自相矛盾。
3. **成本可接受**：典型 25 个素材项目，M3 调用 25 次单素材分析；M4 聚出 5-10 个组，
   每组 1 次组级调用，单次输入 12 张缩略图 vs M3 单素材 4 张图，总成本约 M3 的 60%，
   全链路成本约 1.6 × M3，一杯咖啡的 1/100。
4. **可逆性高**：`arbiter.py` 是孤立模块，未来若想退回纯规则只需把组级仲裁替换为
   `primary = max(group, key=rating)`，~10 行改动。

## 后果

### 正面

- M4 产出的 `similar_reason` 是真实自然语言（"asset_xxx 人物回头与夕阳同框、表情完整；
  asset_yyy 表情自然但人物偏离三分点"），不是模板。
- 候选池起始集中的"组主选"具备 FR-6 描述的判断依据，候选池本身的设计意图（"不是 rating Top N"）
  才真正成立。
- review.html / Eagle 备注里"为什么我是 alternate"的解释能让用户信服。

### 负面

- M4 测试套件与 M3 同纪律——绑定到 cherryin/Gemini 真模型，无法离线 / CI 跑。
- 每次 cluster 多支付 5-10 次 LLM 调用（典型项目）；用户重跑 cluster 时清空旧分组重新打钱。
- 抖动维度仍不覆盖（缩略图判定有限），写入 spec "已知近似" 段。

## 替代方案及拒绝原因

- **路径 A（纯本地）**：覆盖度不够，与 M3 纪律冲突，已在 grilling Q1 拒绝。
- **路径 C（embedding）**：引入新模型类别 + 聚类调参，复杂度不划算，且仍不覆盖图像维度。

## 退出条件

若未来一个月内用户反馈以下任一情况，重新评估本决策：
- 组级仲裁的 `similar_reason` 质量不达预期（机械、错位、与 primary 选择不符）；
- 模型调用成本对单次 cluster 变得不可接受（典型项目>200 次组级调用）；
- 用户明确表示愿意接受 rating-only 的 primary 挑选以换取离线运行。
