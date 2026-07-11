// Stateless, HMAC-signed session tokens.
//
// A session is a short-lived signed token — NOT a server-stored session row.
// Shape:  base64url(JSON payload) + "." + base64url(HMAC-SHA256(payload))
// Payload: { v, uid, name, iat, exp, sid [, pending_consent] }
//
// Only the GitHub user id (`uid`), the display name (`name`), and timestamps
// live in the token. No password, no email — ever. `sid` is an opaque id used
// only for revocation tombstones in KV (see auth.js). The same token works as
// an `Authorization: Bearer` header for the CLI/MCP and as a `session` cookie
// for the web, so one issuer serves every face.
//
// Pending-consent sessions (spec decision c19, task t5): a sign-in with no
// recorded consent mints a token with `pending_consent: true` and an extra
// short TTL. Because sessions are stateless, the marker lives IN the signed
// payload — no D1/KV row backs it, which is the whole point: nothing is
// persisted for the learner until they accept. A pending token's only
// capabilities are /api/me, the consent endpoints, and logout (auth.js
// requireConsented rejects it everywhere else), and it is never
// sliding-refreshed — it expires unless upgraded via consent accept.

import { b64urlStr, b64urlToStr, hmacSign, constantTimeEqual, nowSeconds } from "./util.js";

export const DEFAULT_TTL_SECONDS = 3600; // 1 hour — short-lived by design.
export const REFRESH_WINDOW_SECONDS = 900; // re-issue when <15 min remain.
// Enough to read the consent notice and both policy pages; not enough to
// linger. Decline or expiry leaves zero trace (nothing was ever written).
export const PENDING_CONSENT_TTL_SECONDS = 600; // 10 minutes.

/**
 * Mint a signed session token for a learner.
 * @param {object} [opts]
 * @param {boolean} [opts.pendingConsent] mark the token pending-consent (c19).
 * @param {number} [opts.now] override `iat` (unix seconds) — deterministic
 *   tests only (mirrors voice.js#mintVoiceToken's own `opts.now`); production
 *   callers never pass it and get the real clock.
 * @returns {{ token: string, payload: object }}
 */
export async function issueSession(env, learner, ttlSeconds = DEFAULT_TTL_SECONDS, opts = {}) {
  if (!env || !env.SESSION_SECRET) {
    throw new Error("SESSION_SECRET is not configured");
  }
  const iat = opts.now == null ? nowSeconds() : Math.floor(opts.now);
  const payload = {
    v: 1,
    uid: String(learner.uid),
    name: learner.name || `gh-${learner.uid}`,
    iat,
    exp: iat + ttlSeconds,
    sid: crypto.randomUUID(),
    ...(opts.pendingConsent ? { pending_consent: true } : {}),
  };
  const body = b64urlStr(JSON.stringify(payload));
  const sig = await hmacSign(env.SESSION_SECRET, body);
  return { token: `${body}.${sig}`, payload };
}

/** True when the (verified) payload is a pending-consent session. */
export function isPendingConsent(payload) {
  return !!(payload && payload.pending_consent === true);
}

/**
 * Verify a token's signature and expiry.
 * @returns {object|null} the payload if valid & unexpired, else null.
 */
export async function verifySession(env, token) {
  if (!env || !env.SESSION_SECRET || !token || typeof token !== "string") return null;
  const dot = token.lastIndexOf(".");
  if (dot <= 0) return null;
  const body = token.slice(0, dot);
  const sig = token.slice(dot + 1);
  const expected = await hmacSign(env.SESSION_SECRET, body);
  if (!constantTimeEqual(sig, expected)) return null;
  let payload;
  try {
    payload = JSON.parse(b64urlToStr(body));
  } catch {
    return null;
  }
  if (typeof payload.exp !== "number" || payload.exp <= nowSeconds()) return null;
  return payload;
}

/** True when the token is within the refresh window and should be re-issued. */
export function needsRefresh(payload) {
  return typeof payload.exp === "number" && payload.exp - nowSeconds() < REFRESH_WINDOW_SECONDS;
}
