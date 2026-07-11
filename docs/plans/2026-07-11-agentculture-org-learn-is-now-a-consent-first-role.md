# Build Plan — agentculture.org/learn is now a consent-first, role-aware tutoring service: sign-in asks explicit consent against versioned Terms + Privacy before anything is saved (with self-serve export and delete), an admin approves which learners get the Bedrock tutoring tier — Nova Sonic 2 voice sessions and a Nova Pro teacher with personalized cloze stories — and the curriculum ships a level deeper across french, spanish, and culture-guide with a new cloze exercise type

slug: `agentculture-org-learn-is-now-a-consent-first-role` · status: `exported` · from frame: `agentculture-org-learn-is-now-a-consent-first-role`

> agentculture.org/learn is now a consent-first, role-aware tutoring service: sign-in asks explicit consent against versioned Terms + Privacy before anything is saved (with self-serve export and delete), an admin approves which learners get the Bedrock tutoring tier — Nova Sonic 2 voice sessions and a Nova Pro teacher with personalized cloze stories — and the curriculum ships a level deeper across french, spanish, and culture-guide with a new cloze exercise type

## Tasks

### t1 — Author Terms of Use + Privacy Policy as versioned /learn-local pages (site-astro) with a single TERMS_VERSION source of truth shared with the worker

- covers: c17, h9
- acceptance:
  - Pages render at /learn/terms/ and /learn/privacy/ with a visible version + date, linked from the /learn footer
  - Privacy Policy names GitHub (OAuth), Cloudflare (Workers/KV/D1/Pages), and AWS Bedrock (Nova Sonic 2 / Nova Pro, approved tier only — learner speech/text leaves to the model provider), states retention + the delete/export path
  - A test cross-checks the policy's data claims against schema.sql (no email/password column) and TERMS_VERSION is importable by both site and worker from one place

### t2 — D1 consent schema + db helpers: consents table migration plus getConsent/recordConsent/deleteLearner data-layer functions

- acceptance:
  - schema.sql migration applies cleanly to fresh AND existing remote DB (idempotent CREATE IF NOT EXISTS), consents keyed (github_user_id, terms_version, granted_at)
  - db.js gains getConsent/recordConsent/deleteLearnerData (learners+records+consents in one transaction) with unit tests; no route wiring yet (file-disjoint from index.js)

### t3 — Cloze exercise kind in the subject-plugin contract (learn-cli side): schema, validation, subject doctor check, export rendering

- acceptance:
  - Contract documents the cloze (pick-the-right-word) exercise shape; validate.py/worker validate.js accept it as a contract-valid recorded activity
  - learn subject doctor verifies cloze items when a subject declares them; site export renders a cloze exercise interactively; item_id join-key rules unchanged

### t4 — Voice-bridge serverless spike + SAM template copying league-of-agents-platform infra pattern: API GW WebSocket + arm64 Lambda relaying to Bedrock Nova Sonic 2 bidirectional stream, Budgets alarm with hard monthly ceiling

- acceptance:
  - A spike proves Lambda can hold Bedrock's InvokeModelWithBidirectionalStream (Nova Sonic 2) and relay audio both ways through an API GW WebSocket connection — go/no-go recorded before any UI work
  - infra template mirrors league-of-agents-platform/infra/template.yaml conventions: SAM, arm64, long-form intrinsics, capacity caps + AWS Budgets alarm pinned to a stated USD ceiling, every sizing choice commented against it; zero idle cost
  - The Lambda accepts only short-lived voice tokens minted by learn-api (no session cookie reuse); token verification unit-tested

### t5 — Consent gate on BOTH sign-in paths: pending-consent session, consent accept/decline endpoints, no D1 write pre-consent

- depends on: t2
- covers: c9, h1, c3, h13
- acceptance:
  - FIRST a red test reproduces today's gap: fresh sign-in on web callback AND device poll writes a learners row with no consent — then the fix makes it green
  - Unconsented sign-in issues a pending-consent session: /api/me reports pending_consent, every other authed route 403s, upsertLearner is NOT called; accept records consent + upgrades the session; decline drops the session with zero rows written
  - Worker test asserts zero D1 writes before consent acceptance on both paths (h1 verbatim)

### t6 — Re-consent on version bump: authenticated requests against a stale consented terms_version route back to the consent flow

- depends on: t5, t1
- covers: c10, h2
- acceptance:
  - Consent row stores the exact published TERMS_VERSION at accept time (h2)
  - Bumping TERMS_VERSION makes the next authenticated request return consent_required / route to the consent screen until re-accepted — proven by test

### t7 — Self-serve export + delete: GET data export (JSON) and consent-withdrawal deletion removing learners+records+consents and revoking the session

- depends on: t6
- covers: c11, h3
- acceptance:
  - Export returns the learner's full data (learner row, records, consents) as JSON
  - After delete, a D1 query finds NO row in learners/records/consents for that github_user_id and the old session token is rejected (h3) — deletion test covers the append-only override decision (c18)

### t8 — Roles + visibility: ADMIN_GITHUB_IDS allow-list (20955789), admin list-all surface, default-private learner visibility field

- depends on: t7
- covers: c12, h4
- acceptance:
  - Admin routes enforce the GitHub-id allow-list server-side: non-allow-listed session gets 403 regardless of client claims (h4)
  - No authed route returns another learner's data to a non-admin; visibility defaults to private in learners.state and the learner can toggle it
  - Admin can list all learners + their progress (web + CLI read surface)

### t9 — Approval gate for tutoring: approved flag on the learner, admin approve/revoke (CLI verb + web + API), enforced BEFORE /api/tutor forwards

- depends on: t8
- covers: c13, h5
- acceptance:
  - Signed-in non-approved POST /api/tutor gets 403 with ZERO outbound inference requests — extends the existing signed-out ordering test one level (h5)
  - Approve/revoke is admin-only (allow-list enforced) and takes effect without re-login; learn admin verbs pass teken cli doctor --strict (explain catalog entries included)
  - Approval requires an existing consent to the CURRENT terms version (sequencing decision c20 enforced in code)

### t10 — Consent UI in site-astro: the consent notice page (what/why/retention/visibility), accept/decline flow against the pending-consent API, links to Terms + Privacy

- depends on: t5
- acceptance:
  - OAuth redirect lands a pending-consent user on the consent page (c19 UX decision); accept proceeds into /learn signed-in, decline signs out with a confirmation that nothing was stored
  - The notice states what is stored, why, retention, and who can see it, and links both policy pages with their version

### t11 — french-cli: author cloze exercise items against the new contract kind (upstream repo, own PR cycle)

- depends on: t3
- acceptance:
  - french-cli ships cloze items across its levels, passes learn subject doctor with cloze present, releases to PyPI; existing item_ids untouched

### t12 — spanish-cli: author cloze exercise items against the new contract kind (upstream repo, own PR cycle)

- depends on: t3
- acceptance:
  - spanish-cli ships cloze items across its levels, passes learn subject doctor with cloze present, releases to PyPI; existing item_ids untouched

### t13 — culture-guide: author cloze exercise items against the new contract kind (upstream repo, own PR cycle)

- depends on: t3
- acceptance:
  - culture-guide ships cloze scenarios, passes learn subject doctor with cloze present, releases to PyPI; existing item_ids untouched

### t14 — Re-export + redeploy content: pull the three released subjects, learn site export, Pages redeploy

- depends on: t11, t12, t13
- covers: c16, h8
- acceptance:
  - All three subjects pass learn subject doctor with at least one cloze item (h8); dev- fixture stories still excluded from public export
  - A learner's pre-existing mastery/progress reads back identically after re-export (item_id join keys unchanged, h8); new cloze content is live at /learn

### t15 — Nova Pro tutoring wiring (Bedrock-direct): INFERENCE_URL -> Bedrock OpenAI-compatible endpoint + Bedrock API key; grading, adaptive next-step, personalized cloze-story generation recorded to the ledger

- depends on: t9, t3
- covers: c24, h11
- acceptance:
  - A curl with the Bedrock API key against bedrock-runtime .../openai/v1 returns a Nova Pro completion BEFORE any feature work (h11 / c24 instruction); the region + model id + cost-when-busy (per-token only) are recorded in the worker README
  - The Worker diff adds NO provider SDK — config change plus tutoring prompt/flow modules only (h11)
  - An approved learner gets a graded exercise + adaptive next-step, and a generated cloze story personalized to their weak items lands in the ledger as a contract-valid record with a stable item_id

### t16 — Voice session end-to-end: learn-api mints approval-checked short-lived voice tokens, site voice UI connects to the serverless bridge, session budget caps enforced

- depends on: t4, t9
- covers: c15, h7
- acceptance:
  - No audio byte reaches Bedrock for a session that is not both authenticated AND approved — enforced at the bridge entry (token required, minted only for approved learners), proven by test (h7)
  - An approved learner completes a live Nova Sonic 2 voice exchange from the /learn UI; per-session time/token budget cap enforced server-side
  - The deployed stack stays within the SAM template's Budgets ceiling; idle cost is zero

### t17 — Extended launch gate + prod verification: consent, re-consent, delete, 403-zero-inference, tutor, voice, cloze checks wired into tools/launch-gate/run.sh and run green against prod

- depends on: t10, t14, t15, t16
- covers: c1, h10, c2, h12, c4, h14, c5, h15, c6, h16, c8, h17
- acceptance:
  - Every success-signal check (c8) is a real gate check that FAILED against the pre-uplift build and passes now (h17), run with `LIVE_ORIGIN=https://agentculture.org` (h10)
  - Boundary invariants asserted mechanically: no email/password column, signed-out zero API calls, no provider SDK in the worker bundle, no subject prose authored in learn-cli (h16)
  - Gate demonstrates each audience surface: learner consent+tutoring flows, admin approve/revoke, subject cloze contract, org policy link (h12); after-state clauses each map to a passing check (h15); run recorded while the public nav link is live (h14)

### t18 — File the org issue: link /learn policy pages site-wide and record the /learn-local hosting decision (c26)

- depends on: t1
- acceptance:
  - Issue filed on agentculture/org via /communicate (signed), inlining the decision + the /learn/terms and /learn/privacy URLs; org's footer links land whenever org ships them (non-blocking for /learn)

## Risks

- [unknown_nonblocking] Lambda <-> Bedrock InvokeModelWithBidirectionalStream feasibility: HTTP/2 bidirectional streaming from Lambda relayed over an API GW WebSocket is the unproven link — t4 front-loads the spike with an explicit go/no-go before any voice UI work; fallback shapes (Lambda response streaming, a different serverless relay) stay inside the no-EC2 rule (task t4)
- [unknown_nonblocking] Bedrock OpenAI-compatible endpoint must serve Nova Pro chat completions with a Bedrock API key in the chosen region — t15's first acceptance is the curl proof before feature work; if a region/model gap appears, the fix is region choice, not architecture (task t15)
- [unknown_nonblocking] API Gateway WebSocket limits (2h connection, 10min idle timeout, 32KB frames) bound voice session shape — the per-session budget cap must fit inside them; sizing gets commented against the Budgets ceiling league-style (task t16)
- [unknown_nonblocking] Upstream content latency: t11-t13 ride french-cli/spanish-cli/culture-guide PR + PyPI release cycles owned by their repos (umbrella #9 spawns per-repo issues) — the content lane can lag the platform lanes without blocking them; t14 waits, nothing else does (task t14)
- [unknown_nonblocking] Retention period wording + privacy contact point (frame v4) must be decided during t1 drafting — a drafting detail, not a design fork (task t1)
