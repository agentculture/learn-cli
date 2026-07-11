"""Tests for ``learn admin`` — the admin-only CLI read surface (task t8).

Follows the same authenticated-API pattern as ``learn auth`` (device-flow
session stored locally, then a Bearer-token call against the learn API) —
see ``tests/test_auth_cli.py`` for the sibling tests this mirrors. The
server enforces the GitHub-id allow-list (spec c12/h4); this CLI verb makes
no admin decision of its own, it just surfaces whatever the server says.
"""

from __future__ import annotations

import json

import pytest

from learn.cli import main


def _admin_payload() -> dict:
    return {
        "schema_version": "1.0",
        "kind": "admin_learners",
        "count": 2,
        "learners": [
            {
                "github_user_id": "1",
                "display_name": "Admin",
                "created_at": "2026-01-01T00:00:00.000Z",
                "visibility": "private",
                "consent": {"terms_version": "1.0.0", "granted_at": "2026-01-01T00:00:00.000Z"},
                "consent_status": "current",
                "records": {},
                "records_total": 0,
            },
            {
                "github_user_id": "42",
                "display_name": "Ada",
                "created_at": "2026-02-01T00:00:00.000Z",
                "visibility": "public",
                "consent": {"terms_version": "1.0.0", "granted_at": "2026-02-01T00:00:00.000Z"},
                "consent_status": "current",
                "records": {"french": 2},
                "records_total": 2,
            },
        ],
    }


def _sign_in(profile_home) -> None:
    from learn import profile as p

    p.save_auth(
        p.AuthState(
            token="tok-admin",
            token_type="Bearer",
            expires_at=9999999999,
            github_user_id="1",
            display_name="Admin",
        )
    )


# --- learn admin learners ----------------------------------------------------


def test_admin_learners_requires_sign_in(profile_home, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["admin", "learners", "--json"])
    assert rc == 1
    err = json.loads(capsys.readouterr().err)
    assert "not signed in" in err["message"]


def test_admin_learners_happy_path_json(
    profile_home, fake_api, capsys: pytest.CaptureFixture[str]
) -> None:
    _sign_in(profile_home)
    fake_api.on("GET", "/admin/learners", (200, _admin_payload()))

    rc = main(["admin", "learners", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["count"] == 2
    assert out["learners"][1]["github_user_id"] == "42"

    # Sent the stored bearer token, hit the right path.
    req = next(r for r in fake_api.requests if r["path"] == "/admin/learners")
    assert req["headers"]["Authorization"] == "Bearer tok-admin"


def test_admin_learners_text_mode_lists_every_learner(
    profile_home, fake_api, capsys: pytest.CaptureFixture[str]
) -> None:
    _sign_in(profile_home)
    fake_api.on("GET", "/admin/learners", (200, _admin_payload()))

    rc = main(["admin", "learners"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Admin" in out
    assert "Ada" in out
    assert "42" in out


def test_admin_learners_server_403_surfaces_as_environment_error(
    profile_home, fake_api, capsys: pytest.CaptureFixture[str]
) -> None:
    _sign_in(profile_home)
    fake_api.on(
        "GET",
        "/admin/learners",
        (
            403,
            {"error": "admin_required", "message": "This route is restricted to the learn admin."},
        ),
    )

    rc = main(["admin", "learners", "--json"])
    assert rc == 2
    err = json.loads(capsys.readouterr().err)
    assert "could not list learners" in err["message"]


def test_admin_learners_network_failure_is_environment_error(
    profile_home, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _sign_in(profile_home)
    monkeypatch.setenv("LEARN_API_URL", "http://127.0.0.1:1")  # nothing listens here
    rc = main(["admin", "learners", "--json"])
    assert rc == 2
    err = json.loads(capsys.readouterr().err)
    assert "could not list learners" in err["message"]


# --- learn admin overview ----------------------------------------------------


def test_admin_overview_text(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["admin", "overview"])
    assert rc == 0
    assert "# learn admin" in capsys.readouterr().out


def test_admin_overview_json_shape(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["admin", "overview", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["subject"] == "learn admin"
    assert payload["sections"]


def test_bare_admin_noun_prints_overview(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["admin"])
    assert rc == 0
    assert capsys.readouterr().out.strip()


def test_admin_overview_unknown_flag_structured_error(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["admin", "overview", "--bogus"])
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert err.startswith("error:")
    assert "hint:" in err
