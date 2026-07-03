"""终端实时进度汇总器。"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable, Optional


@dataclass
class ProgressSnapshot:
    label: str
    done: int = 0
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    extra: Optional[str] = None


class PeriodicProgressReporter:
    """线程安全的周期性 stdout 汇总器。

    输出节奏：
    - ``start()`` 总会输出开始行；
    - ``advance_*()`` 在 ``done == 1``、``done % 3 == 0``、``done == total``
      时输出聚合进度行；
    - ``total == 0`` 时只输出开始行。
    """

    def __init__(self, label: str, *, emit: Callable[[str], None]) -> None:
        self._snapshot = ProgressSnapshot(label=label)
        self._emit = emit
        self._lock = threading.Lock()

    def start(
        self,
        total: int,
        *,
        skipped: int = 0,
        extra: Optional[str] = None,
    ) -> None:
        with self._lock:
            self._snapshot.total = total
            self._snapshot.skipped = skipped
            self._snapshot.extra = extra
            self._emit(self._render_start(self._snapshot))

    def note(self, message: str) -> None:
        with self._lock:
            self._emit(f"[{self._snapshot.label}] {message}")

    def advance_success(self) -> None:
        with self._lock:
            self._snapshot.done += 1
            self._snapshot.succeeded += 1
            self._maybe_emit_progress()

    def advance_failure(self) -> None:
        with self._lock:
            self._snapshot.done += 1
            self._snapshot.failed += 1
            self._maybe_emit_progress()

    def _maybe_emit_progress(self) -> None:
        snapshot = self._snapshot
        if snapshot.total <= 0:
            return
        if (
            snapshot.done == 1
            or snapshot.done % 3 == 0
            or snapshot.done == snapshot.total
        ):
            self._emit(self._render_progress(snapshot))

    @staticmethod
    def _render_start(snapshot: ProgressSnapshot) -> str:
        parts = [f"[{snapshot.label}] 开始：总计 {snapshot.total}"]
        if snapshot.skipped:
            parts.append(f"跳过 {snapshot.skipped}")
        if snapshot.extra:
            parts.append(snapshot.extra)
        return "，".join(parts)

    @staticmethod
    def _render_progress(snapshot: ProgressSnapshot) -> str:
        return (
            f"[{snapshot.label}] {snapshot.done}/{snapshot.total}"
            f"（成功 {snapshot.succeeded} / 失败 {snapshot.failed} / "
            f"跳过 {snapshot.skipped}）"
        )


__all__ = ["ProgressSnapshot", "PeriodicProgressReporter"]
