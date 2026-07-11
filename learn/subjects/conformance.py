"""The subject conformance gate behind ``learn subject doctor <subject>``.

learn-cli hosts subjects it never imports, so it must be able to *prove* an
installed subject CLI still honours the subject-plugin contract
(``docs/specs/subject-plugin-contract.md``) before driving it. This module does
that by spawning the subject's verbs as subprocesses over ``--json`` and
checking each answer against the shipped contract schemas.

The result is the standard doctor payload shape
``{healthy, checks: [{id, passed, severity, message, remediation}]}`` — extended
(per the contract's ``doctor.json``) with ``schema_version``, ``kind``,
``subject`` and ``contract_version`` so learn-cli's conformance report for a
subject is itself a valid ``subject_doctor`` payload. The checks cover:

* ``executable-found`` — the subject's console script resolves on PATH;
* ``verb-doctor`` — ``doctor --json`` responds and validates (read first: it
  carries the subject's contract pin);
* ``contract-version-supported`` — that pin is a major learn-cli supports;
* ``verb-overview`` / ``verb-progress`` / ``verb-advice`` / ``verb-story-list``
  — each read-only verb responds with a schema-valid, version-compatible
  payload;
* ``error-contract`` — a deliberately bad invocation exits non-zero with the
  ``{code, message, remediation}`` shape on stderr, an empty stdout, and an exit
  code equal to the payload's ``code``.

Mutating/learner-authoring verbs (``lesson``, ``practice``, ``record``,
``story read``) are validated by golden payloads in each subject repo's own CI;
the runtime gate stays read-only and safe to run against any learner state.
"""

from __future__ import annotations

import json
import subprocess  # nosec B404 - driving subjects as subprocesses is the design
from typing import Any

from learn.contract import CONTRACT_VERSION, validate
from learn.subjects import SubjectEntry, resolve_executable

#: Learner id used for learner-scoped probes. Read-only verbs never mutate
#: state, so this never touches a real learner's ledger.
PROBE_LEARNER = "learn-conformance-probe"

#: A verb no subject defines — used to exercise the error/exit contract.
BAD_VERB = "__learn_conformance_bad_verb__"

#: Default per-subprocess timeout (seconds). A subject that hangs fails the gate.
DEFAULT_TIMEOUT = 20.0

# Read-only, learner-tolerant verbs the gate probes: (check_id, verb argv,
# schema name, learner-scoped?). ``doctor`` is handled first, separately.
_READONLY_PROBES: tuple[tuple[str, tuple[str, ...], str, bool], ...] = (
    ("verb-overview", ("overview",), "overview", False),
    ("verb-progress", ("progress",), "progress", True),
    ("verb-advice", ("advice",), "advice", True),
    ("verb-story-list", ("story", "list"), "story_list", False),
)


def _check(cid: str, passed: bool, message: str, *, remediation: str = "") -> dict[str, Any]:
    return {
        "id": cid,
        "passed": passed,
        "severity": "error",
        "message": message,
        "remediation": remediation if not passed else "",
    }


def _major(version: str) -> str:
    return version.split(".", 1)[0]


def _run(exe: str, entry: SubjectEntry, verb: tuple[str, ...], *, learner: bool, timeout: float):
    """Run one subject verb; return (returncode, stdout, stderr) or a failure str."""
    args = [exe, *entry.argv_prefix[1:], *verb]
    if learner:
        args += ["--learner", PROBE_LEARNER]
    args.append("--json")
    try:
        proc = subprocess.run(  # nosec B603 - args is a resolved path + literal verbs
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return f"did not respond within {timeout:g}s"
    except OSError as err:
        return f"failed to spawn: {err}"
    return proc.returncode, proc.stdout, proc.stderr


def _probe_verb(
    exe: str,
    entry: SubjectEntry,
    cid: str,
    verb: tuple[str, ...],
    schema: str,
    *,
    learner: bool,
    timeout: float,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Probe one read-only verb; return (check, parsed_payload_or_None)."""
    verb_label = " ".join(verb)
    remediation = f"make '{entry.argv_prefix[0]} {verb_label} --json' emit a valid {schema} payload"
    result = _run(exe, entry, verb, learner=learner, timeout=timeout)
    if isinstance(result, str):
        return _check(cid, False, f"{verb_label}: {result}", remediation=remediation), None
    rc, out, err = result
    if rc != 0:
        detail = err.strip().splitlines()[0] if err.strip() else "no stderr"
        return (
            _check(cid, False, f"{verb_label} exited {rc}: {detail}", remediation=remediation),
            None,
        )
    try:
        payload = json.loads(out)
    except json.JSONDecodeError as exc:
        return (
            _check(
                cid, False, f"{verb_label}: stdout is not JSON ({exc})", remediation=remediation
            ),
            None,
        )
    errors = validate(payload, schema)
    if errors:
        return (
            _check(
                cid,
                False,
                f"{verb_label}: payload violates {schema}.json: {errors[0]}",
                remediation=remediation,
            ),
            payload,
        )
    version = payload.get("schema_version")
    if not isinstance(version, str) or _major(version) != _major(CONTRACT_VERSION):
        return (
            _check(
                cid,
                False,
                f"{verb_label}: schema_version {version!r} incompatible with "
                f"contract {CONTRACT_VERSION}",
                remediation=f"emit schema_version {_major(CONTRACT_VERSION)}.x",
            ),
            payload,
        )
    return (
        _check(cid, True, f"{verb_label}: valid {schema} payload (schema_version {version})"),
        payload,
    )


def _probe_doctor(
    exe: str, entry: SubjectEntry, timeout: float
) -> tuple[list[dict[str, Any]], str | None]:
    """Probe ``doctor`` (the pin source) + the contract-version-supported check."""
    check, payload = _probe_verb(
        exe, entry, "verb-doctor", ("doctor",), "doctor", learner=False, timeout=timeout
    )
    checks = [check]
    pin = payload.get("contract_version") if isinstance(payload, dict) else None
    if not check["passed"]:
        return checks, None
    supported = isinstance(pin, str) and _major(pin) == _major(CONTRACT_VERSION)
    checks.append(
        _check(
            "contract-version-supported",
            supported,
            (
                f"subject pins contract {pin}, supported by learn-cli {CONTRACT_VERSION}"
                if supported
                else f"subject pins contract {pin!r}, unsupported "
                f"(learn-cli speaks {CONTRACT_VERSION})"
            ),
            remediation=(
                f"pin a contract {_major(CONTRACT_VERSION)}.x version in doctor.contract_version"
            ),
        )
    )
    return checks, pin if supported else None


def _probe_error_contract(exe: str, entry: SubjectEntry, timeout: float) -> dict[str, Any]:
    """A bad invocation must exit non-zero with the error shape on stderr only."""
    cid = "error-contract"
    remediation = (
        "on failure, emit {code, message, remediation} to stderr (nothing on stdout) "
        "and exit with that code"
    )
    result = _run(exe, entry, (BAD_VERB,), learner=False, timeout=timeout)
    if isinstance(result, str):
        return _check(cid, False, f"bad invocation: {result}", remediation=remediation)
    rc, out, err = result
    if rc == 0:
        return _check(cid, False, "bad invocation exited 0 (should fail)", remediation=remediation)
    if out.strip():
        return _check(
            cid,
            False,
            "bad invocation wrote to stdout (streams must not mix)",
            remediation=remediation,
        )
    try:
        payload = json.loads(err)
    except json.JSONDecodeError:
        return _check(
            cid,
            False,
            "bad invocation: stderr is not the JSON error shape",
            remediation=remediation,
        )
    schema_errors = validate(payload, "error")
    if schema_errors:
        return _check(
            cid, False, f"error payload invalid: {schema_errors[0]}", remediation=remediation
        )
    if payload.get("code") != rc:
        return _check(
            cid,
            False,
            f"exit code {rc} != error payload code {payload.get('code')}",
            remediation=remediation,
        )
    return _check(
        cid, True, f"bad invocation exits {rc} with the {{code,message,remediation}} shape"
    )


def run_conformance(entry: SubjectEntry, *, timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """Drive ``entry``'s verbs and return the ``subject_doctor`` payload.

    ``healthy`` is false when any error-severity check fails. The payload is
    itself a valid contract ``doctor.json`` payload for ``entry.name``.
    """
    checks: list[dict[str, Any]] = []
    exe = resolve_executable(entry.argv_prefix[0])
    if exe is None:
        checks.append(
            _check(
                "executable-found",
                False,
                f"subject executable '{entry.argv_prefix[0]}' is not installed",
                remediation=(
                    f"install {entry.name} (repo: {entry.repo}) so "
                    f"'{entry.argv_prefix[0]}' is on PATH"
                ),
            )
        )
        return _payload(entry, checks)

    checks.append(_check("executable-found", True, f"found '{entry.argv_prefix[0]}' at {exe}"))

    doctor_checks, _pin = _probe_doctor(exe, entry, timeout)
    checks.extend(doctor_checks)

    for cid, verb, schema, learner in _READONLY_PROBES:
        check, _payload_out = _probe_verb(
            exe, entry, cid, verb, schema, learner=learner, timeout=timeout
        )
        checks.append(check)

    checks.append(_probe_error_contract(exe, entry, timeout))
    return _payload(entry, checks)


def _payload(entry: SubjectEntry, checks: list[dict[str, Any]]) -> dict[str, Any]:
    healthy = all(c["passed"] for c in checks if c["severity"] == "error")
    return {
        "schema_version": CONTRACT_VERSION,
        "kind": "subject_doctor",
        "subject": entry.name,
        "contract_version": CONTRACT_VERSION,
        "healthy": healthy,
        "checks": checks,
    }
