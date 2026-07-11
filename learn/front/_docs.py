"""Docs the agentfront App registers — the agent-readable web presence.

All three are derived from package data (the machine-readable contract and the
subject registry) or are static prose, so they ship in the installed wheel and
render identically on every face (HTTP page, ``learn --json`` listing, and the
static-site export). Nothing here reads the wall clock, so the site export stays
byte-deterministic.

* :func:`portal_doc` — what learn-cli is and its three faces (static).
* :func:`contract_doc` — the subject-plugin contract, generated from
  :mod:`learn.contract` (version, vocabularies, the eight verbs, a schema index).
* :func:`subjects_doc` — the subject catalog, generated from the registry
  (metadata only; **no** install status, so the page is environment-independent).
"""

from __future__ import annotations

from learn.contract import (
    CONTRACT_VERSION,
    MASTERY_LEVELS,
    RESULTS,
    SCHEMA_NAMES,
    STORY_LEVELS,
    load_schema,
)
from learn.subjects import load_registry

#: (verb, invocation, what it does) — the eight contract verbs, in contract order.
_VERBS: tuple[tuple[str, str, str], ...] = (
    ("overview", "overview", "the subject describes itself: identity, modules, content counts"),
    ("progress", "progress", "where the learner stands on the mastery ladder"),
    ("advice", "advice", "deterministic study advice, each with a runnable command"),
    ("story", "story list / story read <id>", "the shared content surface (graded readers)"),
    ("lesson", "lesson start|next|repeat", "the subject resolves what to teach next"),
    ("practice", "practice [<scope>]", "a batch of exercises to run and grade"),
    ("record", "record --item <id> --result <r>", "the driver's graded write-back"),
    ("doctor", "doctor", "self-check plus the pinned contract version"),
)


def portal_doc() -> str:
    """The portal's self-description — what learn-cli is and how to reach it."""
    return """# learn-cli — the learning portal

learn-cli is the **learning front** for the AgentCulture mesh: one product with
three faces over a single registry — a **CLI** (`learn`), an **MCP server**, and
an agent-readable **HTTP site** — so humans and agents learn a subject, step by
step. It is **not a tutor**. It is the portal that fronts per-subject tutor CLIs
(`french`, `spanish`, `culture-guide`), driving them as external subprocesses
over `--json`; it never imports subject code and holds no subject content.

## The three faces, one registry

All three faces are derived from one `agentfront.App` (see `learn.front`), so the
human page, the agent's MCP tool, and the `--json` answer cannot drift:

- **CLI** — `learn subjects`, `learn subject doctor <name>`, plus `learn mcp
  serve`, `learn site serve`, and `learn site export`.
- **MCP** — `learn mcp serve` runs a single-dispatch `run` tool over stdio whose
  catalog is every tool below, so an agent can drive a full learning loop.
- **HTTP** — `learn site serve` serves these docs as markdown (`/<slug>`,
  `/sitemap.xml`, `/llms.txt`, `/front`); `learn site export` writes a static
  content bundle the site build consumes.

## Tools (the learning loop)

`subjects_list`, `subject_doctor`, `story_list`, `story_read`, `progress`,
`advice`, `lesson_next`, `practice`, `record` — each drives the matching subject
contract verb. `record` is the write-back that closes the loop and feeds
learn-cli's motivation layer (scores, streaks, review queues).

## Exit-code policy

`0` success · `1` user error · `2` environment error (e.g. a subject not
installed) · `3+` reserved. Every command supports `--json`; results go to
stdout, errors/diagnostics to stderr, never mixed.

## See also

- `subject-plugin-contract` — the interface a subject CLI must satisfy.
- `subjects` — the catalog of registered subjects.
"""


def contract_doc() -> str:
    """The subject-plugin contract, generated from ``learn.contract`` package data."""
    lines: list[str] = [
        "# The subject-plugin contract",
        "",
        f"Contract version **{CONTRACT_VERSION}** "
        "(`learn.contract.CONTRACT_VERSION`). This is the interface a subject CLI "
        "must satisfy to be hosted by learn-cli. The full narrative spec lives at "
        "`docs/specs/subject-plugin-contract.md`; this page is generated from the "
        "machine-readable schemas that ship in the package.",
        "",
        "## The model",
        "",
        "- **The subject CLI** is an LLM-free engine: it owns committed content and "
        "per-learner mastery, resolves what to teach next, and emits structured "
        "teaching directives. It never converses, grades free text, or computes scores.",
        "- **The driver** (an agent or human harness) does the conversational tutoring "
        "the directive describes and writes graded results back via `record`.",
        "- **learn-cli** drives subjects as external `--json` subprocesses (never "
        "importing them) and owns the deterministic motivation layer.",
        "",
        "## The eight verbs",
        "",
        "| Verb | Invocation | What it does |",
        "| --- | --- | --- |",
    ]
    for verb, invocation, meaning in _VERBS:
        lines.append(f"| {verb} | `{invocation}` | {meaning} |")
    lines += [
        "",
        "Invocation is always `<subject-command> <verb> [args] --json [--learner "
        "<id>]`. Errors emit `{code, message, remediation}` on stderr and exit with "
        "that code.",
        "",
        "## Shared vocabularies",
        "",
        f"- **Mastery ladder** (ordered): {' → '.join(MASTERY_LEVELS)}.",
        f"- **Raw results**: {' | '.join(RESULTS)} (subjects never emit scores).",
        f"- **Story/lesson levels**: {' | '.join(STORY_LEVELS)}.",
        "",
        "## Schemas",
        "",
        f"Every payload carries `schema_version` (family `{CONTRACT_VERSION[0]}.x`). "
        "The shipped schemas (`learn.contract.SCHEMA_NAMES`):",
        "",
    ]
    for name in SCHEMA_NAMES:
        schema = load_schema(name)
        title = schema.get("title", name)
        lines.append(f"- **`{name}`** — {title}")
    lines.append("")
    return "\n".join(lines)


def subjects_doc() -> str:
    """The subject catalog, generated from the registry (metadata only, deterministic)."""
    lines: list[str] = [
        "# Subjects catalog",
        "",
        "The subjects learn-cli hosts. This set is pure registry data "
        "(`learn/subjects/registry.json`, overridable via `LEARN_SUBJECTS_REGISTRY`); "
        "adding a subject is a data entry plus a conformant CLI, and deleting the "
        "entry removes it from every face. Install status is intentionally omitted "
        "here (it is environment-dependent) — query it live with `learn subjects`.",
        "",
    ]
    entries = load_registry()
    if not entries:
        lines.append("_No subjects registered._")
        lines.append("")
        return "\n".join(lines)
    for entry in entries:
        lines += [
            f"## {entry.display_name} (`{entry.name}`)",
            "",
            entry.description,
            "",
            f"- Repo: {entry.repo}",
            f"- Driven as: `{' '.join(entry.argv_prefix)} <verb> --json`",
            f"- Contract: {entry.contract_version}",
            "",
        ]
    return "\n".join(lines)
