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
