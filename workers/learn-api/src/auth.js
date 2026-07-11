// Auth middleware — the single gate every learner-scoped route passes through.
//
// This is the "sign-in is the resource gate" invariant (spec c21) in code:
// requireAuth() runs BEFORE any route body, so an unauthenticated request to a
// resource-spending route (notably POST /api/tutor) is rejected with 401
// before a single byte is sent to the inference endpoint. The zero-model-call
// guarantee for signed-out traffic is a property of ordering, and it is proven
// by test (worker.test.js: "signed-out /api/tutor never calls inference").

import { HttpError, parseCookies } from "./util.js";
import { verifySession, isPendingConsent } from "./session.js";
import { getConsent } from "./db.js";
import { consentSatisfiesCurrentTerms, consentRequirement } from "./consent.js";

/** Extract a session token from a Bearer header (CLI/MCP) or cookie (web). */
export function extractToken(request) {
  const auth = request.headers.get("Authorization") || "";
  if (auth.startsWith("Bearer ")) return auth.slice(7).trim();
  const cookies = parseCookies(request);
  return cookies.session || null;
}

/**
 * Require a valid session. Throws HttpError(401) when absent/invalid/expired.
 * @returns {object} the verified session payload.
 */
export async function requireAuth(request, env) {
  const token = extractToken(request);
  const payload = await verifySession(env, token);
  if (!payload) {
    throw new HttpError(
      401,
      "not_authenticated",
      "Authentication required.",
      "Sign in via the web (/api/auth/login) or run `learn auth login` on the CLI.",
    );
  }
  // Revocation: logout writes a `revoked:<sid>` tombstone into KV. Stateless
  // tokens stay valid until expiry unless explicitly revoked.
  if (env.SESSIONS && payload.sid) {
    const revoked = await env.SESSIONS.get(`revoked:${payload.sid}`);
    if (revoked) {
      throw new HttpError(
        401,
        "session_revoked",
        "This session was signed out.",
        "Sign in again to obtain a fresh session.",
      );
    }
  }
  return payload;
}

/**
 * Require a valid, CONSENTED session — requireAuth plus the pending-consent
 * gate (spec decision c19) plus the re-consent gate (spec c10/h2, task t6).
 * A pending-consent token authenticates the learner but grants nothing
 * beyond /api/me, the consent endpoints, and logout; every learner-scoped
 * route (progress, record, tutor, ...) passes through here and rejects it
 * with a structured 403 BEFORE touching D1 or inference.
 *
 * t5 gated on the token's own marker only: "a full session was necessarily
 * issued via consent accept (or a consented sign-in), so no D1 read is
 * needed here." That assumption only holds AT ISSUE TIME — it says nothing
 * about whether the published terms have moved on since. t6 closes that gap:
 * a full session additionally gets its STORED consent re-checked against the
 * currently published version on every protected request, so a
 * TERMS_VERSION bump walls off even a live, unexpired full-session token
 * immediately (no waiting for it to expire or refresh).
 *
 * Design/cost tradeoff (see README "Storage" for the write-up): this is one
 * extra D1 read (`getConsent`) per requireConsented-gated request. The
 * alternative — stamp the consented version into the session token's signed
 * claims at issue time and compare claim-to-current with zero D1 reads — was
 * rejected for v1: it would require every session-issuing call site
 * (callback, device poll, consent accept, AND the sliding-refresh re-issue in
 * handleMe) to correctly propagate the claim, and a bug in any one of them
 * would silently under- or over-grant access. A D1 read is the simple,
 * obviously-correct baseline; revisit only if this route's read volume
 * becomes a measured hot spot.
 * @returns {object} the verified, consented session payload.
 */
export async function requireConsented(request, env) {
  const payload = await requireAuth(request, env);
  if (isPendingConsent(payload)) {
    throw new HttpError(
      403,
      "consent_required",
      "Consent to the current Terms of Use and Privacy Policy is required first.",
      "Review GET /api/consent, then POST /api/consent/accept — or /api/consent/decline to leave with nothing stored.",
      { reason: "pending", consent_required: consentRequirement(env) },
    );
  }
  const consent = await getConsent(env, payload.uid);
  if (!consentSatisfiesCurrentTerms(consent, env)) {
    throw new HttpError(
      403,
      "consent_required",
      "The Terms of Use / Privacy Policy have changed since you last consented — please review and re-accept.",
      "Review GET /api/consent, then POST /api/consent/accept to restore access.",
      { reason: "stale_version", consent_required: consentRequirement(env) },
    );
  }
  return payload;
}
