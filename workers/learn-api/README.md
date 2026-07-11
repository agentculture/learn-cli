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
batch (`src/db.js#deleteLearnerData`) and revokes the *current* session (KV
tombstone) at the route layer, the same mechanism `handleLogout` uses. h3 is
proven literally: after delete, a D1 query finds **no row in any of the
three tables** for that `github_user_id`, and the pre-delete session token is
rejected on the very next authed call. Unlike every other learner-scoped
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

`GET /api/admin/learners` (t8) is the one admin surface that exists today:
a full learner roster with a cheap per-subject record-count summary
(`db.js#listAllLearners`, three D1 reads total regardless of learner
count — a learners scan, one `GROUP BY` over `records`, and a full
`consents` scan — no N+1 as the roster grows). There is **no per-learner
detail route** — a deliberate lean-minimal scope decision; the list already
carries everything the admin surface needs (visibility, consent status/
version, per-subject counts), and a detail route can be added later if a
concrete need appears. The approval flag t9 adds (admin approve/revoke for
the Bedrock tutoring tier) reuses this same `ADMIN_GITHUB_IDS` allow-list
and `requireAdmin` helper — t9 does not reinvent role enforcement.

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
| POST | `/api/delete` | session or pending | Self-serve whole-learner erasure — consent withdrawal (t7). Requires `{ "confirm": "<your github_user_id>" }` in the body. Deletes the learners/records/consents rows, revokes the **current** session (KV tombstone), clears the cookie. Deliberately reachable from a stale-consent (and even pending-consent) session — see "Endpoint shapes" below for why. |
| POST | `/api/tutor` | consented | Broker: forward to `INFERENCE_URL` (a served inference endpoint). Pending OR stale-version session: `403 consent_required`, zero inference calls. |
| POST | `/api/me/visibility` | consented | Set the caller's OWN `visibility` (`private` \| `public`) in their `state` blob (t8). `400 invalid_visibility` for anything else. Pending OR stale-version session: `403 consent_required` — same gate as progress/record/export. |
| GET | `/api/admin/learners` | admin | List every learner + a per-subject record-count summary, admin-only (t8). Consented but non-allow-listed: `403 admin_required`. See "Roles + visibility" below. |

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

The go-live is staged. **Phase 1 (signed-out) is LIVE** at
<https://agentculture.org/learn/> (deployed 2026-07-11); **Phase 2 (signed-in)
is pending** two operator-held credentials.

| | Phase 1 — signed-out (LIVE) | Phase 2 — signed-in (pending) |
| --- | --- | --- |
| Config | [`wrangler.signedout.toml`](wrangler.signedout.toml) | [`wrangler.toml`](wrangler.toml) |
| Serves | Static `/learn/*` proxied to Pages; `/api/*` returns 401 | + sessions, ledger, tutoring |
| KV / D1 | none | KV `SESSIONS` + D1 `learn-ledger` |
| Secrets | none | `SESSION_SECRET`, `GITHUB_CLIENT_SECRET`, `INFERENCE_TOKEN` |
| Token perms | Cloudflare Pages: Edit **+** Workers Scripts: Edit | **+** Workers KV Storage: Edit **+** D1: Edit |
| Deploy | `wrangler deploy -c wrangler.signedout.toml` | `wrangler deploy` |

The signed-out tier touches no storage and spends no inference — `/api/me` and
`POST /api/tutor` return `401` *before* any KV/D1 access (proven live by the
launch gate's "signed-out fires ONLY GET /api/me" walk). That is why Phase 1
deploys with a Pages+Workers token and nothing else.

**Phase 1 was deployed with the repo's `.env` token, which carries Pages: Edit
and Workers Scripts: Edit but NOT KV/D1.** To do Phase 2 self-serve, that token
needs **Workers KV Storage: Edit** and **D1: Edit** added (or swap in a token
that has them).

## Provisioning Phase 2 (signed-in)

These steps are done once, by the operator, before the signed-in deploy.
Nothing here is committed.

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
wrangler secret put INFERENCE_TOKEN       # bearer for the served inference endpoint
```

Set the tutoring endpoint URL as a var (it is not secret) in `wrangler.toml`:

```toml
[vars]
INFERENCE_URL = "https://<cloudai-or-ec2bedrock-served-endpoint>/v1/messages"
PUBLIC_URL    = "https://agentculture.org"
APP_URL       = "https://agentculture.org/learn/"
CORS_ORIGIN   = "https://agentculture.org"
```

`INFERENCE_URL` must be a **served** endpoint from `cloudai-cli` or
`ec2bedrock-cli` (an OpenAI-shaped HTTP API). The broker only POSTs JSON to it —
there is no bespoke provider SDK anywhere in this Worker.

For local dev, mirror the secrets into a git-ignored `.dev.vars`:

```ini
SESSION_SECRET = "dev-only-secret"
GITHUB_CLIENT_SECRET = "..."
INFERENCE_TOKEN = "..."
```

### 4. Deploy

```bash
wrangler deploy   # uses wrangler.toml — full stack, same /learn/* route
```

The `agentculture.org/learn/*` zone route is already live (Phase 1) and is
declared in `wrangler.toml`, so this deploy upgrades the *same* worker in place
— the route does not move. Confirm the signed-in path end-to-end afterward
(`GET /learn/api/me` with a real session cookie should `200`), then merge org's
Learn-nav link to open public discovery.

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
       // + Set-Cookie clearing `session`; the token used to call this is
       //   immediately revoked (KV tombstone) — reuse it anywhere -> 401.
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

### For t9 (approval gate for tutoring)

Reuse, don't reinvent: t9's admin approve/revoke surface (an `approved` flag
on the learner row, gating `POST /api/tutor`) sits on top of the exact same
role machinery t8 just built —

- **`isAdmin(env, uid)` and `requireAdmin(request, env)` live in
  `src/admin.js`.** `requireAdmin` already stacks the allow-list check on
  top of `requireConsented`, so any new admin-only route (e.g.
  `POST /api/admin/learners/:id/approve`) should call it the same way
  `handleAdminLearners` does — `const session = await requireAdmin(request,
  env);` — rather than duplicating the allow-list check inline.
- **`ADMIN_GITHUB_IDS`** (`wrangler.toml` `[vars]`, mirrored as a placeholder
  in `wrangler.signedout.toml`) is the one config surface for admin-ness;
  t9 does not need a second var or a different allow-list.
- **The `approved` flag itself is new state t9 owns** — most naturally
  another key in `learners.state` next to `visibility` (same
  no-schema-change pattern db.js#setLearnerVisibility already established;
  a `setLearnerApproved`-shaped sibling function is the obvious next
  addition to `db.js`), gated in `handleTutor` (`src/index.js`) BEFORE the
  `INFERENCE_URL` check, mirroring how `requireConsented` already gates
  that same handler. `db.js#listAllLearners`'s per-learner shape is a
  natural place to surface `approved` too, so the admin list can show who's
  already approved without a second admin route.
- **The isolation-audit pattern in `test/visibility.test.js`** (seed two
  learners, assert neither route nor toggle ever leaks or mutates the
  other's row) is the template t9's own cross-learner tests should follow
  for the approve/revoke action.

## Testing

```bash
node --test
```

136 tests cover session sign/verify/expiry, `recorded` validation (including the
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
delete erases all three tables and revokes the session so the old token
403→401s on every subsequent call, a stale-consent session can still delete
without re-accepting, isolation — one learner's deletion never touches
another's rows or their ability to keep appending — and the full
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
and the visibility toggle (h4's second half). Tests invoke the Worker's
`fetch` handler directly with in-memory KV/D1 stubs (the D1 stub logs every
write statement, making "zero writes" literal); no network and no wrangler
are needed. A published-version bump is simulated with
`env.TERMS_VERSION_OVERRIDE` (see `src/consent.js#currentTermsVersion`) —
the real published version in `shared/terms-version.mjs` is never edited by
a test.
