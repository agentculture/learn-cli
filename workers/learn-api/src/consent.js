// Consent policy — the one place that decides whether a learner's recorded
// consent satisfies the currently published Terms/Privacy version.
//
// Spec c9/c19 (task t5): sign-in consults this BEFORE writing anything to D1.
// No satisfying consent -> a pending-consent session is issued and zero rows
// are written; the learner row is only upserted after POST /api/consent/accept
// records a consent row (in that order — the consents table deliberately has
// no FK to learners so consent can exist first).
//
// Spec c10/h2 (task t6): re-consent on a published version bump. Extends the
// SAME predicate to require an exact version match — sign-in (t5's
// territory) and requireConsented's stored-version check (auth.js, t6) both
// consult `consentSatisfiesCurrentTerms`, so "consented" means one thing
// everywhere.

import { TERMS_VERSION, TERMS_EFFECTIVE_DATE } from "./terms.js";

/**
 * The terms version a request should be evaluated against. Test seam only —
 * mirrors util.js#outboundFetch's `env.FETCH` pattern: production never
 * declares `TERMS_VERSION_OVERRIDE` (it is not in wrangler.toml or
 * .dev.vars), so `wrangler dev` and prod always resolve the real
 * shared/terms-version.mjs value. Tests simulate a published-version bump
 * with `makeEnv({ TERMS_VERSION_OVERRIDE: "2.0.0" })` — never by editing the
 * shared source, which stays the actual published version ("1.0.0").
 * Never hardcode TERMS_VERSION elsewhere; always resolve it through here.
 */
export function currentTermsVersion(env) {
  return (env && env.TERMS_VERSION_OVERRIDE) || TERMS_VERSION;
}

/**
 * Does this consent row (from db.js getConsent — the learner's most recent
 * consent, or null) satisfy the currently published terms?
 *
 * t5 scope was "ANY recorded consent satisfies". t6 (spec c10/h2) tightens
 * this to an EXACT version match: a consent granted against a
 * since-superseded version no longer satisfies, which is what forces
 * re-consent — on a fresh sign-in (index.js handleCallback/handleDevice) AND
 * on a live full-session token hitting a requireConsented-gated route
 * (auth.js).
 */
export function consentSatisfiesCurrentTerms(consent, env) {
  return consent != null && consent.terms_version === currentTermsVersion(env);
}

/**
 * What consent is currently required — the shape clients render the notice
 * from. Embedded in /api/me (pending sessions, and now — t6 — a full session
 * whose consent has gone stale), the device-poll `consent_required`
 * response, GET /api/consent, and the requireConsented 403 body.
 */
export function consentRequirement(env) {
  return {
    terms_version: currentTermsVersion(env),
    effective_date: TERMS_EFFECTIVE_DATE,
    terms_url: "/learn/terms/",
    privacy_url: "/learn/privacy/",
  };
}
