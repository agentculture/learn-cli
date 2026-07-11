// GitHub OAuth — the only identity provider (spec c30).
//
// Two flows, one issuer:
//   * Web flow    — /api/auth/login -> GitHub -> /api/auth/callback.
//   * Device flow — /api/auth/device {start|poll}, for the CLI/MCP (t12).
//
// PRIVACY INVARIANT: we read ONLY the numeric id and a display name from the
// GitHub user object. We never request the `user:email` scope and never read,
// log, or persist `email`. The stored identity is (id, display_name) — nothing
// else. All outbound calls go through the `outboundFetch(env)` seam so tests
// run with a stub and hit no network.

import { HttpError, outboundFetch } from "./util.js";

export const GH = {
  authorize: "https://github.com/login/oauth/authorize",
  token: "https://github.com/login/oauth/access_token",
  deviceCode: "https://github.com/login/device/code",
  user: "https://api.github.com/user",
};

const SCOPE = "read:user";
const UA = "learn-api (agentculture.org/learn)";

/** Build the GitHub authorize URL for the web flow. */
export function authorizeUrl(env, redirectUri, state) {
  const params = new URLSearchParams({
    client_id: env.GITHUB_CLIENT_ID,
    redirect_uri: redirectUri,
    scope: SCOPE,
    state,
    allow_signup: "true",
  });
  return `${GH.authorize}?${params.toString()}`;
}

/** Exchange a web-flow `code` for a short-lived GitHub access token. */
export async function exchangeCode(env, code) {
  const res = await outboundFetch(env)(GH.token, {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify({
      client_id: env.GITHUB_CLIENT_ID,
      client_secret: env.GITHUB_CLIENT_SECRET,
      code,
    }),
  });
  const data = await res.json();
  if (!data || !data.access_token) {
    throw new HttpError(
      401,
      "oauth_failed",
      data && data.error_description ? data.error_description : "GitHub token exchange failed",
      "Confirm the OAuth app client id/secret and callback URL.",
    );
  }
  return data.access_token;
}

/**
 * Read the authenticated GitHub user. Returns ONLY { uid, name } — email and
 * all other fields are deliberately dropped and never persisted.
 */
export async function fetchUser(env, accessToken) {
  const res = await outboundFetch(env)(GH.user, {
    headers: {
      Authorization: `Bearer ${accessToken}`,
      Accept: "application/vnd.github+json",
      "User-Agent": UA,
    },
  });
  const u = await res.json();
  if (!u || u.id == null) {
    throw new HttpError(401, "oauth_failed", "Could not read the GitHub user profile.");
  }
  return { uid: String(u.id), name: u.name || u.login || `gh-${u.id}` };
}

/** Start the device flow — returns the codes the CLI shows the user. */
export async function startDevice(env) {
  const res = await outboundFetch(env)(GH.deviceCode, {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify({ client_id: env.GITHUB_CLIENT_ID, scope: SCOPE }),
  });
  const data = await res.json();
  if (!data || !data.device_code) {
    throw new HttpError(502, "device_start_failed", "GitHub did not return a device code.");
  }
  return data; // { device_code, user_code, verification_uri, expires_in, interval }
}

/**
 * Poll the device flow.
 * @returns {{pending:true, slow_down?:boolean} | {pending:false, access_token:string}}
 */
export async function pollDevice(env, deviceCode) {
  const res = await outboundFetch(env)(GH.token, {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify({
      client_id: env.GITHUB_CLIENT_ID,
      device_code: deviceCode,
      grant_type: "urn:ietf:params:oauth:grant-type:device_code",
    }),
  });
  const data = await res.json();
  if (data.error === "authorization_pending") return { pending: true };
  if (data.error === "slow_down") return { pending: true, slow_down: true };
  if (!data.access_token) {
    throw new HttpError(
      400,
      "device_failed",
      data.error_description || data.error || "Device authorization failed.",
      "Restart sign-in with `learn auth login`.",
    );
  }
  return { pending: false, access_token: data.access_token };
}
