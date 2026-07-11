"""Edge-branch tests: the value types and the never-empty fallback.

Pins behaviour the golden/simulation tests don't exercise directly — the
``SubjectProgress.is_done`` logic, the unknown-level review skip, dataclass
passthrough into ``build_state``, and the ultimate what-next fallback that keeps
the recommendation from ever being empty.
"""

from __future__ import annotations

from datetime import datetime, timezone

from learn import motivation as m


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


# --- SubjectProgress.is_done ---------------------------------------------------


def test_subject_progress_done_flag_wins() -> None:
    assert m.SubjectProgress("french", done=True).is_done is True
    assert m.SubjectProgress("french", done=False).is_done is False


def test_subject_progress_infers_done_from_counts() -> None:
    assert m.SubjectProgress("french", items_total=3, items_mastered=3).is_done is True
    assert m.SubjectProgress("french", items_total=3, items_mastered=2).is_done is False
    # Zero total is not "done" — an empty subject has nothing mastered.
    assert m.SubjectProgress("french", items_total=0, items_mastered=0).is_done is False


def test_subject_progress_without_facts_is_not_done() -> None:
    assert m.SubjectProgress("french").is_done is False


# --- build_state passthrough + overrides --------------------------------------


def test_build_state_accepts_subject_progress_objects() -> None:
    state = m.build_state(
        [rec("french", "a", 5)],
        subjects=[m.SubjectProgress("french", done=True)],
    )
    assert state.progress_for("french").is_done is True


def test_build_state_mastery_override_beats_inference() -> None:
    # History would infer 'mastered' (a pass), but the subject's stored level wins.
    state = m.build_state(
        [rec("french", "a", 5, result="pass")],
        mastery={("french", "a"): "practiced"},
    )
    (item,) = state.items
    assert item.mastery == "practiced"


def test_unknown_override_is_skipped_from_review() -> None:
    # An item forced to 'unknown' is not a review candidate even when old.
    state = m.build_state(
        [rec("french", "a", 1)],
        mastery={("french", "a"): "unknown"},
    )
    assert m.review_queue(state, utc(30)) == []


# --- the never-empty fallback (what-next step 6) ------------------------------


def test_what_next_fallback_when_done_but_nothing_mastered() -> None:
    # All done, a fresh practiced (not mastered) item last touched via a story:
    # no reviews due, no new material, recent story, no mastered item to deepen —
    # the layer must still return a meaningful fresh_story rather than nothing.
    state = m.build_state(
        [rec("french", "a", 7, result="partial", activity="story")],
        subjects=[{"subject": "french", "items_total": 1, "items_mastered": 1, "done": True}],
        mastery={("french", "a"): "practiced"},
    )
    r = m.what_next(state, utc(7))  # now == last_seen → nothing decayed
    assert r is not None
    assert r.action == m.NextAction.FRESH_STORY
    assert r.subject == "french"


def test_item_and_review_keys_are_subject_item_pairs() -> None:
    state = m.build_state([rec("french", "a", 1)])
    (item,) = state.items
    assert item.key == ("french", "a")
    (review,) = m.review_queue(state, utc(30))
    assert review.key == ("french", "a")


def test_state_subject_ids_union_of_ledger_and_progress() -> None:
    state = m.build_state(
        [rec("french", "a", 5)],
        subjects=[{"subject": "spanish", "items_total": 1, "items_mastered": 0}],
    )
    assert state.subject_ids() == ("french", "spanish")
