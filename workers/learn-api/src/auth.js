// Auth middleware — the single gate every learner-scoped route passes through.
//
// This is the "sign-in is the resource gate" invariant (spec c21) in code:
// requireAuth() runs BEFORE any route body, so an unauthenticated request to a
// resource-spending route (notably POST /api/tutor) is rejected with 401
// before a single byte is sent to the inference endpoint. The zero-model-call
// guarantee for signed-out traffic is a property of ordering, and it is proven
// by test (worker.test.js: "signed-out /api/tutor never calls inference").

import { HttpError, parseCookies } from "./util.js";
import { verifySession } from "./session.js";

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
