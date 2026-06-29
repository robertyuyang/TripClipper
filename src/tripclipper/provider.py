"""OpenAI-compatible vision provider for TripClipper Stage 2 analysis (M3).

This module is a thin wrapper around an OpenAI-compatible ``/chat/completions``
endpoint that takes a single :class:`Asset` and returns an
:class:`AnalysisResult`. It owns the system prompt template, the multimodal
``messages`` construction, the retry loop for transient errors, and the
response parser that defensively maps model output back onto the
:mod:`tripclipper.models` enums.

Scope guardrails (Q1/Q4/Q5/Q7/Q23):

- One public class, one public method (``analyze``): callers do not need to
  know whether the asset is a video, image or audio.
- The provider never mutates an :class:`Asset` directly. ``analyze`` produces
  an :class:`AnalysisResult`; :func:`apply_analysis` is a separate pure
  function that writes the validated result back onto the asset and flips its
  ``analysis_status`` to :attr:`AnalysisStatus.analyzed`.
- API key / Authorization header / full prompt text / model response content
  are never surfaced inside :class:`ProviderError` messages (sliced
  ``resp.text[:200]`` is the only exception, and the analyzer/logs layer
  re-applies :func:`security.redact_secrets` on top).
"""

from __future__ import annotations

import base64
import json
import os
import random
import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

from .config import EditingIntent, ModelConfig
from .models import (
    AnalysisStatus,
    Asset,
    AssetType,
    ClipSuggestion,
    PeoplePresence,
    ShotFunction,
    ShotScale,
    SubjectType,
    WarningItem,
)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_DEFAULT_TIMEOUT_S = 60.0
_MAX_RETRIES = 2  # 共 3 次尝试
_RETRY_BACKOFFS = (1.0, 4.0)  # 重试前等待 1s、4s（再 + 随机 0~1s 抖动）
_TRANSIENT_HTTP = {429, 500, 502, 503, 504}


_SYSTEM_PROMPT_TEMPLATE = """你是一名严谨的旅拍素材剪辑助理，负责对单个素材做画面层面的结构化判读。

## 输出契约（必须严格遵守）

1. 你的回复必须是**单一的、合法的 JSON 对象**，且仅包含该 JSON 对象本身。
   - 禁止在 JSON 前后输出任何散文、问候语、解释、提示语，例如"以下是结果"。
   - 禁止使用 markdown 代码栅（``` 或 ```json）。
   - 禁止输出多个 JSON 对象或 JSON 数组顶层包裹。

2. JSON 对象必须包含以下字段：
   - `summary`：中文一段话，1-3 句，概括画面内容与可用作。
   - `tags`：中文字符串数组，3-8 个标签，覆盖主体、动作、氛围、地点等关键词。
   - `rating`：整数 1-5，5 为最高，依据画面质量、构图、叙事价值打分。
   - `subject_type`：枚举之一 `landscape` / `people` / `people_landscape` / `food` / `building` / `activity` / `object` / `other`。
   - `primary_subject`：中文短词，描述画面里的核心主体（如"雪山"、"小孩"、"拉面"）。
   - `people_presence`：枚举之一 `none` / `single` / `multiple` / `small_group` / `crowd`。
   - `shot_scale`：枚举之一 `extreme_wide` / `wide` / `full` / `medium` / `close_up` / `extreme_close_up`。
   - `shot_function`：枚举之一 `establishing` / `highlight` / `transition` / `detail` / `reaction` / `dialogue` / `b_roll` / `other`。
   - `audio_strategy`：中文字符串，对该素材音频去留与处理的建议；若无明确建议可输出空字符串 `""`。
   - `clip_suggestions`：可选数组，0-3 个对象；每个对象包含：
     * `in`：起点时间码，形如 `HH:MM:SS` 或 `MM:SS` 或纯秒数字符串。
     * `out`：终点时间码，同上格式。
     * `role`：中文字符串，描述该片段在成片里的作用（如"开场镜头"、"高光"、"过场"）。
     * `reason`：中文字符串，为何这段值得保留。
     * `audio_strategy`：中文字符串，该片段的音频策略，可空字符串。
     * `subject_type`：该片段画面主体类型，枚举与 asset 级一致；不确定输出 `"other"`。
     * `shot_scale`：该片段镜头景别，枚举与 asset 级一致；不确定可省略。
     * `rating`：该片段质量打分，整数 1-5。
     * `tags`：中文字符串数组，3-6 个，描述该片段独有的关键词。
     若整段素材没有值得抽取的高光片段（废片 / 过场），输出 `"clip_suggestions": []` 即可。

3. 中文强制：`summary`、`tags`、`primary_subject`、`audio_strategy` 以及
   `clip_suggestions` 内的 `role`/`reason`/`audio_strategy`/`tags` 一律使用中文。
   枚举值保持英文标识符不变。

4. 关于音频：你**无法听到实际音频**。`audio_strategy` 与 `clip_suggestions[*].audio_strategy`
   仅基于画面（嘴型、场景、人群密度等）与素材元数据（是否含音轨）推测，
   推不出就给出保守建议（如"保留环境声"或空字符串），切勿凭空臆造对白内容。

5. **关键帧时间标注与时间码合法性**：用户消息中每张关键帧前会附带
   `"第 N 张关键帧 @ MM:SS.S"` 文字标注，指明该帧在素材中的精确时间点。
   你输出的 `clip_suggestions[*].in` / `out` 必须满足：
   - 时间码可被解析为非负秒数（推荐格式 `HH:MM:SS`、`MM:SS` 或纯秒）。
   - `0 <= in < out <= duration`（素材总时长见下方元数据块）。
   - 在视觉上贴近关键帧标注覆盖的时间区域；如视觉证据不足以确定某个高光段，
     **请直接不输出该 clip_suggestion**，不要凭感觉编造时间码。
{editing_intent_block}
## 评分参考

- 5：构图佳、叙事价值高、可作为成片主轴或高光。
- 4：画面合格，有明确剪辑用途。
- 3：素材可用但不出彩。
- 2：画面瑕疵明显（抖动、过曝、对焦失误）或重复性高。
- 1：废片，仅建议舍弃。

再次强调：只输出 JSON 对象本身，不要任何其他内容。"""


# ---------------------------------------------------------------------------
# Public exception & dataclass
# ---------------------------------------------------------------------------


class ProviderError(Exception):
    """Provider 构造失败或调用失败（含瞬时/非瞬时分类）。

    ``transient=True`` 表示瞬时错误（429/5xx/timeout/network），上层 analyzer
    可在 ``Failure.suggestion`` 中提示用户用 ``--force`` 重跑。
    ``transient=False`` 表示非瞬时错误（4xx 非 429、JSON 非法、枚举非法、
    配置/密钥缺失），重试无意义。
    """

    def __init__(self, message: str, *, transient: bool = False) -> None:
        super().__init__(message)
        self.transient = transient


@dataclass
class AnalysisResult:
    """Pydantic-free lightweight container for a single asset's analysis.

    Mirrors the analysis-related subset of :class:`Asset`. Population is by
    :func:`_parse_response`; consumption is by :func:`apply_analysis`.

    ``dropped_clip_suggestions`` is a list of human-readable strings (one per
    clip_suggestion that failed strict timecode validation) describing the
    original ``(in, out)`` pair and the reason it was discarded; populated
    only when ``duration`` is known to the parser and the model returned at
    least one invalid entry.
    """

    summary: Optional[str] = None
    tags: list[str] = field(default_factory=list)
    rating: Optional[int] = None
    subject_type: Optional[SubjectType] = None
    primary_subject: Optional[str] = None
    people_presence: Optional[PeoplePresence] = None
    shot_scale: Optional[ShotScale] = None
    shot_function: Optional[ShotFunction] = None
    audio_strategy: Optional[str] = None
    clip_suggestions: list[ClipSuggestion] = field(default_factory=list)
    dropped_clip_suggestions: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Provider class
# ---------------------------------------------------------------------------


class Provider:
    """Thin OpenAI-compatible vision provider.

    Construction performs all upfront validation that does NOT require a
    network call:

    1. ``config.is_usable() == False`` → :class:`ProviderError`
       (``transient=False``).
    2. ``os.environ[config.api_key_env]`` empty → :class:`ProviderError`
       (``transient=False``) with the env var name in the message.
    3. Renders ``self._system_prompt`` once by injecting any non-None
       ``editing_intent`` fields; the intent block disappears entirely when
       all five fields are None (Q19).
    4. Holds a per-instance :class:`httpx.Client`. ``httpx.Client`` is **not**
       thread-safe — each analyzer worker thread MUST own its own
       :class:`Provider` (Q8).
    """

    def __init__(self, config: ModelConfig, editing_intent: EditingIntent) -> None:
        if not config.is_usable():
            raise ProviderError(
                "ModelConfig 不可用：provider/base_url/api_key_env/vision_model 必须齐全",
                transient=False,
            )

        api_key_env = config.api_key_env or ""
        api_key = os.environ.get(api_key_env, "")
        if not api_key:
            raise ProviderError(
                f"环境变量 {api_key_env} 未设置",
                transient=False,
            )

        self._config = config
        self._api_key = api_key
        self._base_url = (config.base_url or "").rstrip("/")
        self._vision_model = config.vision_model
        self._system_prompt = self._render_system_prompt(editing_intent)
        # httpx.Client 非线程安全；analyzer 为每个 worker 线程单独构造一个 Provider。
        self._client = httpx.Client(timeout=_DEFAULT_TIMEOUT_S)

    # ------------------------------------------------------------------ public

    def analyze(self, asset: Asset) -> AnalysisResult:
        """Run one analysis pass on ``asset`` and return an :class:`AnalysisResult`.

        Behaviour:

        - Constructs the multimodal ``messages`` payload via
          :func:`_build_user_content`.
        - POSTs to ``{base_url}/chat/completions``.
        - Retries at most :data:`_MAX_RETRIES` times on transient errors
          (429 / 5xx / :class:`httpx.TimeoutException` /
          :class:`httpx.NetworkError`), with the
          :data:`_RETRY_BACKOFFS` schedule plus uniform 0-1s jitter.
        - Non-transient errors (4xx non-429, invalid JSON, enum violations)
          are raised immediately without retry.
        - On success returns the parsed :class:`AnalysisResult`. Never mutates
          ``asset`` directly — use :func:`apply_analysis` for that.
        """
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": _build_user_content(asset)},
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
        for attempt in range(1, _MAX_RETRIES + 2):  # 1, 2, 3
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
                raise ProviderError(
                    f"ProviderTimeoutError: {_DEFAULT_TIMEOUT_S}s × {attempt} 次",
                    transient=True,
                ) from exc
            except httpx.NetworkError as exc:
                last_exc = exc
                if attempt <= _MAX_RETRIES and _should_retry(exc):
                    _sleep_backoff(attempt)
                    continue
                raise ProviderError(
                    f"ProviderNetworkError: {type(exc).__name__}",
                    transient=True,
                ) from exc

            status = resp.status_code
            if status != 200:
                last_status = status
                # 截断响应体以防巨大的 HTML 错误页；analyzer/logs 还会再脱敏一遍。
                last_body = resp.text[:200] if resp.text else ""
                if _should_retry(status) and attempt <= _MAX_RETRIES:
                    _sleep_backoff(attempt)
                    continue
                raise ProviderError(
                    f"HTTP {status}: {last_body}",
                    transient=status in _TRANSIENT_HTTP,
                )

            # 200 OK — 解析响应体。
            try:
                data = resp.json()
            except ValueError as exc:
                # JSON 非法不应重试。
                raise ProviderError(
                    f"响应不是合法 JSON: {type(exc).__name__}",
                    transient=False,
                ) from exc

            try:
                content = data["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError) as exc:
                raise ProviderError(
                    f"响应缺少 choices[0].message.content: {type(exc).__name__}",
                    transient=False,
                ) from exc

            if not isinstance(content, str):
                raise ProviderError(
                    "响应 content 非字符串",
                    transient=False,
                )

            return _parse_response(content, duration=_extract_duration(asset))

        # 防御性兜底：理论上 for 循环要么 return 要么 raise，绝不应走到这里。
        raise ProviderError(
            f"重试耗尽（最后状态 {last_status}）: {type(last_exc).__name__ if last_exc else 'unknown'}",
            transient=True,
        )

    # ----------------------------------------------------------------- helpers

    @staticmethod
    def _render_system_prompt(editing_intent: EditingIntent) -> str:
        """Render ``_SYSTEM_PROMPT_TEMPLATE`` with the editing_intent block.

        Q19: only non-None fields are rendered; when all five fields are None
        the placeholder is replaced with an empty string (no extra blank
        lines).
        """
        block = _render_editing_intent_block(editing_intent)
        return _SYSTEM_PROMPT_TEMPLATE.format(editing_intent_block=block)


# ---------------------------------------------------------------------------
# Pure module-level functions
# ---------------------------------------------------------------------------


def _render_editing_intent_block(editing_intent: EditingIntent) -> str:
    """Render the editing-intent prompt segment (or "" when all fields None).

    Output shape when at least one field is non-None::

        \n## 剪辑意图（请优先满足这些约束）\n\n- output_style: ...\n- target_length: ...\n\n

    Leading and trailing newlines wrap the block so the template ``\n{block}\n``
    site does not collapse adjacent sections when the block is empty.
    """
    fields = (
        ("output_style", editing_intent.output_style),
        ("target_length", editing_intent.target_length),
        ("audience", editing_intent.audience),
        ("people_focus", editing_intent.people_focus),
        ("audio_priority", editing_intent.audio_priority),
    )
    non_null = [(name, value) for name, value in fields if value is not None]
    if not non_null:
        return ""
    lines = ["", "## 剪辑意图（请优先满足这些约束）", ""]
    for name, value in non_null:
        lines.append(f"- {name}: {value}")
    lines.append("")
    return "\n".join(lines)


def _image_data_url(path: str) -> str:
    """Read ``path`` as bytes and return a ``data:image/jpeg;base64,...`` URL.

    The MIME type is hard-coded to ``image/jpeg`` because M2's
    ``thumbnail_path``/``frame_paths`` are always JPEG.
    """
    with open(path, "rb") as fp:
        encoded = base64.b64encode(fp.read()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def _format_frame_timestamp(seconds: float) -> str:
    """Format a seconds offset as ``MM:SS.X`` (decimal: 1 fractional digit).

    Used for the text block placed immediately before each video keyframe in
    :func:`_build_user_content`, so the vision model sees an unambiguous time
    anchor next to every image.

    Examples::

        _format_frame_timestamp(0.0)    == "00:00.0"
        _format_frame_timestamp(10.5)   == "00:10.5"
        _format_frame_timestamp(125.0)  == "02:05.0"
        _format_frame_timestamp(3666.7) == "61:06.7"
    """
    seconds = max(0.0, float(seconds))
    minutes = int(seconds // 60)
    rest = seconds - minutes * 60
    # 强制保留 1 位小数；不四舍五入到 60.0 后回环。
    if rest >= 59.95:
        # 进位到下一分钟以避免出现 "00:60.0"。
        minutes += 1
        rest = 0.0
    return f"{minutes:02d}:{rest:04.1f}"


def _extract_duration(asset: Asset) -> Optional[float]:
    """Return ``asset.metadata.duration`` as a positive float, or ``None``."""
    metadata = asset.metadata or {}
    raw = metadata.get("duration")
    if raw is None:
        raw = metadata.get("duration_s")
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _build_user_content(asset: Asset) -> list[dict[str, Any]]:
    """Construct the OpenAI-compatible ``user`` content list for one asset.

    Branches by :attr:`Asset.type`:

    - ``video``: each ``image_url`` block is preceded by a short text block
      that names the image and (for keyframes) anchors it to a precise
      timestamp — so the model knows which slice of the video each frame
      depicts. All keyframes recorded on the asset are sent (M2 caps the
      count at 12 via ``_compute_frame_count``); when ``frame_timestamps`` is
      missing or shorter than ``frame_paths`` we fall back to an unanchored
      ``"第 N 张关键帧"`` label.
    - ``image``: a single ``image_url`` block from ``thumbnail_path`` prefixed
      by a ``"图片素材"`` text block + a metadata text block.
    - ``audio``: no ``image_url`` blocks; just a metadata text block.
    """
    content: list[dict[str, Any]] = []
    asset_type = asset.type

    if asset_type == AssetType.video:
        if asset.thumbnail_path:
            content.append({"type": "text", "text": "缩略图：素材封面"})
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": _image_data_url(asset.thumbnail_path)},
                }
            )
        frame_paths = list(asset.frame_paths or [])
        frame_timestamps = list(asset.frame_timestamps or [])
        for idx, frame_path in enumerate(frame_paths):
            if idx < len(frame_timestamps):
                stamp = _format_frame_timestamp(frame_timestamps[idx])
                label = f"第 {idx + 1} 张关键帧 @ {stamp}"
            else:
                label = f"第 {idx + 1} 张关键帧"
            content.append({"type": "text", "text": label})
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": _image_data_url(frame_path)},
                }
            )
    elif asset_type == AssetType.image:
        if asset.thumbnail_path:
            content.append({"type": "text", "text": "图片素材"})
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": _image_data_url(asset.thumbnail_path)},
                }
            )
    # audio: no image blocks.

    content.append({"type": "text", "text": _format_metadata_text(asset)})
    return content


def _format_metadata_text(asset: Asset) -> str:
    """Human-readable Chinese metadata block (filename / duration / has_audio)."""
    filename = asset.filename or asset.relative_path or asset.asset_id or "<未知>"
    asset_type = asset.type.value if asset.type else "<未知>"
    metadata = asset.metadata or {}
    duration = metadata.get("duration") or metadata.get("duration_s")
    has_audio = metadata.get("has_audio")

    lines = [
        "素材元数据：",
        f"- 文件名: {filename}",
        f"- 类型: {asset_type}",
    ]
    if duration is not None:
        lines.append(f"- 时长(秒): {duration}")
    if has_audio is not None:
        lines.append(f"- 含音轨: {bool(has_audio)}")
    lines.append(
        "请基于上述图像与元数据完成判读，并按系统指令输出单一 JSON 对象。"
    )
    return "\n".join(lines)


# ---- response parsing ------------------------------------------------------

_CODE_FENCE_RE = re.compile(
    r"^\s*```(?:json|JSON)?\s*\n?(.*?)\n?```\s*$",
    re.DOTALL,
)


def _strip_code_fence(text: str) -> str:
    """Strip a leading/trailing markdown code fence if present.

    Tolerates ````json ... ```` and bare ```` ... ```` blocks. Whitespace-only
    text is returned unchanged.
    """
    if not text:
        return text
    match = _CODE_FENCE_RE.match(text.strip())
    if match:
        return match.group(1).strip()
    return text.strip()


def _coerce_enum(value: Any, enum_cls: type, fallback: Any) -> Any:
    """Return ``enum_cls(value)`` if valid, else ``fallback``."""
    if value is None:
        return fallback
    try:
        return enum_cls(value)
    except (ValueError, TypeError):
        return fallback


def _coerce_rating(value: Any) -> Optional[int]:
    """Return ``value`` as an int in [1, 5], else ``None``."""
    if isinstance(value, bool):  # bool is a subclass of int — exclude it.
        return None
    if isinstance(value, int):
        return value if 1 <= value <= 5 else None
    return None


def _coerce_string_list(value: Any) -> list[str]:
    """Return ``value`` filtered to a list of non-empty strings, else ``[]``."""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


_TIMECODE_HMS_RE = re.compile(r"^(\d{1,2}):(\d{2}):(\d{2})(?:\.(\d+))?$")
_TIMECODE_MS_RE = re.compile(r"^(\d{1,3}):(\d{2})(?:\.(\d+))?$")


def _parse_timecode(value: Any) -> Optional[float]:
    """Parse a timecode (``HH:MM:SS[.f]`` / ``MM:SS[.f]`` / bare seconds) into seconds.

    Returns ``None`` on any parse failure. Pure function — unit-tested in
    ``tests/test_provider.py``.

    Examples::

        _parse_timecode("00:00:05")    == 5.0
        _parse_timecode("01:23:45.5")  == 5025.5
        _parse_timecode("01:30")       == 90.0
        _parse_timecode("30")          == 30.0
        _parse_timecode("30.5")        == 30.5
        _parse_timecode("abc")         is None
        _parse_timecode(5)             == 5.0   (numeric inputs accepted)
        _parse_timecode(-1)            is None  (negative rejected)
    """
    if isinstance(value, bool):
        # bool 是 int 子类；显式排除。
        return None
    if isinstance(value, (int, float)):
        seconds = float(value)
        return seconds if seconds >= 0 else None
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None

    hms = _TIMECODE_HMS_RE.match(text)
    if hms:
        hours, minutes, secs, frac = hms.groups()
        try:
            base = int(hours) * 3600 + int(minutes) * 60 + int(secs)
        except ValueError:
            return None
        if int(minutes) >= 60 or int(secs) >= 60:
            return None
        frac_val = float(f"0.{frac}") if frac else 0.0
        return base + frac_val

    ms = _TIMECODE_MS_RE.match(text)
    if ms:
        minutes, secs, frac = ms.groups()
        try:
            base = int(minutes) * 60 + int(secs)
        except ValueError:
            return None
        if int(secs) >= 60:
            return None
        frac_val = float(f"0.{frac}") if frac else 0.0
        return base + frac_val

    try:
        seconds = float(text)
    except ValueError:
        return None
    return seconds if seconds >= 0 else None


def _coerce_clip_suggestions(
    value: Any,
    *,
    duration: Optional[float],
) -> tuple[list[ClipSuggestion], list[str]]:
    """Parse + strictly validate a ``clip_suggestions`` array from a model response.

    Returns ``(kept, dropped)``:

    - ``kept``: validated :class:`ClipSuggestion` objects (``in`` / ``out``
      kept as the model's original string forms so downstream rendering still
      sees a timecode the user can read).
    - ``dropped``: human-readable strings describing each discarded entry's
      original ``(in, out)`` and the reason it failed validation; consumed by
      :func:`apply_analysis` to emit a non-blocking ``WarningItem``.

    Validation rules (spec §严格时间码校验):

    1. **Format**: ``in`` and ``out`` must parse via :func:`_parse_timecode`.
    2. **Ordering**: ``out_seconds > in_seconds``.
    3. **Bounds**: ``0 <= in_seconds < out_seconds <= duration`` when
       ``duration`` is known; with ``duration is None`` only rules 1–2 apply.

    Any single rule failure discards that one entry; valid siblings survive.
    A top-level non-list returns ``([], [])`` silently (no warning is
    emitted, mirroring the prior tolerant behaviour for malformed shapes).
    """
    if not isinstance(value, list):
        return [], []

    kept: list[ClipSuggestion] = []
    dropped: list[str] = []
    for entry in value:
        if not isinstance(entry, dict):
            dropped.append("非对象条目")
            continue
        in_value = entry.get("in", entry.get("in_"))
        out_value = entry.get("out")
        in_seconds = _parse_timecode(in_value)
        out_seconds = _parse_timecode(out_value)
        if in_seconds is None or out_seconds is None:
            dropped.append(
                f"格式非法 in={in_value!r} out={out_value!r}"
            )
            continue
        if not (out_seconds > in_seconds):
            dropped.append(
                f"out<=in in={in_value!r} out={out_value!r}"
            )
            continue
        if duration is not None and not (
            in_seconds >= 0 and out_seconds <= duration
        ):
            dropped.append(
                f"越界 in={in_value!r} out={out_value!r} duration={duration}"
            )
            continue

        try:
            suggestion = ClipSuggestion.model_validate(
                {
                    "in": in_value if isinstance(in_value, str) else str(in_value),
                    "out": out_value if isinstance(out_value, str) else str(out_value),
                    "role": entry.get("role"),
                    "reason": entry.get("reason"),
                    "audio_strategy": entry.get("audio_strategy"),
                    "subject_type": _coerce_enum(
                        entry.get("subject_type"), SubjectType, None
                    ),
                    "shot_scale": _coerce_enum(
                        entry.get("shot_scale"), ShotScale, None
                    ),
                    "rating": _coerce_rating(entry.get("rating")),
                    "tags": _coerce_string_list(entry.get("tags")),
                }
            )
        except Exception:
            dropped.append(
                f"模型字段不可建模 in={in_value!r} out={out_value!r}"
            )
            continue
        kept.append(suggestion)
    return kept, dropped


def _parse_response(text: str, *, duration: Optional[float] = None) -> AnalysisResult:
    """Parse a model response string into an :class:`AnalysisResult`.

    Pure function (no class state) so it is independently unit-testable.

    Steps:

    1. Strip a markdown code fence (``` or ```json) if present.
    2. ``json.loads`` — invalid JSON raises ``ProviderError(transient=False)``.
    3. Coerce field types defensively:
       - ``summary`` / ``primary_subject`` / ``audio_strategy``: non-string → ``None``.
       - ``tags``: anything not a ``list[str]`` → ``[]``.
       - ``rating``: non-int or out of [1, 5] → ``None``.
       - ``subject_type``: invalid enum → :attr:`SubjectType.other`.
       - ``shot_function``: invalid enum → :attr:`ShotFunction.other`.
       - ``people_presence`` / ``shot_scale``: invalid enum → ``None``
         (no ``other`` member exists on these enums).
       - ``clip_suggestions``: top-level non-list → ``[]``; per-entry strict
         validation (format / order / bounds) — failing entries are dropped
         and recorded in ``dropped_clip_suggestions``.

    ``duration`` (seconds) — when provided, the bounds rule in
    :func:`_coerce_clip_suggestions` is enabled. When ``None`` only format
    and ordering are enforced.
    """
    stripped = _strip_code_fence(text)
    try:
        payload = json.loads(stripped)
    except (json.JSONDecodeError, ValueError) as exc:
        # 截断输入以防巨大错误页或转录大段落；不重试。
        snippet = stripped[:200]
        raise ProviderError(
            f"非法 JSON: {exc}; 内容前 200 字符: {snippet}",
            transient=False,
        ) from exc

    if not isinstance(payload, dict):
        raise ProviderError(
            f"非法 JSON: 顶层期望 object，实际为 {type(payload).__name__}",
            transient=False,
        )

    summary = payload.get("summary")
    summary = summary if isinstance(summary, str) and summary else None

    primary_subject = payload.get("primary_subject")
    primary_subject = (
        primary_subject if isinstance(primary_subject, str) and primary_subject else None
    )

    audio_strategy = payload.get("audio_strategy")
    if not isinstance(audio_strategy, str):
        audio_strategy = None

    tags = _coerce_string_list(payload.get("tags"))
    rating = _coerce_rating(payload.get("rating"))

    subject_type = _coerce_enum(
        payload.get("subject_type"), SubjectType, SubjectType.other
    )
    shot_function = _coerce_enum(
        payload.get("shot_function"), ShotFunction, ShotFunction.other
    )
    # PeoplePresence / ShotScale 没有 ``other`` 成员；非法值降级为 None。
    people_presence = _coerce_enum(payload.get("people_presence"), PeoplePresence, None)
    shot_scale = _coerce_enum(payload.get("shot_scale"), ShotScale, None)

    # 兼容历史输出键名 segments：若模型还在用 segments 字段，与 clip_suggestions 等价处理。
    raw_suggestions = payload.get("clip_suggestions")
    if raw_suggestions is None:
        raw_suggestions = payload.get("segments")
    clip_suggestions, dropped = _coerce_clip_suggestions(
        raw_suggestions, duration=duration
    )

    return AnalysisResult(
        summary=summary,
        tags=tags,
        rating=rating,
        subject_type=subject_type,
        primary_subject=primary_subject,
        people_presence=people_presence,
        shot_scale=shot_scale,
        shot_function=shot_function,
        audio_strategy=audio_strategy,
        clip_suggestions=clip_suggestions,
        dropped_clip_suggestions=dropped,
    )


# ---- retry / backoff -------------------------------------------------------


def _should_retry(exc_or_status: Any) -> bool:
    """Classify a value as a transient (retry-worthy) error.

    - ``int``: HTTP status. ``429`` and ``5xx`` → ``True``; other codes → ``False``.
    - :class:`httpx.TimeoutException` / :class:`httpx.NetworkError` (or
      subclass instances) → ``True``.
    - Anything else → ``False``.
    """
    if isinstance(exc_or_status, bool):
        # bool subclasses int — exclude before the int branch.
        return False
    if isinstance(exc_or_status, int):
        if exc_or_status == 429:
            return True
        return 500 <= exc_or_status <= 599
    if isinstance(exc_or_status, httpx.TimeoutException):
        return True
    if isinstance(exc_or_status, httpx.NetworkError):
        return True
    return False


def _sleep_backoff(attempt: int) -> None:
    """Sleep ``_RETRY_BACKOFFS[attempt - 1] + uniform(0, 1)`` seconds.

    ``attempt`` is the 1-based index of the attempt that just failed.
    """
    base = _RETRY_BACKOFFS[attempt - 1]
    time.sleep(base + random.uniform(0, 1))


# ---- writeback -------------------------------------------------------------


def apply_analysis(asset: Asset, result: AnalysisResult) -> Asset:
    """Write a validated :class:`AnalysisResult` back onto ``asset`` in-place.

    Flips ``asset.analysis_status`` to :attr:`AnalysisStatus.analyzed`.
    Returns the same :class:`Asset` instance for chaining convenience. Must
    only be called with results produced by :func:`_parse_response` (or an
    :class:`AnalysisResult` built with already-validated fields) — there is no
    re-validation here.

    ``result.dropped_clip_suggestions`` (if any) is converted into a
    single non-blocking ``WarningItem`` appended to ``asset.warnings`` so the
    downstream consumer (M5-early HTML / CLI) can surface "the model emitted
    N suggestions but K were discarded due to invalid timecodes" without
    failing the asset.
    """
    asset.summary = result.summary
    asset.tags = list(result.tags)
    asset.rating = result.rating
    asset.subject_type = result.subject_type
    asset.primary_subject = result.primary_subject
    asset.people_presence = result.people_presence
    asset.shot_scale = result.shot_scale
    asset.shot_function = result.shot_function
    asset.audio_strategy = result.audio_strategy
    asset.clip_suggestions = list(result.clip_suggestions)
    asset.analysis_status = AnalysisStatus.analyzed
    if result.dropped_clip_suggestions:
        warning = WarningItem(
            stage="analyze",
            target=asset.asset_id,
            reason=(
                "clip_suggestion 时间码校验失败："
                + "；".join(result.dropped_clip_suggestions)
            ),
            blocking=False,
        )
        # Asset.warnings 字段类型是 ``list[Any]``；M3 整体走 dict 形式写入。
        asset.warnings.append(warning.model_dump())
    return asset


__all__ = [
    "Provider",
    "ProviderError",
    "AnalysisResult",
    "apply_analysis",
]
