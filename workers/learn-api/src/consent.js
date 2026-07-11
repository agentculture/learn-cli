// Consent policy — the one place that decides whether a learner's recorded
// consent satisfies the currently published Terms/Privacy version.
//
// Spec c9/c19 (task t5): sign-in consults this BEFORE writing anything to D1.
// No satisfying consent -> a pending-consent session is issued and zero rows
// are written; the learner row is only upserted after POST /api/consent/accept
// records a consent row (in that order — the consents table deliberately has
// no FK to learners so consent can exist first).

import { TERMS_VERSION, TERMS_EFFECTIVE_DATE } from "./terms.js";

/**
 * Does this consent row (from db.js getConsent — the learner's most recent
 * consent, or null) satisfy the currently published terms?
 *
 * t5 scope: ANY recorded consent satisfies. Task t6 extends this single
 * predicate to require `consent.terms_version === TERMS_VERSION` exactly, so
 * a published version bump routes the learner back to the consent screen
 * (re-consent, spec h2). Extend it HERE — sign-in paths and t6's re-consent
 * check must share one definition of "consented".
 */
export function consentSatisfiesCurrentTerms(consent) {
  return consent != null;
}

/**
 * What consent is currently required — the shape clients render the notice
 * from. Embedded in /api/me (pending sessions), the device-poll
 * `consent_required` response, and GET /api/consent.
 */
export function consentRequirement() {
  return {
    terms_version: TERMS_VERSION,
    effective_date: TERMS_EFFECTIVE_DATE,
    terms_url: "/learn/terms/",
    privacy_url: "/learn/privacy/",
  };
}
