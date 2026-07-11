# Build Plan — learn-cli ships a one-command-free deployment pipeline: merging to main deploys the whole /learn stack — Astro site, the learn-api Cloudflare Worker, and the D1 schema — from CI with no local wrangler, and the same workflow runs on demand from any branch (workflow_dispatch) against a non-production preview target, so the pipeline is proven green before the merge path is trusted.

slug: `learn-cli-ships-a-one-command-free-deployment-pipe` · status: `exported` · from frame: `learn-cli-ships-a-one-command-free-deployment-pipe`

> learn-cli ships a one-command-free deployment pipeline: merging to main deploys the whole /learn stack — Astro site, the learn-api Cloudflare Worker, and the D1 schema — from CI with no local wrangler, and the same workflow runs on demand from any branch (workflow_dispatch) against a non-production preview target, so the pipeline is proven green before the merge path is trusted.

## Tasks

### t1 — Add an [env.preview] environment to workers/learn-api/wrangler.toml: name learn-api-preview, a preview D1 binding (its own database_id, operator-provisioned), NO routes key; the top-level config stays production (learn-ledger D1 + /learn/* route).

- instruction: Model [env.preview] on the top-level config: copy the [[kv_namespaces]]/[[d1_databases]] blocks under [env.preview], set name='learn-api-preview', point d1 at the preview DB (placeholder database_id, operator fills like the prod one), and OMIT the routes key. Do not touch the top-level production config.
- covers: c13, h3
- acceptance:
  - wrangler.toml has an [env.preview] table whose worker name is learn-api-preview, binds a preview D1, and declares no route/routes key
  - the top-level (production) config still binds learn-ledger D1 and the /learn/* zone route, unchanged

### t2 — Add .github/workflows/deploy-worker.yml: push-to-main (path-filtered workers/learn-api/**) runs schema.sql against learn-ledger --remote, syncs secrets, and 'wrangler deploy' (production); workflow_dispatch from any branch runs schema.sql against the preview D1 and 'wrangler versions upload --env preview' (no promote); prod/promote steps gated to ref==main; secrets piped via stdin; secrets-gated skip-notice like deploy-site.yml.

- instruction: Mirror .github/workflows/deploy-site.yml structure (checkout, env-mapped CLOUDFLARE_* secrets, 'if: env.CLOUDFLARE_API_TOKEN != \'\'' skip-notice, npx wrangler@4, working-directory workers/learn-api). Use two guarded step groups: prod (if github.ref=='refs/heads/main') and preview (else / workflow_dispatch). Secrets loop: for each of SESSION_SECRET GITHUB_CLIENT_ID GITHUB_CLIENT_SECRET INFERENCE_TOKEN VOICE_TOKEN_SECRET, 'printf %s "${{ secrets.X }}" | npx wrangler@4 secret put X [--env preview]'.
- depends on: t1
- covers: c1, c4, c5, c12, c14, c15, h1, h4, h5, h6, h8, h9, h10
- acceptance:
  - on push to main the job applies schema.sql to learn-ledger --remote and runs 'wrangler deploy' (top-level wrangler.toml)
  - a workflow_dispatch run off a non-main branch runs 'wrangler versions upload --env preview' and applies schema to the preview D1, and NEVER runs 'wrangler deploy' or promotes to prod
  - every production/promote/prod-D1 step is guarded by an if: condition requiring ref == refs/heads/main
  - each secret is applied via stdin (printf %s $X | wrangler secret put NAME) so no secret value appears as a CLI argument; the deploy step is skipped with a notice when CLOUDFLARE_API_TOKEN is unset

### t3 — Add tests/test_deploy_pipeline_invariants.py: parse deploy-worker.yml + wrangler.toml and assert the mechanical boundaries — prod steps gated to ref==main, no 'sam'/'infra' reference, deploys wrangler.toml (never wrangler.signedout.toml), no secret passed as a CLI arg, schema.sql statements all idempotent.

- instruction: Follow the existing tests/test_launch_gate_invariants.py style (read the workflow YAML + wrangler.toml as text/ast, assert mechanical boundaries). Keep it hermetic — no network, no wrangler invocation.
- depends on: t2
- covers: c6, c9, h2, h11, h14
- acceptance:
  - test asserts the workflow guards prod deploy + prod-D1 apply behind ref==refs/heads/main (or environment: production)
  - test asserts the workflow never references 'sam' or 'infra/', and deploys workers/learn-api/wrangler.toml and never wrangler.signedout.toml
  - test asserts every statement in schema.sql is CREATE ... IF NOT EXISTS (idempotent) and no secret value is a literal CLI argument in the workflow

### t4 — Update workers/learn-api/README.md deploy section: CI now deploys (merge=prod, branch dispatch=preview verify); document the one-time operator prerequisites (create the preview D1, set the 5 GitHub Actions secrets), the pre/post-deploy verify (LIVE launch gate + run-twice idempotency), and the preview-env OAuth-callback caveat; remove local 'wrangler deploy' as the routine path.

- instruction: Edit the deploy/runbook section of workers/learn-api/README.md. Cross-reference tools/launch-gate/BASELINE-2026-07-11.md for the post-merge verify. State the operator prereqs as a numbered list.
- depends on: t2
- covers: c2, c3, c7, c8, h7, h12, h13
- acceptance:
  - README documents the CI pipeline (merge-to-main production vs branch-dispatch preview) and no longer presents a local 'wrangler deploy' as the routine go-live path
  - README lists the one-time operator setup (preview D1 creation + the named GitHub Actions secrets) and the preview OAuth-callback caveat
  - README documents the post-merge verify (LIVE_ORIGIN launch gate vs baseline) and the run-twice idempotency check

### t5 — Bump pyproject.toml version and prepend a CHANGELOG entry describing the deploy-worker pipeline (required by version-check CI on every PR).

- instruction: Use the version-bump skill: echo JSON | python3 .claude/skills/version-bump/scripts/bump.py minor (this is a new feature). Summarize the deploy pipeline in the Added section.
- acceptance:
  - pyproject.toml version is greater than main's and CHANGELOG.md has a dated entry describing the deploy pipeline automation
