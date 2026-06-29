"""Group-level LLM arbitration for TripClipper M4 similar-clustering.

A single ``Arbiter.arbitrate`` call decides ``primary``/``alternate``/
``rejected`` for one candidate group of near-duplicate assets. Input is the
group's thumbnails plus minimal text anchors; output is a defensively-parsed
:class:`ArbitrationResult` consumed by ``cluster_runner``.
"""

from __future__ import annotations

import json
import os
import random
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

from .config import EditingIntent, ModelConfig
from .models import Asset
from .provider import (
    _image_data_url,
    _render_editing_intent_block,
    _should_retry,
    _strip_code_fence,
)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_DEFAULT_TIMEOUT_S = 60.0
_MAX_RETRIES = 1            # 共 2 次尝试（spec Q16）
_RETRY_BACKOFFS = (1.0,)    # 重试前等 1s + 抖动
_TRANSIENT_HTTP = {429, 500, 502, 503, 504}

_BASIS_ENUM = {
    "同一景点", "同一动作", "相近构图", "相近画面内容", "相近声音内容",
}
_CONFIDENCE_FLOOR = 0.6


_ARBITER_SYSTEM_PROMPT_TEMPLATE = """你是一名严谨的旅拍素材剪辑助理，正在做"雷同素材组的组级仲裁"：在一组互为近重复的候选素材里，挑出 1 条 primary，给出 alternate 与 rejected。

## 输出契约（必须严格遵守）

1. 你的回复必须是**单一的、合法的 JSON 对象**，且仅包含该 JSON 对象本身。
   - 禁止在 JSON 前后输出任何散文、问候语、解释、提示语。
   - 禁止使用 markdown 代码栅（``` 或 ```json）。
   - 禁止输出多个 JSON 对象或 JSON 数组顶层包裹。

2. JSON 对象必须包含以下字段：
   - `primary_asset_id`：string 或 null。当置信度不足以稳定决定主选时，必须输出 `null`。
   - `alternate_asset_ids`：string 数组。备选素材 id；**不得**包含 `primary_asset_id`。
   - `rejected_asset_ids`：string 数组。建议舍弃的素材 id。
   - `confidence`：浮点数，范围 [0, 1]，代表整体仲裁置信度。
   - `basis`：string 数组，**只能从**以下五项中选取：
     `["同一景点", "同一动作", "相近构图", "相近画面内容", "相近声音内容"]`。
   - `reason_by_asset`：对象（dict）。key 是素材的 `asset_id`，value 是中文短句（≤ 30 字），
     描述该素材在组内**相对于其他成员**的判断依据（例如"构图最完整"、"轻微抖动"、"主体被遮挡"）。

3. 中文强制：`reason_by_asset` 的所有 value 必须使用中文；`basis` 元素也必须是上述中文枚举之一。
   `asset_id` 字段保持原样字符串，不要翻译或改写。

## 评估维度（参考 PRD §6.2，按需综合权衡）

- 构图完整度：主体是否被裁切、画面留白是否合理
- 人物表情自然度：是否抓拍到合适的瞬间
- 主体清晰度：对焦、锐度、是否被遮挡
- 动作完整度：动作是否被截断在错误的时刻
- 抖动 / 帧间稳定性
- 光线：曝光、白平衡、阴影
- 信息量：画面承载的故事/环境线索
- 与剪辑意图的契合度
- 镜头景别：景别选择是否服务于该镜头的叙事作用
- 场景代表性：能否独立代表该雷同组的场景
{editing_intent_block}
## 置信度与判定纪律

- 当组内最佳素材在多数维度上明显胜出 → 高置信度（≥ 0.8）。
- 当多条素材在不同维度互有胜负、难以稳定排序 → 低置信度（< 0.6），输出 `primary_asset_id: null`。
- 置信度低于 0.6 或主选无法稳定决定时，**必须**输出 `primary_asset_id: null`，
  并把所有素材根据相对优劣分布到 `alternate_asset_ids` / `rejected_asset_ids`，理由写进 `reason_by_asset`。

再次强调：只输出 JSON 对象本身，不要任何其他内容。"""


# ---------------------------------------------------------------------------
# Public exception & dataclass
# ---------------------------------------------------------------------------


class ArbiterError(Exception):
    """Arbiter 构造失败或调用失败（含瞬时/非瞬时分类）。"""

    def __init__(self, message: str, *, transient: bool = False) -> None:
        super().__init__(message)
        self.transient = transient


@dataclass
class ArbitrationResult:
    """组级仲裁结果，由 :func:`_parse_arbitration` 产出。"""

    primary_asset_id: Optional[str] = None
    alternate_asset_ids: list[str] = field(default_factory=list)
    rejected_asset_ids: list[str] = field(default_factory=list)
    confidence: float = 0.0
    basis: list[str] = field(default_factory=list)
    reason_by_asset: dict[str, str] = field(default_factory=dict)
    needs_review: bool = False


# ---------------------------------------------------------------------------
# Arbiter class
# ---------------------------------------------------------------------------


class Arbiter:
    """组级 LLM 仲裁器；单次模型调用决定一个候选组的主选/备选/弃选。

    构造期完成所有不需要网络的预校验：

    1. ``config.is_usable() == False`` → :class:`ArbiterError`
       (``transient=False``)。
    2. ``os.environ[config.api_key_env]`` 为空 → :class:`ArbiterError`
       (``transient=False``)。
    3. 渲染 ``self._system_prompt`` 一次（沿用 M3 Q19 的 editing_intent 渲染规则）。
    4. 持有 per-instance :class:`httpx.Client`（线程不安全，若并发需每线程独立 Arbiter）。
    """

    def __init__(self, config: ModelConfig, editing_intent: EditingIntent) -> None:
        if not config.is_usable():
            raise ArbiterError(
                "ModelConfig 不可用：provider/base_url/api_key_env/vision_model 必须齐全",
                transient=False,
            )

        api_key_env = config.api_key_env or ""
        api_key = os.environ.get(api_key_env, "")
        if not api_key:
            raise ArbiterError(
                f"环境变量 {api_key_env} 未设置",
                transient=False,
            )

        self._config = config
        self._api_key = api_key
        self._base_url = (config.base_url or "").rstrip("/")
        self._vision_model = config.vision_model
        self._system_prompt = self._render_system_prompt(editing_intent)
        self._client = httpx.Client(timeout=_DEFAULT_TIMEOUT_S)

    # ------------------------------------------------------------------ public

    def arbitrate(self, group_assets: list[Asset]) -> ArbitrationResult:
        """对一组候选素材跑一次组级仲裁，返回 :class:`ArbitrationResult`。

        - 缩略图与文本 anchor 一并送入。
        - 重试 1 次（共 2 次尝试，spec Q16）；瞬时错误重试，非瞬时直接抛。
        - 不会修改 ``group_assets``。
        """
        valid_asset_ids = {a.asset_id for a in group_assets if a.asset_id}

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": _build_group_user_content(group_assets)},
        ]
        url = f"{self._base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._vision_model,
            "messages": messages,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }

        last_exc: Optional[BaseException] = None
        last_status: Optional[int] = None
        last_body: str = ""
        for attempt in range(1, _MAX_RETRIES + 2):  # 1, 2
            try:
                resp = self._client.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=_DEFAULT_TIMEOUT_S,
                )
            except httpx.TimeoutException as exc:
                last_exc = exc
                if attempt <= _MAX_RETRIES and _should_retry(exc):
                    _sleep_backoff(attempt)
                    continue
                raise ArbiterError(
                    f"ArbiterTimeoutError: {_DEFAULT_TIMEOUT_S}s × {attempt} 次",
                    transient=True,
                ) from exc
            except httpx.NetworkError as exc:
                last_exc = exc
                if attempt <= _MAX_RETRIES and _should_retry(exc):
                    _sleep_backoff(attempt)
                    continue
                raise ArbiterError(
                    f"ArbiterNetworkError: {type(exc).__name__}",
                    transient=True,
                ) from exc

            status = resp.status_code
            if status != 200:
                last_status = status
                last_body = resp.text[:200] if resp.text else ""
                if _should_retry(status) and attempt <= _MAX_RETRIES:
                    _sleep_backoff(attempt)
                    continue
                raise ArbiterError(
                    f"HTTP {status}: {last_body}",
                    transient=status in _TRANSIENT_HTTP,
                )

            try:
                data = resp.json()
            except ValueError as exc:
                raise ArbiterError(
                    f"响应不是合法 JSON: {type(exc).__name__}",
                    transient=False,
                ) from exc

            try:
                content = data["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError) as exc:
                raise ArbiterError(
                    f"响应缺少 choices[0].message.content: {type(exc).__name__}",
                    transient=False,
                ) from exc

            if not isinstance(content, str):
                raise ArbiterError(
                    "响应 content 非字符串",
                    transient=False,
                )

            return _parse_arbitration(content, valid_asset_ids)

        # 防御性兜底。
        raise ArbiterError(
            f"重试耗尽（最后状态 {last_status}）: {type(last_exc).__name__ if last_exc else 'unknown'}",
            transient=True,
        )

    # ----------------------------------------------------------------- helpers

    @staticmethod
    def _render_system_prompt(editing_intent: EditingIntent) -> str:
        block = _render_editing_intent_block(editing_intent)
        return _ARBITER_SYSTEM_PROMPT_TEMPLATE.format(editing_intent_block=block)


# ---------------------------------------------------------------------------
# Pure module-level functions
# ---------------------------------------------------------------------------


def _build_group_user_content(group_assets: list[Asset]) -> list[dict[str, Any]]:
    """Construct the OpenAI-compatible ``user`` content list for one group.

    形式：
    - 一个汇总 text block 描述任务；
    - 每条素材一个 ``image_url`` block + 一个 text anchor（``asset_id=... rating=... subject_type=...``），
      让模型把图与 id 对齐；
    - 末尾一个 text block，强调按系统指令输出单一 JSON。

    无 ``thumbnail_path`` 的素材跳过 image，只发 text anchor，避免漏 id。
    """
    n = len(group_assets)
    content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": f"以下是 {n} 条候选雷同素材，请综合所有缩略图与文本元数据完成组级仲裁。",
        }
    ]

    for asset in group_assets:
        if asset.thumbnail_path:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": _image_data_url(asset.thumbnail_path)},
                }
            )
        anchor = _format_asset_anchor(asset)
        content.append({"type": "text", "text": anchor})

    content.append(
        {
            "type": "text",
            "text": "请按系统指令输出单一 JSON 对象。",
        }
    )
    return content


def _format_asset_anchor(asset: Asset) -> str:
    """``asset_id=xxx rating=4 subject_type=people`` 形式的 anchor 文本。"""
    asset_id = asset.asset_id or "<未知>"
    rating = asset.rating if asset.rating is not None else "<未评分>"
    subject_type = asset.subject_type.value if asset.subject_type else "<未知>"
    return f"asset_id={asset_id} rating={rating} subject_type={subject_type}"


# ---- response parsing ------------------------------------------------------


def _parse_arbitration(text: str, valid_asset_ids: set[str]) -> ArbitrationResult:
    """Parse a model response string into an :class:`ArbitrationResult`.

    纯函数，独立可测。规则见 spec Q5/Q16/Q18 与本模块顶部约束。
    """
    stripped = _strip_code_fence(text)
    try:
        payload = json.loads(stripped)
    except (json.JSONDecodeError, ValueError) as exc:
        snippet = stripped[:200]
        raise ArbiterError(
            f"非法 JSON: {exc}; 内容前 200 字符: {snippet}",
            transient=False,
        ) from exc

    if not isinstance(payload, dict):
        raise ArbiterError(
            f"非法 JSON: 顶层期望 object，实际为 {type(payload).__name__}",
            transient=False,
        )

    needs_review = False

    # primary_asset_id：string 或 None；不在 valid_asset_ids → 设为 None 且 needs_review。
    raw_primary = payload.get("primary_asset_id")
    primary_asset_id: Optional[str]
    if raw_primary is None:
        primary_asset_id = None
        needs_review = True
    elif isinstance(raw_primary, str) and raw_primary in valid_asset_ids:
        primary_asset_id = raw_primary
    else:
        primary_asset_id = None
        needs_review = True

    # alternate / rejected：list[str]，过滤掉不在 valid_asset_ids 的；非 list → []。
    raw_alternate = payload.get("alternate_asset_ids")
    if isinstance(raw_alternate, list):
        filtered_alternate = [
            item for item in raw_alternate
            if isinstance(item, str) and item in valid_asset_ids
        ]
        if len(filtered_alternate) != len([
            item for item in raw_alternate if isinstance(item, str)
        ]):
            needs_review = True
    else:
        filtered_alternate = []

    raw_rejected = payload.get("rejected_asset_ids")
    if isinstance(raw_rejected, list):
        filtered_rejected = [
            item for item in raw_rejected
            if isinstance(item, str) and item in valid_asset_ids
        ]
        if len(filtered_rejected) != len([
            item for item in raw_rejected if isinstance(item, str)
        ]):
            needs_review = True
    else:
        filtered_rejected = []

    # 防御：primary 不应出现在 alternate / rejected 列表中。
    if primary_asset_id is not None:
        filtered_alternate = [
            item for item in filtered_alternate if item != primary_asset_id
        ]
        filtered_rejected = [
            item for item in filtered_rejected if item != primary_asset_id
        ]

    # confidence：必须是 number 且 [0,1]；缺失/非法 → 0.0 + needs_review。
    raw_confidence = payload.get("confidence")
    confidence: float
    if isinstance(raw_confidence, bool):
        confidence = 0.0
        needs_review = True
    elif isinstance(raw_confidence, (int, float)):
        c = float(raw_confidence)
        if 0.0 <= c <= 1.0:
            confidence = c
        else:
            confidence = 0.0
            needs_review = True
    else:
        confidence = 0.0
        needs_review = True

    if confidence < _CONFIDENCE_FLOOR:
        needs_review = True

    # basis：list[str]，过滤掉不在 _BASIS_ENUM 的元素；过滤后空 → needs_review。
    raw_basis = payload.get("basis")
    if isinstance(raw_basis, list):
        filtered_basis = [
            item for item in raw_basis
            if isinstance(item, str) and item in _BASIS_ENUM
        ]
    else:
        filtered_basis = []
    if not filtered_basis:
        needs_review = True

    # reason_by_asset：dict[str,str]，过滤掉 key 不在 valid_asset_ids 的；非 dict → {}。
    raw_reason = payload.get("reason_by_asset")
    if isinstance(raw_reason, dict):
        reason_by_asset = {
            k: v
            for k, v in raw_reason.items()
            if isinstance(k, str) and k in valid_asset_ids and isinstance(v, str)
        }
    else:
        reason_by_asset = {}

    if primary_asset_id is None:
        needs_review = True

    return ArbitrationResult(
        primary_asset_id=primary_asset_id,
        alternate_asset_ids=filtered_alternate,
        rejected_asset_ids=filtered_rejected,
        confidence=confidence,
        basis=filtered_basis,
        reason_by_asset=reason_by_asset,
        needs_review=needs_review,
    )


# ---- retry / backoff -------------------------------------------------------


def _sleep_backoff(attempt: int) -> None:
    """Sleep ``_RETRY_BACKOFFS[attempt - 1] + uniform(0, 1)`` seconds."""
    base = _RETRY_BACKOFFS[attempt - 1]
    time.sleep(base + random.uniform(0, 1))


__all__ = ["Arbiter", "ArbiterError", "ArbitrationResult"]
