// learn API — the thin Cloudflare Worker behind agentculture.org/learn.
//
// Faces it serves (all signed-in state + the tutoring broker; the static site
// and signed-out tour are served by Cloudflare Pages and never touch this
// Worker):
//   GET  /api/health            public   liveness
//   GET  /api/auth/login        public   web OAuth: redirect to GitHub
//   GET  /api/auth/callback     public   web OAuth: exchange code, set cookie
//   POST /api/auth/device       public   device flow start/poll (CLI/MCP, t12)
//   GET  /api/consent           public   what consent is currently required
//   POST /api/consent/accept    auth*    record consent, THEN create the learner,
//                                        upgrade pending -> full session
//   POST /api/consent/decline   auth*    drop a pending session; zero rows written
//   POST /api/auth/logout       auth*    revoke the current session
//   GET  /api/me                auth*    who am I + session expiry (auto-refresh)
//   GET  /api/progress/:subject consent  ledger-derived progress payload
//   POST /api/record            consent  append a recorded result to the ledger
//   POST /api/tutor             consent  broker -> env.INFERENCE_URL (model call)
//
// auth*   = any valid session, INCLUDING pending-consent (requireAuth).
// consent = full session AND its stored consent still matches the currently
//           published terms version; pending-consent OR stale-version
//           sessions get a structured 403 (requireConsented) before the
//           route body runs.
//
// Resource-gate invariant: requireAuth()/requireConsented() runs before the
// body of every auth route. POST /api/tutor is the only route that spends
// model tokens, and it is unreachable without a valid, CURRENTLY-CONSENTED
// session — signed-out, pending-consent, AND stale-consent traffic can NEVER
// trigger a model call. Proven in worker.test.js + consent.test.js +
// reconsent.test.js.
//
// Consent-gate invariant (spec c9/h1, decision c19): NEITHER sign-in path
// (web callback, device poll) writes to D1 unless a recorded consent already
// satisfies the current terms. An unconsented sign-in gets a short-lived
// pending-consent session (see session.js) whose only capabilities are
// viewing the consent requirement and accepting/declining it. Accept records
// the consent row FIRST, then upserts the learner. Decline revokes the
// session with nothing ever written. Proven in consent.test.js.
//
// Re-consent invariant (spec c10/h2, task t6): "satisfies the current terms"
// means an EXACT terms_version match (consent.js#consentSatisfiesCurrentTerms)
// — a version bump makes a previously-consented learner's NEXT sign-in land
// pending-consent again (zero new D1 writes, same as a first-time sign-in),
// and makes requireConsented reject their EXISTING live full-session token
// with 403 consent_required until they re-accept via POST
// /api/consent/accept (which is reachable throughout, since it runs on
// requireAuth, not requireConsented). Proven in reconsent.test.js.

import {
  HttpError,
  jsonResponse,
  redirect,
  parseCookies,
  cookie,
  outboundFetch,
} from "./util.js";
import { requireAuth, requireConsented } from "./auth.js";
import {
  issueSession,
  needsRefresh,
  isPendingConsent,
  DEFAULT_TTL_SECONDS,
  PENDING_CONSENT_TTL_SECONDS,
} from "./session.js";
import {
  consentSatisfiesCurrentTerms,
  consentRequirement,
  currentTermsVersion,
} from "./consent.js";
import {
  authorizeUrl,
  exchangeCode,
  fetchUser,
  startDevice,
  pollDevice,
} from "./github.js";
import {
  upsertLearner,
  getLearner,
  insertRecord,
  listRecords,
  getConsent,
  recordConsent,
} from "./db.js";
import { deriveProgress } from "./progress.js";
import {
  CONTRACT_VERSION,
  validateSubject,
  validateRecorded,
  inferMastery,
} from "./validate.js";

export default {
  async fetch(request, env, ctx) {
    try {
      if (request.method === "OPTIONS") return withCors(env, request, new Response(null, { status: 204 }));
      const response = await route(request, env, ctx);
      return withCors(env, request, response);
    } catch (err) {
      const response =
        err instanceof HttpError
          ? err.toResponse()
          : jsonResponse(500, { error: "internal", message: "Unexpected error", hint: "" });
      return withCors(env, request, response);
    }
  },
};

async function route(request, env, ctx) {
  const url = new URL(request.url);
  let path = url.pathname.replace(/\/+$/, "") || "/";
  const method = request.method;

  // Zone mount: Cloudflare Pages can't be mounted at a path, so the zone
  // route agentculture.org/learn/* lands here. API calls arrive as
  // /learn/api/* (normalize the prefix away); anything else under /learn
  // proxies to the static Pages origin, which serves the site under /learn/
  // too (the deploy wraps dist/ in a /learn/ directory).
  if (path === "/learn" || path.startsWith("/learn/")) {
    if (path.startsWith("/learn/api")) {
      path = path.slice("/learn".length);
    } else {
      return proxyToPages(request, env, url);
    }
  }

  if (method === "GET" && path === "/api/health") return handleHealth(env);
  if (method === "GET" && path === "/api/auth/login") return handleLogin(request, env);
  if (method === "GET" && path === "/api/auth/callback") return handleCallback(request, env);
  if (method === "POST" && path === "/api/auth/device") return handleDevice(request, env);
  if (method === "GET" && path === "/api/consent") return handleConsentGet(env);
  if (method === "POST" && path === "/api/consent/accept") return handleConsentAccept(request, env);
  if (method === "POST" && path === "/api/consent/decline") return handleConsentDecline(request, env);
  if (method === "POST" && path === "/api/auth/logout") return handleLogout(request, env);
  if (method === "GET" && path === "/api/me") return handleMe(request, env);
  if (method === "POST" && path === "/api/record") return handleRecord(request, env);
  if (method === "POST" && path === "/api/tutor") return handleTutor(request, env, ctx);

  const progressMatch = /^\/api\/progress\/([a-z][a-z0-9-]*)$/.exec(path);
  if (method === "GET" && progressMatch) return handleProgress(request, env, progressMatch[1]);

  throw new HttpError(404, "not_found", `No route for ${method} ${path}`, "");
}

// --- static-site proxy (the /learn zone mount) ------------------------------

async function proxyToPages(request, env, url) {
  if (request.method !== "GET" && request.method !== "HEAD") {
    throw new HttpError(405, "method_not_allowed", "The learn site is read-only", "");
  }
  requireConfig(env, "PAGES_ORIGIN");
  const origin = env.PAGES_ORIGIN.replace(/\/+$/, "");
  const upstream = origin + url.pathname + url.search;
  // Never forward credentials to the static origin: the session cookie (and
  // any Authorization header) is for this API only — the Pages origin serves
  // public files and must not see learner sessions.
  const headers = new Headers(request.headers);
  headers.delete("Cookie");
  headers.delete("Authorization");
  return fetch(new Request(upstream, { method: request.method, headers }));
}

// --- public routes ---------------------------------------------------------

function handleHealth(env) {
  return jsonResponse(200, {
    ok: true,
    service: "learn-api",
    contract_version: CONTRACT_VERSION,
    time: new Date().toISOString(),
  });
}

function handleLogin(request, env) {
  requireConfig(env, "GITHUB_CLIENT_ID");
  const url = new URL(request.url);
  const redirectUri = callbackUrl(env, url);
  const state = crypto.randomUUID();
  return redirect(authorizeUrl(env, redirectUri, state), {
    "Set-Cookie": cookie("oauth_state", state, { maxAge: 600, sameSite: "Lax" }),
  });
}

async function handleCallback(request, env) {
  requireConfig(env, "GITHUB_CLIENT_ID");
  requireConfig(env, "GITHUB_CLIENT_SECRET");
  const url = new URL(request.url);
  const code = url.searchParams.get("code");
  const state = url.searchParams.get("state");
  const cookies = parseCookies(request);
  if (!code) throw new HttpError(400, "missing_code", "No OAuth code in callback.");
  if (!state || state !== cookies.oauth_state) {
    throw new HttpError(400, "bad_state", "OAuth state mismatch — possible CSRF.");
  }
  const accessToken = await exchangeCode(env, code);
  const user = await fetchUser(env, accessToken);

  // CONSENT GATE (spec c9/c19): no satisfying consent -> NO D1 write. The
  // OAuth redirect flow stays intact — the user lands signed-in-PENDING on
  // the consent page with a short-lived pending-consent cookie; the learner
  // row is only created by POST /api/consent/accept.
  const consent = await getConsent(env, user.uid);
  if (!consentSatisfiesCurrentTerms(consent, env)) {
    const { token } = await issueSession(env, user, PENDING_CONSENT_TTL_SECONDS, {
      pendingConsent: true,
    });
    const headers = new Headers({ Location: consentPageUrl(env, url) });
    headers.append("Set-Cookie", cookie("session", token, { maxAge: PENDING_CONSENT_TTL_SECONDS }));
    headers.append("Set-Cookie", cookie("oauth_state", "", { maxAge: 0 }));
    return new Response(null, { status: 302, headers });
  }

  await upsertLearner(env, user);
  const { token } = await issueSession(env, user);
  const dest = env.APP_URL || `${publicOrigin(env, url)}/learn/`;
  const headers = new Headers({ Location: dest });
  headers.append("Set-Cookie", cookie("session", token, { maxAge: DEFAULT_TTL_SECONDS }));
  // Clear the one-shot state cookie.
  headers.append("Set-Cookie", cookie("oauth_state", "", { maxAge: 0 }));
  return new Response(null, { status: 302, headers });
}

async function handleDevice(request, env) {
  requireConfig(env, "GITHUB_CLIENT_ID");
  const body = await readJson(request);
  const action = body.action;
  if (action === "start") {
    const d = await startDevice(env);
    return jsonResponse(200, {
      device_code: d.device_code,
      user_code: d.user_code,
      verification_uri: d.verification_uri,
      expires_in: d.expires_in,
      interval: d.interval,
    });
  }
  if (action === "poll") {
    if (!body.device_code) throw new HttpError(400, "missing_device_code", "device_code required.");
    const r = await pollDevice(env, body.device_code);
    if (r.pending) return jsonResponse(200, { status: "pending", slow_down: !!r.slow_down });
    const user = await fetchUser(env, r.access_token);

    // CONSENT GATE (spec c9/c19), device face: same rule as the web callback —
    // no satisfying consent, no D1 write. The CLI gets a pending-consent
    // Bearer token plus the consent requirement so it can prompt; it then
    // drives POST /api/consent/accept (returns the full token) or /decline.
    const consent = await getConsent(env, user.uid);
    if (!consentSatisfiesCurrentTerms(consent, env)) {
      const { token, payload } = await issueSession(env, user, PENDING_CONSENT_TTL_SECONDS, {
        pendingConsent: true,
      });
      return jsonResponse(200, {
        status: "consent_required",
        token,
        token_type: "Bearer",
        expires_at: payload.exp,
        consent_required: consentRequirement(env),
        learner: { github_user_id: user.uid, display_name: user.name },
      });
    }

    await upsertLearner(env, user);
    const { token, payload } = await issueSession(env, user);
    return jsonResponse(200, {
      status: "complete",
      token,
      token_type: "Bearer",
      expires_at: payload.exp,
      learner: { github_user_id: user.uid, display_name: user.name },
    });
  }
  throw new HttpError(400, "bad_action", "action must be 'start' or 'poll'.");
}

// --- consent routes (spec c9/c19, task t5) ----------------------------------

// What consent is currently required. Public: the consent page (and any CLI)
// can render the notice — version, effective date, policy links — without a
// session; a signed-out reader learns nothing personal here.
function handleConsentGet(env) {
  return jsonResponse(200, consentRequirement(env));
}

// Accept the current terms. Order is the contract (spec c9): the consent row
// is recorded FIRST (the consents table has no FK to learners precisely so it
// can exist alone), and only THEN is the learner row created. The pending
// session is revoked and a full session issued — returned BOTH as a
// `Set-Cookie` (web) and in the JSON body as a Bearer token (device/CLI), so
// the two faces stay symmetric with the sign-in paths.
// Idempotent for an already-consented session: same-version re-accept just
// refreshes granted_at (db.js recordConsent upserts).
// t6 (spec c10/h2): this is ALSO the re-consent route. It deliberately runs
// through requireAuth, not requireConsented — a full session whose stored
// consent has gone stale must still be able to reach this route to fix
// that, even though every requireConsented-gated route now rejects it.
// currentTermsVersion(env), never a bare TERMS_VERSION import, so a
// published bump is what gets stamped on re-accept.
async function handleConsentAccept(request, env) {
  const session = await requireAuth(request, env); // pending-consent allowed — that's the point.
  const consent = await recordConsent(env, session.uid, currentTermsVersion(env));
  await upsertLearner(env, { uid: session.uid, name: session.name });
  await revokeSession(env, session); // the pending (or prior) token dies with the upgrade
  const { token, payload } = await issueSession(env, { uid: session.uid, name: session.name });
  return jsonResponse(
    200,
    {
      ok: true,
      status: "consented",
      consent: { terms_version: consent.terms_version, granted_at: consent.granted_at },
      token,
      token_type: "Bearer",
      expires_at: payload.exp,
      learner: { github_user_id: session.uid, display_name: session.name },
    },
    { "Set-Cookie": cookie("session", token, { maxAge: DEFAULT_TTL_SECONDS }) },
  );
}

// Decline the current terms. Pending sessions only: the session is revoked,
// the cookie cleared, and — because the sign-in paths wrote nothing — there is
// nothing to erase. A FULL session declining is a different act (consent
// withdrawal = data deletion, spec c11/t7), so it is refused here rather than
// silently half-handled.
async function handleConsentDecline(request, env) {
  const session = await requireAuth(request, env);
  if (!isPendingConsent(session)) {
    throw new HttpError(
      409,
      "already_consented",
      "This session already carries recorded consent; decline applies only before accepting.",
      "To withdraw consent (which deletes your stored data), use the self-serve delete flow.",
    );
  }
  await revokeSession(env, session);
  return jsonResponse(
    200,
    { ok: true, status: "declined", stored: false },
    { "Set-Cookie": cookie("session", "", { maxAge: 0 }) },
  );
}

// --- auth routes -----------------------------------------------------------

async function handleLogout(request, env) {
  const session = await requireAuth(request, env); // pending-consent sessions may log out too
  await revokeSession(env, session);
  return jsonResponse(200, { ok: true }, { "Set-Cookie": cookie("session", "", { maxAge: 0 }) });
}

async function handleMe(request, env) {
  const session = await requireAuth(request, env);

  // Pending-consent session (c19): report the state + what must be consented
  // to. No D1 read (no learner row exists), no sliding refresh — a pending
  // session stays short-lived and either upgrades via accept or expires.
  if (isPendingConsent(session)) {
    return jsonResponse(200, {
      authenticated: true,
      pending_consent: true,
      consent_required: consentRequirement(env),
      learner: { github_user_id: session.uid, display_name: session.name },
      session: { expires_at: session.exp, refreshed: false },
    });
  }

  // t6 (spec c10/h2, AC4): a full session never 403s at /api/me — unlike
  // requireConsented-gated routes, this one REPORTS the re-consent
  // requirement instead of walling the learner out of their own identity
  // check. Additive only: `reconsent_required` is a NEW field (false in the
  // common case); `consent_required` is included ONLY when it's true,
  // mirroring the pending-session shape above so a client renders the same
  // notice component either way. One extra D1 read (`getConsent`) alongside
  // the existing `getLearner` read — see README "Storage" for the tradeoff.
  const consent = await getConsent(env, session.uid);
  const reconsentRequired = !consentSatisfiesCurrentTerms(consent, env);

  const learner = (await getLearner(env, session.uid)) || {
    github_user_id: session.uid,
    display_name: session.name,
  };
  const headers = {};
  // Sliding-window refresh: re-issue a cookie when the session is nearly stale.
  if (needsRefresh(session)) {
    const { token } = await issueSession(env, { uid: session.uid, name: session.name });
    headers["Set-Cookie"] = cookie("session", token, { maxAge: DEFAULT_TTL_SECONDS });
  }
  return jsonResponse(
    200,
    {
      authenticated: true,
      pending_consent: false,
      reconsent_required: reconsentRequired,
      ...(reconsentRequired ? { consent_required: consentRequirement(env) } : {}),
      learner: {
        github_user_id: learner.github_user_id,
        display_name: learner.display_name,
      },
      session: { expires_at: session.exp, refreshed: !!headers["Set-Cookie"] },
    },
    headers,
  );
}

async function handleProgress(request, env, subject) {
  const session = await requireConsented(request, env);
  const rows = await listRecords(env, session.uid, subject);
  return jsonResponse(200, deriveProgress(subject, session.uid, rows));
}

async function handleRecord(request, env) {
  const session = await requireConsented(request, env);
  const body = await readJson(request);
  const subject = body.subject;
  const recorded = body.recorded;

  const errors = [...validateSubject(subject), ...validateRecorded(recorded)];
  if (errors.length) {
    throw new HttpError(400, "invalid_record", `Invalid record: ${errors.join("; ")}`, "");
  }

  // Mastery: honor an explicit level if valid, else infer from the raw result.
  const masteryLevel =
    body.mastery && typeof body.mastery.level === "string"
      ? body.mastery.level
      : inferMastery(recorded.result);

  const ledgerId = await insertRecord(env, {
    uid: session.uid,
    subject,
    recorded,
    masteryLevel,
  });

  // A record_ack-shaped response (record.json). The authoritative within-subject
  // `next` comes from the subject CLI; the API returns a neutral pointer.
  return jsonResponse(201, {
    schema_version: CONTRACT_VERSION,
    kind: "record_ack",
    subject,
    learner: String(session.uid),
    recorded,
    mastery: { item_id: recorded.item_id, level: masteryLevel },
    next: {
      done: false,
      text: "Recorded to your cross-subject ledger.",
      command: `learn progress ${subject}`,
    },
    ledger_id: ledgerId,
  });
}

async function handleTutor(request, env, ctx) {
  // AUTH + CONSENT FIRST — before any inference call. This ordering is the
  // guarantee: neither signed-out nor pending-consent traffic reaches the
  // model endpoint.
  const session = await requireConsented(request, env);
  if (!env.INFERENCE_URL) {
    throw new HttpError(
      503,
      "no_inference",
      "Tutoring broker is not configured.",
      "Set INFERENCE_URL to the cloudai-cli / ec2bedrock-cli served endpoint.",
    );
  }
  const payload = await readJson(request);
  const upstream = await outboundFetch(env)(env.INFERENCE_URL, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(env.INFERENCE_TOKEN ? { Authorization: `Bearer ${env.INFERENCE_TOKEN}` } : {}),
    },
    // Stamp the learner so the served endpoint can attribute usage; the broker
    // adds NO provider-specific fields — it forwards to a served OpenAI-shaped
    // endpoint, never a bespoke provider SDK.
    body: JSON.stringify({ ...payload, learner: String(session.uid) }),
  });
  const data = await upstream.json().catch(() => ({}));
  return jsonResponse(upstream.status, data);
}

// --- helpers ---------------------------------------------------------------

function requireConfig(env, key) {
  if (!env[key]) {
    throw new HttpError(503, "not_configured", `${key} is not configured on this Worker.`, "");
  }
}

// Tombstone a session id in KV until well past the token's own expiry.
// Shared by logout, consent decline (drop the pending session), and consent
// accept (the superseded pending token must not outlive its upgrade).
async function revokeSession(env, session) {
  if (env.SESSIONS && session.sid) {
    await env.SESSIONS.put(`revoked:${session.sid}`, "1", {
      expirationTtl: DEFAULT_TTL_SECONDS * 2,
    });
  }
}

// Where an unconsented web sign-in lands: the consent notice page (t10),
// served by the static site under the /learn mount.
function consentPageUrl(env, url) {
  const base = (env.APP_URL || `${publicOrigin(env, url)}/learn/`).replace(/\/+$/, "");
  return `${base}/consent/`;
}

function publicOrigin(env, url) {
  return env.PUBLIC_URL ? env.PUBLIC_URL.replace(/\/+$/, "") : url.origin;
}

// The GitHub OAuth callback URL. It MUST carry the /learn zone-mount prefix so
// it (a) matches the GitHub app's registered callback and (b) routes back to
// THIS worker (agentculture.org/learn/*) rather than org's Pages site at the
// bare origin. APP_URL is the mount root (".../learn/") and the callback lives
// under it; fall back to origin + /learn/ when APP_URL is unset (local/dev).
function callbackUrl(env, url) {
  const base = (env.APP_URL || `${publicOrigin(env, url)}/learn/`).replace(/\/+$/, "");
  return `${base}/api/auth/callback`;
}

async function readJson(request) {
  try {
    return await request.json();
  } catch {
    throw new HttpError(400, "bad_json", "Request body must be valid JSON.", "");
  }
}

function withCors(env, request, response) {
  const origin = env.CORS_ORIGIN;
  if (!origin) return response;
  const reqOrigin = request.headers.get("Origin");
  // Reflect the configured origin (supports a comma-separated allowlist).
  const allowed = origin.split(",").map((s) => s.trim());
  const allow = reqOrigin && allowed.includes(reqOrigin) ? reqOrigin : allowed[0];
  const headers = new Headers(response.headers);
  headers.set("Access-Control-Allow-Origin", allow);
  headers.set("Access-Control-Allow-Credentials", "true");
  headers.set("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  headers.set("Access-Control-Allow-Headers", "Content-Type, Authorization");
  headers.append("Vary", "Origin");
  return new Response(response.body, { status: response.status, headers });
}
