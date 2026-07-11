"""Tests for the local profile store (``learn/profile``): paths, ledger, auth,
and the one-way sync cursor. No CLI, no network — just the storage layer.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from learn import profile as p

# --- paths -------------------------------------------------------------


def test_store_dir_honours_learn_cli_home(profile_home) -> None:
    assert p.store_dir() == profile_home


def test_store_dir_falls_back_to_xdg_data_home(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LEARN_CLI_HOME", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", os.fspath(tmp_path))
    assert p.store_dir() == tmp_path / "learn_cli"


def test_store_dir_falls_back_to_home_local_share(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LEARN_CLI_HOME", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    assert p.store_dir() == Path.home() / ".local" / "share" / "learn_cli"


def test_ensure_store_dir_creates_it(profile_home) -> None:
    assert not profile_home.exists()
    created = p.ensure_store_dir()
    assert created == profile_home
    assert profile_home.is_dir()


# --- ledger --------------------------------------------------------------


def test_read_ledger_empty_when_no_file(profile_home) -> None:
    assert p.read_ledger() == []
    assert p.ledger_count() == 0


def test_append_and_read_ledger_round_trips(profile_home) -> None:
    row1 = {"subject": "french", "item_id": "greetings", "activity": "lesson", "result": "pass"}
    row2 = {"subject": "spanish", "item_id": "hola", "activity": "practice", "result": "partial"}
    p.append_ledger(row1)
    p.append_ledger(row2)
    rows = p.read_ledger()
    assert rows == [row1, row2]
    assert p.ledger_count() == 2


def test_ledger_file_is_one_json_object_per_line(profile_home) -> None:
    p.append_ledger({"subject": "french", "item_id": "a", "activity": "lesson", "result": "pass"})
    p.append_ledger({"subject": "french", "item_id": "b", "activity": "lesson", "result": "pass"})
    lines = p.ledger_path().read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2


def test_read_ledger_skips_blank_lines(profile_home) -> None:
    p.ensure_store_dir()
    p.ledger_path().write_text(
        '{"subject": "french", "item_id": "a", "activity": "lesson", "result": "pass"}\n\n',
        encoding="utf-8",
    )
    assert len(p.read_ledger()) == 1


# --- auth state ------------------------------------------------------------


def test_load_auth_none_when_absent(profile_home) -> None:
    assert p.load_auth() is None


def test_save_and_load_auth_round_trips(profile_home) -> None:
    state = p.AuthState(
        token="tok-abc",
        token_type="Bearer",
        expires_at=1234567890,
        github_user_id="42",
        display_name="Ada",
    )
    p.save_auth(state)
    loaded = p.load_auth()
    assert loaded == state


def test_save_auth_chmods_0600(profile_home) -> None:
    state = p.AuthState(
        token="tok-abc",
        token_type="Bearer",
        expires_at=None,
        github_user_id="42",
        display_name="Ada",
    )
    p.save_auth(state)
    mode = stat.S_IMODE(p.auth_path().stat().st_mode)
    assert mode == stat.S_IRUSR | stat.S_IWUSR


def test_load_auth_tolerates_corrupt_file(profile_home) -> None:
    p.ensure_store_dir()
    p.auth_path().write_text("not json at all", encoding="utf-8")
    assert p.load_auth() is None


def test_clear_auth_removes_file_and_reports_prior_state(profile_home) -> None:
    assert p.clear_auth() is False
    p.save_auth(
        p.AuthState(
            token="t", token_type="Bearer", expires_at=None, github_user_id="1", display_name="X"
        )
    )
    assert p.clear_auth() is True
    assert p.load_auth() is None


# --- sync state --------------------------------------------------------------


def test_load_sync_state_defaults_to_zero_cursor(profile_home) -> None:
    state = p.load_sync_state()
    assert state.cursor == 0


def test_save_and_load_sync_state_round_trips(profile_home) -> None:
    p.save_sync_state(p.SyncState(cursor=3))
    assert p.load_sync_state().cursor == 3


def test_pending_sync_count_reflects_cursor(profile_home) -> None:
    for i in range(3):
        p.append_ledger(
            {"subject": "french", "item_id": str(i), "activity": "lesson", "result": "pass"}
        )
    assert p.pending_sync_count() == 3
    p.save_sync_state(p.SyncState(cursor=2))
    assert p.pending_sync_count() == 1
    p.save_sync_state(p.SyncState(cursor=10))  # never negative even if cursor overshoots
    assert p.pending_sync_count() == 0
