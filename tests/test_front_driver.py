"""Robustness of the subprocess subject driver (:mod:`learn.front._driver`).

The driver is the seam that keeps the portal from importing subject code; its
failure handling (non-JSON output, non-object payloads, non-zero exits with and
without the contract error shape) is what turns a broken subject into a clean
``CliError`` instead of a traceback.
"""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from learn.cli._errors import EXIT_ENV_ERROR, EXIT_USER_ERROR, CliError
from learn.front._driver import drive
from learn.subjects import SubjectEntry


def _script(tmp_path: Path, body: str) -> SubjectEntry:
    """Write an executable python subject stub and wrap it in a SubjectEntry."""
    path = tmp_path / "stub.py"
    path.write_text("#!/usr/bin/env python3\nimport sys\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return SubjectEntry(
        name="stub",
        display_name="Stub",
        description="test stub",
        repo="https://example.invalid/stub",
        argv_prefix=(str(path),),
        contract_version="1.0",
    )


def test_learner_flag_is_forwarded(tmp_path) -> None:
    entry = _script(
        tmp_path,
        "import json\n"
        "args = sys.argv[1:]\n"
        "learner = args[args.index('--learner') + 1] if '--learner' in args else 'none'\n"
        "print(json.dumps({'learner': learner}))\n",
    )
    payload = drive(entry, ("progress",), learner="ori")
    assert payload["learner"] == "ori"


def test_non_json_stdout_is_env_error(tmp_path) -> None:
    entry = _script(tmp_path, "print('not json at all')\n")
    with pytest.raises(CliError) as exc:
        drive(entry, ("overview",))
    assert exc.value.code == EXIT_ENV_ERROR
    assert "not JSON" in exc.value.message


def test_non_object_payload_is_env_error(tmp_path) -> None:
    entry = _script(tmp_path, "print('[1, 2, 3]')\n")
    with pytest.raises(CliError) as exc:
        drive(entry, ("overview",))
    assert exc.value.code == EXIT_ENV_ERROR
    assert "not a JSON object" in exc.value.message


def test_nonzero_exit_with_error_shape_preserves_code(tmp_path) -> None:
    entry = _script(
        tmp_path,
        "import json\n"
        "sys.stderr.write(json.dumps("
        "{'code': 1, 'message': 'bad thing', 'remediation': 'do better'}))\n"
        "sys.exit(1)\n",
    )
    with pytest.raises(CliError) as exc:
        drive(entry, ("progress",))
    assert exc.value.code == EXIT_USER_ERROR  # the subject's own code, preserved
    assert exc.value.message == "bad thing"
    assert exc.value.remediation == "do better"


def test_nonzero_exit_without_error_shape_falls_back(tmp_path) -> None:
    entry = _script(tmp_path, "sys.stderr.write('boom, plain text\\n')\nsys.exit(3)\n")
    with pytest.raises(CliError) as exc:
        drive(entry, ("progress",))
    assert exc.value.code == EXIT_ENV_ERROR
    assert "exited 3" in exc.value.message
    assert "boom, plain text" in exc.value.message


def test_missing_executable_is_env_error(tmp_path) -> None:
    entry = SubjectEntry(
        name="ghost",
        display_name="Ghost",
        description="never installed",
        repo="https://example.invalid/ghost",
        argv_prefix=(str(tmp_path / "does-not-exist"),),
        contract_version="1.0",
    )
    with pytest.raises(CliError) as exc:
        drive(entry, ("overview",))
    assert exc.value.code == EXIT_ENV_ERROR
    assert "not installed" in exc.value.message


def test_timeout_is_env_error(tmp_path) -> None:
    entry = _script(tmp_path, "import time\ntime.sleep(5)\n")
    with pytest.raises(CliError) as exc:
        drive(entry, ("overview",), timeout=0.2)
    assert exc.value.code == EXIT_ENV_ERROR
    assert "did not respond" in exc.value.message


def test_spawn_failure_is_env_error(tmp_path, monkeypatch) -> None:
    entry = _script(tmp_path, "print('{}')\n")

    def boom(*args, **kwargs):
        raise OSError("Exec format error")

    monkeypatch.setattr("learn.front._driver.subprocess.run", boom)
    with pytest.raises(CliError) as exc:
        drive(entry, ("overview",))
    assert exc.value.code == EXIT_ENV_ERROR
    assert "failed to spawn" in exc.value.message
