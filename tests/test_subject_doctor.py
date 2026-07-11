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
from learn.subjects.conformance import (
    _is_cloze_blanks_item,
    _validate_cloze_exercise,
    run_conformance,
)
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


# --- t3: the `cloze-items` check (pick-the-right-word cloze exercises) ------


def test_cloze_free_subject_passes_trivially(install_registry, conformant_prefix) -> None:
    # A subject that declares NO pick-the-right-word cloze items (the fourthlang
    # fixture ships none) must not be penalized — the check passes trivially.
    install_registry([entry("fourthlang", conformant_prefix)])
    report = run_conformance(get_subject("fourthlang"))
    check = next(c for c in report["checks"] if c["id"] == "cloze-items")
    assert check["passed"] is True
    assert "no pick-the-right-word cloze items" in check["message"]


def test_well_formed_cloze_subject_passes(
    install_registry, cloze_conformant_prefix, capsys
) -> None:
    install_registry([entry("clozelang", cloze_conformant_prefix)])
    rc = main(["subject", "doctor", "clozelang", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["healthy"] is True
    check = next(c for c in payload["checks"] if c["id"] == "cloze-items")
    assert check["passed"] is True
    # The fixture ships ONE pick-the-right-word item plus one legacy
    # single-blank free-text cloze item — only the former is counted here.
    assert "1 pick-the-right-word cloze item" in check["message"]


def test_well_formed_cloze_report_validates_as_subject_doctor(
    install_registry, cloze_conformant_prefix
) -> None:
    install_registry([entry("clozelang", cloze_conformant_prefix)])
    report = run_conformance(get_subject("clozelang"))
    assert validate(report, "doctor") == []


def test_malformed_cloze_subject_fails_doctor(
    install_registry, cloze_broken_prefix, capsys
) -> None:
    install_registry([entry("clozebroken", cloze_broken_prefix)])
    rc = main(["subject", "doctor", "clozebroken", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 2
    assert payload["healthy"] is False
    check = next(c for c in payload["checks"] if c["id"] == "cloze-items")
    assert check["passed"] is False
    assert "not among its own `options`" in check["message"]
    assert check["remediation"]
    # Every OTHER check passed — the failure is specifically about content,
    # not plumbing (proves the check inspects content, not just wiring).
    other_failures = {
        c["id"] for c in payload["checks"] if not c["passed"] and c["id"] != "cloze-items"
    }
    assert other_failures == set()


def test_malformed_cloze_report_still_validates_as_subject_doctor(
    install_registry, cloze_broken_prefix
) -> None:
    install_registry([entry("clozebroken", cloze_broken_prefix)])
    report = run_conformance(get_subject("clozebroken"))
    assert report["healthy"] is False
    assert validate(report, "doctor") == []


# --- t3: `_validate_cloze_exercise` unit coverage (granular pass/fail cases) --


def _good_cloze() -> dict:
    return {
        "id": "ex1",
        "type": "cloze",
        "item_id": "greetings",
        "prompt": "Fill in the blanks.",
        "text": "Bonjour, je m'appelle {{name}} et j'ai {{age}} ans.",
        "blanks": [
            {"id": "name", "options": ["Marie", "Paris", "bleu"], "answer": "Marie"},
            {"id": "age", "options": ["dix", "rouge", "vite"], "answer": "dix"},
        ],
    }


def test_is_cloze_blanks_item_true_for_blanks_shape() -> None:
    assert _is_cloze_blanks_item(_good_cloze()) is True


def test_is_cloze_blanks_item_false_for_legacy_single_blank_cloze() -> None:
    legacy = {"id": "ex2", "type": "cloze", "item_id": "x", "prompt": "___", "answer": "y"}
    assert _is_cloze_blanks_item(legacy) is False


def test_is_cloze_blanks_item_false_for_non_cloze_type() -> None:
    mc = {
        "id": "ex3",
        "type": "multiple_choice",
        "item_id": "x",
        "prompt": "?",
        "choices": ["a", "b"],
    }
    assert _is_cloze_blanks_item(mc) is False


def test_validate_cloze_exercise_well_formed_has_no_errors() -> None:
    assert _validate_cloze_exercise("s1", _good_cloze()) == []


def test_validate_cloze_exercise_requires_both_text_and_blanks() -> None:
    only_text = _good_cloze()
    del only_text["blanks"]
    errors = _validate_cloze_exercise("s1", only_text)
    assert any("BOTH `text` and `blanks`" in e for e in errors)


def test_validate_cloze_exercise_rejects_missing_item_id() -> None:
    ex = _good_cloze()
    del ex["item_id"]
    errors = _validate_cloze_exercise("s1", ex)
    assert any("missing `item_id`" in e for e in errors)


def test_validate_cloze_exercise_rejects_answer_not_in_options() -> None:
    ex = _good_cloze()
    ex["blanks"][0]["answer"] = "Nope"
    errors = _validate_cloze_exercise("s1", ex)
    assert any("not among its own `options`" in e for e in errors)


def test_validate_cloze_exercise_rejects_duplicate_blank_ids() -> None:
    ex = _good_cloze()
    ex["blanks"][1]["id"] = "name"  # duplicate of blanks[0]'s id
    errors = _validate_cloze_exercise("s1", ex)
    assert any("duplicate blank id" in e for e in errors)


def test_validate_cloze_exercise_rejects_blank_id_missing_from_text() -> None:
    ex = _good_cloze()
    ex["blanks"][0]["id"] = "nickname"  # no {{nickname}} in text
    errors = _validate_cloze_exercise("s1", ex)
    assert any("no matching {{nickname}} placeholder" in e for e in errors)


def test_validate_cloze_exercise_rejects_orphan_placeholder() -> None:
    ex = _good_cloze()
    ex["text"] = ex["text"].replace("{{age}}", "{{stray}}")
    errors = _validate_cloze_exercise("s1", ex)
    assert any("placeholder {{stray}} has no matching `blanks` entry" in e for e in errors)


def test_validate_cloze_exercise_rejects_too_few_options() -> None:
    ex = _good_cloze()
    ex["blanks"][0]["options"] = ["Marie"]
    errors = _validate_cloze_exercise("s1", ex)
    assert any("at least 2 words" in e for e in errors)


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
