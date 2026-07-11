"""One-way push of unsynced ledger rows to the learn API.

**v1 is push-only, by design.** The local ledger is the append-only source of
truth for this device; the server's per-learner ledger (``workers/learn-api``'s
``insertRecord``/``listRecords``) is additive too, so there is nothing a pull
would give this device that it doesn't already hold. Sync exists purely for
*continuity across devices* (the web face, a second machine) — a future pull
path can be layered on the same cursor without changing this module's shape.

Every function here is best-effort and never raises: a network failure stops
the push loop where it is and reports the partial result, so a caller (``learn
record``, a future ``learn auth status``) can surface sync status without ever
failing the command it's attached to.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from learn.profile._api import DEFAULT_TIMEOUT, ApiError, push_record
from learn.profile._ledger import read_ledger
from learn.profile._syncstate import SyncState, load_sync_state, save_sync_state


@dataclass(frozen=True)
class SyncResult:
    attempted: int
    synced: int
    pending: int
    ok: bool
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempted": self.attempted,
            "synced": self.synced,
            "pending": self.pending,
            "ok": self.ok,
            "error": self.error,
        }


def pending_sync_count() -> int:
    """How many local ledger rows have not yet been pushed. Never touches the network."""
    rows = read_ledger()
    state = load_sync_state()
    return max(len(rows) - state.cursor, 0)


def push_pending(token: str, *, timeout: float = DEFAULT_TIMEOUT) -> SyncResult:
    """Push every unsynced ledger row to the API, in ledger order.

    Stops at the first failure (network or HTTP error) and persists progress
    made so far — the next call resumes from there. Returns ``ok=True`` only
    when every pending row was pushed; never raises.
    """
    rows = read_ledger()
    state = load_sync_state()
    cursor = min(state.cursor, len(rows))
    total_pending = len(rows) - cursor
    synced = 0

    for row in rows[cursor:]:
        subject = row.get("subject")
        recorded = {key: value for key, value in row.items() if key != "subject"}
        try:
            push_record(token, subject, recorded, timeout=timeout)
        except ApiError as err:
            save_sync_state(SyncState(cursor=cursor + synced))
            return SyncResult(
                attempted=total_pending,
                synced=synced,
                pending=total_pending - synced,
                ok=False,
                error=str(err),
            )
        synced += 1

    save_sync_state(SyncState(cursor=cursor + synced))
    return SyncResult(attempted=total_pending, synced=synced, pending=0, ok=True)
