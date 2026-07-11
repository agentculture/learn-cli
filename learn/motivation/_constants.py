"""The motivation layer's tunable constants — one place, so any change is a diff.

Everything here is a policy decision, not a fact. The golden-history fixtures
(``tests/fixtures/motivation/*.json``) freeze the *outputs* these constants
produce, so changing a value here forces a visible diff in the fixtures too:
the numbers can never drift silently. No value is read from the wall clock and
none involves an LLM — the whole scoring path is a pure function of the ledger.

Grouped by concern:

* **Scoring** — how one graded outcome becomes a 0-100 number.
* **Mastery decay** — how a stored ladder level loses *standing* over time.
* **Review** — when a decayed item becomes worth resurfacing.
* **What-next** — the momentum/backlog knobs the recommendation uses.
* **Streaks** — the day boundary (documented in :mod:`learn.motivation._streaks`).
"""

from __future__ import annotations

# --- Scoring -----------------------------------------------------------------
#
# The driver's ``result`` grade is authoritative; the raw correct/total count
# (when the exercise is countable) refines it. Score = a weighted blend:
#
#     score = RESULT_WEIGHT * RESULT_SCORE[result]
#           + ACCURACY_WEIGHT * (100 * correct / total)
#
# collapsing to just ``RESULT_SCORE[result]`` when no count is present. The
# weights sum to 1.0 and lean on the grade (0.6) over the count (0.4) because
# the grade already reflects the driver's rubric judgement.

#: Base 0-100 value each raw result maps to before the accuracy refinement.
RESULT_SCORE: dict[str, float] = {"fail": 0.0, "partial": 60.0, "pass": 100.0}  # nosec B105

#: Weight on the driver's ``result`` grade in the blended score.
RESULT_WEIGHT: float = 0.6

#: Weight on the raw ``correct/total`` accuracy in the blended score.
ACCURACY_WEIGHT: float = 0.4

# --- Mastery decay -----------------------------------------------------------
#
# The subject owns the stored mastery *ladder* (unknown→…→mastered) and we never
# mutate it. On top of it we compute a decayed *standing* in [0, 1]: how well the
# item is still retained now, given when it was last seen. Fresh mastered = 1.0;
# it halves every HALF_LIFE_DAYS of silence (exponential forgetting curve).

#: Numeric strength each ladder level starts at (the value at last_seen, no decay
#: yet). Introduced/practiced sit below mastered so a shaky item is always more
#: review-worthy than a solid one at equal age.
MASTERY_STRENGTH: dict[str, float] = {
    "unknown": 0.0,
    "introduced": 0.4,
    "practiced": 0.7,
    "mastered": 1.0,
}

#: Half-life in days: retention halves after this many days without review.
#: 10 days is a deliberate mid-range spaced-repetition cadence — a mastered item
#: is still ~50% retained after ~10 days, ~25% after ~20.
HALF_LIFE_DAYS: float = 10.0

# --- Review ------------------------------------------------------------------

#: A touched item whose decayed standing drops below this enters the review
#: queue. 0.5 = "half-forgotten." Fresh mastered (1.0) and fresh practiced (0.7)
#: are above it; fresh introduced (0.4) is below it, so shaky new items surface
#: for reinforcement immediately.
REVIEW_DUE_THRESHOLD: float = 0.5

#: Below this, a due item is *urgent*: what-next interrupts forward progress to
#: clear it before it rots further. 0.35 sits just under fresh introduced (0.4),
#: so a freshly-introduced item is due-but-not-urgent (learn it forward), while a
#: decayed one is urgent (review it now).
REVIEW_URGENT_THRESHOLD: float = 0.35

#: A review backlog this large also interrupts forward progress, even without an
#: individually-urgent item — a pile of gently-decayed items is worth a sweep.
REVIEW_BACKLOG: int = 5

#: Cap on how many items one recommended review batch names.
REVIEW_BATCH_SIZE: int = 5

# --- What-next ---------------------------------------------------------------

#: How many of the most recent ledger entries what-next scans to decide whether
#: the learner has read a story lately (breadth) vs. only drilled (depth). In
#: maintenance mode, no recent story → recommend a fresh story; otherwise → a
#: harder repeat of the stalest mastered item.
STORY_RECENCY: int = 5
