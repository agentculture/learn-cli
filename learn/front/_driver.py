"""Drive a registered subject as an external subprocess over ``--json``.

The portal never imports subject code: every subject verb the front tools and
the static-site export need is spawned as ``<subject-command> <verb> [args]
--json [--learner <id>]`` and its stdout parsed as JSON. This is the same design
the conformance gate (:mod:`learn.subjects.conformance`) uses, generalized to any
contract verb so the agentfront App tools can drive a full learning loop.

Every failure is a :class:`~learn.cli._errors.CliError` (never a traceback): an
uninstalled subject, a spawn failure, a timeout, a non-zero exit, or non-JSON
stdout. When a subject exits non-zero with the contract ``{code, message,
remediation}`` error shape on stderr, that structured error is surfaced verbatim
(its ``code`` preserved) rather than flattened.
"""

from __future__ import annotations

import json
import subprocess  # nosec B404 - driving subjects as subprocesses is the design
from typing import Any, Sequence

from learn.cli._errors import EXIT_ENV_ERROR, CliError
from learn.subjects import SubjectEntry, get_subject, resolve_executable

#: Default per-subprocess timeout (seconds); a subject that hangs fails cleanly.
DEFAULT_TIMEOUT = 20.0


def _resolve_entry(subject: str | SubjectEntry, source: str | None) -> SubjectEntry:
    if isinstance(subject, SubjectEntry):
        return subject
    return get_subject(subject, source)


def _structured_stderr_error(
    entry: SubjectEntry, verb_label: str, stderr: str, rc: int
) -> CliError:
    """Build a CliError from a subject's stderr, preserving its error shape if present."""
    stripped = stderr.strip()
    try:
        payload = json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        detail = stripped.splitlines()[0] if stripped else "no stderr"
        return CliError(
            code=EXIT_ENV_ERROR,
            message=f"subject '{entry.name}' {verb_label} exited {rc}: {detail}",
            remediation=f"run '{entry.argv_prefix[0]} {verb_label} --json' and inspect its error",
        )
    if isinstance(payload, dict) and "message" in payload:
        code = payload.get("code", rc)
        return CliError(
            code=code if isinstance(code, int) and code > 0 else EXIT_ENV_ERROR,
            message=str(payload.get("message")),
            remediation=str(payload.get("remediation", "")),
        )
    return CliError(
        code=EXIT_ENV_ERROR,
        message=f"subject '{entry.name}' {verb_label} exited {rc}",
        remediation=f"run '{entry.argv_prefix[0]} {verb_label} --json' and inspect its error",
    )


def drive(
    subject: str | SubjectEntry,
    verb: Sequence[str],
    *,
    learner: str | None = None,
    extra: Sequence[str] = (),
    timeout: float = DEFAULT_TIMEOUT,
    registry_source: str | None = None,
) -> dict[str, Any]:
    """Run one subject contract verb and return its parsed ``--json`` payload.

    ``verb`` is the verb path (e.g. ``("story", "read")``); ``extra`` are the
    verb's positional args (e.g. a story id); ``learner`` adds ``--learner``.
    Raises :class:`CliError` on any failure — the subject is never imported.
    """
    entry = _resolve_entry(subject, registry_source)
    exe = resolve_executable(entry.argv_prefix[0])
    verb_label = " ".join(verb)
    if exe is None:
        raise CliError(
            code=EXIT_ENV_ERROR,
            message=f"subject '{entry.name}' is not installed "
            f"('{entry.argv_prefix[0]}' is not on PATH)",
            remediation=f"install {entry.name} (repo: {entry.repo}) so it can be driven",
        )
    args = [exe, *entry.argv_prefix[1:], *verb, *extra]
    if learner:
        args += ["--learner", learner]
    args.append("--json")
    try:
        proc = subprocess.run(  # nosec B603 - resolved path + literal contract verbs
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
            remediation="the subject CLI hung; check it responds to '<subject> "
            f"{verb_label} --json'",
        ) from err
    except OSError as err:
        raise CliError(
            code=EXIT_ENV_ERROR,
            message=f"failed to spawn subject '{entry.name}': {err}",
            remediation=f"check that '{entry.argv_prefix[0]}' is an executable on PATH",
        ) from err
    if proc.returncode != 0:
        raise _structured_stderr_error(entry, verb_label, proc.stderr, proc.returncode)
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as err:
        raise CliError(
            code=EXIT_ENV_ERROR,
            message=f"subject '{entry.name}' {verb_label}: stdout is not JSON ({err})",
            remediation=f"make '{entry.argv_prefix[0]} {verb_label} --json' emit a JSON payload",
        ) from err
    if not isinstance(payload, dict):
        raise CliError(
            code=EXIT_ENV_ERROR,
            message=f"subject '{entry.name}' {verb_label}: payload is not a JSON object",
            remediation="contract payloads are JSON objects",
        )
    return payload
