"""The time-decayed review queue: which touched items to resurface, in order.

An item is *due* when its decayed standing (:func:`decayed_mastery`) falls below
:data:`REVIEW_DUE_THRESHOLD`; it is *urgent* below :data:`REVIEW_URGENT_THRESHOLD`.
Untouched items (``unknown``) are never reviews — they are new material for
what-next, not resurfacing candidates.

Ordering is fully deterministic: most-decayed first (ascending retention), then
oldest first (ascending ``last_seen``), then ``(subject, item_id)`` as the final
tie-break — so the same state always yields the same queue.
"""

from __future__ import annotations

from datetime import datetime

from learn.motivation._constants import REVIEW_DUE_THRESHOLD, REVIEW_URGENT_THRESHOLD
from learn.motivation._decay import decayed_mastery, elapsed_days
from learn.motivation._models import LearnerState, ReviewItem, ensure_utc


def review_queue(state: LearnerState, now: datetime) -> list[ReviewItem]:
    """Ordered list of items due for review as of ``now`` (UTC).

    Cross-subject: each :class:`ReviewItem` carries its ``subject`` and
    ``item_id``. Empty when nothing has decayed below the due threshold.
    """
    now = ensure_utc(now)
    due: list[ReviewItem] = []
    for item in state.items:
        if item.mastery == "unknown":
            continue
        retention = decayed_mastery(item.mastery, item.last_seen, now)
        if retention < REVIEW_DUE_THRESHOLD:
            due.append(
                ReviewItem(
                    subject=item.subject,
                    item_id=item.item_id,
                    mastery=item.mastery,
                    last_seen=item.last_seen,
                    retention=retention,
                    elapsed_days=elapsed_days(item.last_seen, now),
                    urgent=retention < REVIEW_URGENT_THRESHOLD,
                )
            )
    due.sort(key=lambda r: (r.retention, r.last_seen, r.subject, r.item_id))
    return due
