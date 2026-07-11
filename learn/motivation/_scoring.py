"""Deterministic 0-100 scores from raw recorded outcomes.

No LLM, no wall clock: a score is a pure function of the ``recorded`` object's
``result`` and (when countable) ``correct``/``total``. Subjects never emit
scores — the contract structurally forbids it — so this is the *only* place a
number is minted, on web, CLI, and MCP alike, from the same ledger.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any, Optional

from learn.motivation._constants import ACCURACY_WEIGHT, RESULT_SCORE, RESULT_WEIGHT
from learn.motivation._models import _field


def _round_half_up(value: float) -> int:
    """Round to nearest int, halves up (49.5 → 50) — intuitive and deterministic."""
    return int(math.floor(value + 0.5))


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def score_exercise(recorded: Any) -> int:
    """Score one recorded outcome in ``0..100``.

    Accepts a contract ``recorded`` mapping (the ledger entry verbatim) or a
    :class:`~learn.motivation._models.LedgerEntry`. The driver's ``result`` grade
    sets the base (fail/partial/pass → 0/60/100); when the exercise is countable
    (``total`` present and > 0) the raw accuracy refines it via the documented
    weighted blend. Unknown/missing ``result`` scores 0.
    """
    result = _field(recorded, "result")
    base = RESULT_SCORE.get(str(result), 0.0)
    correct = _field(recorded, "correct")
    total = _field(recorded, "total")
    if total is not None and total > 0 and correct is not None:
        accuracy = min(max(correct / total, 0.0), 1.0) * 100.0
        raw = RESULT_WEIGHT * base + ACCURACY_WEIGHT * accuracy
    else:
        raw = base
    return _clamp(_round_half_up(raw), 0, 100)


def mean_score(recordeds: Iterable[Any]) -> Optional[int]:
    """Mean :func:`score_exercise` over an iterable, or ``None`` when empty.

    The building block for session and lesson aggregations: a plain arithmetic
    mean of the per-exercise scores, rounded half-up to an int.
    """
    scores = [score_exercise(r) for r in recordeds]
    if not scores:
        return None
    return _round_half_up(sum(scores) / len(scores))


def score_session(recordeds: Iterable[Any]) -> Optional[int]:
    """Aggregate score for a session (any set of outcomes): the mean exercise score."""
    return mean_score(recordeds)


def score_lesson(recordeds: Iterable[Any], lesson_id: str) -> Optional[int]:
    """Aggregate score for one lesson: the mean over outcomes with that ``lesson_id``.

    Returns ``None`` when no recorded outcome belongs to the lesson.
    """
    scoped = [r for r in recordeds if _field(r, "lesson_id") == lesson_id]
    return mean_score(scoped)
