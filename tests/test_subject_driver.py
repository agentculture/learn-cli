"""Unit tests for :mod:`learn.subjects.driver` — the runtime subprocess driver
behind ``learn progress``/``learn record`` (distinct from the read-only
conformance gate in :mod:`learn.subjects.conformance`).

Exercises every failure branch directly (missing executable, timeout, spawn
failure, non-zero exit with/without a structured error, invalid/non-object
JSON) by monkeypatching ``subprocess.run`` and ``resolve_executable`` rather
than spawning real processes — these are pure error-shape checks, not
subprocess integration (that's covered end-to-end via the conformant fixture
in ``tests/test_progress_next_record.py``).
"""

from __future__ import annotations

import subprocess

import pytest

from learn.cli._errors import CliError
from learn.subjects import SubjectEntry
from learn.subjects import driver as d

_ENTRY = SubjectEntry(
    name="fourthlang",
    display_name="Fourth Language",
    description="d",
    repo="https://github.com/agentculture/fourthlang-cli",
    argv_prefix=("fourthlang",),
    contract_version="1.0",
)


class _Proc:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_missing_executable_is_environment_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(d, "resolve_executable", lambda _cmd: None)
    with pytest.raises(CliError) as exc:
        d.run_subject_verb(_ENTRY, ("progress",))
    assert exc.value.code == 2
    assert "not installed" in exc.value.message


def test_timeout_is_environment_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(d, "resolve_executable", lambda _cmd: "/bin/fourthlang")

    def _boom(*_a, **_k):
        raise subprocess.TimeoutExpired(cmd="fourthlang", timeout=1.0)

    monkeypatch.setattr(subprocess, "run", _boom)
    with pytest.raises(CliError) as exc:
        d.run_subject_verb(_ENTRY, ("progress",), timeout=1.0)
    assert exc.value.code == 2
    assert "did not respond" in exc.value.message


def test_spawn_failure_is_environment_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(d, "resolve_executable", lambda _cmd: "/bin/fourthlang")

    def _boom(*_a, **_k):
        raise OSError("permission denied")

    monkeypatch.setattr(subprocess, "run", _boom)
    with pytest.raises(CliError) as exc:
        d.run_subject_verb(_ENTRY, ("progress",))
    assert exc.value.code == 2
    assert "failed to run" in exc.value.message


def test_nonzero_exit_with_structured_stderr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(d, "resolve_executable", lambda _cmd: "/bin/fourthlang")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: _Proc(1, stderr='{"code": 1, "message": "boom", "remediation": "fix it"}'),
    )
    with pytest.raises(CliError) as exc:
        d.run_subject_verb(_ENTRY, ("progress",))
    assert exc.value.code == 2
    assert "boom" in exc.value.message


def test_nonzero_exit_with_plain_stderr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(d, "resolve_executable", lambda _cmd: "/bin/fourthlang")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Proc(1, stderr="kaboom\nmore detail"))
    with pytest.raises(CliError) as exc:
        d.run_subject_verb(_ENTRY, ("progress",))
    assert "kaboom" in exc.value.message


def test_nonzero_exit_with_no_stderr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(d, "resolve_executable", lambda _cmd: "/bin/fourthlang")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Proc(1, stderr=""))
    with pytest.raises(CliError) as exc:
        d.run_subject_verb(_ENTRY, ("progress",))
    assert "no stderr" in exc.value.message


def test_invalid_json_stdout_is_environment_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(d, "resolve_executable", lambda _cmd: "/bin/fourthlang")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Proc(0, stdout="not json"))
    with pytest.raises(CliError) as exc:
        d.run_subject_verb(_ENTRY, ("progress",))
    assert "did not emit valid JSON" in exc.value.message


def test_non_object_json_stdout_is_environment_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(d, "resolve_executable", lambda _cmd: "/bin/fourthlang")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Proc(0, stdout="[1, 2, 3]"))
    with pytest.raises(CliError) as exc:
        d.run_subject_verb(_ENTRY, ("progress",))
    assert "non-object JSON" in exc.value.message


def test_happy_path_returns_parsed_payload_and_appends_learner_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(d, "resolve_executable", lambda _cmd: "/bin/fourthlang")
    captured: dict[str, list[str]] = {}

    def _fake_run(args, **_k):
        captured["args"] = args
        return _Proc(0, stdout='{"ok": true}')

    monkeypatch.setattr(subprocess, "run", _fake_run)
    payload = d.run_subject_verb(_ENTRY, ("progress",), learner="ada")
    assert payload == {"ok": True}
    assert captured["args"] == ["/bin/fourthlang", "progress", "--learner", "ada", "--json"]
