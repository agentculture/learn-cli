"""Value types for the motivation layer, plus ledger parsing.

Everything here is immutable (frozen dataclasses) and timezone-explicit: any
``datetime`` that enters the layer is normalized to UTC by :func:`ensure_utc`,
so the pure functions downstream never depend on a local zone or the wall clock.

The load-bearing input type is :class:`LedgerEntry` — a parsed, normalized copy
of the contract's ``recorded`` object (``learn/contract/schemas/record.json``)
with the owning ``subject`` attached. learn-cli appends the raw ``recorded``
object to a cross-subject ledger; this layer parses that ledger and derives
everything from it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

#: The mastery ladder, mirrored from :data:`learn.contract.MASTERY_LEVELS`
#: (a guard test asserts they agree, so this layer stays dependency-free).
MASTERY_LEVELS: tuple[str, ...] = ("unknown", "introduced", "practiced", "mastered")

#: Raw result vocabulary, mirrored from :data:`learn.contract.RESULTS`.
RESULTS: tuple[str, ...] = ("pass", "partial", "fail")

#: Activities a record can come from (mirrors ``record.json``'s ``activity`` enum).
ACTIVITIES: tuple[str, ...] = ("lesson", "practice", "story")


def ensure_utc(value: datetime) -> datetime:
    """Return ``value`` as a timezone-aware UTC datetime.

    A naive datetime is *assumed* to be UTC (the contract stamps ISO-8601 UTC
    timestamps); an aware one is converted. This is the single choke point that
    keeps every time comparison in the layer zone-explicit and deterministic.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def parse_timestamp(raw: str) -> datetime:
    """Parse an ISO-8601 timestamp (contract ``at`` field) to UTC.

    Accepts a trailing ``Z`` as well as explicit offsets. Raises
    :class:`ValueError` on anything unparseable so bad ledger rows fail loudly
    rather than silently sorting to the epoch.
    """
    text = raw.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    return ensure_utc(datetime.fromisoformat(text))


def _field(source: Any, name: str) -> Any:
    """Read ``name`` from a Mapping (dict) or an object, returning None if absent."""
    if isinstance(source, Mapping):
        return source.get(name)
    return getattr(source, name, None)


@dataclass(frozen=True)
class LedgerEntry:
    """One normalized recorded outcome, keyed cross-subject by (subject, item_id).

    A parsed copy of the contract ``recorded`` object with ``subject`` attached.
    Raw observations only — never a derived score (scores are computed here, from
    these).
    """

    subject: str
    item_id: str
    activity: str
    result: str
    at: datetime
    correct: Optional[int] = None
    total: Optional[int] = None
    duration_seconds: Optional[float] = None
    exercise_id: Optional[str] = None
    story_id: Optional[str] = None
    lesson_id: Optional[str] = None
    notes: Optional[str] = None

    @property
    def key(self) -> tuple[str, str]:
        """The cross-subject join key: ``(subject, item_id)``."""
        return (self.subject, self.item_id)

    @classmethod
    def from_recorded(cls, recorded: Any, subject: Optional[str] = None) -> "LedgerEntry":
        """Build an entry from a contract ``recorded`` object (dict or object).

        ``subject`` is taken from the argument, else from a ``subject`` key on
        the row itself (learn-cli's ledger rows carry it). Raises
        :class:`ValueError` when neither supplies it or a required field is
        missing.
        """
        subj = subject if subject is not None else _field(recorded, "subject")
        if not subj:
            raise ValueError("ledger entry is missing 'subject'")
        item_id = _field(recorded, "item_id")
        result = _field(recorded, "result")
        at_raw = _field(recorded, "at")
        if not item_id or not result or not at_raw:
            raise ValueError("ledger entry requires 'item_id', 'result', and 'at'")
        at = at_raw if isinstance(at_raw, datetime) else parse_timestamp(str(at_raw))
        correct = _field(recorded, "correct")
        total = _field(recorded, "total")
        duration = _field(recorded, "duration_seconds")
        return cls(
            subject=str(subj),
            item_id=str(item_id),
            activity=str(_field(recorded, "activity") or "practice"),
            result=str(result),
            at=ensure_utc(at),
            correct=int(correct) if correct is not None else None,
            total=int(total) if total is not None else None,
            duration_seconds=float(duration) if duration is not None else None,
            exercise_id=_opt_str(_field(recorded, "exercise_id")),
            story_id=_opt_str(_field(recorded, "story_id")),
            lesson_id=_opt_str(_field(recorded, "lesson_id")),
            notes=_opt_str(_field(recorded, "notes")),
        )


def _opt_str(value: Any) -> Optional[str]:
    return None if value is None else str(value)


def parse_ledger(rows: Any) -> tuple[LedgerEntry, ...]:
    """Parse an iterable of ledger rows (dicts or :class:`LedgerEntry`) to entries.

    Rows already parsed are passed through, so callers can mix. The result is not
    sorted — callers that need chronological order sort by ``.at``.
    """
    out: list[LedgerEntry] = []
    for row in rows:
        out.append(row if isinstance(row, LedgerEntry) else LedgerEntry.from_recorded(row))
    return tuple(out)


@dataclass(frozen=True)
class SubjectProgress:
    """The authority-facts a subject reports (from its ``progress`` payload).

    The motivation layer never invents whether a subject has more to teach — only
    the subject knows. When these facts are supplied, what-next uses them to tell
    forward-progress (new lessons remain) from maintenance (every item mastered).
    When omitted for a subject, the layer conservatively assumes more remains.
    """

    subject: str
    items_total: Optional[int] = None
    items_mastered: Optional[int] = None
    done: Optional[bool] = None

    @property
    def is_done(self) -> bool:
        """True when the subject reports it has nothing new left to teach."""
        if self.done is not None:
            return self.done
        if self.items_total is not None and self.items_mastered is not None:
            return self.items_total > 0 and self.items_mastered >= self.items_total
        return False


@dataclass(frozen=True)
class ItemState:
    """The layer's per-(subject, item_id) snapshot, derived from the ledger.

    ``mastery`` is the *stored* ladder level (derived from the item's history by
    the same never-regress inference the subject uses, unless the caller supplies
    the subject's own value). Decay is applied on top of this at query time — it
    is never baked into the stored level.
    """

    subject: str
    item_id: str
    mastery: str
    last_seen: datetime
    entry_count: int
    last_result: str

    @property
    def key(self) -> tuple[str, str]:
        return (self.subject, self.item_id)


@dataclass(frozen=True)
class LearnerState:
    """The whole cross-subject picture the review/what-next functions consume."""

    items: tuple[ItemState, ...] = ()
    subjects: tuple[SubjectProgress, ...] = ()
    ledger: tuple[LedgerEntry, ...] = ()

    def subject_ids(self) -> tuple[str, ...]:
        """Every subject known from the ledger or the supplied progress facts."""
        seen = {item.subject for item in self.items}
        seen |= {sp.subject for sp in self.subjects}
        seen |= {entry.subject for entry in self.ledger}
        return tuple(sorted(seen))

    def progress_for(self, subject: str) -> Optional[SubjectProgress]:
        for sp in self.subjects:
            if sp.subject == subject:
                return sp
        return None


class NextAction(str, Enum):
    """The four adaptive recommendation kinds (contract §3.2 maintenance mode)."""

    NEXT_LESSON = "next_lesson"
    REVIEW_BATCH = "review_batch"
    HARDER_REPEAT = "harder_repeat"
    FRESH_STORY = "fresh_story"


@dataclass(frozen=True)
class Recommendation:
    """A typed, deterministic what-next answer. Never ``None`` from what_next()."""

    action: NextAction
    reason: str
    mode: str  # "progress" (new material remains) | "maintenance" (all done)
    subject: Optional[str] = None
    item_id: Optional[str] = None
    items: tuple[tuple[str, str], ...] = ()  # (subject, item_id) pairs for a batch


@dataclass(frozen=True)
class ReviewItem:
    """One entry in the ordered review queue (most-decayed first)."""

    subject: str
    item_id: str
    mastery: str
    last_seen: datetime
    retention: float
    elapsed_days: float
    urgent: bool

    @property
    def key(self) -> tuple[str, str]:
        return (self.subject, self.item_id)


@dataclass(frozen=True)
class Streak:
    """A day-based streak (UTC calendar days; see :mod:`._streaks`)."""

    current_days: int
    longest_days: int
    last_active: Optional[str] = None  # ISO date (YYYY-MM-DD) of most recent activity
    active_today: bool = False


@dataclass(frozen=True)
class StreakReport:
    """Cross-subject and per-subject streaks from one history."""

    overall: Streak
    by_subject: dict[str, Streak] = field(default_factory=dict)
