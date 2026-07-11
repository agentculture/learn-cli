// Stateless, HMAC-signed session tokens.
//
// A session is a short-lived signed token — NOT a server-stored session row.
// Shape:  base64url(JSON payload) + "." + base64url(HMAC-SHA256(payload))
// Payload: { v, uid, name, iat, exp, sid }
//
// Only the GitHub user id (`uid`), the display name (`name`), and timestamps
// live in the token. No password, no email — ever. `sid` is an opaque id used
// only for revocation tombstones in KV (see auth.js). The same token works as
// an `Authorization: Bearer` header for the CLI/MCP and as a `session` cookie
// for the web, so one issuer serves every face.

import { b64urlStr, b64urlToStr, hmacSign, constantTimeEqual, nowSeconds } from "./util.js";

export const DEFAULT_TTL_SECONDS = 3600; // 1 hour — short-lived by design.
export const REFRESH_WINDOW_SECONDS = 900; // re-issue when <15 min remain.

/**
 * Mint a signed session token for a learner.
 * @returns {{ token: string, payload: object }}
 */
export async function issueSession(env, learner, ttlSeconds = DEFAULT_TTL_SECONDS) {
  if (!env || !env.SESSION_SECRET) {
    throw new Error("SESSION_SECRET is not configured");
  }
  const iat = nowSeconds();
  const payload = {
    v: 1,
    uid: String(learner.uid),
    name: learner.name || `gh-${learner.uid}`,
    iat,
    exp: iat + ttlSeconds,
    sid: crypto.randomUUID(),
  };
  const body = b64urlStr(JSON.stringify(payload));
  const sig = await hmacSign(env.SESSION_SECRET, body);
  return { token: `${body}.${sig}`, payload };
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
