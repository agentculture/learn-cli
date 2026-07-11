// Single source of truth for the published Terms of Use / Privacy Policy
// version (spec "agentculture-org-learn-is-now-a-consent-first-role", #11;
// plan task t1). Two consumers import this file, and only this file:
//
//   - the Astro site's pages (site-astro/src/lib/terms.ts -> src/pages/terms/,
//     src/pages/privacy/) — renders the version + effective date visibly on
//     both policy pages.
//   - the Cloudflare Worker (workers/learn-api/src/terms.js) — a later wave
//     (plan task t6) stamps the consent row's `terms_version` with this exact
//     value and treats a mismatch as "re-consent required."
//
// Deliberately a plain ES module, not a `.json` file: `import x from
// "./f.json"` needs an import-assertion clause (`with { type: "json" }` /
// the older `assert { type: "json" }`) whose required syntax has moved
// across recent Node versions, and this file is loaded three different ways
// (Node's own `--test` runner in workers/learn-api, Vite/Rollup for `astro
// build`, esbuild inside `wrangler`/`wrangler deploy`). A plain `export
// const` sidesteps that version skew entirely — every one of those three
// loaders already understands plain ESM with zero extra configuration.
//
// Bumping TERMS_VERSION (and TERMS_EFFECTIVE_DATE alongside it) is what
// forces re-consent: a learner's stored `consent.terms_version` must equal
// this value exactly, or the next authenticated request routes back to the
// consent screen (spec requirement "Consent record", honesty condition h2).
// Keep the date in ISO-8601 (YYYY-MM-DD) to match every other timestamp
// convention in this repo (schema.sql's `created_at`/`updated_at`, the
// ledger's `at`).

export const TERMS_VERSION = "1.0.0";
export const TERMS_EFFECTIVE_DATE = "2026-07-11";
