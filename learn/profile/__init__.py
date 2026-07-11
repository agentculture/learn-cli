"""learn-cli's cross-subject learner profile — local state + optional sync.

The **local ledger is always the source of truth for this device**: every verb
built on this package (``learn progress``, ``learn next``, ``learn record``)
works fully offline with no ``auth.json`` on disk — sign-in
(:func:`learn auth login`) only adds continuity across devices by pushing the
local ledger to the learn API (``workers/learn-api``, t11). Anonymous use is
never degraded: it is the default, not a fallback.

Storage layout (see :mod:`learn.profile._paths` for the resolution order —
``$LEARN_CLI_HOME`` > ``$XDG_DATA_HOME/learn_cli`` > ``~/.local/share/learn_cli``):

* ``ledger.jsonl`` — append-only cross-subject ledger; rows are the contract's
  ``recorded`` object plus a ``subject`` field, exactly what
  :func:`learn.motivation.LedgerEntry.from_recorded` parses.
* ``auth.json`` — the linked learner's device-flow session (token, expiry,
  GitHub identity), ``0600``. Absent when signed out.
* ``sync.json`` — the one-way push cursor (:mod:`learn.profile._sync`).

Public API
----------

* :func:`append_ledger`, :func:`read_ledger`, :func:`ledger_count` — the local
  ledger.
* :class:`AuthState`, :func:`load_auth`, :func:`save_auth`, :func:`clear_auth`
  — the stored session.
* :class:`SyncState`, :func:`load_sync_state`, :func:`save_sync_state` — the
  sync cursor.
* :func:`device_start`, :func:`device_poll`, :func:`device_logout`,
  :func:`fetch_me`, :func:`push_record`, :func:`admin_list_learners`,
  :class:`ApiError`, :func:`api_base` — the learn API client.
* :class:`SyncResult`, :func:`push_pending`, :func:`pending_sync_count` — the
  one-way sync push.
"""

from __future__ import annotations

from learn.profile._api import (
    API_URL_ENV,
    DEFAULT_API_URL,
    DEFAULT_TIMEOUT,
    ApiError,
    admin_list_learners,
    api_base,
    device_logout,
    device_poll,
    device_start,
    fetch_me,
    push_record,
)
from learn.profile._auth import AuthState, clear_auth, load_auth, save_auth
from learn.profile._ledger import append_ledger, ledger_count, read_ledger
from learn.profile._paths import (
    LEARN_CLI_HOME_ENV,
    XDG_DATA_HOME_ENV,
    auth_path,
    ensure_store_dir,
    ledger_path,
    store_dir,
    sync_path,
)
from learn.profile._sync import SyncResult, pending_sync_count, push_pending
from learn.profile._syncstate import SyncState, load_sync_state, save_sync_state

__all__ = [
    # ledger
    "append_ledger",
    "read_ledger",
    "ledger_count",
    # auth
    "AuthState",
    "load_auth",
    "save_auth",
    "clear_auth",
    # sync state
    "SyncState",
    "load_sync_state",
    "save_sync_state",
    # sync push
    "SyncResult",
    "push_pending",
    "pending_sync_count",
    # api client
    "ApiError",
    "api_base",
    "device_start",
    "device_poll",
    "device_logout",
    "fetch_me",
    "push_record",
    "admin_list_learners",
    "DEFAULT_API_URL",
    "API_URL_ENV",
    "DEFAULT_TIMEOUT",
    # paths
    "store_dir",
    "ensure_store_dir",
    "ledger_path",
    "auth_path",
    "sync_path",
    "LEARN_CLI_HOME_ENV",
    "XDG_DATA_HOME_ENV",
]
