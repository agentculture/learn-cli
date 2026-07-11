"""Fold a raw cross-subject ledger into a :class:`LearnerState`.

Pure and time-independent (no ``now`` — a snapshot of *what is stored*, not a
time-decayed view; decay is applied later, at query time, by the review layer).
Per (subject, item_id) it derives the stored mastery level from the item's
history using the contract's never-regress inference (``fail→introduced``,
``partial→practiced``, ``pass→mastered``), unless the caller supplies the
subject's own stored level (from a ``progress`` payload) as an override.
"""

from __future__ import annotations

from typing import Any, Optional

from learn.motivation._models import (
    MASTERY_LEVELS,
    ItemState,
    LearnerState,
    LedgerEntry,
    SubjectProgress,
    parse_ledger,
)

#: Contract inference: a raw result maps to the ladder level it implies.
_RESULT_TO_LEVEL: dict[str, str] = {
    "fail": "introduced",
    "partial": "practiced",
    "pass": "mastered",  # nosec B105 - dict key, not a password (bandit false positive)
}

_LEVEL_RANK: dict[str, int] = {level: rank for rank, level in enumerate(MASTERY_LEVELS)}


def _infer_mastery(entries: list[LedgerEntry]) -> str:
    """Highest ladder level implied by the item's history — never regresses.

    Applies the contract inference to each result and keeps the maximum rank
    reached, so a later ``fail`` after a ``pass`` does not demote the item (the
    subject's own inference has the same never-regress rule).
    """
    best = "unknown"
    for entry in entries:
        implied = _RESULT_TO_LEVEL.get(entry.result, "unknown")
        if _LEVEL_RANK[implied] > _LEVEL_RANK[best]:
            best = implied
    return best


def build_state(
    ledger: Any,
    *,
    mastery: Optional[dict[tuple[str, str], str]] = None,
    subjects: Optional[Any] = None,
) -> LearnerState:
    """Group a ledger into per-item state plus optional subject-progress facts.

    * ``ledger`` — iterable of ledger rows (dicts or :class:`LedgerEntry`).
    * ``mastery`` — optional ``(subject, item_id) -> level`` overrides carrying
      the subject's *stored* ladder level (e.g. from a ``progress`` payload). When
      absent for an item, the level is inferred from the item's own history.
    * ``subjects`` — optional iterable of :class:`SubjectProgress` (dicts accepted)
      telling what-next which subjects still have new material to teach.

    Deterministic: item order is sorted by ``(subject, item_id)``.
    """
    entries = parse_ledger(ledger)
    overrides = mastery or {}

    grouped: dict[tuple[str, str], list[LedgerEntry]] = {}
    for entry in entries:
        grouped.setdefault(entry.key, []).append(entry)

    items: list[ItemState] = []
    for key in sorted(grouped):
        item_entries = sorted(grouped[key], key=lambda e: e.at)
        subject, item_id = key
        level = overrides.get(key) or _infer_mastery(item_entries)
        last = item_entries[-1]
        items.append(
            ItemState(
                subject=subject,
                item_id=item_id,
                mastery=level,
                last_seen=last.at,
                entry_count=len(item_entries),
                last_result=last.result,
            )
        )

    return LearnerState(
        items=tuple(items),
        subjects=_coerce_subjects(subjects),
        ledger=entries,
    )


def _coerce_subjects(subjects: Optional[Any]) -> tuple[SubjectProgress, ...]:
    if not subjects:
        return ()
    out: list[SubjectProgress] = []
    for sp in subjects:
        if isinstance(sp, SubjectProgress):
            out.append(sp)
        else:
            out.append(
                SubjectProgress(
                    subject=sp["subject"],
                    items_total=sp.get("items_total"),
                    items_mastered=sp.get("items_mastered"),
                    done=sp.get("done"),
                )
            )
    return tuple(out)
