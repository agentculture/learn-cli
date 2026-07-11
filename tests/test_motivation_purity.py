"""Structural guards on the motivation layer's purity.

These assert the invariants the acceptance criteria hang on: no wall clock and no
LLM/network anywhere in the scoring path, agreement with the contract's shared
vocabularies, and that the ledger-parsing layer round-trips the contract's
``recorded`` object faithfully.
"""

from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path

from learn import contract
from learn import motivation as m

MOTIVATION_DIR = Path(m.__file__).parent
SOURCES = sorted(MOTIVATION_DIR.glob("*.py"))

# Names that would let logic read the wall clock or reach a model/network.
_FORBIDDEN_CALLS = {"now", "utcnow", "today", "time", "monotonic", "perf_counter"}
_FORBIDDEN_IMPORTS = {
    "requests",
    "httpx",
    "urllib",
    "socket",
    "http",
    "aiohttp",
    "openai",
    "anthropic",
    "boto3",
    "random",
    "secrets",
}


def test_no_wall_clock_call_in_any_source() -> None:
    """No datetime.now()/utcnow()/time() etc. — every time input must be explicit."""
    offenders: list[str] = []
    for path in SOURCES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in _FORBIDDEN_CALLS:
                    offenders.append(f"{path.name}: {node.func.attr}()")
    assert offenders == [], f"wall-clock/timer calls found: {offenders}"


def test_no_network_or_llm_imports() -> None:
    """The layer stays stdlib-only and never imports a model/network client."""
    offenders: list[str] = []
    for path in SOURCES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in _FORBIDDEN_IMPORTS:
                        offenders.append(f"{path.name}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.split(".")[0] in _FORBIDDEN_IMPORTS:
                    offenders.append(f"{path.name}: from {node.module}")
    assert offenders == [], f"forbidden imports found: {offenders}"


def test_only_stdlib_and_learn_imports() -> None:
    """Every top-level import is stdlib or the learn package — no third-party dep."""
    import sys

    allowed_first_party = {"learn"}
    offenders: list[str] = []
    for path in SOURCES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            roots: list[str] = []
            if isinstance(node, ast.Import):
                roots = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                roots = [node.module.split(".")[0]]
            for root in roots:
                if root in allowed_first_party or root == "__future__":
                    continue
                if root not in sys.stdlib_module_names:
                    offenders.append(f"{path.name}: {root}")
    assert offenders == [], f"non-stdlib imports found: {offenders}"


def test_vocabularies_agree_with_contract() -> None:
    """The mirrored ladder/result vocabularies match the contract's exactly."""
    assert m.MASTERY_LEVELS == contract.MASTERY_LEVELS
    assert m.RESULTS == tuple(contract.RESULTS)


def test_recorded_object_round_trips_through_ledger_entry() -> None:
    """A contract 'recorded' object parses into a faithful LedgerEntry."""
    recorded = {
        "item_id": "numbers-money",
        "activity": "practice",
        "exercise_id": "nm-p1",
        "result": "pass",
        "correct": 1,
        "total": 1,
        "duration_seconds": 38.0,
        "notes": "Solid.",
        "at": "2026-07-11T09:14:22+00:00",
    }
    entry = m.LedgerEntry.from_recorded(recorded, subject="french")
    assert entry.subject == "french"
    assert entry.item_id == "numbers-money"
    assert entry.activity == "practice"
    assert entry.result == "pass"
    assert entry.correct == 1 and entry.total == 1
    assert entry.duration_seconds == 38.0
    assert entry.at == datetime(2026, 7, 11, 9, 14, 22, tzinfo=timezone.utc)
    assert entry.key == ("french", "numbers-money")


def test_ledger_entry_requires_subject_and_core_fields() -> None:
    import pytest

    with pytest.raises(ValueError):
        m.LedgerEntry.from_recorded(
            {"item_id": "x", "result": "pass", "at": "2026-07-01T00:00:00Z"}
        )
    with pytest.raises(ValueError):
        m.LedgerEntry.from_recorded(
            {"result": "pass", "at": "2026-07-01T00:00:00Z"}, subject="french"
        )


def test_subject_key_is_read_from_row_when_present() -> None:
    row = {
        "subject": "spanish",
        "item_id": "x",
        "activity": "practice",
        "result": "pass",
        "at": "2026-07-01T00:00:00Z",
    }
    (entry,) = m.parse_ledger([row])
    assert entry.subject == "spanish"


def test_parse_timestamp_handles_z_suffix() -> None:
    assert m.parse_timestamp("2026-07-01T00:00:00Z") == datetime(2026, 7, 1, tzinfo=timezone.utc)
