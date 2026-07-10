# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What learn-cli is

learn-cli is the **learning front** for the AgentCulture mesh: one product with
three faces — a **CLI** (command `learn`), an **MCP server**, and a **web site**
(target: <https://agentculture.org/learn/>, one sub-page per module) — over a
single idea: *humans and agents learn a subject, step by step*.

It is **not a tutor itself**. It is the **portal that fronts per-subject tutor
CLIs** — each tutor stays its own sibling repo with its own progression logic,
and `learn` drives them as external runtimes behind one door, one profile, one
site. The relationship is "learn-cli is to its subject CLIs what
`league-of-agents-platform` is to the arena runtime — it hosts and unifies, it
does not reimplement." The first subjects:

- [`french-cli`](https://github.com/agentculture/french-cli) (command `french`)
  and [`spanish-cli`](https://github.com/agentculture/spanish-cli) (`spanish`) —
  language tutors. **Their verbs define the tutor UX learn-cli inherits; read
  them before designing anything.** Both run `backend: colleague`.
- [`culture-guide`](https://github.com/agentculture/culture-guide) — the
  non-language subject (learning to build and lead agent teams), the proof the
  subject interface generalizes beyond languages.

The authoritative brief is [issue #1](https://github.com/agentculture/learn-cli/issues/1)
("Build brief: learn"). Read it before doing product work.

## Current state: scaffold, not product

**Almost none of the product above is built yet.** This repo was cloned from
[`culture-agent-template`](https://github.com/agentculture/culture-agent-template)
and today contains only the template's **agent-first CLI skeleton** (identity +
introspection verbs) plus the mesh baseline (CI, skills, deploy). The subject
registry, the MCP server, the web site, cross-subject learner profiles, and any
actual tutoring **do not exist**. When you read the code and its self-describing
strings still say *"a clonable template for AgentCulture mesh agents,"* that is
leftover template identity, not a description of the finished product — replacing
it with learn-cli's real identity is part of the build.

Suggested build order from the brief: read french/spanish end-to-end → `/think`
a spec for the **subject-plugin contract** (the central design; everything
composes on it) → build the three faces as **agentfront** surfaces, proven
consistent → cross-subject learner state → hosting + model-access wiring.

## Commands

Python ≥3.12, managed with **uv**. The runtime package has **zero third-party
dependencies** (`dependencies = []`); all tooling lives in the `dev` group.

```bash
uv sync                                   # install deps + dev tools into .venv
uv run pytest -n auto                      # full suite (xdist parallel)
uv run pytest tests/test_cli.py::test_whoami_text   # a single test
uv run pytest -n auto --cov=learn --cov-report=term  # with coverage (CI fails <60%)
uv run learn whoami                        # run the CLI (see naming note below)
uv run teken cli doctor . --strict         # the agent-first rubric gate CI enforces
```

**CLI command-name split (important):** the installed console script is
`learn` (see `[project.scripts]` in `pyproject.toml`), but the argparse `prog`,
the PyPI dist name, and ~100 hard-coded strings all say `learn-cli`. So it is
`uv run learn whoami`, **not** `uv run learn-cli whoami` (the latter fails to
spawn — there is no `learn-cli` executable). The internal help still prints
`usage: learn-cli`; that cosmetic split is noted under scaffold drift below.

Lint/format (each must pass in CI; all are line-length 100):

```bash
uv run black --check learn tests
uv run isort --check-only learn tests
uv run flake8 learn tests
uv run bandit -c pyproject.toml -r learn
markdownlint-cli2 "**/*.md" "#node_modules" "#.claude/skills"
```

## Architecture

### The agent-first CLI (what exists today)

Everything lives under `learn/`. The CLI is a hand-rolled argparse tree built to
pass the **agent-first rubric** (`teken cli doctor --strict`, 7 bundles) — every
surface is machine-consumable.

- **`learn/cli/__init__.py`** — `main()` is the single entry point. `_build_parser()`
  wires up global verbs and noun groups; `_dispatch()` invokes the selected
  handler and translates exceptions to exit codes. `_CliArgumentParser` overrides
  argparse's `.error()` so even parse-level failures (unknown verb, bad flag)
  route through the structured error contract instead of argparse's default
  `stderr`/exit-2. `--json` is peeked out of raw argv *before* parsing so those
  early errors can still honour it.
- **`learn/cli/_commands/`** — one module per verb, each exposing a
  **`register(sub)`** function that adds its subparser and sets `func=` +
  `json=`. **To add a command: write the module, call its `register()` from
  `_build_parser()`, and add an `explain` catalog entry (below).** Global verbs:
  `whoami`, `learn`, `explain`, `overview`, `doctor`. Noun group: `cli` (with
  `cli overview`).
- **`learn/cli/_errors.py`** — `CliError(code, message, remediation)` and the
  exit-code constants. **Every failure raises `CliError`;** `_dispatch` wraps any
  other exception into one, so no Python traceback ever reaches stderr.
- **`learn/cli/_output.py`** — the strict stream split: `emit_result` → stdout,
  `emit_error`/`emit_diagnostic` → stderr, **never mixed**. JSON mode routes
  structured payloads to the same streams. Text-mode errors render as
  `error: …` + `hint: …` (the `hint:` prefix is required by the rubric).
- **`learn/explain/`** — `catalog.py` holds `ENTRIES`, a dict keyed by
  command-path **tuple** → verbatim markdown; `resolve()` looks a path up or
  raises `CliError`. `test_every_catalog_path_resolves` enforces that **every
  registered path has an entry**, so new commands need a catalog entry or the
  suite breaks.

**Output/exit-code contract** (documented in `learn learn`, echoed everywhere):
`--json` on every command; exit `0` success, `1` user error, `2` environment
error, `3+` reserved.

**Rubric constraints to preserve when editing** (these will fail `teken cli
doctor --strict` if broken): the `learn` verb's text must be ≥200 chars and
mention purpose, command map, exit codes, `--json`, and `explain`; any noun with
action-verbs must also expose `overview` (this is the sole reason the `cli` noun
and its `cli overview` exist); descriptive verbs like `overview` must never hard-fail
on a bogus target path (they accept-and-ignore it and exit 0); `doctor` must emit
`{healthy, checks:[{id, passed, severity, message, remediation}]}`.

### `doctor` and the mesh identity invariants

`learn doctor` mirrors what `steward doctor` checks for a mesh agent, reading
`culture.yaml` with a dependency-free parser:

- **prompt-file-present / backend-consistency** — the declared `backend` must
  have its matching prompt file on disk: `claude`→`CLAUDE.md`,
  **`colleague`→`AGENTS.colleague.md`**, `acp`→`AGENTS.md`, `gemini`→`GEMINI.md`.
- **skills-present** — the vendored `.claude/skills/` kit exists.

This repo runs **`backend: colleague`** (a served Qwen model — see
`culture.yaml`), so the mesh-resident prompt is **`AGENTS.colleague.md`**, and
`CLAUDE.md` (this file) is what Claude Code reads when you work here. Keep
`culture.yaml`, the prompt files, and `doctor`'s backend map in agreement — a
mismatch fails the invariant. `test_doctor_recognizes_declared_backend` guards
against changing the backend without teaching `doctor` the new prompt file.

### The intended architecture (issue #1) — three faces from one registry

When you build the real product, the load-bearing decisions are already made in
the brief — follow them rather than re-deciding:

- **Derive all three faces from one registry via
  [`agentfront`](https://github.com/agentculture/agentfront)** (formerly
  `teken`/`afi-cli`; `teken` is still the dev-dep/CLI name today). Declare docs
  and tools once; agentfront emits the CLI, the MCP server, and the HTTP site
  (markdown pages + sitemap) so the human page, the agent's MCP tool, and the
  `--json` answer can't drift. Build *through* agentfront, don't hand-roll three
  renderers.
- **The subject-plugin contract is the central design.** Define what a subject
  CLI must satisfy (progress, overview, advice, lesson/story content, practice)
  so adding a third subject is a registration, not a fork. french/spanish are the
  first entries; culture-guide proves it isn't language-specific.
- **One learner, many subjects** — a single profile/login spanning subjects, with
  cross-subject progress and "what next" that the per-subject tutors track only
  within themselves.
- **The web face** — learn-cli **owns** this surface: its lesson/story/exercise
  content and the subject CLIs as the engines behind it, served at
  `agentculture.org/learn/` with **a sub-page per module** (a learner reads a
  story, does an exercise, sees their streak). The *domain* `agentculture.org` is
  managed by the sibling [`org`](https://github.com/agentculture/org) repo
  (`../org` — a CLI + Astro `site-astro/` in one repo), so the `/learn/` route and
  pages must be **coordinated with org**, and org is the repo shape to match (a
  CLI plus site in one repo). *How* learn-cli's surface is served behind that
  route — static pages published through org's Astro build vs. a service
  learn-cli runs — is part of the **still-open hosting decision** below; per the
  brief, whichever target is chosen must be recorded with a *cost-when-busy* note.
- **Don't hand-roll infra a sibling already owns** (all flagged as open decisions
  in the brief): model calls go through
  [`cloudai-cli`](https://github.com/agentculture/cloudai-cli) or
  [`ec2bedrock-cli`](https://github.com/agentculture/ec2bedrock-cli); learner
  state that outgrows flat files goes to
  [`eidetic-cli`](https://github.com/agentculture/eidetic-cli) or
  [`data-refinery-cli`](https://github.com/agentculture/data-refinery-cli);
  hosting precedents (CLI + site in one repo) are `league-of-agents-platform`,
  [`org`](https://github.com/agentculture/org), and
  [`culture-tools`](https://github.com/agentculture/culture-tools).

## Conventions CI enforces

Three workflows gate `main` (`.github/workflows/tests.yml`, `publish.yml`):

- **Bump the version on every PR.** `publish.yml` publishes to PyPI on *every*
  push to `main` (Trusted Publishing is already registered — `learn-cli 0.4.0`
  is live), so a stale version means a failed publish. The `version-check` job
  fails the PR if `pyproject.toml`'s version equals `main`'s. Use the
  **`version-bump`** skill (`major|minor|patch`) — it updates `pyproject.toml`
  and prepends a Keep-a-Changelog entry to `CHANGELOG.md`. This applies even to
  docs/config/CI-only PRs. (`__version__` is read from installed package
  metadata via `importlib.metadata`, so there is no separate `__init__.py`
  version to keep in sync.)
- **The lint job** runs black, isort, flake8, bandit, markdownlint-cli2, **and
  the rubric gate** (`teken cli doctor . --strict`) — the last will block any
  change that breaks the agent-first contract.
- **SonarCloud quality gate** (`sonar.qualitygate.wait=true`, project key
  `agentculture_learn-cli`) fails the `test` job on a red gate when `SONAR_TOKEN`
  is set; token-less/fork PRs skip it and stay green. Coverage floor is 60%
  (`tool.coverage.report.fail_under`).

**PR lifecycle:** use the **`cicd`** skill (layered on `devex pr`) to open PRs,
poll CI, and address review threads; it adds `status` (Sonar gate + hotspots +
unresolved-thread tally) and `await` (blocks until CI settles, non-zero on a
Sonar ERROR or unresolved threads). See the `sonarclaude` skill for direct
quality queries.

## Vendored skills (cite-don't-import)

`.claude/skills/` holds the guildmaster skill kit, **vendored verbatim, not
installed as a dependency** — each consumer owns its copy.
[`docs/skill-sources.md`](docs/skill-sources.md) is the provenance ledger and
the re-sync procedure; consult it before editing a vendored skill. Notes:

- Every `SKILL.md` must carry `type: command` in its frontmatter — it's
  load-bearing (the culture backend's `core.skill_loader` silently skips skills
  without it), even where guildmaster's upstream copy omits it.
- Most skills come from guildmaster; `think`/`spec-to-plan`/`assign-to-workforce`
  originate in `devague` (re-broadcast via guildmaster); `ask-colleague` is
  vendored **directly from `colleague`** (a tracked divergence until guildmaster
  re-broadcasts the rename). The `agex`→`devex` rename is another tracked
  in-place patch. Both divergences are documented in the ledger.
- **Don't reformat vendored skills** — markdownlint and Sonar both exclude
  `.claude/skills/**` for this reason.

## Known scaffold drift (fair game to fix)

These are leftovers from the template clone, worth correcting as you build:

- **Self-description strings** in `learn/cli/_commands/learn.py`,
  `learn/explain/catalog.py`, `README.md` ("Make it your own"), and
  `overview.py` still call this "a clonable template" and reference a rename
  procedure — that identity is the template's, not learn-cli's. Replacing it with
  learn-cli's real product identity is part of the build.
- **The `prog` name still prints `learn-cli`** — the argparse `prog` and ~100
  internal strings use the PyPI dist name even though the invoked command is
  `learn`. Cosmetic; fold into the product-identity pass rather than churning
  ~100 strings (and the tests that assert `usage: learn-cli`) piecemeal. The
  product/mesh name `learn-cli` (culture.yaml `suffix`, the `# learn-cli` doc
  headings) is correct and stays.

Already reconciled (was drift, now fixed): the README invocations use `learn`,
and the skill count (README + `docs/skill-sources.md`) matches the 14 skills on
disk.

## Signing posts

When posting on GitHub/Slack on the user's behalf: the `cicd`/`communicate`
scripts auto-append the signature (`- learn-cli (Claude)`, resolved from
`culture.yaml`) — don't sign the body manually. For a manual `gh` post the
scripts don't author, sign explicitly as `- learn-cli (Claude)`. Mesh messages
are unsigned (the IRC nick is the speaker).
