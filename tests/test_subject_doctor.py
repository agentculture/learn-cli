"""Tests for ``learn subject doctor`` — the conformance gate.

Cover the acceptance criteria:

* criterion 1 — the gate validates a subject's verbs, schema_version, JSON
  payloads and exit codes, and FAILS on drift (the drifted fixture);
* criterion 2 — a dummy fourth subject registers and PASSES with zero new
  platform code (only a data entry + an external conformant script);

plus the noun's ``overview`` verb, the missing-executable (exit 2) and
unknown-subject (exit 1) paths, and self-validation of the emitted payload
against the contract's own ``doctor.json``.
"""

from __future__ import annotations

import json

import pytest

from learn.cli import main
from learn.contract import validate
from learn.subjects import get_subject
from learn.subjects.conformance import run_conformance
from tests.conftest import entry


def _failed_ids(payload: dict) -> set[str]:
    return {c["id"] for c in payload["checks"] if not c["passed"]}


# --- criterion 2: registration, not a fork ---------------------------------


def test_fourth_subject_registers_and_passes(install_registry, conformant_prefix, capsys) -> None:
    # Zero new platform code: just a registry entry + a conformant executable.
    install_registry([entry("fourthlang", conformant_prefix)])
    rc = main(["subject", "doctor", "fourthlang", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["healthy"] is True
    # Every probed check passed.
    assert _failed_ids(payload) == set()
    # The expected checks were actually run (not a vacuous pass).
    ran = {c["id"] for c in payload["checks"]}
    assert {
        "executable-found",
        "verb-doctor",
        "contract-version-supported",
        "verb-overview",
        "verb-progress",
        "verb-advice",
        "verb-story-list",
        "error-contract",
    } <= ran


def test_emitted_payload_is_a_valid_subject_doctor_payload(
    install_registry, conformant_prefix
) -> None:
    install_registry([entry("fourthlang", conformant_prefix)])
    report = run_conformance(get_subject("fourthlang"))
    # learn-cli's conformance report is itself a contract subject_doctor payload.
    assert validate(report, "doctor") == []
    assert report["kind"] == "subject_doctor"
    assert report["contract_version"] == "1.0"


# --- criterion 1: fails on drift -------------------------------------------


def test_drifted_subject_fails_doctor(install_registry, drifted_prefix, capsys) -> None:
    install_registry([entry("brokenlang", drifted_prefix)])
    rc = main(["subject", "doctor", "brokenlang", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 2  # environment error: the installed subject drifted
    assert payload["healthy"] is False
    failed = _failed_ids(payload)
    # Payload drift (invalid + incompatible overview) is caught...
    assert "verb-overview" in failed
    # ...and exit/stream contract drift (bad invocation exits 0 to stdout) too.
    assert "error-contract" in failed


def test_drift_report_still_validates_as_subject_doctor(install_registry, drifted_prefix) -> None:
    install_registry([entry("brokenlang", drifted_prefix)])
    report = run_conformance(get_subject("brokenlang"))
    assert report["healthy"] is False
    assert validate(report, "doctor") == []


# --- environment + usage error paths ---------------------------------------


def test_missing_executable_is_environment_error(install_registry, capsys) -> None:
    install_registry([entry("ghostlang", ["definitely-not-installed-xyz-123"])])
    rc = main(["subject", "doctor", "ghostlang", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 2
    assert payload["healthy"] is False
    failed = {c["id"] for c in payload["checks"] if not c["passed"]}
    assert "executable-found" in failed
    # The remediation tells the operator how to install it.
    exe_check = next(c for c in payload["checks"] if c["id"] == "executable-found")
    assert exe_check["remediation"]


def test_unknown_subject_is_user_error(capsys) -> None:
    rc = main(["subject", "doctor", "klingon", "--json"])
    err = capsys.readouterr().err
    assert rc == 1
    payload = json.loads(err)
    assert payload["code"] == 1
    assert "unknown subject" in payload["message"]


def test_subject_doctor_text_mode(install_registry, conformant_prefix, capsys) -> None:
    install_registry([entry("fourthlang", conformant_prefix)])
    rc = main(["subject", "doctor", "fourthlang"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "learn subject doctor fourthlang" in out
    assert "conforms" in out


# --- the subject noun's overview -------------------------------------------


def test_subject_overview_text(capsys) -> None:
    rc = main(["subject", "overview"])
    assert rc == 0
    assert "# learn subject" in capsys.readouterr().out


def test_subject_overview_json_shape(capsys) -> None:
    rc = main(["subject", "overview", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["subject"] == "learn subject"
    assert isinstance(payload["sections"], list)
    assert payload["sections"]


def test_bare_subject_noun_prints_overview(capsys) -> None:
    rc = main(["subject"])
    assert rc == 0
    assert capsys.readouterr().out.strip()


def test_subject_overview_lists_registered_subjects(
    install_registry, conformant_prefix, capsys
) -> None:
    install_registry([entry("fourthlang", conformant_prefix)])
    rc = main(["subject", "overview", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    flat = json.dumps(payload)
    assert "fourthlang" in flat


def test_subject_overview_unknown_flag_structured_error(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["subject", "overview", "--bogus"])
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert err.startswith("error:")
    assert "hint:" in err
