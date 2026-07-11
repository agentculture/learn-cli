"""Unit tests for day-based streaks.

The day boundary is UTC midnight and a streak stays alive until a full day is
missed (active today, or active yesterday and today not yet over). ``now`` is
always explicit, so these are deterministic regardless of host zone.
"""

from __future__ import annotations

from datetime import datetime, timezone

from learn import motivation as m


def at(day: int, hour: int = 12, subject: str = "french", item: str = "x") -> dict:
    return {
        "subject": subject,
        "item_id": item,
        "activity": "practice",
        "result": "pass",
        "at": datetime(2026, 7, day, hour, tzinfo=timezone.utc).isoformat(),
    }


def now(day: int, hour: int = 12) -> datetime:
    return datetime(2026, 7, day, hour, tzinfo=timezone.utc)


def test_consecutive_days_build_a_streak() -> None:
    report = m.streaks([at(1), at(2), at(3)], now(3))
    assert report.overall.current_days == 3
    assert report.overall.longest_days == 3
    assert report.overall.active_today is True
    assert report.overall.last_active == "2026-07-03"


def test_multiple_entries_same_day_count_once() -> None:
    report = m.streaks([at(1, 8), at(1, 20), at(2, 9)], now(2))
    assert report.overall.current_days == 2


def test_streak_alive_when_active_yesterday_not_today() -> None:
    # Studied through jul-3, now is jul-4 (nothing today yet): streak still 3.
    report = m.streaks([at(1), at(2), at(3)], now(4))
    assert report.overall.current_days == 3
    assert report.overall.active_today is False


def test_streak_breaks_after_a_full_missed_day() -> None:
    # Last activity jul-3, now is jul-5: jul-4 was missed entirely → broken.
    report = m.streaks([at(1), at(2), at(3)], now(5))
    assert report.overall.current_days == 0
    # ...but the longest run in history is preserved.
    assert report.overall.longest_days == 3


def test_gap_resets_current_but_longest_remembers() -> None:
    # jul 1,2,3 then gap then jul 10 (=today).
    entries = [at(1), at(2), at(3), at(10)]
    report = m.streaks(entries, now(10))
    assert report.overall.current_days == 1
    assert report.overall.longest_days == 3


def test_per_subject_and_overall_diverge() -> None:
    entries = [
        at(1, subject="french"),
        at(2, subject="spanish"),
        at(3, subject="french"),
    ]
    report = m.streaks(entries, now(3))
    # Overall: active every day jul 1-3.
    assert report.overall.current_days == 3
    # French alone: jul-1 and jul-3, not consecutive; current = 1 (today).
    assert report.by_subject["french"].current_days == 1
    assert report.by_subject["french"].longest_days == 1
    # Spanish: jul-2 only, now jul-3 (yesterday) → still alive at 1.
    assert report.by_subject["spanish"].current_days == 1
    assert report.by_subject["spanish"].active_today is False


def test_empty_history_is_zeroed() -> None:
    report = m.streaks([], now(3))
    assert report.overall.current_days == 0
    assert report.overall.longest_days == 0
    assert report.overall.last_active is None
    assert report.by_subject == {}


def test_day_boundary_is_utc_midnight() -> None:
    # 23:30 UTC jul-1 and 00:30 UTC jul-2 are *different* UTC days → 2-day streak.
    entries = [at(1, 23), at(2, 0)]
    report = m.streaks(entries, now(2, 1))
    assert report.overall.current_days == 2
    # A naive timestamp is assumed UTC (contract stamps UTC).
    naive = {
        "subject": "french",
        "item_id": "x",
        "activity": "practice",
        "result": "pass",
        "at": "2026-07-02T00:30:00",
    }
    assert m.streaks([naive], now(2, 1)).overall.active_today is True


def test_streaks_are_deterministic() -> None:
    entries = [at(1), at(2), at(3)]
    a = m.streaks(entries, now(3))
    b = m.streaks(list(reversed(entries)), now(3))
    assert a == b
