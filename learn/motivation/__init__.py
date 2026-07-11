"""learn-cli's motivation layer — deterministic scores, streaks, reviews, what-next.

This is the portal's half of the contract's state division: subjects report raw
observations (``pass|partial|fail``, optional counts, timestamps) and own their
mastery ladder; learn-cli appends those raw ``recorded`` objects to a
cross-subject ledger and derives all *motivation* from the ledger alone —
**deterministically, with no LLM and no wall clock in the path**. The same
history yields the same numbers on web, CLI, and MCP.

Every function that depends on time takes an explicit ``now: datetime`` (UTC);
none reads the clock. The tunable policy constants live in
:mod:`learn.motivation._constants` (one file, so a change is a visible diff), and
the golden-history fixtures freeze the outputs they produce.

Public API
----------

* :func:`score_exercise`, :func:`score_session`, :func:`score_lesson`,
  :func:`mean_score` — 0-100 scores from recorded outcomes.
* :func:`streaks` — per-subject and cross-subject day-based streaks
  (day boundary: UTC midnight).
* :func:`decayed_mastery` — exponential-decay retention on top of the stored
  ladder (half-life :data:`~learn.motivation._constants.HALF_LIFE_DAYS`).
* :func:`build_state` — fold a ledger into a :class:`LearnerState`.
* :func:`review_queue` — ordered items due for review.
* :func:`what_next` — one typed :class:`Recommendation`; never ``None``, even for
  a learner who has mastered every track (the never-ending mode).
"""

from __future__ import annotations

from learn.motivation._constants import (
    ACCURACY_WEIGHT,
    HALF_LIFE_DAYS,
    MASTERY_STRENGTH,
    RESULT_SCORE,
    RESULT_WEIGHT,
    REVIEW_BACKLOG,
    REVIEW_BATCH_SIZE,
    REVIEW_DUE_THRESHOLD,
    REVIEW_URGENT_THRESHOLD,
    STORY_RECENCY,
)
from learn.motivation._decay import decayed_mastery, elapsed_days
from learn.motivation._models import (
    ACTIVITIES,
    MASTERY_LEVELS,
    RESULTS,
    ItemState,
    LearnerState,
    LedgerEntry,
    NextAction,
    Recommendation,
    ReviewItem,
    Streak,
    StreakReport,
    SubjectProgress,
    ensure_utc,
    parse_ledger,
    parse_timestamp,
)
from learn.motivation._review import review_queue
from learn.motivation._scoring import (
    mean_score,
    score_exercise,
    score_lesson,
    score_session,
)
from learn.motivation._state import build_state
from learn.motivation._streaks import streaks
from learn.motivation._whatnext import what_next

__all__ = [
    # scoring
    "score_exercise",
    "score_session",
    "score_lesson",
    "mean_score",
    # streaks
    "streaks",
    # decay + review
    "decayed_mastery",
    "elapsed_days",
    "review_queue",
    # state + what-next
    "build_state",
    "what_next",
    # value types
    "LedgerEntry",
    "SubjectProgress",
    "ItemState",
    "LearnerState",
    "Recommendation",
    "NextAction",
    "ReviewItem",
    "Streak",
    "StreakReport",
    # parsing helpers
    "parse_ledger",
    "parse_timestamp",
    "ensure_utc",
    # vocabularies
    "MASTERY_LEVELS",
    "RESULTS",
    "ACTIVITIES",
    # constants (the tunable policy surface)
    "RESULT_SCORE",
    "RESULT_WEIGHT",
    "ACCURACY_WEIGHT",
    "MASTERY_STRENGTH",
    "HALF_LIFE_DAYS",
    "REVIEW_DUE_THRESHOLD",
    "REVIEW_URGENT_THRESHOLD",
    "REVIEW_BACKLOG",
    "REVIEW_BATCH_SIZE",
    "STORY_RECENCY",
]
