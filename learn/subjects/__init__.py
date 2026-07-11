"""The data-driven subject registry — learn-cli's single source of subjects.

learn-cli is a *portal*: it hosts per-subject tutor CLIs and never reimplements
tutoring. Which subjects exist is pure **data** — the ``registry.json`` package
file (overridable via the ``LEARN_SUBJECTS_REGISTRY`` env var). Adding a subject
is a registry entry plus a conformant subject CLI on PATH; **deleting the entry
removes the subject from every face.** Registry entries carry subject *metadata
only* (:data:`SubjectEntry.ALLOWED_KEYS`) — never content, lessons, or
progression logic, which live in the subject repo. This is what keeps criterion
"learn-cli contains no subject content or progression logic" true by
construction.

Subjects are driven **only** as external subprocesses over ``--json`` (see
:mod:`learn.subjects.conformance`); their code is never imported. A subject
whose executable is not installed is an *environment* error (exit 2), not a
crash.

Public API (stable for wave-3 consumers — the agentfront faces and the
cross-subject profile):

* :class:`SubjectEntry` — one immutable registry record.
* :func:`load_registry` — every registered :class:`SubjectEntry`.
* :func:`get_subject` — one entry by name (raises :class:`CliError` if unknown).
* :func:`resolve_executable` / :func:`is_available` — PATH resolution + a
  subject's install status, used by ``learn subjects`` and the gate.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

from learn.cli._errors import EXIT_ENV_ERROR, EXIT_USER_ERROR, CliError
from learn.contract import CONTRACT_VERSION

#: Env var naming an alternate registry.json (absolute or cwd-relative path).
#: Lets a subject author test a local registry and lets tests register a dummy
#: subject with zero source changes.
REGISTRY_ENV = "LEARN_SUBJECTS_REGISTRY"


@dataclass(frozen=True)
class SubjectEntry:
    """One registered subject — metadata only, never content.

    ``argv_prefix`` is the subprocess argv head for the subject's contract
    verbs: ``["french"]`` runs ``french overview --json``; ``["culture-guide",
    "subject"]`` runs ``culture-guide subject overview --json`` (culture-guide
    mounts the contract verbs under a ``subject`` noun).
    """

    name: str
    display_name: str
    description: str
    repo: str
    argv_prefix: tuple[str, ...]
    contract_version: str

    #: The only keys a registry entry may carry. Unknown keys are rejected so
    #: subject content or progression logic can never leak into the registry.
    ALLOWED_KEYS = frozenset(
        {"name", "display_name", "description", "repo", "argv_prefix", "contract_version"}
    )
    _REQUIRED_KEYS = frozenset({"name", "argv_prefix", "description", "repo"})

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SubjectEntry":
        """Build an entry from a registry record, validating its shape.

        A malformed registry is an *environment* error (exit 2): the operator's
        data file, not the caller's command, is wrong.
        """
        unknown = set(data) - cls.ALLOWED_KEYS
        if unknown:
            raise CliError(
                code=EXIT_ENV_ERROR,
                message=f"registry entry has unsupported keys: {sorted(unknown)}",
                remediation=(
                    "registry entries carry subject metadata only "
                    f"({', '.join(sorted(cls.ALLOWED_KEYS))}) — never content or progression"
                ),
            )
        for key in cls._REQUIRED_KEYS:
            if key not in data:
                raise CliError(
                    code=EXIT_ENV_ERROR,
                    message=f"registry entry missing required key '{key}'",
                    remediation=f"add '{key}' to the entry in the subject registry",
                )
        argv_prefix = tuple(data["argv_prefix"])
        if not argv_prefix or not all(isinstance(p, str) and p for p in argv_prefix):
            raise CliError(
                code=EXIT_ENV_ERROR,
                message=f"registry entry '{data.get('name')}' has an empty/invalid argv_prefix",
                remediation='argv_prefix must be a non-empty list of strings, e.g. ["french"]',
            )
        name = str(data["name"])
        return cls(
            name=name,
            display_name=str(data.get("display_name", name)),
            description=str(data["description"]),
            repo=str(data["repo"]),
            argv_prefix=argv_prefix,
            contract_version=str(data.get("contract_version", CONTRACT_VERSION)),
        )

    def to_dict(self) -> dict[str, Any]:
        """The entry as a JSON-friendly dict (argv_prefix as a list)."""
        return {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "repo": self.repo,
            "argv_prefix": list(self.argv_prefix),
            "contract_version": self.contract_version,
        }


def _read_registry_text(source: str | Path | None) -> str:
    """Read the raw registry JSON from ``source``, the env override, or package data."""
    chosen = source if source is not None else os.environ.get(REGISTRY_ENV)
    if chosen is not None:
        path = Path(chosen)
        try:
            return path.read_text(encoding="utf-8")
        except OSError as err:
            raise CliError(
                code=EXIT_ENV_ERROR,
                message=f"cannot read subject registry at {path}: {err.strerror or err}",
                remediation=f"point {REGISTRY_ENV} at a readable registry.json, or unset it",
            ) from err
    return resources.files(__package__).joinpath("registry.json").read_text(encoding="utf-8")


def load_registry(source: str | Path | None = None) -> tuple[SubjectEntry, ...]:
    """Return every registered subject, in registry order.

    ``source`` (or the ``LEARN_SUBJECTS_REGISTRY`` env var) overrides the shipped
    ``registry.json``; otherwise the package-data file is used.
    """
    text = _read_registry_text(source)
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as err:
        raise CliError(
            code=EXIT_ENV_ERROR,
            message=f"subject registry is not valid JSON: {err}",
            remediation="fix the registry.json syntax",
        ) from err
    entries = raw.get("subjects", []) if isinstance(raw, dict) else raw
    if not isinstance(entries, list):
        raise CliError(
            code=EXIT_ENV_ERROR,
            message='subject registry must be a list of entries (or {"subjects": [...]})',
            remediation="wrap the entries in a 'subjects' array",
        )
    return tuple(SubjectEntry.from_dict(entry) for entry in entries)


def get_subject(name: str, source: str | Path | None = None) -> SubjectEntry:
    """Return the registered subject named ``name``.

    Raises :class:`CliError` (exit 1, *user* error) when no such subject is
    registered — a typo in the command, not a broken environment.
    """
    for entry in load_registry(source):
        if entry.name == name:
            return entry
    known = ", ".join(e.name for e in load_registry(source)) or "(none)"
    raise CliError(
        code=EXIT_USER_ERROR,
        message=f"unknown subject '{name}'",
        remediation=f"run 'learn subjects --json' to list registered subjects (have: {known})",
    )


def resolve_executable(command: str) -> str | None:
    """Resolve ``command`` to a runnable absolute path, or ``None`` if missing.

    A bare name (``french``) is looked up on ``PATH``; a value containing a path
    separator (a test fixture, a local build) is treated as a file path and must
    be an executable regular file. Mirrors how the shell would find it — and
    passing the resolved absolute path to subprocess avoids a partial-path call.
    """
    if os.sep in command or (os.altsep and os.altsep in command):
        path = Path(command)
        if path.is_file() and os.access(path, os.X_OK):
            return str(path.resolve())
        return None
    return shutil.which(command)


def is_available(entry: SubjectEntry) -> bool:
    """True when the subject's executable (``argv_prefix[0]``) resolves."""
    return resolve_executable(entry.argv_prefix[0]) is not None
