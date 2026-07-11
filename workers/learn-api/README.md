# learn API (Cloudflare Worker)

The thin, Cloudflare-native dynamic layer behind
[agentculture.org/learn](https://agentculture.org/learn/) (spec decision c22).
It owns exactly three things: **GitHub OAuth sessions**, the **cross-subject
learner ledger**, and the **tutoring broker**. The static site and the
signed-out tour are served by Cloudflare Pages and never touch this Worker.

The load-bearing invariant (spec c21, "sign-in is the resource gate"):
**signed-out requests can never trigger a model call.** Auth runs before the
body of every learner-scoped route, and `POST /api/tutor` — the only route that
spends inference tokens — is unreachable without a valid session. This is
proven by `test/worker.test.js` ("signed-out `/api/tutor` never calls
inference"), not merely asserted.

The consent-gate invariant (spec c9/h1, decision c19) sits directly on top:
**neither sign-in path writes anything to D1 until the learner has accepted
the current Terms/Privacy version.** An unconsented sign-in (web callback or
device poll) mints a short-lived **pending-consent session** — a stateless
signed token marked `pending_consent: true`, TTL 10 minutes — whose only
capabilities are `GET /api/me`, the consent endpoints, and logout. Every other
authed route rejects it with a structured `403 consent_required` before
touching D1 or inference. Accept records the consent row **first**, then
creates the learner row (`consents` deliberately has no FK to `learners` so
that order is possible), and upgrades to a full session. Decline revokes the
pending session — nothing was ever written. Proven by `test/consent.test.js`,
which asserts **zero D1 write statements** on both paths via a write log in
the D1 stub.

The re-consent invariant (spec c10/h2, task t6) extends the SAME gate to a
**published version bump**: "consented" means `consent.terms_version` equals
the *currently* published `TERMS_VERSION` exactly
(`src/consent.js#consentSatisfiesCurrentTerms`), not merely "a consent row
exists." Bumping the published version therefore:

- routes a previously-consented learner's **next sign-in** (either path) back
  to a pending-consent session, with the same zero-new-D1-writes guarantee as
  a first-time sign-in;
- walls off an **existing, still-unexpired full-session token** at every
  `requireConsented`-gated route (`/api/progress/:subject`, `/api/record`,
  `/api/tutor`) with a structured `403 consent_required` — the token doesn't
  need to expire or be re-issued for the gate to take effect;
- leaves `POST /api/consent/accept` reachable throughout (it runs on
  `requireAuth`, not `requireConsented`), so re-accepting is always possible,
  and re-accepting records a **new** consent row for the new version
  (`consents` keeps one row per accepted version — see "Storage" below) and
  restores access immediately.

`GET /api/me` never 403s for a stale-consent full session — it *reports* the
requirement via an additive `reconsent_required` field (see "Endpoint shapes"
below) so a client can explain why other routes started rejecting, without
losing the ability to check who's signed in. Proven by `test/reconsent.test.js`
(the version-bump paths, the live-token wall, the accept-restores-access full
cycle, and the `/api/me` additive shape).

The erasure invariant (spec c11/h3, decision c18, task t7) is the exit door
on the other side of consent: **withdrawal of consent means deletion, and
whole-learner deletion is the only erasure path there is.** The `records`
ledger stays append-only for normal operation — there is no update-a-row or
delete-one-row API anywhere in this Worker — but `POST /api/delete` hard-
deletes every row a learner has (`learners`, `records`, `consents`) in one D1
batch (`src/db.js#deleteLearnerData`) and revokes **every session for that
uid, not only the one that called delete** (a Qodo review finding, fixed
alongside t7's original per-sid revoke): sessions are stateless signed
tokens and `/api/me`'s sliding refresh mints a fresh token without revoking
the old one, so a learner can hold several simultaneously valid sessions
(another browser tab, a CLI token, a second device). `handleDelete` writes
BOTH the per-sid `revoked:<sid>` tombstone `handleLogout` also uses AND a
per-uid `revoked_uid:<uid>` marker stamped with the delete's epoch second;
`src/auth.js#requireAuth` rejects any token for that uid whose `iat`
predates the marker (strict `<`, not `<=`, so a session minted in the same
epoch-second as the delete — e.g. an immediate resignup — is never
false-revoked; see that function's own comment). h3 is proven literally:
after delete, a D1 query finds **no row in any of the three tables** for
that `github_user_id`, and every pre-delete session token for that learner —
not just the one used to call delete — is rejected on the very next authed
call (`test/export-delete.test.js`, `test/auth.test.js`). Unlike every other
learner-scoped
route, `POST /api/delete` runs on `requireAuth`, not `requireConsented` — a
learner whose stored consent has gone stale (t6) must still be able to erase
their data *without* being forced to re-accept terms they no longer agree to
first; gating erasure behind fresh consent would be a contradiction. `GET
/api/export` (the data-portability counterpart) *does* run on
`requireConsented`, same as progress/record/tutor — export is a resource
read, not one of the narrow `requireAuth` escape-hatch routes. Proven by
`test/export-delete.test.js`, including the isolation case (another
learner's data and their ability to keep appending to the ledger are
unaffected by someone else's deletion) and the full cycle (delete, sign in
again, land pending-consent with zero consent rows surviving, re-consent,
start with an empty ledger).

The roles-and-visibility invariant (spec c12/h4, task t8) is the last piece
before the tutoring-tier approval gate (t9): **admin is a server-side
GitHub-id allow-list, and no authed route ever returns another learner's
data to a non-admin.** `ADMIN_GITHUB_IDS` (a comma-separated Worker var, see
wrangler.toml) is consulted fresh on every admin request by
`src/admin.js#isAdmin` — never from anything the client sends (a request
body flag, a header, a query param). `requireAdmin` (also `src/admin.js`)
stacks that check on top of `requireConsented`, so an admin is a learner
too and passes through the same consent gate first. h4 is proven literally
by `test/admin.test.js`, including a forged-claim test (a non-admin session
sends `?admin=true` plus `X-Admin`/`X-Is-Admin` headers and still gets
`403 admin_required`), and by `test/visibility.test.js`'s isolation suite
(every existing route re-checked for cross-learner leaks: `/api/me`,
`/api/progress/:subject`, `/api/export`, and the visibility toggle each
stay scoped to the caller's own `session.uid`, which is exactly what was
already true before t8 — this task adds the tests that prove it, not a
behavior change).

Visibility (spec c12, t8) is a single field, `visibility` (`"private"` |
`"public"`), inside `learners.state` — the same small JSON blob
`upsertLearner` already owns. **No schema change**: an absent key means
`"private"` for every existing and new learner, asserted directly in
`test/visibility.test.js`. A consented learner reads it via the additive
`learner.visibility` field on `GET /api/me` and sets it via
`POST /api/me/visibility`. Nothing public-facing consumes `"public"`
visibility yet — there is no leaderboard or shared-profile surface anywhere
in this repo — so the toggle is honestly forward-looking state today, not a
live feature; see `db.js#setLearnerVisibility`'s doc comment.

`GET /api/admin/learners` (t8) is the admin read surface: a full learner
roster with a cheap per-subject record-count summary
(`db.js#listAllLearners`, three D1 reads total regardless of learner
count — a learners scan, one `GROUP BY` over `records`, and a full
`consents` scan — no N+1 as the roster grows). There is **no per-learner
detail route** — a deliberate lean-minimal scope decision; the list already
carries everything the admin surface needs (visibility, tutoring-tier
`approved`, consent status/version, per-subject counts), and a detail route
can be added later if a concrete need appears.

The approval-gate invariant (spec c13/h5, decision c20, task t9) puts a
fourth level on top of the resource-gate ordering: **signed-out <
signed-in < consented < APPROVED — only an admin-approved learner can spend
inference.** The flag is `approved: true` in `learners.state` (the same
no-schema-change pattern as `visibility`; an absent key means *not*
approved for every existing and new learner, no migration), settable only
via `POST /api/admin/approve` / `POST /api/admin/revoke` behind t8's
`requireAdmin` — t9 reinvented no role enforcement. `handleTutor` reads the
flag **fresh from the learner row on every request** (one indexed
`getLearner` D1 read — negligible next to the inference call this route
exists to spend), so approve and revoke take effect immediately, with no
re-login and no token re-issue; a consented-but-unapproved learner gets a
structured `403 approval_required` **before** the `INFERENCE_URL` config
check, so they cannot even probe whether inference is wired up, and — h5
verbatim — the Worker makes **zero outbound inference requests** for them,
proven by extending the signed-out ordering test one level
(`test/approval.test.js`). Decision c20 is enforced in code: approve 409s
(`consent_stale`, `reason: "none" | "stale_version"`) unless the target's
recorded consent covers the **current** terms version — no learner joins
the Bedrock tier without having consented to the terms that disclose
Bedrock processing. The reverse direction is defense in depth: a terms bump
does **not** clear an existing approval (revocation is an admin act, not a
version-bump side effect), but tutoring still stops instantly because
`requireConsented` (t6) walls the route off independently — both gates hold
on their own, test-proven. And erasure composes (t7): `POST /api/delete`
removes the learner row, `approved` flag included, so a re-signup lands
consented-but-**unapproved** — approval never survives deletion.

No third-party runtime deps: the Worker uses only Web-standard APIs (`fetch`,
`Request`/`Response`, `crypto.subtle`, `btoa`/`atob`), so the same code runs in
`wrangler dev`, in production, and under `node --test`.

## Routes

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| GET | `/api/health` | public | Liveness. |
| GET | `/api/auth/login` | public | Web OAuth: 302 to GitHub, sets a `oauth_state` cookie. |
| GET | `/api/auth/callback` | public | Web OAuth: exchange code. Consented user: upsert learner, set full `session` cookie, redirect to the site. Unconsented: set a pending-consent cookie, redirect to `/learn/consent/`, **zero D1 writes**. |
| POST | `/api/auth/device` | public | Device flow `start` / `poll` for the CLI + MCP (wave-3 t12). Unconsented poll returns `status: "consent_required"` + a pending Bearer token, zero D1 writes. |
| GET | `/api/consent` | public | What consent is currently required: `terms_version`, `effective_date`, policy links. |
| POST | `/api/consent/accept` | session or pending | Record consent for the exact **currently published** `TERMS_VERSION` (t6: not necessarily the version last consented to), **then** upsert the learner, upgrade to a full session (cookie + body token). Reachable even from a stale-consent full session — this is the re-consent route. |
| POST | `/api/consent/decline` | pending only | Revoke the pending session, clear the cookie, nothing ever written. Full session gets `409 already_consented`. |
| POST | `/api/auth/logout` | session or pending | Revoke the current session (KV tombstone) and clear the cookie. |
| GET | `/api/me` | session or pending | Identity + session expiry; auto-refreshes a near-stale full session. Pending session: reports `pending_consent: true` + `consent_required`. Full session (t6): reports `reconsent_required` (+ `consent_required` when true) instead of 403ing. Never refreshes a pending session. |
| GET | `/api/progress/:subject` | consented | Ledger-derived `progress.json`-shaped payload. Pending OR stale-version session: `403 consent_required` (t6 adds `reason` + `consent_required` to the body — see "Endpoint shapes"). |
| POST | `/api/record` | consented | Validate the `recorded` shape and append it to the ledger. Pending OR stale-version session: `403 consent_required`. |
| GET | `/api/export` | consented | Self-serve data export: the learner's identity row, every recorded result across **every subject**, and their full consent history, as one JSON document (t7). Pending OR stale-version session: `403 consent_required` — same gate as progress/record/tutor. |
| POST | `/api/delete` | session or pending | Self-serve whole-learner erasure — consent withdrawal (t7). Requires `{ "confirm": "<your github_user_id>" }` in the body. Deletes the learners/records/consents rows, revokes **every session for that uid** (both the per-sid KV tombstone and a per-uid `revoked_uid:<uid>` marker — "delete logs you out everywhere," not just the current device), clears the cookie. Deliberately reachable from a stale-consent (and even pending-consent) session — see "Endpoint shapes" below for why. |
| POST | `/api/tutor` | approved | Broker: forward to `INFERENCE_URL` (Bedrock Converse in production — see "For t15"). Pending OR stale-version session: `403 consent_required`; consented but not admin-approved: `403 approval_required` (t9) — zero inference calls either way. |
| POST | `/api/voice/token` | approved | Mint a short-lived voice token for the serverless bridge (t16) — same learner-side gates as `/api/tutor`, in the same order, plus the per-learner monthly voice budget (`429 voice_budget_exhausted`). `503 not_configured` until `VOICE_BRIDGE_URL` + `VOICE_TOKEN_SECRET` are set. See "For t16" below. |
| POST | `/api/me/visibility` | consented | Set the caller's OWN `visibility` (`private` \| `public`) in their `state` blob (t8). `400 invalid_visibility` for anything else. Pending OR stale-version session: `403 consent_required` — same gate as progress/record/export. |
| GET | `/api/admin/learners` | admin | List every learner + a per-subject record-count summary and their tutoring-tier `approved` state, admin-only (t8, t9). Consented but non-allow-listed: `403 admin_required`. See "Roles + visibility" below. |
| POST | `/api/admin/approve` | admin | Grant a learner the tutoring tier (t9): set `state.approved`. Body `{ "github_user_id": "<id>" }`. `409 consent_stale` unless the target's consent covers the CURRENT terms version (decision c20); `404 learner_not_found` for an unknown id. |
| POST | `/api/admin/revoke` | admin | Withdraw the tutoring tier (t9): clear `state.approved`. Same body; idempotent. Effective on the learner's very next `/api/tutor` call — no re-login involved. |

Sessions are stateless HMAC-signed tokens (short TTL, ~1h; pending-consent
tokens 10 min) accepted either as an `Authorization: Bearer <token>` header
(CLI/MCP) or a `session` cookie (web). Pending-consent tokens carry
`pending_consent: true` in their signed payload — no server-side row backs
them, which is how sign-in stays write-free until consent.

## Storage

- **KV namespace `SESSIONS`** — device-flow bookkeeping and session-revocation
  tombstones only. Sessions themselves are stateless tokens; KV is not a
  session store.
- **D1 database `DB` (`learn-ledger`)** — see [`schema.sql`](schema.sql):
  - `learners (github_user_id, display_name, state, ...)` — the entire persisted
    identity is the GitHub id + display name; `state` is a small cross-subject
    profile blob. No password, no email, ever. `state.visibility` (t8) is the
    one field it carries today — `"private"` (the absent-key default) or
    `"public"` — see "Roles + visibility" above.
  - `records (...)` — append-only ledger. Every `POST /api/record` inserts one
    row; rows are never updated or deleted. Derived numbers
    (`score`/`grade`/`points`) are rejected before insert.
  - `consents (github_user_id, terms_version, granted_at)` — one row per
    accepted terms version. Deliberately **no FK to `learners`**: the consent
    row is recorded *before* the learner row exists (accept-order contract).
    For any learner, this is the first row that ever exists for them.

**Stale-consent detection cost (t6, spec c10/h2):** `requireConsented`
(`src/auth.js`) does one extra `getConsent` D1 read per request to
`/api/progress/:subject`, `/api/record`, and `/api/tutor`, to re-check the
learner's *stored* consent against the *currently published* `TERMS_VERSION`
on every call — not just at token-issue time. `GET /api/me` does the same for
a full session (on top of its existing `getLearner` read) so it can report
`reconsent_required`. This was chosen over a claims-based design (stamp the
accepted version into the session token's signed payload at issue time,
compare claim-to-current with **zero** D1 reads) for one reason: correctness
now, at the cost of one indexed `SELECT ... WHERE github_user_id = ?` read per
protected request. The claims alternative would need every session-issuing
call site (web callback, device poll, consent accept, **and** the
sliding-refresh re-issue inside `handleMe`) to correctly propagate the
version claim — a single missed call site would silently under- or
over-grant access, and that failure mode is worse than a few extra reads on
D1 (Cloudflare's globally-replicated SQLite, not a cross-region round trip).
Revisit only if this becomes a measured hot spot; a claims-based cache would
still need a D1 fallback path to catch tokens issued before the cache was
introduced.

## Local development

Requires Node >= 18 (the tests) and, for the running Worker, `wrangler`.

```bash
# Run the test suite — no wrangler, no network, no secrets needed.
node --test          # or: npm test

# Run the Worker locally against a local SQLite D1 + local KV.
npm install          # installs wrangler (devDependency)
wrangler d1 execute learn-ledger --local --file schema.sql
wrangler dev         # serves http://localhost:8787
```

For `wrangler dev`, put non-secret vars in `wrangler.toml` and provide dev
secrets in a git-ignored `.dev.vars` file (see below).

## Deploy status: two phases

The go-live was staged. **Phase 1 (signed-out) went LIVE** at
<https://agentculture.org/learn/> on 2026-07-11, and **Phase 2 (signed-in)** —
sessions, ledger, tutoring broker — was provisioned and deployed the same day
(see `CHANGELOG.md` 0.5.3). Both phases are live today; `wrangler.signedout.toml`
is kept only as a historical record of the Phase-1 config and is **never**
deployed by CI (`tests/test_deploy_pipeline_invariants.py` asserts this).

| | Phase 1 — signed-out (historical) | Phase 2 — signed-in (LIVE) |
| --- | --- | --- |
| Config | [`wrangler.signedout.toml`](wrangler.signedout.toml) | [`wrangler.toml`](wrangler.toml) |
| Serves | Static `/learn/*` proxied to Pages; `/api/*` returns 401 | + sessions, ledger, tutoring |
| KV / D1 | none | KV `SESSIONS` + D1 `learn-ledger` |
| Secrets | none | `SESSION_SECRET`, `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`, `INFERENCE_TOKEN`, `VOICE_TOKEN_SECRET` |
| Token perms | Cloudflare Pages: Edit **+** Workers Scripts: Edit | **+** Workers KV Storage: Edit **+** D1: Edit |
| Deploy | (superseded — see "CI deploy pipeline" below) | `.github/workflows/deploy-worker.yml`, merge to `main` |

The signed-out tier touched no storage and spent no inference — `/api/me` and
`POST /api/tutor` return `401` *before* any KV/D1 access (proven live by the
launch gate's "signed-out fires ONLY GET /api/me" walk); that invariant still
holds under the full Phase-2 config, just gated one level deeper (consent,
then approval — see the invariants documented above).

## CI deploy pipeline

`.github/workflows/deploy-worker.yml` is the routine way this Worker ships —
**merging to `main` is the deploy**; nobody runs `wrangler deploy` from a
laptop for the normal case anymore (a manual fallback still exists for when
CI itself is unavailable — see "Manual fallback / break-glass" below). One
workflow, two paths, gated purely by `github.ref`:

| | Push to `main` (production) | `workflow_dispatch` off any other branch (preview) |
| --- | --- | --- |
| D1 schema | `wrangler d1 execute learn-ledger --remote --file schema.sql` | `wrangler d1 execute learn-ledger-preview --remote --file schema.sql` |
| Secrets | synced to production | synced to the `preview` environment (`--env preview`) |
| Deploy step | `wrangler deploy` — promotes the top-level (production) `wrangler.toml` | `wrangler versions upload --env preview` — uploads a non-promoted preview version |
| Route touched | `/learn/*` (live) | none — `[env.preview]` declares no route |

`workflow_dispatch` deliberately ignores the `push` path filter
(`workers/learn-api/**`), so a preview run can always be forced regardless of
what changed. Every production/promote/prod-D1 step is guarded by
`github.ref == 'refs/heads/main'`; every preview step is guarded by the
complementary `github.ref != 'refs/heads/main'`, so the two paths can never
both fire in the same run. Every secret is piped over stdin
(`printf '%s' "$VALUE" | wrangler secret put NAME`), never a CLI argument, so
no value can appear in a process list or a CI log.

If `CLOUDFLARE_API_TOKEN` / `CLOUDFLARE_ACCOUNT_ID` are not both set on the
repo, the deploy/upload steps are skipped with a `::notice::` and a
job-summary note — the rest of the workflow still runs, which validates the
pipeline's shape even before Cloudflare credentials exist.

### One-time operator setup

Before the preview path (and, for the Cloudflare credentials, the production
path too) can go green, an operator does the following once:

1. **Provision the preview D1**: run `wrangler d1 create learn-ledger-preview`,
   then paste the printed `database_id` into the `[env.preview.d1_databases]`
   block in `wrangler.toml`, replacing the `PLACEHOLDER_PREVIEW_D1_ID`
   placeholder. Do the same for the preview KV namespace — run
   `wrangler kv namespace create SESSIONS_PREVIEW` and paste its id into
   `[env.preview.kv_namespaces]`, replacing `PLACEHOLDER_PREVIEW_KV_ID`.
2. **Create the GitHub Actions repository secrets** the pipeline reads:
   - `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` — the deploy
     credentials (Pages: Edit + Workers Scripts: Edit + Workers KV Storage:
     Edit + D1: Edit).
   - `SESSION_SECRET`, `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`,
     `INFERENCE_TOKEN`, `VOICE_TOKEN_SECRET` — the five Worker secrets, synced
     by CI to both the production and preview environments on every relevant
     run.

Until both steps are done, a branch `workflow_dispatch` run fails red (the
preview D1/KV ids are still placeholders) — expected, not a bug in the
workflow.

### Preview-env OAuth-callback caveat

The preview Worker (`learn-api-preview`) has no `routes` binding, so it is
only reachable at its own `*.workers.dev` origin — which is **not** the
registered GitHub OAuth app callback
(`https://agentculture.org/learn/api/auth/callback`, see step 1 below). A full
authed sign-in against preview will fail GitHub's `redirect_uri` check unless
a second, preview-scoped OAuth app is registered with a matching
`*.workers.dev` callback. Absent that, the preview target verifies
**unauthenticated** probes only — `/api/health`, the `401` shape of
session-gated routes, and so on — which is still enough to prove the pipeline
mechanics that matter: the build succeeds, the version uploads, the preview D1
schema applies cleanly, and the bindings resolve. The full
consented/approved/tutoring flows stay proven against the real topology by
`consent_walk.mjs`'s LOCAL mode and the Worker's own unit suite (see
"Testing" below), and against production by the post-merge verify next.

### Post-merge verify

After a push to `main` deploys, confirm the live surface actually flipped:

```bash
LIVE_ORIGIN=https://agentculture.org node tools/launch-gate/consent_walk.mjs
```

Compare the result to
[`tools/launch-gate/BASELINE-2026-07-11.md`](../../tools/launch-gate/BASELINE-2026-07-11.md):
every check recorded there as failing pre-uplift (`404` routes/pages) must now
read `PASS` (routes exist and reject unauth with `401`; pages serve `200`),
per that file's "Post-deploy: re-run to green" section.

**Idempotency (run-twice) check.** `schema.sql` is entirely
`CREATE ... IF NOT EXISTS` statements, so re-running the pipeline against
unchanged source must be a no-op: the schema-apply step changes nothing on
the second run, and `wrangler deploy` (which does not reset or delete
already-set Worker secrets) redeploys behavior-identically with secrets
intact. Verify by triggering the workflow twice in a row (a no-op commit, or
re-running the job) and confirming the second run's job summary reports the
same deploy, the `wrangler d1 execute` step exits clean, and a live
`GET /learn/api/me` with an existing session cookie still `200`s afterward
(secrets were not rotated out from under it).

### Manual fallback / break-glass

Local `wrangler deploy` is no longer the routine path, but it still works as
an escape hatch if CI itself is unavailable: authenticate with
`wrangler login` (or a Cloudflare API token with the same
Pages/Workers Scripts/KV/D1 Edit scopes CI uses), then from
`workers/learn-api/` run the same two commands the workflow runs —
`wrangler d1 execute learn-ledger --remote --file schema.sql` and
`wrangler deploy`. Prefer fixing the pipeline over reaching for this; a manual
deploy bypasses the CI audit trail the pipeline exists to provide.

## Initial provisioning reference (historical)

These steps were performed once, by the operator, to stand up the signed-in
tier originally (2026-07-11 — see `CHANGELOG.md` 0.5.3/0.5.4/0.7.0). They are
kept here as a disaster-recovery reference (e.g. re-provisioning production
KV/D1 from scratch) — **not** as the routine deploy path, which is now the CI
pipeline above. Nothing here is committed.

### 1. Create the GitHub OAuth app

Create an OAuth app at
`https://github.com/settings/developers` (or in the AgentCulture org):

- **Authorization callback URL:**
  `https://agentculture.org/learn/api/auth/callback` (the live zone route).
- **Enable Device Flow** — required for the CLI/MCP device sign-in (t12).
- Requested scope is `read:user` only. Do **not** request `user:email`; the API
  never reads or stores email.

Note the **Client ID** (public) and generate a **Client secret**.

### 2. Provision KV + D1

```bash
wrangler kv namespace create SESSIONS
wrangler kv namespace create SESSIONS --preview
wrangler d1 create learn-ledger
wrangler d1 execute learn-ledger --file schema.sql
```

Copy the returned ids into `wrangler.toml` (replace the `REPLACE_ME_*`
placeholders for `id`, `preview_id`, and `database_id`). The route +
`PUBLIC_URL` / `APP_URL` / `CORS_ORIGIN` / `PAGES_ORIGIN` vars are already
filled in `wrangler.toml` from the live Phase-1 deploy. `GITHUB_CLIENT_ID`
is NOT committed — it is set as a secret in step 3 (sourced from the
repo-root `.env` `GITHUB_APP_CLIENT_ID`).

Apply the schema to the **remote** D1 (the `--local` form only touches the
`wrangler dev` SQLite):

```bash
wrangler d1 execute learn-ledger --remote --file schema.sql
```

### 3. Set secrets

```bash
wrangler secret put SESSION_SECRET        # random >= 32 bytes (e.g. openssl rand -base64 48)
wrangler secret put GITHUB_CLIENT_ID      # GitHub-App client id (.env GITHUB_APP_CLIENT_ID; public but not committed)
wrangler secret put GITHUB_CLIENT_SECRET  # from the OAuth app
wrangler secret put INFERENCE_TOKEN       # Bedrock API key (.env AWS_BEDROCK_API_KEY_SECRET) — t15
```

Set the tutoring endpoint URL as a var (it is not secret) in `wrangler.toml` —
the exact production value ships there commented out (t15; uncomment to
enable, t17's launch gate drives the live flip):

```toml
[vars]
INFERENCE_URL = "https://bedrock-runtime.us-east-1.amazonaws.com/model/us.amazon.nova-pro-v1:0/converse"
PUBLIC_URL    = "https://agentculture.org"
APP_URL       = "https://agentculture.org/learn/"
CORS_ORIGIN   = "https://agentculture.org"
```

`INFERENCE_URL` is **Bedrock-direct** (spec decision: AWS Bedrock is the only
service that serves AWS Nova models) — the native Converse API, not an SDK
integration and not a sibling-hosted model server. The broker only POSTs JSON
to it — there is no bespoke provider SDK anywhere in this Worker. See "For
t15" below for the probe results behind the URL choice.

For local dev, mirror the secrets into a git-ignored `.dev.vars`:

```ini
SESSION_SECRET = "dev-only-secret"
GITHUB_CLIENT_SECRET = "..."
INFERENCE_TOKEN = "..."
```

### 4. Deploy (historical — now done by CI)

The original Phase-2 deploy ran `wrangler deploy` directly (recorded in
`CHANGELOG.md` 0.5.3) against the `agentculture.org/learn/*` zone route
already live from Phase 1. That command still works as the manual fallback
(see "Manual fallback / break-glass" above), but every deploy since has
gone through `.github/workflows/deploy-worker.yml` — see "CI deploy
pipeline" above for the routine path.

## Endpoint shapes for downstream waves

Consumers should treat these as the contract. All payloads carry
`schema_version: "1.0"` where they mirror a contract schema.

### For t12 (CLI / MCP device sign-in)

```text
POST /api/auth/device   { "action": "start" }
  -> 200 { device_code, user_code, verification_uri, expires_in, interval }

POST /api/auth/device   { "action": "poll", "device_code": "<dc>" }
  -> 200 { "status": "pending", "slow_down": false }
  -> 200 { "status": "complete", "token": "<jwt-lite>", "token_type": "Bearer",
           "expires_at": <unix>, "learner": { github_user_id, display_name } }
  -> 200 { "status": "consent_required", "token": "<pending jwt-lite>",
           "token_type": "Bearer", "expires_at": <unix>,
           "consent_required": { terms_version, effective_date,
                                 terms_url, privacy_url },
           "learner": { github_user_id, display_name } }
```

On `consent_required` (a first sign-in, or no consent recorded yet): nothing is
stored server-side; the CLI shows the notice (render `consent_required`, link
both policy URLs) and prompts. The returned `token` is a **pending-consent**
Bearer token (10 min TTL) valid only for `GET /api/me`, the consent endpoints,
and logout — use it to call:

```text
POST /api/consent/accept    Authorization: Bearer <pending token>
  -> 200 { ok: true, status: "consented",
           consent: { terms_version, granted_at },
           token: "<full jwt-lite>", token_type: "Bearer", expires_at: <unix>,
           learner: { github_user_id, display_name } }

POST /api/consent/decline   Authorization: Bearer <pending token>
  -> 200 { ok: true, status: "declined", stored: false }   // token revoked, zero rows written
  -> 409 { error: "already_consented", ... }               // on a full session
```

After accept, replace the stored token with the returned full `token` (the
pending one is revoked). Do **not** re-poll the device code — GitHub codes are
one-shot; the pending token is the continuation.

The CLI stores `token` and sends it as `Authorization: Bearer <token>` on every
subsequent call. Poll at `interval` seconds; back off on `slow_down`. Refresh by
calling `GET /api/me` (which re-issues when near expiry) or re-running the device
flow.

Record + read progress from the CLI:

```text
POST /api/record   { "subject": "french", "recorded": { ...record.json recorded... },
                     "mastery": { "item_id": "...", "level": "mastered" }  // optional
                   }
  -> 201 { schema_version, kind: "record_ack", subject, learner, recorded,
           mastery: { item_id, level }, next, ledger_id }

GET  /api/progress/:subject
  -> 200 { schema_version, kind: "progress", subject, learner,
           items_total, items_touched, items_mastered, completed, mastery, weak, next }
```

`recorded` is validated exactly like `record.json`: `score`/`grade`/`points`
are rejected with `400`. `items_total` here is **ledger coverage** (items the
learner has touched); the authoritative subject total comes from the subject
CLI's own `progress`.

### For t14 (web site hydration)

Signed-in panels hydrate client-side by calling this API with credentials
(cookies). Set `CORS_ORIGIN` to the site origin so `fetch(..., {credentials:
"include"})` works. Session bootstrap:

```text
GET /api/me
  -> 200 { authenticated: true, pending_consent: false, reconsent_required: false,
           learner: { github_user_id, display_name },
           session: { expires_at, refreshed } }
  -> 200 { authenticated: true, pending_consent: false, reconsent_required: true,
           consent_required: { terms_version, effective_date,
                               terms_url, privacy_url },
           learner: { github_user_id, display_name },
           session: { expires_at, refreshed } }
  -> 200 { authenticated: true, pending_consent: true,
           consent_required: { terms_version, effective_date,
                               terms_url, privacy_url },
           learner: { github_user_id, display_name },
           session: { expires_at, refreshed: false } }
  -> 401 (not signed in) — render the signed-out state, make NO further calls
```

`reconsent_required` (t6, spec c10/h2) is **additive**: it is always present
on a full session (`pending_consent: false`), defaulting to `false`; the
sibling `consent_required` field appears **only** when it's `true` — same
shape as the pending-session `consent_required`, so one notice component
renders both "first consent" and "re-consent" cases. Unlike the
`requireConsented`-gated routes below, `/api/me` never 403s for stale
consent — it keeps reporting identity/session so the client can explain
*why* everything else just started rejecting.

Sign-in button: link to `GET /api/auth/login`. Sign-out: `POST /api/auth/logout`.
Progress/record shapes are identical to the CLI's above.

### For t6 (re-consent on a published version bump)

`GET /api/progress/:subject`, `POST /api/record`, and `POST /api/tutor` all
go through `requireConsented`, which now rejects TWO distinct situations with
the same `403 consent_required` status but a distinguishing `reason`:

```text
403 { error: "consent_required", message, hint,
      reason: "pending",                 // never consented (or declined) yet
      consent_required: { terms_version, effective_date, terms_url, privacy_url } }

403 { error: "consent_required", message, hint,
      reason: "stale_version",           // consented, but to a superseded version
      consent_required: { terms_version, effective_date, terms_url, privacy_url } }
```

Either way, the client's recovery is identical: send the learner through the
consent notice (or straight to `POST /api/consent/accept` if it already has
their acknowledgement) — `consent_required.terms_version` is always the
version to accept. `POST /api/consent/accept` itself never 403s this way: it
runs on `requireAuth` (any valid, unexpired session, pending or full), so it
stays reachable specifically to recover from `reason: "stale_version"`.

### For t7 (self-serve export + delete)

**Route naming.** `GET /api/export` and `POST /api/delete` (not `DELETE
/api/me`) — chosen to match this Worker's existing convention: every
mutation here is a `POST` to a verb-named path (`/api/consent/accept`,
`/api/consent/decline`, `/api/auth/logout`), never the HTTP `DELETE` method,
so `Access-Control-Allow-Methods` (see `withCors`) doesn't need a new entry
and no route needs to special-case its own verb. `/api/export`/`/api/delete`
sit at the same level as `/api/record`/`/api/progress/:subject` — they act
on the same "your data" resource, just export it wholesale or erase it
wholesale instead of appending to it.

```text
GET /api/export                       (requireConsented — same gate as progress/record/tutor)
  -> 200 {
       schema_version: "1.0",
       kind: "export",
       exported_at: "<ISO-8601, now>",
       schema_note: "<prose: what each top-level field means>",
       learner: { github_user_id, display_name, state },
       records: [
         { subject, item_id, activity, result, at, mastery_level,
           recorded: { ...the exact object your subject CLI/the web reader submitted... } },
         ...   // every row, every subject, oldest first
       ],
       consents: [
         { terms_version, granted_at },
         ...   // every version you have ever accepted, oldest first
       ],
     }
  -> 403 { error: "consent_required", reason: "pending" | "stale_version", ... }  // nothing to export
  -> 401                                                                          // signed out
```

`exported_at` + `schema_note` make the payload self-describing (a learner
opening the downloaded JSON months later doesn't need this README to
understand what they're looking at). `records[].recorded` is the **parsed**
object, not the JSON-TEXT-column string `records.sql` stores it as — see
`parseRecorded()` in `src/index.js`.

```text
POST /api/delete                      (requireAuth — pending, stale, OR current session)
  Body: { "confirm": "<your github_user_id>" }
  -> 200 { ok: true, status: "deleted",
           deleted: { records: <n>, consents: <n>, learners: <n> } }
       // + Set-Cookie clearing `session`; EVERY session for this uid is
       //   immediately revoked — the token used to call this (KV
       //   `revoked:<sid>` tombstone) AND every other still-live session
       //   for the same learner (KV `revoked_uid:<uid>` marker, checked in
       //   auth.js#requireAuth) — reuse ANY of them anywhere -> 401.
  -> 400 { error: "confirmation_required", ... }   // confirm missing/wrong/absent body
  -> 401                                            // signed out
```

**Why a `confirm` field instead of a bare `POST`:** the one-extra-step guard
is deliberately cheap (no CAPTCHA, no second request) but not "one click" —
a stray retry, a misclicked button, or a naive `fetch(..., {method:
"POST"})` with no body cannot trigger deletion; the caller must already know
its own `github_user_id` (trivially available from `GET /api/me`, which any
UI wiring this up will have already called). This mirrors GitHub's own
"type the repo name to confirm" pattern at API scale rather than UI scale.

**Why `POST /api/delete` uses `requireAuth`, not `requireConsented`, while
`GET /api/export` uses `requireConsented`:** export is a resource *read* —
gated exactly like progress/record/tutor, and a pending or stale-consent
session has either nothing to export (h1) or can trivially re-consent first.
Delete is the *escape hatch itself* — the same class of route as `POST
/api/consent/accept`/`decline` and `GET /api/me`, which all run on
`requireAuth` specifically so they stay reachable from a non-current-consent
session. Gating erasure behind a **fresh** consent would force a learner who
no longer agrees with the current terms to accept them anyway just to leave
— exactly backwards. A pending-consent session may also call `/api/delete`;
since sign-in never wrote anything for it (h1), `deleteLearnerData` is a
documented no-op (see `test/db.test.js`) and the route still revokes the
pending token, same effect as `POST /api/consent/decline`.

**Site-side affordance (t7 scope decision, delivered by t8):** no
`site-astro` change shipped with t7 itself — the only existing signed-in
surface site-wide at the time was `Header.astro`'s auth slot (display name
plus "Sign out"), with no account/settings page to extend, and the consent
notice's own copy ("decline below, or delete your account later") was
static prose with nothing to hang a live control on yet. That gap is now
closed: t8's account panel (`src/components/LearnerPanelOverview.astro`'s
`data-account-panel` block, wired by `hydrateAccountPanel()` in
`src/scripts/learner.js`) adds "Export my data" (downloads the `GET
/api/export` response as a file) and "Delete my data" (a type-your-
github-id confirm flow before `POST /api/delete` — the same one-extra-step
guard the API itself enforces, just mirrored client-side) alongside the
visibility toggle. Both routes were already fully CLI/agent-ready
(`curl`/`learn`/MCP could call them from t7 on); this is their first web
affordance.

### For t10 (the consent page, `/learn/consent/`)

An unconsented web sign-in 302s from the OAuth callback to `/learn/consent/`
carrying a pending-consent `session` cookie (10 min TTL). The page:

1. Calls `GET /api/me` with credentials. `pending_consent: true` → render the
   notice from `consent_required` (version, effective date, `terms_url`,
   `privacy_url`). A `401` here means the pending session expired — offer the
   sign-in link again. (`GET /api/consent` serves the same requirement shape
   without a session, e.g. for pre-rendering.)
2. **Accept** → `POST /api/consent/accept` with credentials. The response sets
   the upgraded full-session cookie itself (the body token can be ignored on
   the web) — then navigate into `/learn/` signed in.
3. **Decline** → `POST /api/consent/decline` with credentials. The cookie is
   cleared and the session revoked; confirm to the user that nothing was
   stored (`stored: false` in the response is that guarantee, test-proven).

### For t9 (approval gate for tutoring) — SHIPPED

The approve/revoke surface, exactly as t8 laid it out — same
`ADMIN_GITHUB_IDS` allow-list, same `requireAdmin`, `approved` as a
`learners.state` key next to `visibility` (no schema change),
`db.js#setLearnerApproved` as `setLearnerVisibility`'s sibling. Two flat
verb-named POST routes (matching this Worker's every-mutation-is-a-POST-to-
a-verb-path convention — see t7's route-naming note above — and keeping the
site's fetch whitelist exactly enumerable):

```text
POST /api/admin/approve               (requireAdmin)
  Body: { "github_user_id": "<id>" }
  -> 200 { ok: true, github_user_id, approved: true }
  -> 409 { error: "consent_stale", reason: "none" | "stale_version",
           terms_version: "<current>" }   // decision c20: consent not current
  -> 404 { error: "learner_not_found", ... }
  -> 400 { error: "missing_github_user_id", ... }

POST /api/admin/revoke                (requireAdmin)
  Body: { "github_user_id": "<id>" }
  -> 200 { ok: true, github_user_id, approved: false }   // idempotent
  -> 404 / 400 as above
```

`GET /api/me` (full session) gains an additive `learner.approved` boolean;
`GET /api/admin/learners` gains an additive per-learner `approved`. The
tutor gate itself lives in `handleTutor` and 403s `approval_required`
before the `INFERENCE_URL` check — see "The approval-gate invariant" above.

### For t15 (Nova Pro wiring) — SHIPPED, config only

**h11 holds literally: the Worker diff for t15 is zero lines of code.** The
four-level gate (auth → consent → approval → `INFERENCE_URL` presence) and
the forward-verbatim broker are entirely inside `handleTutor` (`src/index.js`),
unchanged since t9 — t15 ships as a `wrangler.toml` comment block (the exact
URL, ready to uncomment), an `INFERENCE_TOKEN` secret recipe, and the client
surface in `site-astro/` (below). `test/tutor-converse.test.js` (additive)
proves the unchanged broker carries a native Converse payload verbatim and
relays the Converse response and error statuses untranslated.

**Probe results (live, 2026-07-11) — how the URL was chosen:**

- **OpenAI-compat NO-GO.** Bedrock's OpenAI-compatible chat-completions
  surface (`bedrock-runtime.<region>.amazonaws.com/openai/v1/...`) does
  **not** serve Nova Pro: `model_not_found` in every probed region
  (us-east-1, us-west-2, eu-west-1, eu-central-1), and `/openai/v1/models`
  is not even an operation. This supersedes the spec's and this README's
  earlier "OpenAI-compatible endpoint" wording.
- **Converse GO.** The native Converse API returns real Nova Pro
  completions with a plain Bedrock API key as the Bearer token:

  ```text
  POST https://bedrock-runtime.us-east-1.amazonaws.com/model/us.amazon.nova-pro-v1:0/converse
  Authorization: Bearer <Bedrock API key>     (.env AWS_BEDROCK_API_KEY_SECRET)
  ```

  Re-verified from this task (2026-07-11, sanitized): `HTTP 200 in 0.95s`,
  body `{"metrics":{"latencyMs":491},"output":{"message":{"content":
  [{"text":"OK"}],"role":"assistant"}},"stopReason":"end_turn","usage":
  {"inputTokens":11,"outputTokens":2,...}}`.

- **The learner stamp needs no change.** Converse tolerates the broker's
  `learner` field both as an extra top-level field and under
  `requestMetadata` (live-verified) — `handleTutor`'s existing
  spread-then-stamp forward works as-is.

**Wiring facts** (also recorded next to the commented-out var in
`wrangler.toml`): model `us.amazon.nova-pro-v1:0`, region `us-east-1`,
`INFERENCE_TOKEN` = a Bedrock API key set via
`wrangler secret put INFERENCE_TOKEN` (sourced from the repo-root `.env`
`AWS_BEDROCK_API_KEY_SECRET`). **Cost-when-busy: per-token Nova Pro spend
only — no model host, no provisioned throughput, zero idle cost.**

**Request/response shapes** the client builds and parses (Converse, not
chat-completions — `site-astro/src/scripts/tutor-core.js` is the one
builder/parser, unit-tested by `site-astro/scripts/check-tutor-logic.mjs`):

```text
request:  { system: [{text}], messages: [{role, content: [{text}]}],
            inferenceConfig: {maxTokens, temperature} }
response: { output: {message: {content: [{text}]}}, stopReason, usage }
```

**The tutor surface** (site-astro, approved learners only — the gate note
renders for everyone else): `TutorPanel.astro` + `src/scripts/tutor.js`
drive three flows through this broker — exercise **grading**
(pass/partial/fail + explanation, rubric pinned in the system prompt),
adaptive **next-step** (from `GET /api/progress/:subject`, targeting the
weakest items), and personalized **cloze-story generation**
(contract-§3.6.1-validated client-side, `item_id` reused verbatim from a
weak item as the stable join key; the played result records through the
existing `POST /api/record` with `correct`/`total` tallies — no new record
fields, no new routes).

### For t16 (voice sessions) — SHIPPED (live bridge deploy deferred)

The Worker half of the voice approval gate (spec c15/h7). The serverless
bridge (`infra/` — SAM: API GW WebSocket + arm64 Lambda + Nova Sonic 2, see
`infra/SPIKE.md` for the live-proven GO) only upgrades a WebSocket at
`$connect` for a token minted here with the shared secret; this route only
mints for a learner who passes the same gates as `/api/tutor`, so **no audio
byte can reach Bedrock for anyone below signed-in + consented + approved** —
enforced independently at both ends, test-proven at both ends
(`test/voice.test.js` here, `tests/test_voice_bridge_handler.py` at the
bridge).

```text
POST /api/voice/token                 (requireConsented + the approvedOf check)
  -> 200 { token,                       // base64url(payload).base64url(HMAC-SHA256)
           wss_url,                     // VOICE_BRIDGE_URL + "?token=" + token
           expires_at,                  // unix seconds; TTL 120s (mint->connect window)
           limits: { max_session_seconds,          // the bridge's per-session cap
                     monthly_seconds_cap,          // per-learner budget (below)
                     monthly_seconds_used,         // incl. this mint's booking
                     monthly_seconds_remaining } }
  -> 401                                            // signed out — no token, ever
  -> 403 { error: "consent_required", ... }         // pending OR stale consent
  -> 403 { error: "approval_required", ... }        // consented, not admin-approved
  -> 503 { error: "not_configured", ... }           // VOICE_BRIDGE_URL/VOICE_TOKEN_SECRET unset
  -> 429 { error: "voice_budget_exhausted",
           month, monthly_seconds_cap, monthly_seconds_used }
```

Gate order matters and mirrors `handleTutor`: the approval 403 fires
**before** the config 503, so an unapproved learner cannot even probe
whether the bridge is wired up. The token's claim set
(`{v, scope: "voice", uid, approved: true, iat, exp, sid}`) is pinned
byte-for-byte against the bridge's verifier: the committed fixture
`tests/fixtures/voice_token_cross_language.json` (repo root) was minted by
`src/voice.js` and is asserted reproducible by `test/voice.test.js` AND
verifiable by `infra/voice_bridge/tokens.py` in
`tests/test_voice_token_cross_language.py` — neither side can drift alone.
A learn-api *session* token can never open the bridge (wrong `scope`), and a
voice token can never call this API (it is not a session token).

**The per-learner monthly voice budget — honest scope.** Each mint books the
full bridge session cap (`VOICE_MAX_SESSION_SECONDS`, default 300 — keep it
equal to the SAM stack's `MaxSessionSeconds`) against
`learners.state.voice_usage = { month: "YYYY-MM", seconds_minted: n }`, and
the mint that would push the month past `VOICE_MONTHLY_SECONDS_CAP`
(default 1800 s = 30 min = 6 max-length sessions) is refused with `429` and
books nothing. **The check-then-book is atomic** (a Qodo review finding,
fixed): `src/db.js#setLearnerVoiceUsage` is a compare-and-swap on the
learner row's `updated_at`, not a plain read-then-write, so two concurrent
mints can never both read the same `used`, both pass the cap check, and
both write — `src/index.js#bookVoiceUsage` retries (bounded, 3 attempts)
against a fresh read on a lost CAS and refuses the mint rather than risk an
unmetered token if it still can't secure a booking. Proven by
`test/db.test.js`'s direct CAS tests and `test/voice.test.js`'s real
concurrent-request test. Month rollover is free: a stale stored month reads
as zero (no cron, no migration). **This caps MINTED session-seconds — intent, the
worst case that every minted token is fully used — not actual streamed
seconds.** A learner who hangs up after 10 s still spent a 300 s booking.
Actual per-session length and global concurrency are enforced by the bridge
itself (`MaxSessionSeconds` + `MaxConcurrentVoiceSessions`, the real cost
backstops along with the stack's AWS Budgets alarm); tightening this meter
to actual usage needs bridge→worker usage reporting — a follow-up, not
claimed here. Sizing rationale against the $20/month Budgets ceiling lives
as a comment in `src/voice.js` (spike-measured ~$0.01–0.02 per
conversation-minute → one exhausted cap ≈ $0.30–0.60 of speech tokens).

**The site face** is `site-astro/src/pages/voice/` +
`site-astro/src/scripts/voice.js` (its own page + script, loaded only
there): gate states for signed-out / consent-needed / not-approved /
approved, then mic → 16 kHz/16-bit/mono LPCM upstream as
`{"seq": n, "audio": "<b64>"}` frames and 24 kHz LPCM downstream via
WebAudio — t4's spike-proven client contract (`infra/voice_bridge/relay.py`
pins the same shapes). The client opens its one WebSocket only after this
route returned a grant — `site-astro/scripts/check-static-auth.mjs` and
`tests/test_voice_page.py` both assert that structurally.

**What is deferred to the launch-gate phase (t17): the live Nova Sonic
exchange.** Everything above is code-complete and tested without AWS — token
mint/verify in both directions, gate ordering, budget arithmetic incl.
rollover, page states — but no bridge is deployed yet, so "an approved
learner completes a live voice exchange from /learn" cannot be verified
until the supervised deploy. Operator runbook for that step:

1. `cd infra && sam build && sam deploy` — supply parameters
   `VoiceTokenSecretValue=<secret>` (random ≥32 bytes; **the SAME value** as
   the Worker's `VOICE_TOKEN_SECRET` below) and `BudgetAlertEmail=<inbox>`;
   note the stack's WebSocket URL output
   (`wss://<api-id>.execute-api.us-east-1.amazonaws.com/prod`).
2. `wrangler secret put VOICE_TOKEN_SECRET` — paste the same secret.
3. Set `VOICE_BRIDGE_URL = "<the wss URL>"` under `[vars]` in
   `wrangler.toml` (and `VOICE_MAX_SESSION_SECONDS` if the stack's
   `MaxSessionSeconds` was overridden), then `wrangler deploy`.
4. Verify: as an approved learner, `/learn/voice/` → Start → speak → hear
   the answer; a second concurrent session beyond the cap must be refused,
   and rotating `VoiceTokenSecretValue` is the instant kill switch.

## Testing

```bash
node --test
```

183 tests cover session sign/verify/expiry, `recorded` validation (including the
`score`/`grade`/`points` rejection), the full record round-trip, per-learner
ledger isolation, web + device OAuth flows, the consent gate (zero D1 writes on
both unconsented sign-in paths, the pending-session 403 wall, accept ordering —
consent row before learner row — and write-free decline), the re-consent gate
(`test/reconsent.test.js`: a simulated `TERMS_VERSION` bump re-routes a
previously-consented learner's next sign-in to pending-consent with zero new
writes, walls off a live full-session token at every `requireConsented`
route with `reason: "stale_version"`, the full consent-v1 → bump → 403 →
re-accept → 200 cycle, and `/api/me`'s additive `reconsent_required`
reporting), the export + delete gate (`test/export-delete.test.js`: a
consented session's export spans every subject and its full consent
history, a pending session gets `403` with literally nothing to export,
delete erases all three tables and revokes **every** session for that uid
(not just the one that called delete — a Qodo review finding; `test/auth.test.js`
pins the underlying `requireAuth` boundary deterministically, including the
same-epoch-second edge case a delete-then-immediate-resignup can hit) so
every old token for that learner 403→401s on every subsequent call, a
stale-consent session can still delete without re-accepting, isolation — one
learner's deletion never touches another's rows, sessions, or their ability
to keep appending — and the full
delete→sign-in-again→pending→re-accept→empty-ledger cycle), and —
critically — that a signed-out `/api/tutor` request returns `401` with
**zero** inference calls. The roles + visibility gate (`test/admin.test.js`,
`test/visibility.test.js`) adds: `isAdmin`'s allow-list parsing, the
allow-list enforced against `GET /api/admin/learners` with a forged
client-side admin claim (query string + headers) proven ignored (h4), the
admin payload's per-subject aggregate shape (`test/db.test.js` also proves
`listAllLearners` issues exactly three D1 reads regardless of learner
count), default-private visibility with no migration, the
`POST /api/me/visibility` round-trip, and an explicit cross-learner
isolation audit across `/api/me`, `/api/progress/:subject`, `/api/export`,
and the visibility toggle (h4's second half). The approval gate
(`test/approval.test.js`, t9) extends the ordering proof one final level:
a consented-but-unapproved learner's `/api/tutor` call 403s
`approval_required` with **zero** outbound inference (h5) and without even
reaching the `INFERENCE_URL` config check; approve/revoke flip tutoring on
a live token with no re-login; approve 409s `consent_stale` unless the
target's consent is current (c20); a terms bump blocks tutoring even for an
approved learner (both gates independent); approving one learner never
touches another's row; and deletion erases the flag so a re-signup is not
approved. The voice-token mint (`test/voice.test.js`, t16) extends the same
ordering proof to the voice transport: signed-out/pending/stale/unapproved
callers get 401/403/403/403 with **no token in any body**, the approval 403
fires before the config 503, the happy-path token's claim set and signature
are pinned to `infra/voice_bridge/tokens.py`'s contract (including the
committed cross-language fixture, byte-for-byte), and the monthly budget
books per mint, refuses without overshoot, rolls over by month, merges into
`learners.state` without clobbering other keys, and — a Qodo review finding,
fixed — cannot be double-booked by two real concurrent mint requests racing
past the same pre-state (`test/db.test.js` pins the underlying
compare-and-swap primitive in `setLearnerVoiceUsage` deterministically;
`test/voice.test.js` proves the route wires it up correctly under actual
`Promise.all` contention). The Converse
pass-through (`test/tutor-converse.test.js`, t15, additive) proves the
unchanged broker carries a native Bedrock Converse payload verbatim — plus
exactly the `learner` stamp — and relays the Converse response shape and
upstream error statuses untranslated. Tests invoke the Worker's
`fetch` handler directly with in-memory KV/D1 stubs (the D1 stub logs every
write statement, making "zero writes" literal); no network and no wrangler
are needed. A published-version bump is simulated with
`env.TERMS_VERSION_OVERRIDE` (see `src/consent.js#currentTermsVersion`) —
the real published version in `shared/terms-version.mjs` is never edited by
a test.
