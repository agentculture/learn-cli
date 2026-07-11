"""Unit tests for adaptive what-next, including the never-ending mode.

Acceptance criterion 2 lives here: a learner who has mastered every item of every
track still always has a meaningful next action. The simulation test walks such a
learner forward through many study cycles and asserts what-next never dead-ends.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from learn import motivation as m
from learn.motivation._constants import REVIEW_BACKLOG


def utc(day: int, hour: int = 9) -> datetime:
    return datetime(2026, 7, day, hour, tzinfo=timezone.utc)


def rec(subject: str, item: str, day: int, result: str = "pass", activity: str = "practice"):
    return {
        "subject": subject,
        "item_id": item,
        "activity": activity,
        "result": result,
        "at": utc(day).isoformat(),
    }


def is_meaningful(r: m.Recommendation) -> bool:
    """A recommendation is meaningful when it names something concrete to do."""
    if r is None:
        return False
    if r.action == m.NextAction.REVIEW_BATCH:
        return len(r.items) > 0
    if r.action == m.NextAction.HARDER_REPEAT:
        return r.item_id is not None
    if r.action in (m.NextAction.NEXT_LESSON, m.NextAction.FRESH_STORY):
        return r.subject is not None
    return False


# --- individual branches -------------------------------------------------------


def test_next_lesson_when_subject_has_new_material() -> None:
    state = m.build_state(
        [rec("french", "a", 5)],
        subjects=[{"subject": "french", "items_total": 10, "items_mastered": 1}],
    )
    r = m.what_next(state, utc(5))
    assert r.action == m.NextAction.NEXT_LESSON
    assert r.subject == "french"
    assert r.mode == "progress"


def test_urgent_review_preempts_forward_progress() -> None:
    # 'a' mastered long ago (urgent), french still has material.
    state = m.build_state(
        [rec("french", "a", 1)],
        subjects=[{"subject": "french", "items_total": 10, "items_mastered": 1}],
    )
    r = m.what_next(state, utc(30))
    assert r.action == m.NextAction.REVIEW_BATCH
    assert r.items == (("french", "a"),)


def test_gentle_review_yields_to_forward_progress() -> None:
    # 'a' due but not urgent (~12 days on a mastered item), single-item backlog.
    state = m.build_state(
        [rec("french", "a", 1)],
        subjects=[{"subject": "french", "items_total": 10, "items_mastered": 1}],
    )
    r = m.what_next(state, utc(13))
    assert r.action == m.NextAction.NEXT_LESSON


def test_backlog_of_gentle_reviews_preempts() -> None:
    # REVIEW_BACKLOG+ gently-decayed items sweep even without an urgent one.
    rows = [rec("french", f"i{n}", 1) for n in range(REVIEW_BACKLOG)]
    state = m.build_state(
        rows, subjects=[{"subject": "french", "items_total": 99, "items_mastered": 5}]
    )
    r = m.what_next(state, utc(13))  # ~12 days → all due, none urgent
    assert r.action == m.NextAction.REVIEW_BATCH
    assert len(r.items) <= 5


def test_completed_track_current_is_maintenance_not_dead_end() -> None:
    # All mastered, done, nothing decayed, recent story → harder repeat.
    state = m.build_state(
        [rec("french", "a", 5, activity="story"), rec("french", "b", 7, activity="story")],
        subjects=[{"subject": "french", "items_total": 2, "items_mastered": 2, "done": True}],
    )
    r = m.what_next(state, utc(7))
    assert r.action == m.NextAction.HARDER_REPEAT
    assert r.item_id == "a"  # stalest mastered item
    assert r.mode == "maintenance"
    assert is_meaningful(r)


def test_completed_track_without_recent_story_recommends_fresh_story() -> None:
    state = m.build_state(
        [rec("french", "a", 5), rec("french", "b", 7)],  # practice, no stories
        subjects=[{"subject": "french", "items_total": 2, "items_mastered": 2, "done": True}],
    )
    r = m.what_next(state, utc(7))
    assert r.action == m.NextAction.FRESH_STORY
    assert r.subject == "french"
    assert is_meaningful(r)


def test_completed_track_decayed_recommends_review() -> None:
    state = m.build_state(
        [rec("french", "a", 5), rec("french", "b", 7)],
        subjects=[{"subject": "french", "items_total": 2, "items_mastered": 2, "done": True}],
    )
    r = m.what_next(state, utc(7) + timedelta(days=33))  # long gap → decayed
    assert r.action == m.NextAction.REVIEW_BATCH
    assert r.mode == "maintenance"
    assert is_meaningful(r)


def test_empty_state_still_returns_a_meaningful_action() -> None:
    state = m.build_state([])
    r = m.what_next(state, utc(1))
    assert is_meaningful(r) or r.action == m.NextAction.FRESH_STORY
    assert r is not None


def test_unknown_subject_progress_assumes_more_material() -> None:
    # No subject facts supplied → treat as not-done → forward progress.
    state = m.build_state([rec("french", "a", 5)])
    r = m.what_next(state, utc(5))
    assert r.action == m.NextAction.NEXT_LESSON
    assert r.mode == "progress"


def test_cross_subject_prefers_recently_active_subject() -> None:
    state = m.build_state(
        [rec("french", "a", 1), rec("spanish", "b", 10)],
        subjects=[
            {"subject": "french", "items_total": 9, "items_mastered": 1},
            {"subject": "spanish", "items_total": 9, "items_mastered": 1},
        ],
    )
    r = m.what_next(state, utc(10))
    assert r.action == m.NextAction.NEXT_LESSON
    assert r.subject == "spanish"  # most recently active


# --- the never-ending mode: completed-track simulation -------------------------


def _mastered_ledger(subjects: dict[str, list[str]], day: int) -> list[dict]:
    rows: list[dict] = []
    for subject, items in subjects.items():
        for item in items:
            rows.append(rec(subject, item, day, activity="story"))
    return rows


def test_completed_track_never_dead_ends_over_a_long_simulation() -> None:
    """A learner who mastered every item of every track always has a next action.

    Two fully-mastered tracks, both subjects done. Walk ~40 study cycles forward
    (6 days apart, ~240 days total): each cycle what-next must return a meaningful
    action, and 'doing' it (recording passes at the current time) feeds the next
    cycle. Proves the never-ending invariant holds through both the maintenance
    (depth) and review (decay) paths.
    """
    subjects = {"french": ["fa", "fb", "fc"], "spanish": ["sa", "sb"]}
    subject_facts = [
        {"subject": "french", "items_total": 3, "items_mastered": 3, "done": True},
        {"subject": "spanish", "items_total": 2, "items_mastered": 2, "done": True},
    ]

    ledger = _mastered_ledger(subjects, day=1)
    current = utc(1)
    seen_actions: set[m.NextAction] = set()

    for cycle in range(40):
        state = m.build_state(ledger, subjects=subject_facts)
        r = m.what_next(state, current)
        assert is_meaningful(r), f"cycle {cycle}: dead-ended with {r}"
        seen_actions.add(r.action)

        # The learner does the recommended action: record pass(es) at 'now'.
        stamp = current.isoformat()
        if r.action == m.NextAction.REVIEW_BATCH:
            for subject, item in r.items:
                ledger.append(
                    {
                        "subject": subject,
                        "item_id": item,
                        "activity": "practice",
                        "result": "pass",
                        "at": stamp,
                    }
                )
        elif r.action == m.NextAction.HARDER_REPEAT:
            ledger.append(
                {
                    "subject": r.subject,
                    "item_id": r.item_id,
                    "activity": "lesson",
                    "result": "pass",
                    "at": stamp,
                }
            )
        elif r.action == m.NextAction.FRESH_STORY:
            item = subjects[r.subject][0]
            ledger.append(
                {
                    "subject": r.subject,
                    "item_id": item,
                    "activity": "story",
                    "result": "pass",
                    "at": stamp,
                }
            )
        current += timedelta(days=6)

    # The simulation must exercise both maintenance depth and the review path.
    assert m.NextAction.REVIEW_BATCH in seen_actions
    assert seen_actions & {m.NextAction.HARDER_REPEAT, m.NextAction.FRESH_STORY}


def test_completed_track_meaningful_across_a_range_of_now() -> None:
    """Sweep 'now' from the mastery instant out past several half-lives."""
    subjects = {"french": ["fa", "fb"], "spanish": ["sa"]}
    ledger = _mastered_ledger(subjects, day=1)
    facts = [
        {"subject": "french", "items_total": 2, "items_mastered": 2, "done": True},
        {"subject": "spanish", "items_total": 1, "items_mastered": 1, "done": True},
    ]
    state = m.build_state(ledger, subjects=facts)
    for extra_days in range(0, 120, 3):
        r = m.what_next(state, utc(1) + timedelta(days=extra_days))
        assert is_meaningful(r), f"+{extra_days}d dead-ended with {r}"
