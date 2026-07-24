"""Deterministic session (activity segment) splitting.

Pure functions, no LLM and no IO. Groups assets into time-contiguous
"sessions" (e.g. morning-beach / afternoon-boardgames / evening-dinner) by
looking at :attr:`Asset.modified_time` and cutting whenever the gap between two
adjacent assets is at least :data:`SESSION_GAP_HOURS` hours.

Design decisions (session-splitting spec, grilling Q1/Q7/Q9):

* 时间源优先使用 ``Asset.metadata['captured_at']``，缺失时回退
  ``Asset.modified_time``；两者都缺失的素材归入 ``session_00_unknown``。
* The gap threshold is a module constant, never a CLI flag (Q6/Q8).
* Numbered sessions are ``session_01``, ``session_02``, ... ; the unknown
  bucket is only emitted when at least one asset lacks a time.
"""

from __future__ import annotations

from datetime import datetime

from .models import Asset, Session

__all__ = ["SESSION_GAP_HOURS", "UNKNOWN_SESSION_ID", "split_sessions", "apply_sessions"]

# Cut a new session whenever adjacent assets are at least this many hours apart.
SESSION_GAP_HOURS = 1.0

UNKNOWN_SESSION_ID = "session_00_unknown"


def _parse_time(value: str | None) -> datetime | None:
    """解析 ISO 8601 时间字符串；空值或非法值返回 ``None``。"""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo is not None else parsed.astimezone()
    except (ValueError, TypeError):
        return None


def split_sessions(
    assets: list[Asset], *, gap_hours: float = SESSION_GAP_HOURS
) -> list[Session]:
    """Group ``assets`` into time-contiguous sessions.

    Returns a list of :class:`Session` objects and does **not** mutate the
    assets; call :func:`apply_sessions` to write ``session_id`` back.
    """
    timed: list[tuple[datetime, Asset]] = []
    unknown: list[Asset] = []
    for asset in assets:
        parsed = _parse_time(asset.metadata.get("captured_at"))
        if parsed is None:
            parsed = _parse_time(asset.modified_time)
        if parsed is None:
            unknown.append(asset)
        else:
            timed.append((parsed, asset))

    timed.sort(key=lambda pair: pair[0])

    gap_seconds = gap_hours * 3600.0
    segments: list[list[tuple[datetime, Asset]]] = []
    current: list[tuple[datetime, Asset]] = []
    prev_time: datetime | None = None
    for when, asset in timed:
        if prev_time is not None and (when - prev_time).total_seconds() >= gap_seconds:
            segments.append(current)
            current = []
        current.append((when, asset))
        prev_time = when
    if current:
        segments.append(current)

    sessions: list[Session] = []
    for index, segment in enumerate(segments, start=1):
        sessions.append(
            Session(
                session_id=f"session_{index:02d}",
                asset_ids=[asset.asset_id for _, asset in segment],
                started_at=segment[0][0],
                ended_at=segment[-1][0],
                asset_count=len(segment),
            )
        )

    if unknown:
        sessions.append(
            Session(
                session_id=UNKNOWN_SESSION_ID,
                asset_ids=[asset.asset_id for asset in unknown],
                started_at=None,
                ended_at=None,
                asset_count=len(unknown),
            )
        )

    return sessions


def apply_sessions(assets: list[Asset], sessions: list[Session]) -> None:
    """Write each session's ``session_id`` back onto its member assets."""
    by_id = {asset.asset_id: asset for asset in assets}
    for session in sessions:
        for asset_id in session.asset_ids:
            asset = by_id.get(asset_id)
            if asset is not None:
                asset.session_id = session.session_id
