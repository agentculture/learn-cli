"""Agent audience acceptance test — the MCP face of the scripted success walk.

Drives learn-cli's real agentfront App (the same registry the CLI and site
derive from) over ``call_mcp`` against the three real subject CLIs, and asserts
parity (b): the numbers an agent sees over MCP are IDENTICAL to the numbers the
CLI shows, because both faces drive the same subject subprocess from the same
isolated state. That's the "local-ledger faces agree with each other" half of the
gate's parity claim (the "synced rows appear in the API-backed web view" half is
proven by tools/launch-gate/walk.mjs's browser + CLI bridge).
"""

from __future__ import annotations

import json
import subprocess  # nosec B404 - the CLI cross-check drives the real learn CLI

import pytest
from agentfront.testing import call_mcp

from learn.front import build_app
from tests.e2e.conftest import SUBJECT_LESSON_ITEMS

SUBJECTS = tuple(SUBJECT_LESSON_ITEMS.items())


def _learn_progress(subject: str) -> dict:
    proc = subprocess.run(  # nosec B603 B607 - literal argv; PATH set by run.sh
        ["learn", "progress", subject, "--json"],
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    assert proc.returncode == 0, f"learn progress {subject} exited {proc.returncode}: {proc.stderr}"
    return json.loads(proc.stdout)["subjects"][0]


def test_mcp_harness_lists_three_installed_subjects(isolated_profile) -> None:
    app = build_app()
    result = call_mcp(app, ["subjects_list"], {})["result"]
    assert result["count"] == 3
    names = {row["name"] for row in result["subjects"]}
    assert names == {"french", "spanish", "culture-guide"}
    assert all(row["available"] for row in result["subjects"])


@pytest.mark.parametrize("subject,item", SUBJECTS)
def test_mcp_harness_progress_matches_cli(isolated_profile, subject, item) -> None:
    """Record a scored pass over MCP, then assert MCP progress == CLI progress."""
    app = build_app()

    # Agent write-back: the MCP `record` tool drives the subject's own record verb.
    ack = call_mcp(
        app,
        ["record"],
        {"subject": subject, "item_id": item, "result": "pass", "activity": "lesson"},
    )["result"]
    assert ack["kind"] == "record_ack"
    assert ack["mastery"]["level"] == "mastered"

    # Parity (b): both faces drive the same subject subprocess over the same
    # isolated state, so the authoritative facts must be numerically identical.
    mcp_prog = call_mcp(app, ["progress"], {"subject": subject})["result"]
    cli_row = _learn_progress(subject)

    assert mcp_prog["kind"] == "progress"
    assert mcp_prog["items_total"] == cli_row["items_total"]
    assert mcp_prog["items_touched"] == cli_row["items_touched"]
    assert mcp_prog["items_mastered"] == cli_row["items_mastered"]
    assert mcp_prog["mastery"] == cli_row["mastery"]
    # And the item we just recorded shows as mastered in both.
    assert mcp_prog["mastery"].get(item) == "mastered"
    assert cli_row["mastery"].get(item) == "mastered"


def test_mcp_harness_unknown_subject_is_structured_error(isolated_profile) -> None:
    app = build_app()
    err = call_mcp(app, ["progress"], {"subject": "nope"})["error"]
    assert err["code"] == 1
    assert "unknown subject" in err["message"]
