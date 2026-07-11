"""Adaptive what-next: one typed, deterministic recommendation, never ``None``.

The never-ending contract: ``progress.done == true`` is *not* a dead end — it
switches the learner into maintenance + depth mode. So :func:`what_next` always
returns a meaningful :class:`Recommendation`, whether the learner has fresh
material, a decayed backlog, or has mastered every item of every track.

Decision order (first match wins — deterministic, no randomness, no clock beyond
the explicit ``now``):

1. **review_batch** — an *urgent* due item (retention below the urgent
   threshold) or a backlog of :data:`REVIEW_BACKLOG`+ due items. Protect memory
   before it rots; interrupts forward progress.
2. **next_lesson** — a subject still has new material (per its reported progress;
   unknown ⇒ assume it does). Make forward progress. Prefers the most-recently
   active such subject to keep momentum.
3. **review_batch** — a remaining, non-urgent due backlog. Clear it once forward
   progress has nothing to offer.
4. **fresh_story** — maintenance, and no story read in the recent window: widen
   with a fresh story.
5. **harder_repeat** — maintenance with recent stories: deepen the stalest
   mastered item at a higher difficulty rung.
6. **fresh_story** (fallback) — nothing else applies (e.g. no mastered item to
   repeat): still a meaningful action, so the return is never empty.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from learn.motivation._constants import (
    REVIEW_BACKLOG,
    REVIEW_BATCH_SIZE,
    STORY_RECENCY,
)
from learn.motivation._models import (
    ItemState,
    LearnerState,
    NextAction,
    Recommendation,
    ReviewItem,
    ensure_utc,
)
from learn.motivation._review import review_queue


def _all_done(state: LearnerState) -> bool:
    """True when every known subject reports it is done (and there is ≥1)."""
    subject_ids = state.subject_ids()
    if not subject_ids:
        return False
    for subject in subject_ids:
        sp = state.progress_for(subject)
        if sp is None or not sp.is_done:
            return False
    return True


def _subject_with_new_material(state: LearnerState) -> Optional[str]:
    """Pick the subject to advance: a not-done subject, most-recently active first.

    A subject is a candidate unless its reported progress says it is done. Among
    candidates, the one whose items were most recently practiced wins (momentum);
    a candidate with no activity yet sorts after active ones, by subject id.
    """
    last_seen_by_subject: dict[str, datetime] = {}
    for item in state.items:
        prev = last_seen_by_subject.get(item.subject)
        if prev is None or item.last_seen > prev:
            last_seen_by_subject[item.subject] = item.last_seen

    candidates: list[tuple[int, float, str]] = []
    for subject in state.subject_ids():
        sp = state.progress_for(subject)
        if sp is not None and sp.is_done:
            continue
        last = last_seen_by_subject.get(subject)
        has_activity = 0 if last is not None else 1  # active subjects sort first
        recency = -last.timestamp() if last is not None else 0.0
        candidates.append((has_activity, recency, subject))
    if not candidates:
        return None
    candidates.sort()
    return candidates[0][2]


def _recent_activities(state: LearnerState, window: int) -> list[str]:
    """The ``activity`` of the ``window`` most recent ledger entries (by time)."""
    ordered = sorted(state.ledger, key=lambda e: e.at, reverse=True)
    return [entry.activity for entry in ordered[:window]]


def _oldest_mastered(state: LearnerState) -> Optional[ItemState]:
    """The mastered item last seen longest ago — the stalest to deepen."""
    mastered = [item for item in state.items if item.mastery == "mastered"]
    if not mastered:
        return None
    mastered.sort(key=lambda i: (i.last_seen, i.subject, i.item_id))
    return mastered[0]


def _any_subject(state: LearnerState) -> Optional[str]:
    """A deterministic subject to attach to a story recommendation, if any exist."""
    ids = state.subject_ids()
    return ids[0] if ids else None


def _review_batch(queue: list[ReviewItem], mode: str) -> Recommendation:
    batch = tuple((r.subject, r.item_id) for r in queue[:REVIEW_BATCH_SIZE])
    lead = queue[0]
    return Recommendation(
        action=NextAction.REVIEW_BATCH,
        reason=(
            f"{len(queue)} item(s) have decayed below the review threshold; "
            f"reviewing the {len(batch)} most urgent (led by "
            f"{lead.subject}:{lead.item_id})."
        ),
        mode=mode,
        subject=lead.subject,
        item_id=lead.item_id,
        items=batch,
    )


def what_next(state: LearnerState, now: datetime) -> Recommendation:
    """The single best next action as of ``now`` (UTC). Never ``None``."""
    now = ensure_utc(now)
    queue = review_queue(state, now)
    all_done = _all_done(state)
    mode = "maintenance" if all_done else "progress"

    # 1. Urgent decay or a real backlog preempts forward progress.
    urgent = any(item.urgent for item in queue)
    if urgent or len(queue) >= REVIEW_BACKLOG:
        return _review_batch(queue, mode)

    # 2. Make forward progress if any subject still has new material.
    subject = _subject_with_new_material(state)
    if subject is not None:
        return Recommendation(
            action=NextAction.NEXT_LESSON,
            reason=f"{subject} still has new material — continue with the next lesson.",
            mode="progress",
            subject=subject,
        )

    # 3. Clear a remaining, non-urgent review backlog.
    if queue:
        return _review_batch(queue, mode)

    # 4/5. Maintenance depth: widen with a story, or deepen a stale mastered item.
    if "story" not in _recent_activities(state, STORY_RECENCY):
        return Recommendation(
            action=NextAction.FRESH_STORY,
            reason="Everything is mastered and current — read a fresh story for breadth.",
            mode="maintenance",
            subject=_any_subject(state),
        )

    stale = _oldest_mastered(state)
    if stale is not None:
        return Recommendation(
            action=NextAction.HARDER_REPEAT,
            reason=(
                f"All mastered and current — deepen the stalest item "
                f"({stale.subject}:{stale.item_id}) at a harder rung."
            ),
            mode="maintenance",
            subject=stale.subject,
            item_id=stale.item_id,
        )

    # 6. Fallback — always meaningful, never empty.
    return Recommendation(
        action=NextAction.FRESH_STORY,
        reason="Read a fresh story to keep learning.",
        mode=mode,
        subject=_any_subject(state),
    )
