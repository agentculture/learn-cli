# agentculture.org/learn is now a consent-first, role-aware tutoring service: sign-in asks explicit consent against versioned Terms + Privacy before anything is saved (with self-serve export and delete), an admin approves which learners get the Bedrock tutoring tier — Nova Sonic 2 voice sessions and a Nova Pro teacher with personalized cloze stories — and the curriculum ships a level deeper across french, spanish, and culture-guide with a new cloze exercise type

> agentculture.org/learn is now a consent-first, role-aware tutoring service: sign-in asks explicit consent against versioned Terms + Privacy before anything is saved (with self-serve export and delete), an admin approves which learners get the Bedrock tutoring tier — Nova Sonic 2 voice sessions and a Nova Pro teacher with personalized cloze stories — and the curriculum ships a level deeper across french, spanish, and culture-guide with a new cloze exercise type
> instruction: Verify by extending tools/launch-gate/run.sh with the consent/approval/deletion checks and running it with `LIVE_ORIGIN=https://agentculture.org` — the uplift ships only when the extended gate is fully green

## Audience

- Signed-in learners at agentculture.org/learn (humans on the web + agents via CLI/MCP device flow), the admin (GitHub id 20955789 / OriNachum), upstream subject-CLI maintainers (french-cli, spanish-cli, culture-guide), and org as the domain owner for the policy pages

## Before → After

- Before: Live gap: both sign-in paths (web handleCallback and device-flow poll) upsertLearner + issue a session with NO consent step — verified on the first real sign-in. No roles: every signed-in user has the same view. /api/tutor requires only a session (no approval flag exists) and 503s because INFERENCE_URL is unset. No Terms/Privacy pages exist. Curriculum is launch-depth; no cloze exercise type in the contract.
- After: First sign-in presents a consent notice pinned to a published Terms/Privacy version and writes nothing until the learner accepts; consent is recorded (learner, terms_version, granted_at) and a version bump forces re-consent; learners can export and delete everything self-serve; the admin (id allow-list) approves who gets tutoring; approved learners get a Nova Pro teacher (grading, adaptive next-step, personalized cloze stories) and a Nova Sonic 2 voice session; all three subjects ship cloze exercises and a deeper curriculum, re-exported to /learn

## Why it matters

- The nav link is public on agentculture.org — real users can sign in today into a system that persists identity + full learning history with no recorded consent (compliance exposure that grows with every new user), and the tutoring tier is the actual product value: inference costs real money, so it must be admin-approved per learner

## Requirements

- Consent gate (#10): neither sign-in path (web handleCallback nor device-flow poll) may call upsertLearner — or write anything to D1 — before a recorded consent exists for the current terms version. Unconsented sign-in lands in an explicit pending-consent state instead of silently persisting.
  - honesty: A worker test drives a fresh sign-in on BOTH paths (web callback and device poll) and asserts zero D1 writes occur before consent is accepted — the test fails if upsertLearner runs pre-consent on either path
- Consent record (#10/#11): consent is stored in D1 as (github_user_id, terms_version, granted_at) — a consents table — where terms_version is exactly the published version of the #11 documents at accept time; publishing a new version forces re-consent before further writes
  - honesty: The consent row's terms_version equals the exact published document version at accept time, and bumping the published version makes the next authenticated request route back to the consent screen — both proven by test
- Right to withdraw/delete (#10): a self-serve authenticated path exports the learner's data (JSON) and deletes it — the learners row, all their records, their consents — and revokes the session. Withdrawal of consent means deletion.
  - honesty: After self-serve delete, a D1 query finds no row in learners, records, or consents carrying that github_user_id, and the old session token is rejected (revoked) — proven by test
- Roles + visibility (#8): admin is an explicit GitHub-id allow-list (20955789) in Worker config, enforced server-side; admin can list all learners and their progress; a regular learner sees only their own data by default (default private) and controls what of theirs is visible to others
  - honesty: Admin capability is enforced server-side against the GitHub-id allow-list (a non-allow-listed session calling an admin route gets 403 regardless of any client claim), and no authed route ever returns another learner's data to a non-admin — proven by test
- Approval gate (#8): an approved flag on the D1 learner row, settable only via an admin-only surface (CLI verb + web), enforced in the Worker BEFORE any /api/tutor forwarding — signed-in but non-approved gets 403 and zero outbound inference. Extends the existing ordering-based resource-gate invariant one level: signed-out < signed-in < approved.
  - honesty: A signed-in, non-approved learner POSTing /api/tutor receives 403 and the Worker makes ZERO outbound inference requests — proven by extending the existing signed-out-never-calls-inference ordering test to the approval level
- Nova Sonic 2 voice (#8): learner speech is a real-time bidirectional audio session against Bedrock Nova Sonic 2 on a SEPARATE transport (WebSocket/WebRTC bridge, not the JSON broker), enforcing the same approval gate before any audio reaches Bedrock
  - honesty: No audio byte reaches Bedrock for a session that is not both authenticated AND approved — the voice transport enforces the same gate as /api/tutor, provable at its entry point
- Cloze exercise type (#9): the subject-plugin contract gains a cloze (pick-the-right-word) exercise kind; french-cli, spanish-cli, and culture-guide each ship cloze items; existing item_ids stay stable so learner mastery survives re-export; learn subject doctor stays green for all three; then learn site export + Pages redeploy publishes the new content
  - honesty: All three subjects pass learn subject doctor with at least one cloze item present, and a learner's pre-existing mastery/progress reads back identically after the re-export (item_id join keys unchanged)
- Terms of Use + Privacy Policy (#11): both pages published, versioned, linked from the /learn footer and from the consent notice. The Privacy Policy names GitHub (OAuth identity), Cloudflare (Workers/KV/D1/Pages hosting), and AWS Bedrock (Nova Sonic 2 / Nova Pro — approved tier only, learner speech/text leaves to the model provider) as processors, states retention + the delete/export path, and matches what the code actually persists (no email, no password).
  - honesty: Every processor the code actually calls (GitHub OAuth endpoints, Cloudflare storage/hosting, the Bedrock-backed inference endpoint) is named in the published Privacy Policy, and nothing the policy claims about data (no email, no password, deletable on request) is contradicted by the schema or worker code
- Nova Pro tutoring (#8): text tutoring (exercise grading, adaptive next-step, explanation, personalized cloze-story generation) routes through the existing /api/tutor broker with INFERENCE_URL pointing directly at AWS Bedrock's OpenAI-compatible chat-completions endpoint (bedrock-runtime .../openai/v1) and a Bedrock API key as INFERENCE_TOKEN — AWS Bedrock is the only service that serves AWS Nova models; no sibling-hosted model server, no idle host. Cost-when-busy: per-token Nova Pro spend only. Generated cloze stories and their results are recorded to the existing ledger as contract-valid records with stable item_ids.
  - instruction: Verify with a curl against the Bedrock OpenAI-compatible endpoint using the Bedrock API key (expect a Nova Pro completion), then the worker test that /api/tutor forwards approved traffic and the Worker diff shows no provider SDK added
  - honesty: The Worker gains no Bedrock/provider SDK and no code change beyond config — a Bedrock API key against the OpenAI-compatible endpoint returns a Nova Pro completion, and the broker forwards approved traffic to it unchanged (h6's condition, retargeted at Bedrock-direct)

## Honesty conditions

- The announcement is only true when every acceptance check in the success signal (c8) is demonstrable against prod agentculture.org/learn — consent-gated writes, versioned re-consent, self-serve delete, 403-with-zero-inference for non-approved, a working approved-tier Nova Pro + Nova Sonic 2 session, cloze content live
- Each named audience has a concrete surface in the shipped uplift: learners get the consent + tutoring flows, the admin gets the approve/revoke surface, subject repos get the cloze contract change, org gets the policy-page link touchpoint
- The gap is reproducible today: a fresh sign-in on prod writes a learners row with no consent prompt, and the code shows no approval flag and no consent table (index.js handleCallback + handleDevice both call upsertLearner unconditionally; schema.sql has two tables)
- Holds while the nav link is public and sign-in is open: any new user's first sign-in persists identity + history unconsented, and once INFERENCE_URL is set every tutor call spends real money — so both halves (consent, approval) are live risks, not hypotheticals
- Every clause of the after-state maps to at least one confirmed requirement (c9-c13, c15-c17, c24) and is exercised by a success-signal check — no aspirational orphan clauses in the spec
- The invariants are mechanically checkable: the schema stores no email/password column, signed-out pages make zero API calls (existing launch gate), the Worker diff adds no provider SDK, and no subject prose is authored inside learn-cli
- Each listed check becomes a real test in the extended launch gate or worker suite and FAILS against today's build — they are acceptance tests that distinguish shipped from not-shipped, not restatements

## Success signals

- Launch-gate-style checks, all green against prod: a fresh first sign-in writes zero D1 rows until consent is accepted (web AND device paths); bumping the published terms version forces re-consent on next authenticated request; self-serve delete leaves no row carrying the learner's github_user_id and revokes the session; a signed-in but non-approved learner calling /api/tutor gets 403 with zero outbound inference calls; an approved learner completes a Nova Pro-graded exercise and a Nova Sonic 2 voice exchange; cloze exercises from all three subjects are live at /learn with subject doctor green

## Scope / boundaries

- Invariants that hold: no email/password ever (GitHub id + public display name only); signed-out stays fully static with zero API/model calls; the Worker stays provider-agnostic (no Bedrock SDK in the Worker — inference only via served OpenAI-shaped endpoints). Deep curriculum authoring happens UPSTREAM in the subject repos (their own issues spawn from #9) — this spec covers the contract change (cloze), the export/redeploy, and all learn-cli-side wiring, not the prose of new French stories.

## Non-goals

- Not building: bespoke model hosting or any sibling-hosted model server — AWS Bedrock is the only service that serves AWS Nova models, so learn talks to Bedrock directly; also not building a general-purpose LMS or analytics product, org-site changes beyond a link to the /learn policy pages, or payment/billing for the tutoring tier (approval is manual admin action)

## Decisions

- Deletion vs append-only: the records ledger's append-only rule governs normal operation (rows are never edited or individually removed) — but a learner's consent withdrawal overrides it and hard-deletes all of that learner's rows. Erasure beats immutability; the two are not in conflict because they operate at different granularities (per-row edits vs whole-learner exit).
- Consent UX shape: an unconsented sign-in issues a short-lived pending-consent session whose ONLY capabilities are viewing the consent notice + accepting or declining — no learner row exists yet, /api/me reports pending_consent, every other authed route 403s. Decline = the session is dropped and nothing was ever written. This keeps the OAuth redirect flow intact (the user lands signed-in-pending on the consent page) without persisting pre-consent.
- Sequencing: the consent gate + published policy docs (#10/#11) ship BEFORE the tutoring tier is enabled for anyone — no learner is approved for Bedrock until the Privacy Policy disclosing Bedrock processing is live and they have consented to it. Content work (#9) proceeds upstream in parallel, unblocked.
- Content flows upstream-first (#9): curriculum improvements are authored in french-cli / spanish-cli / culture-guide, released to PyPI, then pulled into /learn via learn site export + redeploy — learn-cli never forks subject content locally
- Model access is Bedrock-direct (user decision): AWS Bedrock is the only service that can serve AWS Nova models — both the Nova Pro text path (OpenAI-compatible endpoint + Bedrock API key) and the Nova Sonic 2 voice path (InvokeModelWithBidirectionalStream) terminate at Bedrock itself. Anything between the learner and Bedrock is thin credentialed plumbing enforcing the approval gate, never a model host. Supersedes the earlier cloudai-cli/ec2bedrock-cli serving framing.
- Policy docs live /learn-local (user decision, resolves v1): learn-cli authors, versions, and serves the Terms of Use + Privacy Policy under /learn — it is the only surface processing personal data (auth, ledger, Bedrock); org's static site collects nothing. Re-consent versioning stays inside learn-cli, uncoupled from org releases. org gets a filed issue to link the policies site-wide and to record this decision.
- AWS plumbing is serverless, pay-as-you-go (user decision, resolves v7): no EC2 unless explicitly requested. The Nova Sonic 2 voice bridge follows league-of-agents-platform's proven infra pattern (built by Fable): AWS SAM, Lambda (arm64) behind an API Gateway WebSocket API relaying learner audio to Bedrock's bidirectional stream, an AWS Budgets alarm pinned to a hard monthly USD ceiling with every sizing choice commented against it, and zero idle cost. Bedrock itself is serverless GenAI — nothing always-on sits between the learner and it.

## Post-convergence correction (2026-07-11, pending user confirmation)

> This note annotates — it does not silently rewrite — a converged claim. It is
> captured as `q1` in the frame's questions store and awaits user confirmation
> at the final PR gate.

- **c24 endpoint wording (OpenAI-compatible → native Converse).** c24 (and the
  Decisions "Model access is Bedrock-direct" line) say the Nova Pro text path
  points `INFERENCE_URL` at Bedrock's *OpenAI-compatible chat-completions*
  endpoint (`bedrock-runtime.<region>.amazonaws.com/openai/v1/...`). A live probe
  during t15 (2026-07-11) proved that endpoint returns `model_not_found` for
  Nova Pro in every region tried (us-east-1, us-west-2, eu-west-1, eu-central-1),
  and `/openai/v1/models` is not even an operation. The **native Bedrock Converse
  API** — `POST /model/us.amazon.nova-pro-v1:0/converse` with a Bedrock API key as
  the Bearer token — DID return real Nova Pro completions (HTTP 200, ~0.5–1s) and
  tolerates the broker's `learner` stamp as an extra field. So the honesty
  condition **h11 still holds** (no Worker code change beyond config; no provider
  SDK): only the endpoint URL and the request/response *shape* change from the
  OpenAI chat-completions form to the Converse form. The shipped code
  (`wrangler.toml`, `workers/learn-api/README.md`, `site-astro/src/scripts/
  tutor-core.js`) already targets Converse; this note reconciles the spec's
  wording with what shipped. **Proposed:** retarget c24's "OpenAI-compatible
  chat-completions endpoint" wording to the native Converse API. Awaiting user
  confirmation.
