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


_MCP = """\
# learn mcp

The MCP face of the portal. `mcp serve` runs agentfront's single-dispatch MCP
server over stdio — one `run` tool whose catalog is every tool in the portal's
App registry (`learn.front.build_app`), so an agent can drive a full learning
loop (list subjects, read a story, get a lesson, record a result) over MCP.
learn-cli writes no MCP-protocol code: the CLI, MCP, and HTTP faces are all
derived from one registry and cannot drift.

## Verbs

- `learn mcp overview` — describe this noun and its tools.
- `learn mcp serve` — run the MCP server over stdio.

## Usage

    learn mcp overview
    learn mcp serve

Needs agentfront's `mcp` extra (a runtime dependency of learn-cli).
"""

_MCP_SERVE = """\
# learn mcp serve

Runs the portal's MCP server over stdio. The server exposes a single `run` tool
whose description embeds the command catalog derived from the App registry; an
agent calls `run({command:[...], args:{...}})` to invoke a subject verb.

Tools available over MCP: `subjects_list`, `subject_doctor`, `story_list`,
`story_read`, `progress`, `advice`, `lesson_next`, `practice`, `record` — the
last closes the learning loop by writing a graded result back to the subject.

Blocking (stdio transport). Wire it into an MCP client's server config. Results
are the subjects' `--json` payloads; errors carry `{code, message, remediation}`.

## Usage

    learn mcp serve
"""

_SITE = """\
# learn site

The HTTP face of the portal plus the static-site export. Both are derived from
the same App registry the CLI and MCP faces read.

## Verbs

- `learn site overview` — describe this noun, its routes, and the export format.
- `learn site serve [--host --port]` — serve the docs as an agent-readable
  markdown site (`/<slug>`, `/sitemap.xml`, `/llms.txt`, `/front`).
- `learn site export --out <dir>` — write the pinned static content bundle for
  the Astro site build.

## Usage

    learn site overview
    learn site serve --host 127.0.0.1 --port 8080
    learn site export --out ./_export
"""

_SITE_SERVE = """\
# learn site serve

Serves the portal's docs as an agent-readable markdown HTTP site (a WSGI app on
the standard library). Routes: `GET /<slug>` (markdown doc), `GET /sitemap.xml`,
`GET /llms.txt` (the agent entry point), and `GET /front` (the live-cockpit view
as markdown). Blocking; stop with Ctrl-C.

## Usage

    learn site serve
    learn site serve --host 0.0.0.0 --port 8080
"""

_SITE_EXPORT = """\
# learn site export

Writes the pinned static content bundle the Astro site build consumes, into
`--out <dir>`:

- `meta.json` — `{contract_version, schema_version, subjects}`.
- `subjects.json` — `[{name, display_name, description, repo, available, modules}]`
  (modules best-effort from each subject's `overview`; `[]` if unavailable).
- `stories-<subject>.json` — `{subject, stories:[...]}` for each AVAILABLE
  subject (full story objects from `story list` + `story read`); unavailable
  subjects are skipped.
- `docs/<slug>.md` — every doc page registered in the App.

Deterministic (sorted keys, registry/story-list order, no wall clock), so a
re-run over unchanged inputs yields byte-identical files. It never fails because
a subject is missing — an uninstalled subject is listed `available: false`.

## Usage

    learn site export --out ./_export
    learn site export --out ./_export --json
"""


_AUTH = """\
# learn auth

GitHub device-flow sign-in linking this CLI to the same learner account the
web uses. Sign-in is additive, never a gate: every other verb (`progress`,
`next`, `record`) works fully offline with no session — signing in only adds
cross-device sync/continuity through the learn API.

## Verbs

- `learn auth login` — start the device flow: prints a verification URL + user
  code, polls until confirmed, stores the session locally (`~/.local/share/
  learn_cli/auth.json`, `0600`).
- `learn auth logout` — best-effort server-side revoke, then always clears the
  local session.
- `learn auth status` — local sign-in + sync status. Reads only local files —
  never touches the network.
- `learn auth overview` — describe this noun (you are here).

## Usage

    learn auth login
    learn auth status --json
    learn auth logout

`LEARN_API_URL` overrides the API base (default
`https://agentculture.org/learn/api`, a placeholder until the Worker is
routed live).
"""

_AUTH_LOGIN = """\
# learn auth login

Starts the GitHub device flow against the learn API (`POST /api/auth/device`),
prints the verification URL and user code, then polls until the learner
confirms in a browser. On success the session (bearer token, expiry, linked
GitHub identity) is stored at `~/.local/share/learn_cli/auth.json` (`0600`).

## Usage

    learn auth login
    learn auth login --json

Exits 2 (environment error) on a network failure or a timeout waiting for
confirmation; retry the command to start a fresh device code.
"""

_AUTH_LOGOUT = """\
# learn auth logout

Signs out: attempts a best-effort server-side session revoke
(`POST /api/auth/logout`), then always clears the local session file —
signing out succeeds even if the network call fails.

## Usage

    learn auth logout
    learn auth logout --json
"""

_AUTH_STATUS = """\
# learn auth status

Reports local sign-in and sync status: the linked learner identity, token
expiry, and how many local ledger rows have been pushed vs. are pending.
Reads only local files — makes no network call, so it is always instant and
works offline.

## Usage

    learn auth status
    learn auth status --json
"""

_ADMIN = """\
# learn admin

The admin-only CLI surface (tasks t8 + t9): `admin learners` lists every
learner plus a cheap per-subject progress summary via
`GET /api/admin/learners`; `admin approve` / `admin revoke` grant or
withdraw a learner's tutoring tier via `POST /api/admin/approve` /
`POST /api/admin/revoke`. All require a local session (`learn auth login`) —
the same authenticated-API pattern `learn auth` uses. Admin-ness itself is a
SERVER-SIDE decision (spec c12/h4, allow-listed GitHub ids enforced in
`workers/learn-api/src/admin.js`): this CLI makes none of its own — a
non-admin token gets whatever structured error the server returns, surfaced
here as an environment error (exit 2).

## Verbs

- `learn admin learners` — list every learner + a per-subject progress
  summary and their tutoring-tier approval (admin-only; server-enforced).
- `learn admin approve <github_user_id>` — grant the tutoring tier
  (server enforces decision c20: the learner's consent must be current).
- `learn admin revoke <github_user_id>` — withdraw the tutoring tier
  (effective on the learner's next tutor call; no re-login involved).
- `learn admin overview` — describe this noun (you are here).

## Usage

    learn auth login
    learn admin learners
    learn admin approve 20955789
    learn admin revoke 20955789 --json

`LEARN_API_URL` overrides the API base (default
`https://agentculture.org/learn/api`).
"""

_ADMIN_LEARNERS = """\
# learn admin learners

Lists every learner registered with the learn API, each with `github_user_id`,
`display_name`, `created_at`, `visibility`, tutoring-tier `approved` (t9),
consent status/version, and a per-subject record-count summary — via
`GET /api/admin/learners`. Requires a local session (`learn auth login`); the
server 403s a non-admin token (`admin_required`), surfaced here as an
environment error (exit 2), never a silent empty list.

## Usage

    learn admin learners
    learn admin learners --json
"""

_ADMIN_APPROVE = """\
# learn admin approve <github_user_id>

Grants a learner the Bedrock tutoring tier via `POST /api/admin/approve`
(spec c13, task t9). Requires a local session (`learn auth login`); the
server enforces the admin allow-list (403 `admin_required` for anyone else)
AND decision c20 — the target learner's recorded consent must cover the
CURRENT terms version, otherwise the server 409s `consent_stale` and nothing
is written. Both failures surface here as environment errors (exit 2).

Approval takes effect on the learner's very next `/api/tutor` call — the
Worker reads the flag per request, so the learner does not re-login. Until
approved, a consented learner's tutor calls get a structured
`403 approval_required` and spend zero inference.

## Usage

    learn admin learners            # find the github_user_id + consent status
    learn admin approve 20955789
    learn admin approve 20955789 --json
"""

_ADMIN_REVOKE = """\
# learn admin revoke <github_user_id>

Withdraws a learner's Bedrock tutoring tier via `POST /api/admin/revoke`
(task t9). Requires a local session (`learn auth login`); admin-only
(server-enforced allow-list, 403 `admin_required` otherwise). Idempotent — a
never-approved learner revokes to the same state. Takes effect on the
learner's very next `/api/tutor` call (the Worker reads the flag per
request): they get a structured `403 approval_required` and spend zero
inference, while progress/records/export keep working.

## Usage

    learn admin revoke 20955789
    learn admin revoke 20955789 --json
"""

_PROGRESS = """\
# learn progress

Cross-subject learning standing. For each registered (and installed) subject,
drives its own `progress --json` subprocess for the authoritative facts
(items total/touched/mastered, its mastery map, its own within-subject
`next`), then blends those with the local ledger via `learn.motivation` for
what only the ledger can produce: per-subject mean scores and day-based
streaks (plus an overall cross-subject streak). A subject that isn't
installed is reported `available: false` rather than failing the command.

Anonymous-safe: drives each subject with no `--learner` flag, so it resolves
its own default exactly as if run directly by hand.

## Usage

    learn progress
    learn progress french --json
"""

_NEXT = """\
# learn next

The single best next action across every subject, from
`learn.motivation.what_next()`: folds each installed subject's own progress
facts with the local ledger and renders one typed recommendation — never
empty, even for a learner who has mastered everything (maintenance mode:
review, a fresh story, or a harder repeat).

## Usage

    learn next
    learn next --json
"""

_RECORD = """\
# learn record <subject>

Records one graded outcome. Proxies to the subject's own `record` verb (the
subject stays the source of truth for its mastery ladder), appends the
acknowledged `recorded` object to the local cross-subject ledger, and — when
signed in — makes a best-effort push of unsynced ledger rows to the learn
API. A network failure during that push never fails the command; the
`sync` block in the JSON payload reports what happened.

## Usage

    learn record french --item greetings --result pass --activity lesson --json
    learn record french --item numbers --result partial --correct 2 --total 3 \\
        --duration-seconds 45 --json

Required: `--item`, `--result` (`pass|partial|fail`). Optional: `--activity`
(`lesson|practice|story`, default `practice`), `--exercise`, `--story`,
`--lesson`, `--correct`, `--total`, `--duration-seconds`, `--notes`.
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
    ("mcp",): _MCP,
    ("mcp", "overview"): _MCP,
    ("mcp", "serve"): _MCP_SERVE,
    ("site",): _SITE,
    ("site", "overview"): _SITE,
    ("site", "serve"): _SITE_SERVE,
    ("site", "export"): _SITE_EXPORT,
    ("auth",): _AUTH,
    ("auth", "overview"): _AUTH,
    ("auth", "login"): _AUTH_LOGIN,
    ("auth", "logout"): _AUTH_LOGOUT,
    ("auth", "status"): _AUTH_STATUS,
    ("progress",): _PROGRESS,
    ("next",): _NEXT,
    ("record",): _RECORD,
    ("admin",): _ADMIN,
    ("admin", "overview"): _ADMIN,
    ("admin", "learners"): _ADMIN_LEARNERS,
    ("admin", "approve"): _ADMIN_APPROVE,
    ("admin", "revoke"): _ADMIN_REVOKE,
}
