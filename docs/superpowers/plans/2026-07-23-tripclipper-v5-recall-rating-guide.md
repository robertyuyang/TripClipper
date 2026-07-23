# TripClipper 接入 V5 召回版评分规则实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 TripClipper 正式视觉分析固定使用已经完成 45 条实验和人工复核的 V5 召回版评分规则。

**Architecture:** 新建独立的生产评分规则模块，`Provider` 在正式调用方未注入实验规则时使用该常量。保留现有 `rating_guide` 注入接口供 `rating-lab` 做 A/B 实验，但 TripClipper CLI 不提供 Prompt 选择参数，也不在运行时读取 `rating-lab` 文件。

**Tech Stack:** Python 3.10+、pytest、TripClipper `Provider`

## Global Constraints

- TripClipper 正式流程不增加选择 Prompt 的命令行参数。
- 正式代码固定使用 V5 召回版评分规则。
- `rating-lab` 继续保留 `--rating-guide`，用于独立运行历史版和候选版实验。
- V5 三份历史 Prompt 均不修改、不删除。
- 不修改或重跑任何现有项目的 `cut_index.json`。
- 不针对单个雨衣案例增加新规则。
- `src/tripclipper/provider.py` 和 `tests/test_provider.py` 当前已有未提交的实验规则注入改动；实施时保留这些改动，不覆盖、不回退。

---

## 文件结构

- 创建 `src/tripclipper/rating_guide.py`：只保存 TripClipper 正式评分规则常量。
- 修改 `src/tripclipper/provider.py`：删除本文件中的五行旧默认规则，导入并使用生产评分规则。
- 修改 `tests/test_provider.py`：验证生产规则内容、默认渲染和实验覆盖行为。
- 修改 `README.md`：记录正式 Prompt 固定在代码中，实验 Prompt 仍由 `rating-lab` 管理。

### Task 1: 生产评分规则及 Provider 默认行为

**Files:**
- Create: `src/tripclipper/rating_guide.py`
- Modify: `src/tripclipper/provider.py:35-65`
- Modify: `tests/test_provider.py:19-40, 400-480`

**Interfaces:**
- Produces: `tripclipper.rating_guide.PRODUCTION_RATING_GUIDE: str`
- Consumes: `Provider._render_system_prompt(editing_intent, rating_guide=None) -> str`
- Preserves: `Provider(..., rating_guide=<实验规则>)` 覆盖生产规则的能力

- [ ] **Step 1: 写生产规则和默认行为的失败测试**

在 `tests/test_provider.py` 的导入区加入：

```python
from tripclipper.rating_guide import PRODUCTION_RATING_GUIDE
```

在现有 Prompt 渲染测试后加入：

```python
def test_production_rating_guide_is_v5_recall() -> None:
    assert "v5-recall：优先避免遗漏真实高光" in PRODUCTION_RATING_GUIDE
    assert "素材总评分必须等于最佳片段的评分" in PRODUCTION_RATING_GUIDE
    assert "局部高光不因占素材比例小而降级" in PRODUCTION_RATING_GUIDE
    assert "主体过小、处于边缘或构图意图不清时，最高 3 星" in (
        PRODUCTION_RATING_GUIDE
    )
    assert "持续且非叙事性的倾斜导致观看明显不自然时，最高 2 星" in (
        PRODUCTION_RATING_GUIDE
    )
    assert "一个足够强且清楚可见的趣味细节" in PRODUCTION_RATING_GUIDE
    assert "不得编造关键帧没有提供的动作" in PRODUCTION_RATING_GUIDE


def test_render_system_prompt_uses_production_rating_guide_by_default() -> None:
    prompt = Provider._render_system_prompt(EditingIntent())

    assert PRODUCTION_RATING_GUIDE in prompt
    assert "构图佳、叙事价值高、可作为成片主轴或高光" not in prompt
```

- [ ] **Step 2: 运行测试并确认按预期失败**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/test_provider.py::test_production_rating_guide_is_v5_recall \
  tests/test_provider.py::test_render_system_prompt_uses_production_rating_guide_by_default
```

Expected: collection 阶段因 `tripclipper.rating_guide` 不存在而失败。

- [ ] **Step 3: 新增生产评分规则模块**

创建 `src/tripclipper/rating_guide.py`，内容如下：

```python
"""TripClipper 正式视觉评分规则。"""

from __future__ import annotations

PRODUCTION_RATING_GUIDE = """## v5-recall：优先避免遗漏真实高光

本版本允许一个足够强的可见高光支持高分，但不放宽事实依据。

## 核心契约：只给最佳片段打分

先检查全部可见关键帧，找出 0–3 个可独立剪入成片的连续候选片段，再选择最佳片段。

素材总评分必须等于最佳片段的评分：

`rating == clip_suggestions[0].rating`

- 局部高光不因占素材比例小而降级。
- 不评价整段平均质量。
- 最佳片段之外的问题不拖低总评分。
- 无值得保留的片段时输出 `rating: 1` 和空片段列表。

## 强制观察顺序

1. 定位具体 `in` / `out`。
2. 描述实际看到的主体、位置、大小、动作、表情、小细节、空间、光线或变化。
3. 检查主体显著性。
4. 主动检查短暂但清楚的趣味动作、人物反应和少见运镜。
5. 检查技术问题。
6. 按门槛评分；不得因为高光持续短就自动降级。

## 正向证据

- 视觉：特殊光线、明确色彩、空间层次、视觉尺度或有明确结果的少见运镜。
- 人物：真实反应、自然互动、有记忆点的姿态、趣味动作或清楚可见的小细节。
- 动作：动作峰值、完整过程、速度变化或明确结果。
- 叙事：出发、抵达、准备、庆祝、关键反应、阶段变化或收尾。

少见运镜必须揭示新内容或形成明确空间变化。普通移动、旋转或平稳本身不算高光。

## 主体显著性与构图

- 主体过小、处于边缘或构图意图不清时，最高 3 星。
- 主体理解明显受阻时，最高 2 星。
- 不能因为知道场景类型就假设小主体具有高光价值。

## 技术问题与横竖版

- 持续且非叙事性的倾斜导致观看明显不自然时，最高 2 星。
- 合理旋转运镜、短暂转动、轻微手持感不降级。
- 横竖方向本身不决定评分；只有项目明确限制时才考虑适配。

## 5 星：强局部高光

满足技术可用和合法时间范围后，一个特别强、清楚可见的局部高光可以支持 5 星，例如关键人物反应、罕见趣味时刻、动作峰值或具有明显视觉结果的特殊运镜。

必须说明适合高潮、关键反应、音乐重拍、慢动作、情绪停留或重点展示中的哪一种处理，不能只使用抽象形容词。

## 4 星：大概率入片

满足技术可用和合法时间范围后，以下任一项足够强且清楚可见时即可成立：

- 一个足够强且清楚可见的趣味细节、人物反应或互动。
- 一次少见且有明确视觉结果的旋转、推进或空间揭示。
- 清楚的动作阶段、事件变化或叙事节点。
- 一项具有明显区分度的视觉证据。

## 3 星：需要人工复核

存在潜在价值，但证据强度、主体显著性、时间范围或最终用途不够确定。高光疑似存在但关键帧不足以确认时评 3 星。

## 2 星：低优先级备用

只有普通补画面价值，缺少清楚主体状态和事件；或存在持续倾斜、主体理解困难等问题。内容意义不明、只能给出泛化用途时最高 2 星。

## 1 星：舍弃

没有可靠可用片段，或画面与内容无法支持实际剪辑用途。

## 防止错误升降级

- 不放宽事实依据和时间范围要求。
- “可作过场”“镜头平稳”“有氛围”本身不是高分证据。
- 不得忽略短暂但清楚的趣味动作、人物反应或小细节。
- 不得把普通移动误写成少见运镜。
- 不得把持续不自然倾斜解释成普通手持感。
- 不考虑其他素材的重复性、稀缺性或组内排名。

## 输出证据要求

- `summary` 必须写出最佳片段的可见事实、主体显著性、强证据、建议处理和真实限制。
- `clip_suggestions[0].rating` 必须等于素材总 `rating`。
- 片段按评分从高到低排列。
- 不得编造关键帧没有提供的动作、情绪、对白、细节或时间范围。
"""
```

- [ ] **Step 4: 让 Provider 使用生产评分规则**

在 `src/tripclipper/provider.py` 的本地模块导入区加入：

```python
from .rating_guide import PRODUCTION_RATING_GUIDE
```

删除 `provider.py` 内的 `_DEFAULT_RATING_GUIDE` 五行旧规则，并把
`_render_system_prompt()` 中的回退值改成：

```python
return _SYSTEM_PROMPT_TEMPLATE.format(
    editing_intent_block=block,
    rating_guide=rating_guide or PRODUCTION_RATING_GUIDE,
)
```

不修改现有 `rating_guide: Optional[str] = None` 参数及其实验覆盖语义。

- [ ] **Step 5: 运行 Provider 测试并确认通过**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_provider.py
```

Expected: 全部通过，无失败。

- [ ] **Step 6: 验证生产规则与已冻结的实验文件完全一致**

Run:

```bash
.venv/bin/python -c 'from pathlib import Path; from tripclipper.rating_guide import PRODUCTION_RATING_GUIDE; expected=Path("rating-lab/prompts/single-highlight-v5-recall.txt").read_text(encoding="utf-8").strip(); assert PRODUCTION_RATING_GUIDE.strip()==expected; print("生产评分规则与V5召回版一致")'
```

Expected:

```text
生产评分规则与V5召回版一致
```

- [ ] **Step 7: 提交生产规则和 Provider 改动**

提交前检查 `provider.py` 和 `test_provider.py` 的完整差异，确认保留当前工作区已有的实验注入改动：

```bash
git diff -- src/tripclipper/provider.py tests/test_provider.py
```

然后提交：

```bash
git add src/tripclipper/rating_guide.py src/tripclipper/provider.py tests/test_provider.py
git commit -m "feat: 接入v5召回版正式评分规则"
```

### Task 2: 文档与全量回归验证

**Files:**
- Modify: `README.md`
- Verify: `rating-lab/prompts/single-highlight-v5-balanced.txt`
- Verify: `rating-lab/prompts/single-highlight-v5-conservative.txt`
- Verify: `rating-lab/prompts/single-highlight-v5-recall.txt`

**Interfaces:**
- Consumes: `tripclipper.rating_guide.PRODUCTION_RATING_GUIDE`
- Produces: 面向使用者的生产与实验边界说明

- [ ] **Step 1: 更新 README**

在 README 的模型分析说明附近加入：

```markdown
### 正式评分规则

TripClipper 正式视觉分析固定使用代码中的 V5 召回版评分规则，不提供运行时
Prompt 选择参数。`rating-lab/prompts/` 保存历史版和候选版，实验运行可通过
`rating-lab/cli.py run --rating-guide` 显式选择，但不会自动影响正式流程。
```

- [ ] **Step 2: 运行完整相关测试**

Run:

```bash
.venv/bin/python -m pytest -q rating-lab/tests tests/test_provider.py tests/test_analyzer.py
```

Expected: 全部通过，无失败。

- [ ] **Step 3: 运行编译与边界检查**

Run:

```bash
.venv/bin/python -m compileall -q \
  src/tripclipper/rating_guide.py \
  src/tripclipper/provider.py
git diff --exit-code HEAD -- \
  rating-lab/prompts/single-highlight-v5-balanced.txt \
  rating-lab/prompts/single-highlight-v5-conservative.txt \
  rating-lab/prompts/single-highlight-v5-recall.txt
rg -n -- '--rating-guide' src/tripclipper README.md
git diff --check
```

Expected:

- `compileall` 退出码为 0。
- 三份 V5 实验 Prompt 相对 `HEAD` 无变化。
- `src/tripclipper` 中没有 `--rating-guide`；README 只在实验边界说明中出现一次。
- `git diff --check` 无输出。

- [ ] **Step 4: 提交文档**

```bash
git add README.md
git commit -m "docs: 说明正式评分规则来源"
```

- [ ] **Step 5: 核对最终提交范围**

Run:

```bash
git status --short
git log -4 --oneline
```

Expected:

- 本任务涉及的 `rating_guide.py`、`provider.py`、`test_provider.py` 和 README 已提交。
- 用户原有的其他未提交修改仍保留。
- 不存在 `cut_index.json`、V5 实验 Prompt 或历史运行结果的新增改动。
