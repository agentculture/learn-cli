"""The local append-only cross-subject ledger (``ledger.jsonl``).

One JSON object per line: the contract's ``recorded`` object (see
``learn/contract/schemas/record.json``) plus a ``subject`` field — exactly the
row shape :func:`learn.motivation.LedgerEntry.from_recorded` expects. This is
the offline source of truth for ``learn progress``/``learn next``: it is
written to by ``learn record`` (never by a subject CLI directly) and read by
every motivation computation. Append-only by design — nothing here ever
rewrites or deletes a row, so the sync cursor (:mod:`learn.profile._syncstate`)
can track "pushed so far" as a simple row count.
"""

from __future__ import annotations

import json
from typing import Any

from learn.profile._paths import ensure_store_dir, ledger_path


def append_ledger(row: dict[str, Any]) -> None:
    """Append one row to the local ledger, creating the store dir if needed."""
    ensure_store_dir()
    with ledger_path().open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False))
        handle.write("\n")


def read_ledger() -> list[dict[str, Any]]:
    """Read every row, in append order. Empty list when the ledger doesn't exist yet."""
    path = ledger_path()
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            rows.append(json.loads(stripped))
    return rows


def ledger_count() -> int:
    return len(read_ledger())
