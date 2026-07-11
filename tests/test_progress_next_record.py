"""Tests for ``learn progress``, ``learn next``, and ``learn record``.

Covers the acceptance criteria: ``record`` proxies to a subject CLI (the
``fourthlang`` fixture, driven purely as a subprocess) and appends to the
local ledger; ``progress`` blends the fixture subject's own facts with that
ledger; ``next`` renders a typed recommendation from the same blend; and the
anonymous path never makes an HTTP call.
"""

from __future__ import annotations

import json

import pytest

from learn.cli import main
from tests.conftest import entry


@pytest.fixture
def fourthlang_registry(install_registry, conformant_prefix):
    install_registry([entry("fourthlang", conformant_prefix)])


# --- record ------------------------------------------------------------------


def test_record_proxies_to_subject_and_ledgers_locally(
    profile_home, fourthlang_registry, capsys: pytest.CaptureFixture[str]
) -> None:
    from learn import profile as p

    rc = main(
        [
            "record",
            "fourthlang",
            "--item",
            "greetings",
            "--result",
            "pass",
            "--activity",
            "lesson",
            "--json",
        ]
    )
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["subject"] == "fourthlang"
    assert out["recorded"]["item_id"] == "greetings"
    assert out["recorded"]["result"] == "pass"
    assert out["mastery"] == {"item_id": "greetings", "level": "mastered"}
    assert out["sync"]["signed_in"] is False

    rows = p.read_ledger()
    assert len(rows) == 1
    assert rows[0]["subject"] == "fourthlang"
    assert rows[0]["item_id"] == "greetings"
    assert rows[0]["activity"] == "lesson"
    assert rows[0]["result"] == "pass"


def test_record_passes_optional_counters_through(
    profile_home, fourthlang_registry, capsys: pytest.CaptureFixture[str]
) -> None:
    from learn import profile as p

    rc = main(
        [
            "record",
            "fourthlang",
            "--item",
            "numbers",
            "--result",
            "partial",
            "--correct",
            "2",
            "--total",
            "3",
            "--duration-seconds",
            "45",
            "--json",
        ]
    )
    assert rc == 0
    row = p.read_ledger()[0]
    assert row["correct"] == 2
    assert row["total"] == 3
    assert row["duration_seconds"] == 45.0


def test_record_unknown_subject_is_user_error(
    profile_home, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["record", "klingon", "--item", "x", "--result", "pass", "--json"])
    err = json.loads(capsys.readouterr().err)
    assert rc == 1
    assert "unknown subject" in err["message"]


def test_record_bad_result_choice_is_structured_error(
    profile_home, fourthlang_registry, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["record", "fourthlang", "--item", "x", "--result", "bogus", "--json"])
    assert exc.value.code == 1
    err = json.loads(capsys.readouterr().err)
    assert "invalid choice" in err["message"]


def test_record_signed_in_syncs_to_the_api(
    profile_home, fake_api, fourthlang_registry, capsys: pytest.CaptureFixture[str]
) -> None:
    from learn import profile as p

    p.save_auth(
        p.AuthState(
            token="tok-1",
            token_type="Bearer",
            expires_at=None,
            github_user_id="1",
            display_name="X",
        )
    )
    fake_api.on("POST", "/record", (201, {"kind": "record_ack"}))

    rc = main(["record", "fourthlang", "--item", "greetings", "--result", "pass", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["sync"] == {
        "signed_in": True,
        "attempted": 1,
        "synced": 1,
        "pending": 0,
        "ok": True,
        "error": None,
    }
    record_requests = [r for r in fake_api.requests if r["path"] == "/record"]
    assert len(record_requests) == 1
    assert record_requests[0]["headers"]["Authorization"] == "Bearer tok-1"
    assert record_requests[0]["body"]["subject"] == "fourthlang"
    assert record_requests[0]["body"]["recorded"]["item_id"] == "greetings"

    assert p.load_sync_state().cursor == 1


def test_record_signed_in_but_offline_never_fails_the_command(
    profile_home,
    fourthlang_registry,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from learn import profile as p

    p.save_auth(
        p.AuthState(
            token="tok-1",
            token_type="Bearer",
            expires_at=None,
            github_user_id="1",
            display_name="X",
        )
    )
    monkeypatch.setenv("LEARN_API_URL", "http://127.0.0.1:1")  # unreachable

    rc = main(["record", "fourthlang", "--item", "greetings", "--result", "pass", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0  # the command still succeeds — the row is ledgered locally
    assert out["sync"]["ok"] is False
    assert out["sync"]["synced"] == 0
    assert out["sync"]["pending"] == 1
    assert out["sync"]["error"]
    assert len(p.read_ledger()) == 1
    assert p.load_sync_state().cursor == 0  # nothing pushed yet — will retry next time


def test_record_anonymous_never_touches_the_network(
    profile_home, fourthlang_registry, no_network
) -> None:
    rc = main(["record", "fourthlang", "--item", "greetings", "--result", "pass", "--json"])
    assert rc == 0  # would have raised via no_network if it had tried a request


# --- progress ------------------------------------------------------------------


def test_progress_blends_subject_facts_with_ledger(
    profile_home, fourthlang_registry, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["record", "fourthlang", "--item", "greetings", "--result", "pass", "--json"])
    capsys.readouterr()

    rc = main(["progress", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert len(out["subjects"]) == 1
    row = out["subjects"][0]
    assert row["subject"] == "fourthlang"
    assert row["available"] is True
    # facts straight from the fixture's `progress` payload:
    assert row["items_total"] == 3
    # ledger-derived numbers only learn-cli's motivation layer can produce:
    assert row["score"] == 100
    assert row["streak"]["current_days"] == 1
    assert row["streak"]["active_today"] is True
    assert row["item_history"] == [
        {
            "item_id": "greetings",
            "mastery": "mastered",
            "last_seen": row["item_history"][0]["last_seen"],
            "entry_count": 1,
            "last_result": "pass",
        }
    ]
    assert out["overall"]["ledger_rows"] == 1
    assert out["overall"]["streak"]["current_days"] == 1


def test_progress_single_subject_filter(profile_home, fourthlang_registry, capsys) -> None:
    rc = main(["progress", "fourthlang", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert [s["subject"] for s in out["subjects"]] == ["fourthlang"]


def test_progress_unknown_subject_is_user_error(profile_home, capsys) -> None:
    rc = main(["progress", "klingon", "--json"])
    err = json.loads(capsys.readouterr().err)
    assert rc == 1
    assert "unknown subject" in err["message"]


def test_progress_reports_uninstalled_subject_gracefully(profile_home, capsys) -> None:
    # The shipped registry (french/spanish/culture-guide) isn't installed here.
    rc = main(["progress", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["subjects"]
    for row in out["subjects"]:
        assert row["available"] is False
        assert row["note"]


def test_progress_text_mode_renders(profile_home, fourthlang_registry, capsys) -> None:
    rc = main(["progress"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "fourthlang" in out
    assert "overall streak" in out


def test_progress_never_touches_the_network(profile_home, fourthlang_registry, no_network) -> None:
    rc = main(["progress", "--json"])
    assert rc == 0


# --- next ----------------------------------------------------------------------


def test_next_returns_a_typed_recommendation(
    profile_home, fourthlang_registry, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["next", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["action"] in {"next_lesson", "review_batch", "harder_repeat", "fresh_story"}
    assert out["mode"] in {"progress", "maintenance"}
    assert "reason" in out


def test_next_prefers_forward_progress_for_a_fresh_subject(
    profile_home, fourthlang_registry, capsys: pytest.CaptureFixture[str]
) -> None:
    # The fixture's `progress` always reports done=False -> plenty of new material.
    rc = main(["next", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["action"] == "next_lesson"
    assert out["subject"] == "fourthlang"


def test_next_text_mode_renders(profile_home, fourthlang_registry, capsys) -> None:
    rc = main(["next"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "next:" in out


def test_next_never_touches_the_network(profile_home, fourthlang_registry, no_network) -> None:
    rc = main(["next", "--json"])
    assert rc == 0
