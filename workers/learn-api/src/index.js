// learn API — the thin Cloudflare Worker behind agentculture.org/learn.
//
// Faces it serves (all signed-in state + the tutoring broker; the static site
// and signed-out tour are served by Cloudflare Pages and never touch this
// Worker):
//   GET  /api/health            public   liveness
//   GET  /api/auth/login        public   web OAuth: redirect to GitHub
//   GET  /api/auth/callback     public   web OAuth: exchange code, set cookie
//   POST /api/auth/device       public   device flow start/poll (CLI/MCP, t12)
//   POST /api/auth/logout       auth     revoke the current session
//   GET  /api/me                auth     who am I + session expiry (auto-refresh)
//   GET  /api/progress/:subject auth     ledger-derived progress payload
//   POST /api/record            auth     append a recorded result to the ledger
//   POST /api/tutor             auth     broker -> env.INFERENCE_URL (model call)
//
// Resource-gate invariant: requireAuth() runs before the body of every auth
// route. POST /api/tutor is the only route that spends model tokens, and it is
// unreachable without a valid session — signed-out traffic can NEVER trigger a
// model call. Proven in worker.test.js.

import {
  HttpError,
  jsonResponse,
  redirect,
  parseCookies,
  cookie,
  outboundFetch,
} from "./util.js";
import { requireAuth } from "./auth.js";
import { issueSession, needsRefresh, DEFAULT_TTL_SECONDS } from "./session.js";
import {
  authorizeUrl,
  exchangeCode,
  fetchUser,
  startDevice,
  pollDevice,
} from "./github.js";
import { upsertLearner, getLearner, insertRecord, listRecords } from "./db.js";
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
  const redirectUri = `${publicOrigin(env, url)}/api/auth/callback`;
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

// --- auth routes -----------------------------------------------------------

async function handleLogout(request, env) {
  const session = await requireAuth(request, env);
  if (env.SESSIONS && session.sid) {
    // Tombstone until well past the token's own expiry.
    await env.SESSIONS.put(`revoked:${session.sid}`, "1", { expirationTtl: DEFAULT_TTL_SECONDS * 2 });
  }
  return jsonResponse(200, { ok: true }, { "Set-Cookie": cookie("session", "", { maxAge: 0 }) });
}

async function handleMe(request, env) {
  const session = await requireAuth(request, env);
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
  const session = await requireAuth(request, env);
  const rows = await listRecords(env, session.uid, subject);
  return jsonResponse(200, deriveProgress(subject, session.uid, rows));
}

async function handleRecord(request, env) {
  const session = await requireAuth(request, env);
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
  // AUTH FIRST — before any inference call. This ordering is the guarantee.
  const session = await requireAuth(request, env);
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

function publicOrigin(env, url) {
  return env.PUBLIC_URL ? env.PUBLIC_URL.replace(/\/+$/, "") : url.origin;
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
