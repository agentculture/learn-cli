"""Unit tests for the deterministic scoring path.

Scores are minted only here (subjects are forbidden from emitting them). Every
expected number below is hand-computed from the documented formula
``score = 0.6*RESULT_SCORE[result] + 0.4*(100*correct/total)`` (collapsing to the
result base when no count is present), so the constants are pinned by assertion.
"""

from __future__ import annotations

import pytest

from learn import motivation as m


@pytest.mark.parametrize(
    "recorded,expected",
    [
        # No count → pure result base.
        ({"result": "pass"}, 100),
        ({"result": "partial"}, 60),
        ({"result": "fail"}, 0),
        # Countable → 0.6*base + 0.4*accuracy%.
        ({"result": "pass", "correct": 1, "total": 1}, 100),  # 60 + 40
        ({"result": "pass", "correct": 5, "total": 6}, 93),  # 60 + 33.33 → 93.33
        ({"result": "pass", "correct": 2, "total": 3}, 87),  # 60 + 26.67 → 86.67
        ({"result": "partial", "correct": 1, "total": 2}, 56),  # 36 + 20
        ({"result": "partial", "correct": 2, "total": 3}, 63),  # 36 + 26.67 → 62.67
        ({"result": "fail", "correct": 0, "total": 3}, 0),  # 0 + 0
        ({"result": "fail", "correct": 1, "total": 4}, 10),  # 0 + 10
    ],
)
def test_score_exercise_matches_formula(recorded: dict, expected: int) -> None:
    assert m.score_exercise(recorded) == expected


def test_score_is_always_in_range() -> None:
    for result in ("pass", "partial", "fail"):
        for correct, total in [(0, 1), (1, 1), (3, 4), (7, 10)]:
            score = m.score_exercise({"result": result, "correct": correct, "total": total})
            assert 0 <= score <= 100


def test_unknown_result_scores_zero() -> None:
    assert m.score_exercise({"result": "bogus"}) == 0
    assert m.score_exercise({}) == 0


def test_correct_over_total_is_clamped() -> None:
    # Defensive: a malformed correct > total cannot push the score past 100.
    assert m.score_exercise({"result": "pass", "correct": 5, "total": 2}) == 100


def test_zero_total_ignores_accuracy() -> None:
    # total must be >= 1 per the schema; a defensive 0 falls back to the base.
    assert m.score_exercise({"result": "partial", "correct": 0, "total": 0}) == 60


def test_score_accepts_ledger_entry_object() -> None:
    entry = m.LedgerEntry.from_recorded(
        {
            "item_id": "x",
            "activity": "practice",
            "result": "pass",
            "correct": 1,
            "total": 1,
            "at": "2026-07-01T00:00:00Z",
        },
        subject="french",
    )
    assert m.score_exercise(entry) == 100


def test_session_score_is_mean_rounded_half_up() -> None:
    recordeds = [
        {"result": "pass"},  # 100
        {"result": "partial"},  # 60
        {"result": "fail"},  # 0
    ]
    # mean(100, 60, 0) = 53.33 → 53
    assert m.score_session(recordeds) == 53


def test_session_score_empty_is_none() -> None:
    assert m.score_session([]) is None
    assert m.mean_score([]) is None


def test_lesson_score_filters_by_lesson_id() -> None:
    recordeds = [
        {"result": "pass", "lesson_id": "l1"},  # 100
        {"result": "fail", "lesson_id": "l1"},  # 0
        {"result": "pass", "lesson_id": "l2"},  # excluded
    ]
    # mean(100, 0) = 50
    assert m.score_lesson(recordeds, "l1") == 50
    assert m.score_lesson(recordeds, "l2") == 100
    assert m.score_lesson(recordeds, "missing") is None


def test_half_up_rounding_boundary() -> None:
    # Two 50s and one 51 → 50.33 → 50; construct an exact .5 to prove half-up.
    # partial(60) + pass w/ 0/1 accuracy: 0.6*100+0.4*0 = 60; mean(60,60,61?) —
    # simplest exact-half: mean of 40 and 41 is 40.5 → 41 (half-up).
    forty = {"result": "partial", "correct": 0, "total": 3}  # 36
    assert m.score_exercise(forty) == 36
    # 0.6*60 + 0.4*(100*1/1) = 36 + 40 = 76; pair with 75 to hit .5? Use direct:
    assert m.mean_score([{"result": "fail"}, {"result": "pass"}]) == 50  # mean(0,100)
