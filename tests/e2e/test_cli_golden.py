"""CLI audience acceptance test — the golden ``learn ... --json`` contract.

Drives the real ``learn`` console script against the three real subject CLIs and
asserts the STABLE (timestamp-free) shape and values of a scored lesson flow:
``learn record`` → ``learn progress`` → ``learn next``. This is the CLI face of
the scripted success walk; the web face is tools/launch-gate/walk.mjs and the
agent face is test_mcp_harness.py.

Parity (b), CLI internal edge: the subject-authoritative facts ``learn progress``
reports come from the same subject subprocess the MCP ``progress`` tool drives,
so test_mcp_harness asserts the two faces report identical numbers.
"""

from __future__ import annotations

import json
import subprocess  # nosec B404 - driving the real learn CLI is the test's purpose

import pytest

from learn.motivation import NextAction
from tests.e2e.conftest import SUBJECT_LESSON_ITEMS

SUBJECTS = tuple(SUBJECT_LESSON_ITEMS.items())


def _learn(*args: str) -> dict:
    proc = subprocess.run(  # nosec B603 B607 - literal argv; PATH set by run.sh
        ["learn", *args, "--json"],
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    assert proc.returncode == 0, f"learn {' '.join(args)} exited {proc.returncode}: {proc.stderr}"
    return json.loads(proc.stdout)


@pytest.mark.parametrize("subject,item", SUBJECTS)
def test_cli_golden_record_shape(isolated_profile, subject, item) -> None:
    """`learn record` emits the golden record_ack shape with a scored mastery."""
    payload = _learn("record", subject, "--item", item, "--result", "pass", "--activity", "lesson")

    assert set(payload) == {"subject", "recorded", "mastery", "next", "sync"}
    assert payload["subject"] == subject
    assert payload["recorded"]["item_id"] == item
    assert payload["recorded"]["result"] == "pass"
    assert payload["recorded"]["activity"] == "lesson"
    assert payload["mastery"]["item_id"] == item
    assert payload["mastery"]["level"] == "mastered"
    # No auth.json on disk + unreachable API → the offline, signed-out sync path.
    assert payload["sync"]["signed_in"] is False
    assert payload["sync"]["ok"] is True


@pytest.mark.parametrize("subject,item", SUBJECTS)
def test_cli_golden_progress_after_record(isolated_profile, subject, item) -> None:
    """After one scored pass, `learn progress <subject>` reflects it deterministically."""
    _learn("record", subject, "--item", item, "--result", "pass", "--activity", "lesson")
    prog = _learn("progress", subject)

    assert len(prog["subjects"]) == 1
    row = prog["subjects"][0]
    assert row["subject"] == subject
    assert row["available"] is True
    # One graded pass → mean score 100 and a 1-day streak in the local ledger.
    assert row["score"] == 100
    assert row["streak"]["current_days"] == 1
    hist = {h["item_id"]: h for h in row["item_history"]}
    assert item in hist
    assert hist[item]["mastery"] == "mastered"
    assert hist[item]["last_result"] == "pass"
    assert prog["overall"]["ledger_rows"] == 1


def test_cli_golden_next_is_actionable(isolated_profile) -> None:
    """`learn next` always returns one typed, actionable recommendation."""
    # Record across all three subjects, then ask for the single best next action.
    for subject, item in SUBJECTS:
        _learn("record", subject, "--item", item, "--result", "pass", "--activity", "lesson")
    rec = _learn("next")

    assert rec["action"] in {a.value for a in NextAction}
    assert isinstance(rec["reason"], str) and rec["reason"]
    assert isinstance(rec["mode"], str) and rec["mode"]
