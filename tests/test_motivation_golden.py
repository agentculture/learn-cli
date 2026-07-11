"""Golden-history tests for the motivation layer (acceptance criterion 1).

Each fixture under ``tests/fixtures/motivation/`` pins a fixed recorded history
plus the exact scores, streaks, review queue, and what-next it must produce at a
fixed ``now``. The layer is a pure function of the ledger with no LLM and no wall
clock, so identical history must yield identical numbers — these tests enforce
that, and freeze the constants: any change to a scoring/decay/threshold constant
changes a fixture's expected block, which shows up as a visible diff.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from learn import motivation as m

FIXTURES = Path(__file__).parent / "fixtures" / "motivation"
GOLDEN_FILES = sorted(p.name for p in FIXTURES.glob("*.json"))


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _overrides(fixture: dict):
    raw = fixture.get("mastery")
    if not raw:
        return None
    return {tuple(k.split("::")): v for k, v in raw.items()}


def _streak_dict(s: m.Streak) -> dict:
    return {
        "current_days": s.current_days,
        "longest_days": s.longest_days,
        "last_active": s.last_active,
        "active_today": s.active_today,
    }


def _rec_dict(r: m.Recommendation) -> dict:
    return {
        "action": r.action.value,
        "mode": r.mode,
        "subject": r.subject,
        "item_id": r.item_id,
        "items": [list(pair) for pair in r.items],
    }


def test_at_least_four_golden_histories_exist() -> None:
    assert len(GOLDEN_FILES) >= 4


@pytest.mark.parametrize("name", GOLDEN_FILES)
def test_golden_scores(name: str) -> None:
    fx = _load(name)
    exp = fx["expected"]
    assert [m.score_exercise(e) for e in fx["ledger"]] == exp["exercise_scores"]
    assert m.score_session(fx["ledger"]) == exp["session_score"]


@pytest.mark.parametrize("name", GOLDEN_FILES)
def test_golden_streaks(name: str) -> None:
    fx = _load(name)
    now = m.parse_timestamp(fx["now"])
    report = m.streaks(fx["ledger"], now)
    exp = fx["expected"]["streaks"]
    assert _streak_dict(report.overall) == exp["overall"]
    assert {k: _streak_dict(v) for k, v in report.by_subject.items()} == exp["by_subject"]


@pytest.mark.parametrize("name", GOLDEN_FILES)
def test_golden_review_queue(name: str) -> None:
    fx = _load(name)
    now = m.parse_timestamp(fx["now"])
    state = m.build_state(fx["ledger"], subjects=fx.get("subjects"), mastery=_overrides(fx))
    queue = m.review_queue(state, now)
    assert [[r.subject, r.item_id] for r in queue] == fx["expected"]["review_queue"]


@pytest.mark.parametrize("name", GOLDEN_FILES)
def test_golden_what_next(name: str) -> None:
    fx = _load(name)
    now = m.parse_timestamp(fx["now"])
    state = m.build_state(fx["ledger"], subjects=fx.get("subjects"), mastery=_overrides(fx))
    assert _rec_dict(m.what_next(state, now)) == fx["expected"]["what_next"]


@pytest.mark.parametrize("name", GOLDEN_FILES)
def test_golden_is_reproducible(name: str) -> None:
    """Running twice yields byte-identical structured results — determinism."""
    fx = _load(name)
    now = m.parse_timestamp(fx["now"])
    state = m.build_state(fx["ledger"], subjects=fx.get("subjects"), mastery=_overrides(fx))
    first = _rec_dict(m.what_next(state, now))
    second = _rec_dict(m.what_next(state, now))
    assert first == second
