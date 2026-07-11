"""Unit tests for time-decayed mastery and the review queue.

Decay is exponential with a 10-day half-life on top of per-level base strengths;
the review queue surfaces touched items whose decayed standing has dropped below
the due threshold, most-decayed first. All time is explicit and UTC.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from learn import motivation as m
from learn.motivation._constants import HALF_LIFE_DAYS, MASTERY_STRENGTH


def utc(day: int, hour: int = 9) -> datetime:
    return datetime(2026, 7, day, hour, tzinfo=timezone.utc)


# --- decay ---------------------------------------------------------------------


def test_fresh_mastery_equals_base_strength() -> None:
    t = utc(1)
    for level, base in MASTERY_STRENGTH.items():
        assert m.decayed_mastery(level, t, t) == base


def test_half_life_halves_retention() -> None:
    start = utc(1)
    ten_days = start + timedelta(days=HALF_LIFE_DAYS)
    assert m.decayed_mastery("mastered", start, ten_days) == pytest.approx(0.5)
    twenty_days = start + timedelta(days=2 * HALF_LIFE_DAYS)
    assert m.decayed_mastery("mastered", start, twenty_days) == pytest.approx(0.25)


def test_practiced_decays_from_its_lower_base() -> None:
    start = utc(1)
    ten = start + timedelta(days=HALF_LIFE_DAYS)
    assert m.decayed_mastery("practiced", start, ten) == pytest.approx(0.35)  # 0.7/2


def test_unknown_never_has_standing() -> None:
    assert m.decayed_mastery("unknown", utc(1), utc(30)) == 0.0


def test_negative_elapsed_clamps_to_base() -> None:
    # now before last_seen (skew / out-of-order) never exceeds base strength.
    assert m.decayed_mastery("mastered", utc(10), utc(1)) == 1.0


def test_decay_is_monotonic_over_time() -> None:
    start = utc(1)
    prev = m.decayed_mastery("mastered", start, start)
    for d in range(1, 40):
        cur = m.decayed_mastery("mastered", start, start + timedelta(days=d))
        assert cur < prev
        prev = cur


def test_decay_is_timezone_explicit() -> None:
    # Same instant expressed in a different zone yields the same retention.
    start = utc(1)
    now_utc = utc(11)
    now_other = now_utc.astimezone(timezone(timedelta(hours=5)))
    assert m.decayed_mastery("mastered", start, now_utc) == m.decayed_mastery(
        "mastered", start, now_other
    )


# --- review queue --------------------------------------------------------------


def _ledger(*rows: tuple[str, str, int]):
    """rows of (item_id, result, last_seen_day) for a single french learner."""
    return [
        {
            "subject": "french",
            "item_id": item,
            "activity": "practice",
            "result": result,
            "at": utc(day).isoformat(),
        }
        for item, result, day in rows
    ]


def test_fresh_items_are_not_due() -> None:
    state = m.build_state(_ledger(("a", "pass", 10), ("b", "partial", 10)))
    assert m.review_queue(state, utc(10)) == []


def test_decayed_items_enter_queue_most_decayed_first() -> None:
    # 'a' mastered jul-1 (old, very decayed), 'b' mastered jul-15 (recent).
    state = m.build_state(_ledger(("a", "pass", 1), ("b", "pass", 15)))
    queue = m.review_queue(state, utc(30))
    assert [r.item_id for r in queue] == ["a", "b"]
    assert queue[0].retention < queue[1].retention


def test_fresh_introduced_is_due_but_not_urgent() -> None:
    # introduced base 0.4 < due 0.5 but > urgent 0.35 → due, not urgent.
    state = m.build_state(_ledger(("a", "fail", 10)))
    queue = m.review_queue(state, utc(10))
    assert len(queue) == 1
    assert queue[0].urgent is False


def test_deeply_decayed_item_is_urgent() -> None:
    state = m.build_state(_ledger(("a", "pass", 1)))
    queue = m.review_queue(state, utc(30))  # ~29 days → deeply decayed
    assert queue[0].urgent is True


def test_review_queue_is_deterministic_under_input_order() -> None:
    forward = m.build_state(_ledger(("a", "pass", 1), ("b", "pass", 1), ("c", "pass", 1)))
    reverse = m.build_state(_ledger(("c", "pass", 1), ("b", "pass", 1), ("a", "pass", 1)))
    fq = [r.item_id for r in m.review_queue(forward, utc(30))]
    rq = [r.item_id for r in m.review_queue(reverse, utc(30))]
    assert fq == rq == ["a", "b", "c"]  # equal retention → item-id tie-break
