# Hosting and cost-when-busy note

This records the hosting choice for `agentculture.org/learn` and its
cost-when-busy profile, per the brief's honesty condition h8 (the hosting
choice must be recorded with a cost-when-busy note before build) and spec
decisions c21/c22.

## Shape of the deployment

Two surfaces, deliberately split by cost:

1. **Static shell + signed-out tour — Cloudflare Pages.** The subject catalog,
   module sub-pages, sample stories, and the whole visitor tour are pre-built
   static content (the `org` house style, Astro `output: 'static'`). Serving
   them is free and infinitely cacheable at the edge.
2. **Dynamic layer — the learn API Worker** (`workers/learn-api/`). Auth
   sessions, the learner ledger (KV + D1), and the tutoring broker. Only
   signed-in learners reach it.

The load-bearing invariant: **signed-out traffic is served entirely from the
static pages and can never reach the broker.** Sign-in is the resource gate
(spec c21). `POST /api/tutor` is the only route that spends model tokens, and it
sits behind auth middleware that runs before the route body — so a visitor who
never signs in costs nothing beyond static bandwidth (free) and cannot trigger a
model call. This is enforced in code and proven by test
(`workers/learn-api/test/worker.test.js`).

## How it deploys (CI pipeline)

Both surfaces deploy from CI on merge to `main` — **no local `wrangler`**. Two
sibling GitHub Actions workflows, each path-filtered so it only runs when its
surface changes:

| Workflow | Deploys | Triggers |
| --- | --- | --- |
| `.github/workflows/deploy-site.yml` | the static shell + tour (Cloudflare **Pages**, project `agentculture-learn`) | push to `main` on `site-astro/**`; PR = preview alias; `workflow_dispatch` |
| `.github/workflows/deploy-worker.yml` | the `learn-api` **Worker** + the **D1 schema** | push to `main` on `workers/learn-api/**`; `workflow_dispatch` = preview |

The Worker workflow has two paths (added in `learn-cli 0.7.0`, PR #14):

- **Merge to main → production.** Applies `schema.sql` to the `learn-ledger` D1
  `--remote` (idempotent — every statement is `CREATE … IF NOT EXISTS`, so
  re-applying is a no-op), syncs the Worker secrets, and runs `wrangler deploy`
  on the top-level `wrangler.toml` (the config with the `/learn/*` route).
  **Consequence: merging any PR that touches `workers/learn-api/**` performs a
  real production Worker deploy.**
- **Branch `workflow_dispatch` → preview.** Runs `wrangler versions upload
  --env preview` (uploads a non-promoted version with its own `*.workers.dev`
  URL) against a **separate preview D1** declared in the `[env.preview]` block
  (`learn-api-preview`, `learn-ledger-preview`, **no route**). Production —
  deployed version, route, and D1 — is never touched by a branch run. The
  dispatch button only appears once the workflow is on the default branch, so
  the branch-verify path is available **after** the first merge.

Load-bearing safety properties (guarded by
`tests/test_deploy_pipeline_invariants.py`):

- Every production / promote / prod-D1 step is gated to
  `github.ref == 'refs/heads/main'`; a branch run can never reach them.
- Secret sync pipes each value over **stdin** (never a CLI argument) and is
  **guarded by a non-empty check** — an unset GitHub Actions secret is *skipped*,
  leaving the deployed value unchanged, so a deploy never clobbers a live prod
  secret with `""` (and the intentionally-unset optional secrets
  `INFERENCE_TOKEN` / `VOICE_TOKEN_SECRET`, while tutoring/voice are off, don't
  wipe or fail).
- The workflows never touch `infra/` — the SAM voice bridge stays a separate
  manual `sam deploy`.

**Operator setup and the step-by-step runbook** (provisioning the preview D1,
the GitHub Actions secrets to create, the post-merge verify via the LIVE launch
gate, and the OAuth-callback caveat for preview) live in
[`workers/learn-api/README.md`](../workers/learn-api/README.md) — the single
source of truth. The design rationale (why a preview *environment* + separate
D1, why CI-synced secrets) is in the converged spec,
[`docs/specs/2026-07-11-learn-cli-ships-a-one-command-free-deployment-pipe.md`](specs/2026-07-11-learn-cli-ships-a-one-command-free-deployment-pipe.md).

## Cost-when-busy

Rough order-of-magnitude figures (Cloudflare pricing as of 2026; confirm
against the current plan before launch — these move):

| Component | When idle | When busy | Notes |
| --- | --- | --- | --- |
| Cloudflare Pages (static shell + tour) | free | free | Signed-out visitors, however many, cost ~0. Static assets cache at the edge. |
| Workers (the learn API) | ~$5/mo base (paid plan) | + per-request beyond the included allotment (~10M requests/mo included; ~$0.30 per additional million) | Only signed-in requests hit the Worker. CPU-time billing is negligible for this thin JSON layer. |
| KV (`SESSIONS`) | pennies | usage-priced reads/writes + storage | Only device-flow codes + revocation tombstones — tiny. |
| D1 (`learn-ledger`) | free tier covers early usage | usage-priced (rows read/written + storage) | Append-only ledger; one small row per recorded result. Reads on progress. |
| Inference (tutoring broker) | $0 | **per-use, and the dominant cost when busy** | Live tutoring tokens billed per-call through the served `cloudai-cli` / `ec2bedrock-cli` endpoint. Signed-in interactive lessons only. |

### The dominant term when busy is inference, and only signed-in learners incur it

Everything except inference is either free (static, Pages) or cheap and
usage-metered (Workers/KV/D1 for signed-in JSON traffic). The one materially
variable cost is **live model tokens**, and by construction it is gated behind
sign-in:

- A traffic spike of signed-out visitors (a launch, a link on the front page)
  scales on free static bandwidth — **zero marginal model cost**.
- Only a signed-in learner running an interactive lesson brokers a model call,
  and each such call is billed per-use by the served inference endpoint
  (`cloudai-cli` / `ec2bedrock-cli`), never a bespoke provider SDK.
- Pre-generated content (stories, starter lessons) is batch-produced, human
  reviewed, and committed to each subject repo (spec decision on model access),
  so serving it is static and free — live calls are reserved for genuinely
  interactive, personalized tutoring.

### Containing the busy-case bill

Levers available if signed-in inference volume grows:

- Rate-limit `POST /api/tutor` per learner (add a KV counter — the binding is
  already present).
- Point `INFERENCE_URL` at a cheaper served model or an autoscaled
  `ec2bedrock-cli` endpoint that scales to zero when idle.
- Cache/pre-generate more content so fewer interactions need a live call.
- Keep the token TTL short (already 1h) so abandoned sessions can't be replayed
  to spend tokens.

## Why this split

It honors the brief's cost discipline: the expensive resource (model tokens) is
spent only for signed-in, interactive learning; the free resource (static edge
content) carries every anonymous visitor. The dynamic layer stays thin and
Cloudflare-native (Worker + KV + D1) rather than a always-on server, so idle
cost is near the Workers base plan and busy cost tracks actual signed-in usage.
