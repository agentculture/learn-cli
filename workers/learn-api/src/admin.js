// Admin allow-list — the server-side-only role check (spec c12/h4, task t8).
//
// h4 verbatim: "Admin capability is enforced server-side against the
// GitHub-id allow-list (a non-allow-listed session calling an admin route
// gets 403 regardless of any client claim)". That is the whole contract this
// module exists to satisfy: admin-ness is NEVER read from anything the
// client sends — not a request body flag, not a header, not a query
// parameter. It is looked up fresh, on every admin request, against
// `env.ADMIN_GITHUB_IDS` (a comma-separated Worker var — see wrangler.toml),
// keyed off the session's own `uid`, which itself only ever came from a
// verified, HMAC-signed token (session.js) — never from request content a
// caller controls. There is no path from "the client claims admin" to "the
// server believes it"; test/admin.test.js proves this with a forged claim.
//
// isAdmin() is a pure, side-effect-free config check so it is trivially
// reusable outside the request path too (e.g. a future CLI-side dry-run) —
// requireAdmin() is the route-facing wrapper every admin handler in
// index.js actually calls.

import { HttpError } from "./util.js";
import { requireConsented } from "./auth.js";

/** Parse ADMIN_GITHUB_IDS ("id,id,...") into a Set of trimmed id strings. */
function adminIds(env) {
  const raw = (env && env.ADMIN_GITHUB_IDS) || "";
  return new Set(
    raw
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean),
  );
}

/** Is this GitHub user id on the server-side admin allow-list? */
export function isAdmin(env, uid) {
  return adminIds(env).has(String(uid));
}

/**
 * Require a valid, CONSENTED, ADMIN session for an admin-only route.
 *
 * Builds on requireConsented (spec t8 acceptance: "Admin routes
 * (requireConsented + admin)") — the admin is a learner too and passes
 * through the same consent gate as every other resource-reading route
 * (progress/record/export/tutor) before the allow-list check ever runs.
 * A consented, non-allow-listed session gets a structured 403
 * `admin_required` here; nothing about the request itself (body, headers,
 * query string) is ever consulted for the decision — see this module's own
 * header comment.
 * @returns {object} the verified, consented, admin session payload.
 */
export async function requireAdmin(request, env) {
  const session = await requireConsented(request, env);
  if (!isAdmin(env, session.uid)) {
    throw new HttpError(
      403,
      "admin_required",
      "This route is restricted to the learn admin.",
      "",
    );
  }
  return session;
}
