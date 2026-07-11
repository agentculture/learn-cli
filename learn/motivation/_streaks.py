"""Day-based streaks — per-subject and cross-subject — from a recorded history.

**The day boundary is UTC midnight.** A "day" is a UTC calendar date
(``at`` normalized to UTC, then ``.date()``); a day *counts* toward a streak if
it holds at least one recorded outcome. This choice is deterministic and
location-independent — the same history yields the same streak on any host, in
any zone, which is the whole point of computing streaks here rather than in a
locale-aware client.

**A streak is alive until a full day is missed.** The current streak counts
consecutive active days ending at *today* (the UTC day of ``now``) when today is
active, or at *yesterday* when today is not yet active but yesterday was — so a
learner who studied yesterday still has their streak today until the day ends.
If the most recent activity is older than yesterday, the current streak is 0.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, timedelta
from typing import Any

from learn.motivation._models import (
    LedgerEntry,
    Streak,
    StreakReport,
    ensure_utc,
    parse_ledger,
)


def _active_dates(entries: Iterable[LedgerEntry]) -> set[date]:
    """The set of UTC calendar dates on which at least one outcome was recorded."""
    return {entry.at.date() for entry in entries}


def _current_streak(active: set[date], today: date) -> int:
    """Consecutive active days ending at ``today`` or ``yesterday``; else 0."""
    if not active:  # pragma: no cover - guarded by _streak_for; defensive only
        return 0
    most_recent = max(active)
    if most_recent < today - timedelta(days=1):
        return 0  # missed a full day — streak broken
    count = 0
    cursor = most_recent
    while cursor in active:
        count += 1
        cursor -= timedelta(days=1)
    return count


def _longest_streak(active: set[date]) -> int:
    """The longest run of consecutive active days anywhere in the history."""
    if not active:  # pragma: no cover - guarded by _streak_for; defensive only
        return 0
    ordered = sorted(active)
    longest = 1
    run = 1
    for prev, cur in zip(ordered, ordered[1:]):
        if cur - prev == timedelta(days=1):
            run += 1
        else:
            run = 1
        longest = max(longest, run)
    return longest


def _streak_for(entries: Iterable[LedgerEntry], today: date) -> Streak:
    active = _active_dates(entries)
    if not active:
        return Streak(current_days=0, longest_days=0, last_active=None, active_today=False)
    last = max(active)
    return Streak(
        current_days=_current_streak(active, today),
        longest_days=_longest_streak(active),
        last_active=last.isoformat(),
        active_today=(today in active),
    )


def streaks(history: Any, now: datetime) -> StreakReport:
    """Per-subject and cross-subject day-based streaks as of ``now`` (UTC).

    ``history`` is an iterable of ledger rows (dicts or
    :class:`~learn.motivation._models.LedgerEntry`); ``now`` is the explicit
    reference time — never the wall clock — so identical histories yield
    identical streaks. Cross-subject ("overall") counts a day active if *any*
    subject was practiced that day.
    """
    entries = parse_ledger(history)
    today = ensure_utc(now).date()

    by_subject: dict[str, list[LedgerEntry]] = {}
    for entry in entries:
        by_subject.setdefault(entry.subject, []).append(entry)

    return StreakReport(
        overall=_streak_for(entries, today),
        by_subject={
            subject: _streak_for(subject_entries, today)
            for subject, subject_entries in sorted(by_subject.items())
        },
    )
