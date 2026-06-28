"""分析阶段的结构化 JSONL 日志写入器（M3 / Q24）。

每次 analyze/run 调用一个 AnalyzeLogger 实例，写到
``projects/<slug>/logs/analyze-<ISO8601>.jsonl``。所有事件经
``_scrub`` 走显式字段白名单，绝不写 API key / Authorization header /
完整 prompt / 模型响应 content。
"""

from __future__ import annotations

import json
import re
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from .paths import analyze_log_path, logs_dir
from .security import REDACTION, redact_secrets

# 模块级锁：跨线程、跨 Logger 实例都共用同一把锁，保证 JSONL 行完整。
# 即便同进程内有多个 AnalyzeLogger 写不同文件，单进程内一次只允许一行 append。
_WRITE_LOCK = threading.Lock()

# 每个事件类型的字段白名单。事件 dict 经 ``_scrub`` 过滤后才进入 JSONL。
# Authorization / api_key / prompt / content / response 等敏感字段不在白名单里。
_EVENT_WHITELIST: dict[str, tuple[str, ...]] = {
    "stage_start": ("event", "ts", "stage", "total", "concurrency", "project_slug"),
    "stage_end": (
        "event",
        "ts",
        "stage",
        "succeeded",
        "failed",
        "skipped",
        "duration_ms",
        "project_slug",
    ),
    "call_start": (
        "event",
        "ts",
        "asset_id",
        "attempt",
        "asset_type",
        "frame_count",
        "project_slug",
    ),
    "call_end": (
        "event",
        "ts",
        "asset_id",
        "attempt",
        "status",
        "http_code",
        "latency_ms",
        "prompt_tokens",
        "completion_tokens",
        "error",
        "project_slug",
    ),
}

_ERROR_FIELD_MAX_LEN = 512

# 在 ``security.redact_secrets`` 的 key=value 兜底之上，额外脱敏裸 token：
# - ``Authorization: Bearer xxx`` / ``bearer xxx``
# - ``sk-xxx``（OpenAI 风格 key 裸串）
_BEARER_RE = re.compile(r"(?i)(bearer)\s+[A-Za-z0-9._\-]+")
_SK_RE = re.compile(r"\bsk-[A-Za-z0-9._\-]+")


def _scrub_error(value: str) -> str:
    """对 ``error`` 字段做脱敏 + 截断（不含 stacktrace 是调用者的责任）。"""
    text = redact_secrets(value)
    text = _BEARER_RE.sub(lambda m: f"{m.group(1)} {REDACTION}", text)
    text = _SK_RE.sub(REDACTION, text)
    if len(text) > _ERROR_FIELD_MAX_LEN:
        text = text[:_ERROR_FIELD_MAX_LEN]
    return text


def _scrub(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    """按事件类型的白名单过滤字段，并对 ``error`` 字段做截断与脱敏。

    Whitelist-based — any field not explicitly listed is dropped. The caller's
    ``error`` value is additionally:

    - cast to ``str`` (defensive),
    - run through :func:`security.redact_secrets` (strips ``api_key=...``,
      ``Bearer xxx`` etc. via the shared regex backstop),
    - truncated to ``_ERROR_FIELD_MAX_LEN`` chars (no stacktrace shall ever
      reach the log).
    """
    allowed = _EVENT_WHITELIST.get(event_type)
    if allowed is None:
        # 未声明的事件类型一律落空，避免误把任意字段写盘。
        return {"event": event_type, "ts": _utc_now_iso(_default_now)}

    scrubbed: dict[str, Any] = {}
    for key in allowed:
        if key not in payload:
            continue
        value = payload[key]
        if key == "error" and value is not None:
            value = _scrub_error(str(value))
        scrubbed[key] = value
    return scrubbed


def _default_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso(now: Callable[[], datetime]) -> str:
    return now().isoformat()


def _compact_ts(now: Callable[[], datetime]) -> str:
    """Compact ISO8601 form for filenames (e.g. ``20260625T140000Z``)."""
    dt = now().astimezone(timezone.utc)
    return dt.strftime("%Y%m%dT%H%M%SZ")


class AnalyzeLogger:
    """Append-only JSONL logger for one analyze/run invocation.

    Construction:

    - Resolves the destination file via
      :func:`tripclipper.paths.analyze_log_path` using a compact UTC timestamp.
    - Creates ``projects/<slug>/logs/`` (``parents=True, exist_ok=True``) but
      does **not** touch the file — the first ``stage_start`` will append the
      first line.

    Concurrency:

    - A module-level ``threading.Lock`` serialises every append, guaranteeing
      that JSONL line framing is never corrupted even with multiple loggers
      writing in parallel from different threads.

    Failure handling:

    - Any ``OSError``/``PermissionError`` raised while appending is swallowed.
      The first such failure prints a single warning to ``sys.stderr``
      (recording the path and exception class); subsequent failures are
      silent. Logging never propagates an exception to the analyze pipeline.
    """

    def __init__(
        self,
        project_slug: str,
        base_dir: Optional[Path] = None,
        *,
        now: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self._project_slug = project_slug
        self._now: Callable[[], datetime] = now or _default_now
        ts = _compact_ts(self._now)
        self._log_path = analyze_log_path(project_slug, ts, base_dir)
        self._warned: bool = False
        # 仅建目录，不预先 touch 文件——首次写事件时 append 才创建文件。
        try:
            logs_dir(project_slug, base_dir).mkdir(parents=True, exist_ok=True)
        except (OSError, PermissionError) as exc:
            self._emit_warning(exc)

    @property
    def log_path(self) -> Path:
        return self._log_path

    # ------------------------------------------------------------------ stage
    def stage_start(self, *, stage: str, total: int, concurrency: int) -> None:
        self._write_event(
            "stage_start",
            {
                "stage": stage,
                "total": total,
                "concurrency": concurrency,
                "project_slug": self._project_slug,
            },
        )

    def stage_end(
        self,
        *,
        stage: str,
        succeeded: int,
        failed: int,
        skipped: int,
        duration_ms: int,
    ) -> None:
        self._write_event(
            "stage_end",
            {
                "stage": stage,
                "succeeded": succeeded,
                "failed": failed,
                "skipped": skipped,
                "duration_ms": duration_ms,
                "project_slug": self._project_slug,
            },
        )

    # ------------------------------------------------------------------- call
    def call_start(
        self,
        *,
        asset_id: str,
        attempt: int,
        asset_type: str,
        frame_count: int,
    ) -> None:
        self._write_event(
            "call_start",
            {
                "asset_id": asset_id,
                "attempt": attempt,
                "asset_type": asset_type,
                "frame_count": frame_count,
                "project_slug": self._project_slug,
            },
        )

    def call_end(
        self,
        *,
        asset_id: str,
        attempt: int,
        status: str,
        http_code: Optional[int] = None,
        latency_ms: int = 0,
        prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None,
        error: Optional[str] = None,
    ) -> None:
        self._write_event(
            "call_end",
            {
                "asset_id": asset_id,
                "attempt": attempt,
                "status": status,
                "http_code": http_code,
                "latency_ms": latency_ms,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "error": error,
                "project_slug": self._project_slug,
            },
        )

    # ---------------------------------------------------------------- closing
    def close(self) -> None:
        """No-op flush hook.

        Each event is written with ``open(..., "a")`` and closes the file
        handle immediately, so there is no buffered state to flush. Provided
        for API symmetry and forward compatibility.
        """
        return None

    # --------------------------------------------------------------- internal
    def _write_event(self, event_type: str, payload: dict[str, Any]) -> None:
        event: dict[str, Any] = {
            "event": event_type,
            "ts": _utc_now_iso(self._now),
        }
        event.update(payload)
        scrubbed = _scrub(event_type, event)
        line = json.dumps(scrubbed, ensure_ascii=False) + "\n"
        try:
            with _WRITE_LOCK:
                with open(self._log_path, "a", encoding="utf-8") as fp:
                    fp.write(line)
        except (OSError, PermissionError) as exc:
            self._emit_warning(exc)

    def _emit_warning(self, exc: BaseException) -> None:
        if getattr(self, "_warned", False):
            return
        self._warned = True
        try:
            sys.stderr.write(
                f"[tripclipper.logs] WARN: failed to write JSONL log "
                f"path={self._log_path} error={type(exc).__name__}\n"
            )
        except Exception:
            # 连 stderr 都坏掉就彻底闭嘴，绝不让日志拖垮分析流程。
            pass


__all__ = ["AnalyzeLogger"]
