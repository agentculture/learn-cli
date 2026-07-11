"""The one-way sync cursor (``sync.json``).

v1 sync is **push-only**: the CLI pushes unsynced ledger rows to
``POST /api/record`` and never pulls anything back (the server ledger is
additive-only too, per learner, so there is nothing a pull would add that this
device doesn't already have — see :mod:`learn.profile._sync` for the push
loop). The cursor is a plain row count: rows ``[0:cursor)`` of the local ledger
have been pushed; everything from ``cursor`` onward is pending. Because the
ledger is append-only, a row count is a sufficient, trivially-resumable cursor
— no row ids or timestamps to reconcile.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from learn.profile._paths import ensure_store_dir, sync_path


@dataclass(frozen=True)
class SyncState:
    cursor: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"cursor": self.cursor}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SyncState":
        return cls(cursor=int(data.get("cursor", 0)))


def load_sync_state() -> SyncState:
    """Return the stored cursor, or a fresh ``cursor=0`` when absent/unreadable."""
    path = sync_path()
    if not path.is_file():
        return SyncState()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return SyncState()
    return SyncState.from_dict(data)


def save_sync_state(state: SyncState) -> None:
    ensure_store_dir()
    sync_path().write_text(json.dumps(state.to_dict()), encoding="utf-8")
