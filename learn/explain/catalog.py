"""Markdown catalog for ``learn-cli explain <path>``.

Each entry is verbatim markdown. Keys are command-path tuples. The empty tuple
and ``("learn-cli",)`` both resolve to the root entry.

Keep bodies self-contained: an agent reading one entry should get enough
context without chaining reads.
"""

from __future__ import annotations

_ROOT = """\
# learn-cli

A clonable template for AgentCulture mesh agents. It carries an agent-first CLI
(cited from the teken `python-cli` reference), a mesh identity (`culture.yaml` +
`CLAUDE.md`), the canonical guildmaster skill kit under `.claude/skills/`, and a
buildable/deployable package baseline. Clone it, rename the package, edit
`culture.yaml`, and you have a new agent.

## Verbs

- `learn-cli whoami` — identity probe from `culture.yaml`.
- `learn-cli learn` — structured self-teaching prompt.
- `learn-cli explain <path>` — markdown docs for any noun/verb.
- `learn-cli overview` — descriptive snapshot of the agent.
- `learn-cli doctor` — check the agent-identity invariants.
- `learn-cli cli overview` — describe the CLI surface.

## Exit-code policy

- `0` success
- `1` user-input error
- `2` environment / setup error
- `3+` reserved

## See also

- `learn-cli explain whoami`
- `learn-cli explain doctor`
"""

_WHOAMI = """\
# learn-cli whoami

Reports the agent's identity from `culture.yaml`: nick (`suffix`), backend,
served model, and the package version. Read-only.

## Usage

    learn-cli whoami
    learn-cli whoami --json
"""

_LEARN = """\
# learn-cli learn

Prints a structured self-teaching prompt covering purpose, command map,
exit-code policy, `--json` support, and the `explain` pointer.

## Usage

    learn-cli learn
    learn-cli learn --json
"""

_EXPLAIN = """\
# learn-cli explain <path>

Prints markdown documentation for any noun/verb path. Unlike `--help` (terse,
positional), `explain` is global and addressable by path.

## Usage

    learn-cli explain learn-cli
    learn-cli explain whoami
    learn-cli explain --json <path>
"""

_OVERVIEW = """\
# learn-cli overview

Read-only descriptive snapshot of the agent: identity (from `culture.yaml`), the
verb surface, and the sibling-pattern artifacts the template carries. Accepts an
ignored `target` so a stray path never hard-fails.

## Usage

    learn-cli overview
    learn-cli overview --json
"""

_DOCTOR = """\
# learn-cli doctor

Checks the agent-identity invariants `steward doctor` verifies:
prompt-file-present and backend-consistency (`colleague` → `AGENTS.colleague.md`), plus a
skills-present check. Exits 1 when unhealthy.

## Usage

    learn-cli doctor
    learn-cli doctor --json
"""

_CLI = """\
# learn-cli cli

Noun group for CLI-surface introspection. `cli overview` describes the CLI
itself (distinct from the global `overview`, which describes the agent).

## Usage

    learn-cli cli overview
    learn-cli cli overview --json
"""

_SUBJECTS = """\
# learn subjects

Lists the registered subjects and whether each subject CLI is installed. The
set of subjects is pure data — the `learn/subjects/registry.json` registry
(override with the `LEARN_SUBJECTS_REGISTRY` env var). Deleting a registry entry
removes the subject from every face; learn-cli holds no subject content.

## Usage

    learn subjects
    learn subjects --json

Each `--json` entry carries `name`, `display_name`, `description`, `repo`,
`argv_prefix`, `contract_version`, and `available`.
"""

_SUBJECT = """\
# learn subject

The noun that fronts per-subject tutor CLIs. learn-cli hosts subjects it never
imports, driving them only as external subprocesses over `--json`.

## Verbs

- `learn subject overview` — describe this noun and the registered subjects.
- `learn subject doctor <name>` — check a subject CLI against the contract.

## Usage

    learn subject overview
    learn subject doctor french --json
"""

_SUBJECT_DOCTOR = """\
# learn subject doctor <name>

The conformance gate. Drives a registered subject's verbs as subprocesses and
validates each `--json` answer against the subject-plugin contract
(`docs/specs/subject-plugin-contract.md`): the executable resolves, each
read-only verb (`doctor`, `overview`, `progress`, `advice`, `story list`)
responds with a schema-valid, version-compatible payload, and a bad invocation
honours the error/exit contract (`{code, message, remediation}` on stderr,
empty stdout, exit == code).

Emits the standard doctor payload `{healthy, checks:[{id, passed, severity,
message, remediation}]}` — itself a valid `subject_doctor` payload. Exits 0 when
the subject conforms, 2 when it has drifted or its executable is missing, and 1
for an unknown subject name.

## Usage

    learn subject doctor french
    learn subject doctor french --json
"""


ENTRIES: dict[tuple[str, ...], str] = {
    (): _ROOT,
    ("learn-cli",): _ROOT,
    ("whoami",): _WHOAMI,
    ("learn",): _LEARN,
    ("explain",): _EXPLAIN,
    ("overview",): _OVERVIEW,
    ("doctor",): _DOCTOR,
    ("cli",): _CLI,
    ("cli", "overview"): _CLI,
    ("subjects",): _SUBJECTS,
    ("subject",): _SUBJECT,
    ("subject", "overview"): _SUBJECT,
    ("subject", "doctor"): _SUBJECT_DOCTOR,
}
