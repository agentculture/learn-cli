"""Launch-gate E2E fixtures — the CLI (golden --json) and agent (MCP) audience
tests.

These drive the REAL sibling subject CLIs (french / spanish / culture-guide) as
subprocesses, so they only run inside the launch gate, never the normal suite.
Two guards keep ``uv run pytest -n auto`` fast and green without them:

* every test here is skipped unless ``RUN_LAUNCH_GATE=1`` (set by
  ``tools/launch-gate/run.sh``), so the default run collects but skips them;
* when the gate runs them and ``LAUNCH_GATE_RESULTS`` points at a file, each
  test's outcome is appended there as one NDJSON line, so the gate's report can
  fold the CLI/agent audiences into the same PASS/FAIL table as the web walk.

The gate's ``run.sh`` puts the three subject ``.venv/bin`` dirs on PATH before
invoking pytest, so the ``learn`` console script and the ``french`` / ``spanish``
/ ``culture-guide`` executables all resolve.
"""

from __future__ import annotations

import json
import os

import pytest

RUN_LAUNCH_GATE = os.environ.get("RUN_LAUNCH_GATE") == "1"

# The three subjects and a valid lesson item id in each — the scored lesson flow.
SUBJECT_LESSON_ITEMS = {
    "french": "fr.greetings.bonjour",
    "spanish": "es.saludos.hola",
    "culture-guide": "tokens",
}


def pytest_runtest_setup(item: pytest.Item) -> None:
    if not RUN_LAUNCH_GATE:
        pytest.skip("launch-gate E2E test — set RUN_LAUNCH_GATE=1 (see tools/launch-gate/run.sh)")


def _audience_for(nodeid: str) -> str:
    if "test_cli_golden" in nodeid:
        return "cli"
    if "test_mcp_harness" in nodeid:
        return "agent"
    return "e2e"


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    results_file = os.environ.get("LAUNCH_GATE_RESULTS")
    # Only record the actual test-body outcome (the "call" phase), so a skipped
    # test (setup-phase skip when the gate isn't active) writes nothing.
    if not results_file or report.when != "call":
        return
    status = "PASS" if report.passed else "FAIL"
    check = report.nodeid.split("::", 1)[-1]
    line = {
        "audience": _audience_for(report.nodeid),
        "check": check,
        "status": status,
        "detail": "" if report.passed else str(report.longrepr).splitlines()[-1][:200],
    }
    with open(results_file, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(line) + "\n")


@pytest.fixture
def isolated_profile(tmp_path, monkeypatch):
    """Point the learn profile AND each subject's own state at a fresh temp dir.

    ``LEARN_CLI_HOME`` isolates learn's cross-subject ledger; ``XDG_DATA_HOME``
    isolates the subject CLIs' own learner-state dirs (french resolves
    ``$XDG_DATA_HOME/french_cli/learn``), so every run starts from zero mastery
    and is repeatable. ``LEARN_API_URL`` points at an unreachable port so the
    offline (signed-out) sync path is exercised deterministically.
    """
    home = tmp_path / "learn-home"
    xdg = tmp_path / "xdg"
    home.mkdir()
    xdg.mkdir()
    monkeypatch.setenv("LEARN_CLI_HOME", str(home))
    monkeypatch.setenv("XDG_DATA_HOME", str(xdg))
    monkeypatch.setenv("LEARN_API_URL", "http://127.0.0.1:9/learn/api")
    return {"home": home, "xdg": xdg}
