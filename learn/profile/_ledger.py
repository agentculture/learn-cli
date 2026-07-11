"""The local append-only cross-subject ledger (``ledger.jsonl``).

One JSON object per line: the contract's ``recorded`` object (see
``learn/contract/schemas/record.json``) plus a ``subject`` field — exactly the
row shape :func:`learn.motivation.LedgerEntry.from_recorded` expects. This is
the offline source of truth for ``learn progress``/``learn next``: it is
written to by ``learn record`` (never by a subject CLI directly) and read by
every motivation computation. Append-only by design — nothing here ever
rewrites or deletes a row, so the sync cursor (:mod:`learn.profile._syncstate`)
can track "pushed so far" as a simple row count.

The ledger is learner data: the file is created ``0600`` (like ``auth.json``),
and a malformed line — a crash mid-append, a manual edit — is skipped rather
than crashing every ``progress``/``next``/sync flow. Because the ledger is
append-only and a malformed line never becomes valid, skipping is stable, so
the sync cursor's count-of-valid-rows arithmetic stays consistent across runs.
"""

from __future__ import annotations

import json
import os
from typing import Any

from learn.profile._paths import ensure_store_dir, ledger_path

#: Learner data is private to the local user, like ``auth.json``.
_LEDGER_MODE = 0o600


def append_ledger(row: dict[str, Any]) -> None:
    """Append one row to the local ledger, creating the store dir if needed."""
    ensure_store_dir()
    path = ledger_path()
    created = not path.exists()
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False))
        handle.write("\n")
    if created:
        os.chmod(path, _LEDGER_MODE)


def read_ledger() -> list[dict[str, Any]]:
    """Read every valid row, in append order. Empty list when no ledger exists yet.

    A line that fails to parse (or parses to a non-object) is skipped — one
    corrupt row must not take down ``progress``/``next``/sync.
    """
    path = ledger_path()
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                rows.append(parsed)
    return rows


def ledger_count() -> int:
    return len(read_ledger())
