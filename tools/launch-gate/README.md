# learn-cli launch gate

The **pre-launch E2E gate**: the scripted success walk plus the measurable
launch bar, every number machine-checked, nothing asserted by hand. Run it
before declaring launch (spec claims c14/h23, c32/h24).

```bash
bash tools/launch-gate/run.sh
```

It boots the **real production topology locally** — the Cloudflare Worker in
front of the built static site, one origin serving `/learn/` (static) and
`/learn/api/*` (API) — with **no cloud, no wrangler, no miniflare**, runs the
whole walk at a phone viewport (390x844) and a desktop viewport (1280x800),
prints a final PASS/FAIL table, and exits non-zero if any check failed.

## Not wired into CI (on purpose)

This gate runs **pre-launch, by hand**, not per-PR. It drives the sibling
subject CLIs (`french`, `spanish`, `culture-guide`) and builds the site, so it
is heavier and less hermetic than the unit suite. Nothing here is added to
`.github/workflows/`. The audience tests under `tests/e2e/` are **skipped**
unless `RUN_LAUNCH_GATE=1` (which `run.sh` sets), so the normal
`uv run pytest -n auto` stays fast and green (they show as skipped).

## Prerequisites

- The three subject CLIs built and conformant, on PATH via their venvs. Default:
  `/home/spark/git/{french-cli,spanish-cli,culture-guide}/.venv/bin` — override
  with `LAUNCH_GATE_SUBJECT_BIN` (a colon-separated list). `run.sh` prepends
  them and fails preflight with a clear remediation if a CLI is missing.
- `node` (>=18) and `npm`, for the site build, the local API server, and the
  Playwright walk.
- `uv`, for the Python launch-bar checks and the pytest audience tests.
- Read-only access to a sibling `org` checkout for the CSS-token diff (found at
  `../org`, `../../org`, or `~/git/org`; override with `LAUNCH_GATE_ORG_CSS`).
- Playwright's Chromium. `run.sh` runs `npx playwright install chromium`
  (a no-op when already cached). If the browser can't launch, the browser-level
  checks are reported **SKIPPED** and a fetch/DOM fallback still exercises the
  API-level walk — the gate never silently passes an un-run check.

## The hermetic topology (`api-server.mjs`)

`workers/learn-api/src/index.js` is a Web-standard `{ fetch(request, env, ctx) }`
handler. `api-server.mjs` wraps that **exact default export** with the **same
in-memory stubs the Worker's own unit tests use** — `KVStub`, `D1Stub`,
`makeEnv`, `mintToken`, imported straight from
`workers/learn-api/test/helpers.js`. It stands up two servers:

- a loopback-only **static file server** for the built site (the deploy tree,
  `dist/` wrapped under `learn/` exactly like `deploy-site.yml`'s "Prepare
  deploy directory" step), and
- the **Worker-wrapping server** — the single public origin — with the Worker's
  `PAGES_ORIGIN` pointed at that static server, so the Worker's own `/learn/*`
  **zone-mount proxy** (`proxyToPages` in `index.js`) is exercised for real.

The browser therefore sees one origin: `/learn/` proxied to the static site,
`/learn/api/*` served by the Worker. A signed-in session is a token minted with
`mintToken` (the Worker tests' helper) using the same `SESSION_SECRET` as the
stub env, set as the `session` cookie in Playwright's context.

## The walk (assert, don't eyeball)

Signed-out (fresh context, no cookie), at each viewport:

- loads `/learn/`, sees the three subject cards and the invitation card;
- opens a french story, asserts its body + glossary rendered and its sign-in
  CTA visible, asserts `html[data-auth="out"]`;
- asserts the **network invariant**: the signed-out story visit fires exactly
  one `/learn/api/*` call (`GET /api/me`) and nothing else — no `/progress`,
  `/record`, or `/tutor` (the resource gate; spec c21/c22).

Signed-in (context with the minted session cookie), at each viewport, per
subject (french, spanish, culture-guide):

- loads `/learn/`, asserts `html[data-auth="in"]` and the display name;
- records a pass by **clicking the story exercise's record button** (the real
  web write path), and asserts the write lands in `GET /api/progress/:subject`;
- via the parity bridge (below) proves a CLI-synced row appears identically in
  the browser-rendered learner panel and the raw API.

## Parity: exactly what it means

"Progress parity across web, `learn --json`, and MCP" is two honest claims, each
machine-checked:

- **Local-ledger faces agree with each other.** For the same isolated profile +
  subjects on PATH, `learn progress <subject> --json` and the MCP `progress`
  tool drive the same subject subprocess over the same state, so they report
  **numerically identical** `items_total` / `items_touched` / `items_mastered` /
  `mastery`. Proven by `tests/e2e/test_mcp_harness.py` (agent) cross-checked
  against `learn progress` (CLI), and by `tests/e2e/test_cli_golden.py`.
- **Synced rows appear identically in the API-backed web view.** The web write
  (a story-exercise button) and a CLI write (`learn record`, signed in with the
  same session token, syncing to the local API) both land in the server ledger
  under one learner. The subject page's learner panel is then reloaded and its
  displayed `touched`/`mastered` counts are asserted **equal to the raw
  `GET /api/progress/:subject`** the panel reads from, and the CLI-synced
  `item_id` is asserted **present in both** the rendered panel's totals and the
  API. Proven by `walk.mjs`'s browser + CLI bridge.

These are distinct ledgers by design: `learn progress` blends the **local**
append-only ledger with each subject's own state; the web/API view is the
**server** ledger of synced + web-recorded rows. The gate proves each face is
self-consistent and that a row crossing from CLI to server shows up unchanged in
the browser — not that two different stores hold byte-identical numbers.

## The audience acceptance tests

One green acceptance test per audience:

- **Web** — `walk.mjs` (Playwright, signed-in and signed-out, phone + desktop).
- **CLI** — `tests/e2e/test_cli_golden.py` (pytest, golden `learn ... --json`).
- **Agent** — `tests/e2e/test_mcp_harness.py` (pytest, MCP via `call_mcp`).

## The measurable launch bar (`launch_bar.py`)

Every launch-bar number, machine-checked:

- 3 subjects pass `learn subject doctor <s> --json` (`healthy: true`).
- Content counts from the real content (driven through the subject CLIs, dev-`*`
  fixtures excluded): french + spanish each >=10 stories across >=3 levels;
  culture-guide >=3 scenarios.
- Zero new design tokens vs org: the set of custom-property names **defined** in
  this site's `global.css` is a subset of org's.
- The zero-API static check is `site-astro`'s own `npm run check` (static-auth +
  export-pages), run as a `run.sh` step since it needs the node build.

## The consent-tutoring uplift checks (t17)

The extended gate adds the uplift's four new guarantees — consent, approval,
deletion, and the tutoring/voice tiers — on top of the original walk. They live
in two places so the pre/post-deploy story is legible:

- **`consent_walk.mjs`** — the success signals as HTTP flows over a real origin,
  in two modes with the SAME check ids:
  - **LOCAL** (default): the FULL authed flows against the in-process topology
    (`api-server.mjs`) — a fresh sign-in writes **zero D1 rows until consent is
    accepted** (and the consent row is written **before** the learner row); a
    published-version bump forces **re-consent**; **self-serve delete** erases
    every row and revokes the session; a consented-but-unapproved `/api/tutor`
    call gets **403 with the inference endpoint hit zero times**; **admin
    approve/revoke** flips the tutoring tier; the **voice-token mint** enforces
    the same gate in the same order (approval before config); and the policy /
    consent / voice pages plus **cloze** story content are actually served. This
    is the "passes now" evidence.
  - **LIVE** (`LIVE_ORIGIN` set): the deployed origin's **unauthenticated**
    surface — new routes must answer 401 (not 404), new pages must exist with
    their markers. Against **pre-uplift** prod these FAIL (404s) — the recorded
    **`BASELINE-2026-07-11.md`** baseline (spec h17); post-deploy they pass.
- **`tests/test_launch_gate_invariants.py`** (repo `tests/`, always-on — not
  gated by `RUN_LAUNCH_GATE`) — the mechanical boundary invariants (h16): the
  schema stores **no email/password** column, the Worker adds **no provider
  SDK** (dependency or import), the static-auth zero-API check stays wired, and
  **no subject prose is authored inside learn-cli** (the exporter drives the
  subject CLIs and embeds no prose; learn-cli's own JSON carries no story
  content). These run in the normal `uv run pytest` suite.

The **authed** consent/approval/delete/voice flows cannot be reproduced against
LIVE prod (no mintable prod session), so the Worker's own unit suite
(`cd workers/learn-api && npm test`, 183 tests) is run as a `run.sh` step and is
the authoritative proof of the zero-inference counting, consent ordering, and
revocation invariants — `consent_walk.mjs` LOCAL mode re-proves them at the HTTP
layer.

## Files

- `run.sh` — the single entrypoint; orchestrates every check, prints the table.
- `api-server.mjs` — wraps the real Worker + static site into one local origin.
- `walk.mjs` — the Playwright walk (web audience) + the CLI parity bridge.
- `consent_walk.mjs` — the consent → approval → deletion → tutoring/voice success
  signals (t17), LOCAL authed flows + LIVE unauthenticated probes.
- `launch_bar.py` — the measurable launch-bar checks.
- `report.py` — reads the collected NDJSON results, renders the PASS/FAIL table.
- `BASELINE-2026-07-11.md` — the recorded pre-uplift LIVE baseline (h17).
- `package.json` — this package's own `playwright` devDependency (**not** added
  to `site-astro/package.json`).
- `.out/` — generated results (gitignored).

Each producer appends NDJSON lines (`{audience, check, status, detail}`) to
`$LAUNCH_GATE_RESULTS`; `report.py` folds them into one table and sets the exit
code (non-zero on any FAIL; SKIPs are surfaced but do not fail the gate).

## Live mode (post-deploy)

After the site is deployed, re-run the **signed-out** walk against the live
origin:

```bash
LIVE_ORIGIN=https://agentculture.org bash tools/launch-gate/run.sh
```

Both `walk.mjs` (the signed-out progress walk) and `consent_walk.mjs` (the
uplift LIVE probes) honor `LIVE_ORIGIN`. `walk.mjs` re-runs the signed-out walk
(cards, story body/glossary, `data-auth="out"`, the single-`/api/me` network
invariant); `consent_walk.mjs` probes the new routes (must 401, not 404) and
pages (must 200 with their markers). The signed-in walk and the authed
consent/approval/delete/voice flows need a real session, which the gate cannot
mint against production — the Worker's unit suite + `consent_walk.mjs` LOCAL
mode prove those; against prod, sign in through the deployed site and drive the
last mile by hand. The local-artifact checks (launch bar, `npm run check`, the
CLI/agent audiences, the boundary invariants) validate the very build deployed.

**The uplift ships behind a fully-green LIVE run.** Before deploy,
`BASELINE-2026-07-11.md` records the 9-of-10 `consent_walk.mjs` LIVE failures
that distinguish shipped-from-not (spec h17). After `wrangler deploy` (Worker) +
the Pages redeploy (site) — and `sam deploy` for the voice bridge — the same
command flips them to PASS:

```bash
RUN_LAUNCH_GATE=1 LIVE_ORIGIN=https://agentculture.org bash tools/launch-gate/run.sh
```

## What an operator must re-run against the LIVE site after deployment

- The signed-out live walk above (routing, the `agentculture.org/learn/*` zone
  mount, the static assets, and the single-`/api/me` invariant on real infra).
- The uplift LIVE probes (`consent_walk.mjs` via `run.sh` with `LIVE_ORIGIN`):
  every new route 401s unauthenticated, every new page is served with its
  markers, the subject page carries the tutor panel, the cloze story renders.
- A manual signed-in pass: sign in on the deployed site, accept the consent
  notice, record a result, confirm the learner panel + `GET
  /learn/api/progress/:subject` agree, then (as an admin-approved learner) run a
  Nova Pro-graded exercise and a Nova Sonic 2 voice exchange — the live-infra
  version of the tiers this gate proves locally.
