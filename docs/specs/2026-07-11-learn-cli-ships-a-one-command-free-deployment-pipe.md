# learn-cli ships a one-command-free deployment pipeline: merging to main deploys the whole /learn stack — Astro site, the learn-api Cloudflare Worker, and the D1 schema — from CI with no local wrangler, and the same workflow runs on demand from any branch (workflow_dispatch) against a non-production preview target, so the pipeline is proven green before the merge path is trusted.

> learn-cli ships a one-command-free deployment pipeline: merging to main deploys the whole /learn stack — Astro site, the learn-api Cloudflare Worker, and the D1 schema — from CI with no local wrangler, and the same workflow runs on demand from any branch (workflow_dispatch) against a non-production preview target, so the pipeline is proven green before the merge path is trusted.
> instruction: Land deploy-worker CI + branch-dispatch preview; demo one green dispatch and one green main deploy.

## Audience

- The learn-cli operator/maintainer who merges to main or needs to verify a deploy, and the agent driving go-live (which the auto-mode classifier currently forbids from running local wrangler).
  - instruction: Verify the go-live runbook no longer contains a local 'wrangler deploy' step for the routine path.

## Before → After

- Before: The Astro site auto-deploys on merge (deploy-site.yml), but the learn-api Worker, its D1 schema, and its secrets are a manual out-of-band wrangler runbook the auto-mode classifier blocks the agent from running — so go-live is a hand-run, non-reproducible checklist.
  - instruction: Diff against the current .github/workflows (only deploy-site/publish/tests exist).
- After: Merge to main runs one CI pipeline that deploys the site, deploys the learn-api Worker, and idempotently applies the D1 schema — no local wrangler, no agent-run deploy; a branch workflow_dispatch runs the same jobs against a non-prod preview target and reports green/red without mutating production.
  - instruction: Trace the workflow jobs: site, worker, schema; assert the non-main path skips prod promote + prod-D1 write.

## Why it matters

- The deploy becomes reproducible, auditable, and executable by CI's credentials rather than a human/agent laptop — which also resolves the auto-mode deploy blocker — and branch-dispatch lets the pipeline mechanics be verified before a real merge relies on them.
  - instruction: Confirm every input (config, schema, secrets) comes from the repo or GitHub Actions secrets.

## Requirements

- The pipeline deploys the Worker from the committed workers/learn-api/wrangler.toml (the full signed-in config, not wrangler.signedout.toml) and applies workers/learn-api/schema.sql to the remote D1 before/with the Worker deploy.
  - instruction: Point the deploy step at workers/learn-api/wrangler.toml and run 'wrangler d1 execute learn-ledger --remote --file schema.sql' on the main path.
  - honesty: schema.sql is fully idempotent (verified: every statement is CREATE TABLE/INDEX IF NOT EXISTS), so applying it on every prod deploy is a no-op once migrated.
  - honesty: wrangler.toml (not wrangler.signedout.toml) is the config CI deploys, and it carries the KV+D1 bindings and /learn/* route the running product needs.
- A branch workflow_dispatch (preview) run must not deploy to the production Worker/route or write to production KV/D1 — production is left untouched by any non-main run.
  - instruction: Gate the promote/prod-D1 steps to ref==main (or environment:production); branch dispatch uses versions upload / preview only.
  - honesty: The mechanism chosen for preview (per the open question) provably cannot promote to the production Worker, bind the /learn/* route, or write prod D1/KV — a preview run leaves prod's deployed version and data unchanged.
- Secrets are never printed to CI logs nor committed: CI reads them from GitHub Actions secrets (masked) and pipes them to wrangler; no secret value appears in the workflow file or logs.
  - instruction: Store each app secret as a masked GitHub Actions secret; pipe via stdin to 'wrangler secret put NAME' (value never on the command line); apply to both the prod and preview-env Workers.
  - honesty: wrangler deploy does NOT reset or delete already-set Worker secrets, and 'wrangler secret put' (if ever used) reads the value from stdin/env so it never appears as a command-line arg in logs; GitHub masks secrets.* in logs.
- A deploy failure (bad wrangler.toml, missing binding, D1 error) fails the CI job visibly red and does not leave a partially-promoted production Worker.
  - instruction: Let non-zero wrangler exit fail the job; rely on wrangler deploy atomicity so no partial prod version is promoted.
  - honesty: A failing wrangler deploy / d1 execute returns a non-zero exit that fails the job, and 'wrangler deploy' is atomic (a bad upload does not partially replace the live version).

## Honesty conditions

- The whole claim is provable by two runs: a green branch workflow_dispatch and a green merge-to-main deploy that together cover site + Worker + schema.
- After this ships, neither operator nor agent runs local wrangler for a normal deploy — CI holds the Cloudflare credentials and does it.
- Today no workflow references wrangler deploy / learn-api (grep-verified), so the manual Worker gap is real, not already-solved.
- One triggered CI run performs all three actions (site deploy, Worker deploy, remote schema apply) on main, and a branch run is provably non-prod.
- The deploy is reproducible from committed git state + repo secrets alone, with no laptop-specific or agent-specific state.
- A preview run leaves the production Worker version id, the /learn/* route binding, and D1 row counts unchanged — checkable before/after.
- Post-merge, LIVE_ORIGIN=https://agentculture.org consent_walk.mjs flips the recorded BASELINE-2026-07-11 failures to green.
- A second identical pipeline run changes nothing: schema apply is a no-op and the Worker redeploy preserves secrets and behavior.
- The workflows never invoke sam / touch infra/ — the voice bridge stays undeployed by this pipeline.

## Success signals

- A branch workflow_dispatch run goes green end-to-end against the preview target while production stays byte-identical (route, Worker version, D1 rows unchanged).
  - instruction: Capture 'wrangler deployments list' + a row count before/after a preview dispatch; assert identical.
- After a merge to main, the LIVE_ORIGIN=https://agentculture.org launch gate (consent_walk.mjs) flips from the recorded pre-uplift baseline to green with no local wrangler invoked.
  - instruction: Run the LIVE launch gate after the first main deploy and compare to the baseline artifact.
- Re-running the pipeline is a no-op-safe idempotent operation: schema re-apply changes nothing, and a Worker redeploy preserves already-set secrets.
  - instruction: Run the main pipeline twice; assert the second run reports no schema change and OAuth still works.

## Scope / boundaries

- Not automating the SAM voice bridge deploy (infra/ — sam deploy stays a separate, later manual step); this phase is site + Worker + D1 schema only.
  - instruction: Grep the new workflow for 'sam'/'infra' — must be absent; voice remains a separate manual step.

## Non-goals

- Not building a D1 migrations framework — the pipeline applies the existing idempotent schema.sql (all CREATE ... IF NOT EXISTS); destructive/ALTER migrations are out of scope.
- Not changing the tutoring enablement model — INFERENCE_URL stays commented-in-wrangler.toml config, so enabling Nova Pro remains a deliberate commit, not a pipeline toggle.

## Decisions

- A new sibling workflow .github/workflows/deploy-worker.yml (modeled on deploy-site.yml: same checkout, npx wrangler, secrets-gated skip-notice) rather than folding Worker steps into deploy-site.yml — keeps site and Worker deploys independently triggerable and path-filtered.
- Branch preview = 'wrangler versions upload' (uploads a Worker version + a preview URL, does NOT promote to production and does NOT bind the /learn/* route); merge-to-main = 'wrangler deploy' (promotes to production). Mirrors deploy-site.yml's --branch preview-vs-production split.
- Worker deploy is path-filtered to workers/learn-api/** + the workflow file on push; workflow_dispatch ignores path filters so a branch preview can always be forced. The prod job is gated to github.ref == main (or a GitHub environment: production) so a dispatch from a branch can never hit the deploy/promote path.
- Worker secrets are CI-synced from GitHub Actions secrets every deploy: SESSION_SECRET, GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET, INFERENCE_TOKEN, VOICE_TOKEN_SECRET are each stored as masked Actions secrets and applied via 'printf %s "$X" | wrangler secret put NAME' (stdin, never an arg). Deploys are fully hands-off; the tradeoff is these secrets now also live in GitHub's encrypted store.
- A separate preview D1 database backs branch runs: [env.preview] in wrangler.toml binds a preview D1 (its own database_id) and NO /learn/* route. Branch workflow_dispatch applies schema.sql to the preview D1 and uploads a preview version there; the main path applies schema.sql to the prod learn-ledger D1 and deploys the top-level (production) Worker. No branch run ever reads or writes prod D1.
- Branch preview is realized as a Cloudflare preview ENVIRONMENT: 'wrangler versions upload --env preview' uploads a non-promoted version of the learn-api-preview Worker (bound to the preview D1, no route, its own workers.dev preview URL). This composes Q1 (versions upload / no promote) with Q3 (separate preview D1), since a plain version of the top-level Worker cannot swap its D1 binding.
