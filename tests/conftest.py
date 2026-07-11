"""Shared fixtures for the subject-registry and conformance-gate tests.

The fake subject CLIs under ``tests/fixtures/subjects/`` stand in for real
subject console scripts: the conformance gate drives them purely as external
subprocesses over ``--json``. These fixtures make one executable and hand the
tests a helper that installs a temporary registry (via the
``LEARN_SUBJECTS_REGISTRY`` env override) — so a test can register a subject
with zero source changes, exactly as a real subject would register with a data
entry.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any, Callable

import pytest

FIXTURE_SUBJECTS = Path(__file__).parent / "fixtures" / "subjects"
CONFORMANT_SCRIPT = FIXTURE_SUBJECTS / "conformant_subject.py"
DRIFTED_SCRIPT = FIXTURE_SUBJECTS / "drifted_subject.py"


def _make_executable(path: Path) -> str:
    """Ensure a fixture script is executable (git may not preserve the bit)."""
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return str(path)


def entry(
    name: str,
    argv_prefix: list[str],
    *,
    contract_version: str = "1.0",
) -> dict[str, Any]:
    """A registry entry dict with sensible defaults for the metadata fields."""
    return {
        "name": name,
        "display_name": name.replace("-", " ").title(),
        "description": f"Fixture subject {name}.",
        "repo": f"https://github.com/agentculture/{name}-cli",
        "argv_prefix": argv_prefix,
        "contract_version": contract_version,
    }


@pytest.fixture
def conformant_prefix() -> list[str]:
    """argv_prefix that runs the conformant fixture as an executable script."""
    return [_make_executable(CONFORMANT_SCRIPT)]


@pytest.fixture
def drifted_prefix() -> list[str]:
    """argv_prefix that runs the drifted fixture as an executable script."""
    return [_make_executable(DRIFTED_SCRIPT)]


@pytest.fixture
def install_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Callable[[list[dict[str, Any]]], Path]:
    """Return a callable that writes a temp registry and activates it via env."""

    def _install(entries: list[dict[str, Any]]) -> Path:
        path = tmp_path / "registry.json"
        path.write_text(json.dumps({"subjects": entries}), encoding="utf-8")
        monkeypatch.setenv("LEARN_SUBJECTS_REGISTRY", os.fspath(path))
        return path

    return _install
