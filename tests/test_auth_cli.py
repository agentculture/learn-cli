"""Tests for ``learn auth`` — the device-flow login, logout, status, overview.

Uses the ``fake_api`` fixture (a real localhost ``http.server``, see
``tests/conftest.py``) standing in for ``workers/learn-api``'s
``POST /api/auth/device`` — a pending→complete poll sequence, exactly like the
real GitHub-backed worker. ``time.sleep`` is patched to a no-op so the poll
loop runs at test speed.
"""

from __future__ import annotations

import json
import time

import pytest

from learn.cli import main


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)


def _device_handler(poll_count: dict, learner: dict):
    def handler(body: dict) -> tuple[int, dict]:
        if body.get("action") == "start":
            return 200, {
                "device_code": "dc_123",
                "user_code": "WXYZ-1234",
                "verification_uri": "https://github.com/login/device",
                "expires_in": 60,
                "interval": 1,
            }
        assert body.get("action") == "poll"
        assert body.get("device_code") == "dc_123"
        poll_count["n"] += 1
        if poll_count["n"] < 2:
            return 200, {"status": "pending"}
        return 200, {
            "status": "complete",
            "token": "tok-abc",
            "token_type": "Bearer",
            "expires_at": 9999999999,
            "learner": learner,
        }

    return handler


# --- auth login: device flow -------------------------------------------------


def test_auth_login_happy_path_pending_then_complete(
    profile_home, fake_api, capsys: pytest.CaptureFixture[str]
) -> None:
    poll_count = {"n": 0}
    learner = {"github_user_id": "42", "display_name": "Ada"}
    fake_api.on("POST", "/auth/device", _device_handler(poll_count, learner))

    rc = main(["auth", "login", "--json"])
    out = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert out["signed_in"] is True
    assert out["learner"] == learner
    # It really polled more than once (pending, then complete).
    assert poll_count["n"] >= 2

    from learn import profile as p

    state = p.load_auth()
    assert state is not None
    assert state.token == "tok-abc"
    assert state.github_user_id == "42"
    assert state.display_name == "Ada"


def test_auth_login_prints_verification_uri_and_code_to_stderr(
    profile_home, fake_api, capsys: pytest.CaptureFixture[str]
) -> None:
    poll_count = {"n": 0}
    learner = {"github_user_id": "1", "display_name": "X"}
    fake_api.on("POST", "/auth/device", _device_handler(poll_count, learner))

    main(["auth", "login"])
    err = capsys.readouterr().err
    assert "https://github.com/login/device" in err
    assert "WXYZ-1234" in err


def test_auth_login_times_out_waiting_for_confirmation(
    profile_home, fake_api, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_api.on(
        "POST",
        "/auth/device",
        lambda body: (
            (
                200,
                {
                    "device_code": "dc_1",
                    "user_code": "AAAA-1111",
                    "verification_uri": "https://github.com/login/device",
                    "expires_in": 2,
                    "interval": 1,
                },
            )
            if body.get("action") == "start"
            else (200, {"status": "pending"})
        ),
    )
    rc = main(["auth", "login", "--json"])
    assert rc == 2
    # stderr carries the verification-code diagnostic *and* the JSON error line.
    err = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert "timed out" in err["message"]


def test_auth_login_network_failure_on_start_is_environment_error(
    profile_home, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("LEARN_API_URL", "http://127.0.0.1:1")  # nothing listens here
    rc = main(["auth", "login", "--json"])
    assert rc == 2
    err = json.loads(capsys.readouterr().err)
    assert "could not start" in err["message"]


# --- auth logout -------------------------------------------------------------


def test_auth_logout_with_no_session(profile_home, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["auth", "logout", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out == {"signed_out": True, "had_session": False, "server_revoked": False}


def test_auth_logout_clears_local_session_even_if_server_call_fails(
    profile_home, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from learn import profile as p

    p.save_auth(
        p.AuthState(
            token="tok", token_type="Bearer", expires_at=None, github_user_id="1", display_name="X"
        )
    )
    monkeypatch.setenv("LEARN_API_URL", "http://127.0.0.1:1")  # unreachable -> ApiError, swallowed

    rc = main(["auth", "logout", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["had_session"] is True
    assert out["server_revoked"] is False
    assert p.load_auth() is None


def test_auth_logout_revokes_server_side_when_reachable(
    profile_home, fake_api, capsys: pytest.CaptureFixture[str]
) -> None:
    from learn import profile as p

    p.save_auth(
        p.AuthState(
            token="tok", token_type="Bearer", expires_at=None, github_user_id="1", display_name="X"
        )
    )
    fake_api.on("POST", "/auth/logout", (200, {"ok": True}))

    rc = main(["auth", "logout", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["server_revoked"] is True
    assert any(r["path"] == "/auth/logout" for r in fake_api.requests)


# --- auth status --------------------------------------------------------------


def test_auth_status_signed_out(profile_home, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["auth", "status", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out == {"signed_in": False}


def test_auth_status_signed_in_reports_sync_pending(
    profile_home, capsys: pytest.CaptureFixture[str]
) -> None:
    from learn import profile as p

    p.save_auth(
        p.AuthState(
            token="tok",
            token_type="Bearer",
            expires_at=1234,
            github_user_id="9",
            display_name="Grace",
        )
    )
    p.append_ledger({"subject": "french", "item_id": "a", "activity": "lesson", "result": "pass"})
    p.append_ledger({"subject": "french", "item_id": "b", "activity": "lesson", "result": "pass"})
    p.save_sync_state(p.SyncState(cursor=1))

    rc = main(["auth", "status", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["signed_in"] is True
    assert out["learner"]["display_name"] == "Grace"
    assert out["sync"] == {"pushed": 1, "ledger_rows": 2, "pending": 1}


def test_auth_status_never_touches_network(profile_home, no_network) -> None:
    from learn import profile as p

    p.save_auth(
        p.AuthState(
            token="tok", token_type="Bearer", expires_at=None, github_user_id="1", display_name="X"
        )
    )
    rc = main(["auth", "status", "--json"])
    assert rc == 0  # would have raised via no_network if it had tried a request


# --- auth overview -------------------------------------------------------------


def test_auth_overview_text(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["auth", "overview"])
    assert rc == 0
    assert "# learn auth" in capsys.readouterr().out


def test_auth_overview_json_shape(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["auth", "overview", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["subject"] == "learn auth"
    assert payload["sections"]


def test_bare_auth_noun_prints_overview(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["auth"])
    assert rc == 0
    assert capsys.readouterr().out.strip()


def test_auth_overview_unknown_flag_structured_error(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["auth", "overview", "--bogus"])
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert err.startswith("error:")
    assert "hint:" in err
