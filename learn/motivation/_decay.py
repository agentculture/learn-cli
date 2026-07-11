"""Time-decayed mastery *standing* — the review layer that sits on top of the ladder.

The subject owns the stored mastery ladder and we never mutate it. Here we
compute how much of that mastery is still *retained* now: a value in ``[0, 1]``
that starts at the level's base strength (:data:`MASTERY_STRENGTH`) at
``last_seen`` and decays with an exponential forgetting curve of half-life
:data:`HALF_LIFE_DAYS`. Fresh mastered = 1.0; after one half-life, 0.5; after
two, 0.25. This decayed standing lowers an item's review priority-standing
without ever changing the subject's stored level — exactly the split the
contract prescribes.
"""

from __future__ import annotations

from datetime import datetime

from learn.motivation._constants import HALF_LIFE_DAYS, MASTERY_STRENGTH
from learn.motivation._models import ensure_utc

#: Seconds per day, for elapsed-time math.
_SECONDS_PER_DAY = 86400.0


def elapsed_days(last_seen: datetime, now: datetime) -> float:
    """Days elapsed between ``last_seen`` and ``now`` (both coerced to UTC).

    Never negative: a ``now`` before ``last_seen`` (clock skew, out-of-order
    ledger) clamps to 0, so retention can't exceed the base strength.
    """
    delta = (ensure_utc(now) - ensure_utc(last_seen)).total_seconds()
    return max(delta, 0.0) / _SECONDS_PER_DAY


def decayed_mastery(mastery: str, last_seen: datetime, now: datetime) -> float:
    """Retention in ``[0, 1]`` for a stored ladder ``mastery`` level as of ``now``.

    ``base = MASTERY_STRENGTH[mastery]`` at ``last_seen``, decaying by
    ``0.5 ** (elapsed_days / HALF_LIFE_DAYS)``. An unknown/unmapped level has base
    0.0 (nothing to retain). Deterministic: identical inputs → identical float.
    """
    base = MASTERY_STRENGTH.get(mastery, 0.0)
    if base <= 0.0:
        return 0.0
    days = elapsed_days(last_seen, now)
    if days <= 0.0:
        return base
    return base * (0.5 ** (days / HALF_LIFE_DAYS))
