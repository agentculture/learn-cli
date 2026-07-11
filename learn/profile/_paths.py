"""XDG-style local state paths for the cross-subject learner profile.

Resolution order for the store directory (first hit wins):

1. ``$LEARN_CLI_HOME`` — an explicit override (tests, containers, a pinned dev
   checkout).
2. ``$XDG_DATA_HOME/learn_cli`` — the XDG base-dir spec, when the caller's
   environment sets it.
3. ``~/.local/share/learn_cli`` — the XDG default.

Nothing here touches the network or a subject CLI; it only resolves paths. The
directory is created lazily (:func:`ensure_store_dir`) the first time something
is written, so a read-only `learn progress`/`learn next` on a brand-new machine
never creates files it doesn't need.
"""

from __future__ import annotations

import os
from pathlib import Path

#: Highest-priority override — points straight at the store directory.
LEARN_CLI_HOME_ENV = "LEARN_CLI_HOME"

#: XDG base-dir env var; ``learn_cli`` is nested under it when set.
XDG_DATA_HOME_ENV = "XDG_DATA_HOME"

#: The append-only cross-subject ledger: one JSON object per line, each the
#: contract's ``recorded`` object plus a ``subject`` field.
LEDGER_FILENAME = "ledger.jsonl"

#: The stored device-flow session: token, expiry, and linked learner identity.
AUTH_FILENAME = "auth.json"

#: The one-way sync cursor: how many ledger rows have been pushed to the API.
SYNC_FILENAME = "sync.json"


def store_dir() -> Path:
    """Resolve the profile store directory, honouring the override chain."""
    override = os.environ.get(LEARN_CLI_HOME_ENV)
    if override:
        return Path(override)
    xdg = os.environ.get(XDG_DATA_HOME_ENV)
    if xdg:
        return Path(xdg) / "learn_cli"
    return Path.home() / ".local" / "share" / "learn_cli"


def ensure_store_dir() -> Path:
    """Resolve the store directory and make sure it exists on disk."""
    directory = store_dir()
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def ledger_path() -> Path:
    return store_dir() / LEDGER_FILENAME


def auth_path() -> Path:
    return store_dir() / AUTH_FILENAME


def sync_path() -> Path:
    return store_dir() / SYNC_FILENAME
