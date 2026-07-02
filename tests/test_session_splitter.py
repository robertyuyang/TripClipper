"""Tests for the deterministic session splitter.

Zero mock: feed hand-built ``Asset`` objects to the pure functions and assert
on the returned ``Session`` objects. No IO, no LLM.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tripclipper.models import Asset
from tripclipper.session_splitter import (
    SESSION_GAP_HOURS,
    UNKNOWN_SESSION_ID,
    apply_sessions,
    split_sessions,
)

BASE = datetime(2026, 6, 15, 9, 0, 0, tzinfo=timezone.utc)


def _asset(idx: int, when: datetime | None) -> Asset:
    return Asset(
        asset_id=f"asset_{idx}",
        modified_time=when.isoformat() if when is not None else None,
    )


def test_all_within_gap_yields_single_session() -> None:
    assets = [_asset(i, BASE + timedelta(minutes=7 * i)) for i in range(5)]
    sessions = split_sessions(assets)

    assert len(sessions) == 1
    assert sessions[0].session_id == "session_01"
    assert sessions[0].asset_count == 5
    assert sessions[0].started_at == BASE
    assert sessions[0].ended_at == BASE + timedelta(minutes=28)


def test_each_two_hours_apart_yields_one_session_each() -> None:
    assets = [_asset(i, BASE + timedelta(hours=2 * i)) for i in range(5)]
    sessions = split_sessions(assets)

    assert [s.session_id for s in sessions] == [
        "session_01",
        "session_02",
        "session_03",
        "session_04",
        "session_05",
    ]
    assert all(s.asset_count == 1 for s in sessions)


def test_ninety_minute_gap_splits_into_two() -> None:
    early = [_asset(i, BASE + timedelta(minutes=10 * i)) for i in range(3)]
    late_start = BASE + timedelta(minutes=20) + timedelta(minutes=90)
    late = [_asset(3 + i, late_start + timedelta(minutes=10 * i)) for i in range(2)]
    sessions = split_sessions(early + late)

    assert len(sessions) == 2
    assert sessions[0].asset_count == 3
    assert sessions[1].asset_count == 2
    assert sessions[0].asset_ids == ["asset_0", "asset_1", "asset_2"]
    assert sessions[1].asset_ids == ["asset_3", "asset_4"]


def test_missing_times_go_to_unknown_bucket_last() -> None:
    timed = [_asset(i, BASE + timedelta(minutes=5 * i)) for i in range(2)]
    untimed = [_asset(10 + i, None) for i in range(2)]
    sessions = split_sessions(timed + untimed)

    assert sessions[-1].session_id == UNKNOWN_SESSION_ID
    unknown = sessions[-1]
    assert unknown.asset_count == 2
    assert unknown.started_at is None
    assert unknown.ended_at is None
    assert set(unknown.asset_ids) == {"asset_10", "asset_11"}


def test_empty_assets_yield_empty_sessions() -> None:
    assert split_sessions([]) == []


def test_all_unknown_yields_only_unknown_session() -> None:
    sessions = split_sessions([_asset(i, None) for i in range(3)])
    assert len(sessions) == 1
    assert sessions[0].session_id == UNKNOWN_SESSION_ID


def test_unsorted_input_is_ordered_by_time() -> None:
    a_late = _asset(1, BASE + timedelta(hours=3))
    a_early = _asset(2, BASE)
    sessions = split_sessions([a_late, a_early])

    assert len(sessions) == 2
    assert sessions[0].asset_ids == ["asset_2"]
    assert sessions[1].asset_ids == ["asset_1"]


def test_apply_sessions_writes_ids_back() -> None:
    assets = [_asset(i, BASE + timedelta(hours=2 * i)) for i in range(3)]
    sessions = split_sessions(assets)
    apply_sessions(assets, sessions)

    assert [a.session_id for a in assets] == ["session_01", "session_02", "session_03"]


def test_apply_sessions_marks_unknown() -> None:
    assets = [_asset(0, BASE), _asset(1, None)]
    sessions = split_sessions(assets)
    apply_sessions(assets, sessions)

    assert assets[0].session_id == "session_01"
    assert assets[1].session_id == UNKNOWN_SESSION_ID


def test_gap_constant_is_one_hour() -> None:
    assert SESSION_GAP_HOURS == 1.0
