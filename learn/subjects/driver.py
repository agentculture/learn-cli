"""Drive a registered subject's verbs as a subprocess, for real work.

The runtime counterpart to :mod:`learn.subjects.conformance` (a read-only gate
behind ``learn subject doctor``): this module is what learner-facing verbs
(``learn progress``, ``learn record``) use to actually call into a subject CLI,
always over subprocess + ``--json``, per the subject-plugin contract. It never
imports subject code — the contract's whole point is that learn-cli hosts
subjects without knowing their internals.
"""

from __future__ import annotations

import json
import subprocess  # nosec B404 - driving subjects as subprocesses is the design
from typing import Any, Optional

from learn.cli._errors import EXIT_ENV_ERROR, CliError
from learn.subjects import SubjectEntry, resolve_executable

#: Default per-subprocess timeout (seconds), matching the conformance gate.
DEFAULT_TIMEOUT = 20.0


def run_subject_verb(
    entry: SubjectEntry,
    verb: tuple[str, ...],
    *,
    learner: Optional[str] = None,
    extra_args: tuple[str, ...] = (),
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """Run one subject verb and return its parsed ``--json`` payload.

    ``learner`` is omitted by default — a subject resolves its own default
    (env var, then OS user) exactly as it would when run directly by hand, so
    driving it through learn-cli never changes which local learner state it
    reads/writes. Pass it explicitly only when the caller has a specific
    learner id to scope the call to.

    Raises :class:`CliError` (exit 2, environment error) when the subject's
    executable is missing, the process fails to spawn or times out, exits
    non-zero, or emits invalid JSON — a drifted/unavailable subject is an
    environment problem for the caller, not a bug.
    """
    exe = resolve_executable(entry.argv_prefix[0])
    if exe is None:
        raise CliError(
            code=EXIT_ENV_ERROR,
            message=f"subject '{entry.name}' executable '{entry.argv_prefix[0]}' is not installed",
            remediation=(
                f"install {entry.name} (repo: {entry.repo}) so "
                f"'{entry.argv_prefix[0]}' is on PATH"
            ),
        )
    args = [exe, *entry.argv_prefix[1:], *verb, *extra_args]
    if learner:
        args += ["--learner", learner]
    args.append("--json")

    verb_label = " ".join(verb)
    try:
        proc = subprocess.run(  # nosec B603 - args is a resolved path + literal verbs
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as err:
        raise CliError(
            code=EXIT_ENV_ERROR,
            message=f"subject '{entry.name}' {verb_label} did not respond within {timeout:g}s",
            remediation=f"run 'learn subject doctor {entry.name}' to check conformance",
        ) from err
    except OSError as err:
        raise CliError(
            code=EXIT_ENV_ERROR,
            message=f"failed to run subject '{entry.name}' {verb_label}: {err}",
            remediation=(
                f"install {entry.name} (repo: {entry.repo}) so "
                f"'{entry.argv_prefix[0]}' is on PATH"
            ),
        ) from err

    if proc.returncode != 0:
        detail = _stderr_message(proc.stderr)
        raise CliError(
            code=EXIT_ENV_ERROR,
            message=f"subject '{entry.name}' {verb_label} failed: {detail}",
            remediation=f"run 'learn subject doctor {entry.name}' to check conformance",
        )
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as err:
        raise CliError(
            code=EXIT_ENV_ERROR,
            message=f"subject '{entry.name}' {verb_label} did not emit valid JSON",
            remediation=f"run 'learn subject doctor {entry.name}' to check conformance",
        ) from err
    if not isinstance(payload, dict):
        raise CliError(
            code=EXIT_ENV_ERROR,
            message=f"subject '{entry.name}' {verb_label} emitted a non-object JSON payload",
            remediation=f"run 'learn subject doctor {entry.name}' to check conformance",
        )
    return payload


def _stderr_message(stderr: str) -> str:
    text = stderr.strip()
    if not text:
        return "(no stderr)"
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return text.splitlines()[0]
    if isinstance(payload, dict) and "message" in payload:
        return str(payload["message"])
    return text.splitlines()[0]
