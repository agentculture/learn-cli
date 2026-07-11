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

No third-party runtime deps: the Worker uses only Web-standard APIs (`fetch`,
`Request`/`Response`, `crypto.subtle`, `btoa`/`atob`), so the same code runs in
`wrangler dev`, in production, and under `node --test`.

## Routes

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| GET | `/api/health` | public | Liveness. |
| GET | `/api/auth/login` | public | Web OAuth: 302 to GitHub, sets a `oauth_state` cookie. |
| GET | `/api/auth/callback` | public | Web OAuth: exchange code, upsert learner, set `session` cookie, redirect to the site. |
| POST | `/api/auth/device` | public | Device flow `start` / `poll` for the CLI + MCP (wave-3 t12). |
| POST | `/api/auth/logout` | session | Revoke the current session (KV tombstone) and clear the cookie. |
| GET | `/api/me` | session | Identity + session expiry; auto-refreshes a near-stale session. |
| GET | `/api/progress/:subject` | session | Ledger-derived `progress.json`-shaped payload. |
| POST | `/api/record` | session | Validate the `recorded` shape and append it to the ledger. |
| POST | `/api/tutor` | session | Broker: forward to `INFERENCE_URL` (a served inference endpoint). |

Sessions are stateless HMAC-signed tokens (short TTL, ~1h) accepted either as an
`Authorization: Bearer <token>` header (CLI/MCP) or a `session` cookie (web).

## Storage

- **KV namespace `SESSIONS`** — device-flow bookkeeping and session-revocation
  tombstones only. Sessions themselves are stateless tokens; KV is not a
  session store.
- **D1 database `DB` (`learn-ledger`)** — see [`schema.sql`](schema.sql):
  - `learners (github_user_id, display_name, state, ...)` — the entire persisted
    identity is the GitHub id + display name; `state` is a small cross-subject
    profile blob. No password, no email, ever.
  - `records (...)` — append-only ledger. Every `POST /api/record` inserts one
    row; rows are never updated or deleted. Derived numbers
    (`score`/`grade`/`points`) are rejected before insert.

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

## Provisioning (operator steps still owed)

These steps are done once, by the operator, before the first deploy. Nothing
here is committed.

### 1. Create the GitHub OAuth app

Create an OAuth app at
`https://github.com/settings/developers` (or in the AgentCulture org):

- **Authorization callback URL:** `https://<worker-host>/api/auth/callback`
  (e.g. the route mounted under `agentculture.org/learn`).
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
placeholders for `id`, `preview_id`, and `database_id`), and set
`GITHUB_CLIENT_ID` there too (it is public).

### 3. Set secrets

```bash
wrangler secret put SESSION_SECRET        # random >= 32 bytes (e.g. openssl rand -base64 48)
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
wrangler deploy
```

Then mount the Worker under the `agentculture.org/learn` zone via the
operator-owned Cloudflare routing (coordinated with the `org` / cultureflare
path — the same route that fronts the Pages site).

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
```

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
  -> 200 { authenticated: true, learner: { github_user_id, display_name },
           session: { expires_at, refreshed } }
  -> 401 (not signed in) — render the signed-out state, make NO further calls
```

Sign-in button: link to `GET /api/auth/login`. Sign-out: `POST /api/auth/logout`.
Progress/record shapes are identical to the CLI's above.

## Testing

```bash
node --test
```

34 tests cover session sign/verify/expiry, `recorded` validation (including the
`score`/`grade`/`points` rejection), the full record round-trip, per-learner
ledger isolation, web + device OAuth flows, and — critically — that a signed-out
`/api/tutor` request returns `401` with **zero** inference calls. Tests invoke
the Worker's `fetch` handler directly with in-memory KV/D1 stubs; no network and
no wrangler are needed.
