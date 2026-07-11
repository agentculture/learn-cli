// Consent gate (spec c9/h1, decision c19; plan task t5).
//
// The load-bearing test here is the h1 pair: a FRESH sign-in — a GitHub user
// with no recorded consent — must cause ZERO D1 writes on BOTH sign-in paths
// (web /api/auth/callback and device-flow poll) until consent is accepted.
// The D1Stub logs every write statement into `db.writes`, so "zero writes"
// is asserted literally, not inferred from table sizes.
//
// Written red-first: against the pre-t5 Worker both h1 tests FAIL because
// handleCallback and handleDevice(poll) call upsertLearner unconditionally.

import { test } from "node:test";
import assert from "node:assert/strict";

import worker from "../src/index.js";
import { GH } from "../src/github.js";
import { TERMS_VERSION, TERMS_EFFECTIVE_DATE } from "../src/terms.js";
import {
  makeEnv,
  makeFetchStub,
  mintToken,
  authedRequest,
  jsonResp,
  seedConsent,
} from "./helpers.js";

const BASE = "https://learn-api.example";
const INFERENCE_URL = "https://inference.example/v1/messages";

function call(env, request) {
  return worker.fetch(request, env, { waitUntil() {} });
}

/** env whose GitHub endpoints authenticate `user` (fresh, unconsented). */
function envWithGitHubUser(user = { id: 900, login: "fresh", name: "Fresh" }, overrides = {}) {
  const fetchStub = makeFetchStub({
    [GH.token]: () => jsonResp({ access_token: "gho_x", token_type: "bearer" }),
    [GH.user]: () => jsonResp(user),
  });
  return makeEnv({ FETCH: fetchStub, APP_URL: "https://agentculture.org/learn/", ...overrides });
}

function webCallbackRequest() {
  return new Request(`${BASE}/api/auth/callback?code=abc&state=xyz`, {
    headers: { Cookie: "oauth_state=xyz" },
  });
}

function devicePollRequest() {
  return new Request(`${BASE}/api/auth/device`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "poll", device_code: "dc_123" }),
  });
}

// --- h1 verbatim: zero D1 writes before consent acceptance, BOTH paths -------

test("h1 web: fresh sign-in via /api/auth/callback writes ZERO D1 rows before consent", async () => {
  const env = envWithGitHubUser();
  const res = await call(env, webCallbackRequest());

  // The redirect flow stays intact — the user lands signed-in-pending.
  assert.equal(res.status, 302);

  // THE point: nothing was persisted. No learner row, no consent row, no
  // write statement of any kind.
  assert.equal(env.DB.writes.length, 0, `expected zero D1 writes, saw: ${JSON.stringify(env.DB.writes)}`);
  assert.equal(env.DB.learners.size, 0, "no learners row before consent");
  assert.equal(env.DB.consents.length, 0, "no consent row before acceptance");
  assert.equal(env.DB.records.length, 0);
});

test("h1 device: fresh sign-in via device poll writes ZERO D1 rows before consent", async () => {
  const env = envWithGitHubUser();
  const res = await call(env, devicePollRequest());
  assert.equal(res.status, 200);

  assert.equal(env.DB.writes.length, 0, `expected zero D1 writes, saw: ${JSON.stringify(env.DB.writes)}`);
  assert.equal(env.DB.learners.size, 0, "no learners row before consent");
  assert.equal(env.DB.consents.length, 0, "no consent row before acceptance");
  assert.equal(env.DB.records.length, 0);
});

// --- pending-consent session mechanics (c19) ---------------------------------

/** Extract the `session` cookie value from a response, or null. */
function sessionCookie(res) {
  const c = res.headers.getSetCookie().find((v) => v.startsWith("session="));
  return c ? decodeURIComponent(c.split(";")[0].slice("session=".length)) : null;
}

test("web: unconsented callback redirects to the consent page with a pending cookie", async () => {
  const env = envWithGitHubUser();
  const res = await call(env, webCallbackRequest());

  assert.equal(res.status, 302);
  assert.equal(res.headers.get("Location"), "https://agentculture.org/learn/consent/");
  const token = sessionCookie(res);
  assert.ok(token, "a pending session cookie is set");

  // The pending token authenticates against /api/me and reports the state.
  const me = await (await call(env, authedRequest(`${BASE}/api/me`, token))).json();
  assert.equal(me.authenticated, true);
  assert.equal(me.pending_consent, true);
  assert.equal(me.consent_required.terms_version, TERMS_VERSION);
  assert.equal(me.consent_required.effective_date, TERMS_EFFECTIVE_DATE);
  assert.equal(me.learner.github_user_id, "900");
});

test("device: unconsented poll returns status consent_required with a usable pending token", async () => {
  const env = envWithGitHubUser();
  const body = await (await call(env, devicePollRequest())).json();

  assert.equal(body.status, "consent_required");
  assert.ok(body.token, "the CLI gets a token to drive the consent endpoints");
  assert.equal(body.token_type, "Bearer");
  assert.ok(typeof body.expires_at === "number");
  assert.equal(body.consent_required.terms_version, TERMS_VERSION);
  assert.equal(body.learner.github_user_id, "900");
  assert.equal(env.DB.writes.length, 0, "still zero writes after the poll response");
});

test("pending session: /api/me reports pending_consent and never sliding-refreshes", async () => {
  const env = makeEnv();
  // ttl 60 — inside the refresh window, where a FULL session would re-issue.
  const { token } = await mintToken(env, { uid: "42", name: "Ada" }, 60, { pendingConsent: true });
  const res = await call(env, authedRequest(`${BASE}/api/me`, token));
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.pending_consent, true);
  assert.equal(body.session.refreshed, false);
  assert.equal(res.headers.getSetCookie().length, 0, "pending sessions are never refreshed");
});

test("pending session: progress, record, and tutor all 403 with consent_required", async () => {
  const fetchStub = makeFetchStub({ [INFERENCE_URL]: () => jsonResp({ reply: "never" }) });
  const env = makeEnv({ INFERENCE_URL, INFERENCE_TOKEN: "secret", FETCH: fetchStub });
  const { token } = await mintToken(env, { uid: "42", name: "Ada" }, 600, { pendingConsent: true });

  const progress = await call(env, authedRequest(`${BASE}/api/progress/french`, token));
  assert.equal(progress.status, 403);
  assert.equal((await progress.json()).error, "consent_required");

  const record = await call(
    env,
    authedRequest(`${BASE}/api/record`, token, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        subject: "french",
        recorded: { item_id: "x", activity: "practice", result: "pass", at: "2026-07-11T10:00:00Z" },
      }),
    }),
  );
  assert.equal(record.status, 403);
  assert.equal((await record.json()).error, "consent_required");

  const tutor = await call(
    env,
    authedRequest(`${BASE}/api/tutor`, token, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ subject: "french", messages: [] }),
    }),
  );
  assert.equal(tutor.status, 403);
  assert.equal((await tutor.json()).error, "consent_required");

  // The resource-gate invariant, extended one level: pending-consent traffic
  // never reaches inference and never writes.
  assert.equal(fetchStub.calls.length, 0, "inference endpoint must not be touched");
  assert.equal(env.DB.writes.length, 0, "no D1 write from a pending session");
});

test("pending session: logout is allowed and revokes the token", async () => {
  const env = makeEnv();
  const { token } = await mintToken(env, { uid: "42", name: "Ada" }, 600, { pendingConsent: true });
  const out = await call(env, authedRequest(`${BASE}/api/auth/logout`, token, { method: "POST" }));
  assert.equal(out.status, 200);
  assert.equal((await call(env, authedRequest(`${BASE}/api/me`, token))).status, 401);
  assert.equal(env.DB.writes.length, 0);
});

// --- GET /api/consent (the notice source) ------------------------------------

test("GET /api/consent is public and states the current requirement", async () => {
  const env = makeEnv();
  const res = await call(env, new Request(`${BASE}/api/consent`));
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.terms_version, TERMS_VERSION);
  assert.equal(body.effective_date, TERMS_EFFECTIVE_DATE);
  assert.equal(body.terms_url, "/learn/terms/");
  assert.equal(body.privacy_url, "/learn/privacy/");
});

// --- POST /api/consent/accept -------------------------------------------------

test("accept: records consent (exact TERMS_VERSION) THEN the learner, in that order", async () => {
  const env = makeEnv();
  const { token } = await mintToken(env, { uid: "42", name: "Ada" }, 600, { pendingConsent: true });

  const res = await call(env, authedRequest(`${BASE}/api/consent/accept`, token, { method: "POST" }));
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.status, "consented");
  assert.equal(body.consent.terms_version, TERMS_VERSION);
  assert.ok(body.consent.granted_at);
  assert.equal(body.learner.github_user_id, "42");

  // Write ORDER is the contract: the consent row exists before the learner row.
  assert.deepEqual(env.DB.writes, [
    { table: "consents", op: "insert" },
    { table: "learners", op: "insert" },
  ]);
  assert.equal(env.DB.consents[0].terms_version, TERMS_VERSION);
  assert.equal(env.DB.learners.get("42").display_name, "Ada");
});

test("accept: upgrades to a full session (body token + cookie) and revokes the pending one", async () => {
  const env = makeEnv();
  const { token: pendingTok } = await mintToken(env, { uid: "42", name: "Ada" }, 600, {
    pendingConsent: true,
  });

  const res = await call(
    env,
    authedRequest(`${BASE}/api/consent/accept`, pendingTok, { method: "POST" }),
  );
  const body = await res.json();
  assert.equal(body.token_type, "Bearer");
  assert.equal(sessionCookie(res), body.token, "cookie and body carry the same full token");

  // The full token opens the previously-403'd routes...
  const progress = await call(env, authedRequest(`${BASE}/api/progress/french`, body.token));
  assert.equal(progress.status, 200);
  const me = await (await call(env, authedRequest(`${BASE}/api/me`, body.token))).json();
  assert.equal(me.pending_consent, false);

  // ...and the superseded pending token is dead (KV tombstone).
  assert.equal((await call(env, authedRequest(`${BASE}/api/me`, pendingTok))).status, 401);
});

test("accept via web cookie works too (one issuer, two faces)", async () => {
  const env = makeEnv();
  const { token } = await mintToken(env, { uid: "7", name: "Web" }, 600, { pendingConsent: true });
  const res = await call(
    env,
    new Request(`${BASE}/api/consent/accept`, {
      method: "POST",
      headers: { Cookie: `session=${encodeURIComponent(token)}` },
    }),
  );
  assert.equal(res.status, 200);
  assert.ok(sessionCookie(res), "the upgraded session is set as a cookie");
  assert.equal(env.DB.learners.get("7").display_name, "Web");
});

test("accept is idempotent for an already-consented session (same version re-grant)", async () => {
  const env = makeEnv();
  seedConsent(env, "42", TERMS_VERSION, "2026-07-01T00:00:00Z");
  env.DB.learners.set("42", { github_user_id: "42", display_name: "Ada", state: "{}" });
  const { token } = await mintToken(env, { uid: "42", name: "Ada" }); // full session

  const res = await call(env, authedRequest(`${BASE}/api/consent/accept`, token, { method: "POST" }));
  assert.equal(res.status, 200);
  assert.equal(env.DB.consents.length, 1, "no duplicate consent row");
  assert.notEqual(env.DB.consents[0].granted_at, "2026-07-01T00:00:00Z", "granted_at refreshed");
});

test("accept requires a session (signed-out -> 401)", async () => {
  const env = makeEnv();
  const res = await call(env, new Request(`${BASE}/api/consent/accept`, { method: "POST" }));
  assert.equal(res.status, 401);
  assert.equal(env.DB.writes.length, 0);
});

// --- POST /api/consent/decline --------------------------------------------------

test("decline: drops the pending session with ZERO rows ever written", async () => {
  const env = makeEnv();
  const { token } = await mintToken(env, { uid: "42", name: "Ada" }, 600, { pendingConsent: true });

  const res = await call(env, authedRequest(`${BASE}/api/consent/decline`, token, { method: "POST" }));
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.status, "declined");
  assert.equal(body.stored, false);
  // The web cookie is cleared (empty value, Max-Age=0).
  assert.ok(
    res.headers.getSetCookie().some((c) => c.startsWith("session=;") && c.includes("Max-Age=0")),
    "session cookie cleared",
  );

  // Nothing was ever written, and the session is gone.
  assert.equal(env.DB.writes.length, 0, "decline leaves zero D1 writes");
  assert.equal(env.DB.learners.size, 0);
  assert.equal(env.DB.consents.length, 0);
  assert.equal((await call(env, authedRequest(`${BASE}/api/me`, token))).status, 401);
});

test("decline on a consented (full) session -> 409 already_consented", async () => {
  const env = makeEnv();
  seedConsent(env, "42", TERMS_VERSION);
  const { token } = await mintToken(env, { uid: "42", name: "Ada" }); // full session
  const res = await call(env, authedRequest(`${BASE}/api/consent/decline`, token, { method: "POST" }));
  assert.equal(res.status, 409);
  assert.equal((await res.json()).error, "already_consented");
});

// --- the full device round-trip ------------------------------------------------

test("device round-trip: poll -> consent_required -> accept -> full token records progress", async () => {
  const env = envWithGitHubUser({ id: 901, login: "roundtrip", name: "Round Trip" });

  const poll = await (await call(env, devicePollRequest())).json();
  assert.equal(poll.status, "consent_required");
  assert.equal(env.DB.writes.length, 0, "no write until the pending token accepts");

  const accept = await (
    await call(env, authedRequest(`${BASE}/api/consent/accept`, poll.token, { method: "POST" }))
  ).json();
  assert.equal(accept.status, "consented");

  const rec = await call(
    env,
    authedRequest(`${BASE}/api/record`, accept.token, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        subject: "french",
        recorded: { item_id: "n1", activity: "practice", result: "pass", at: "2026-07-11T10:00:00Z" },
      }),
    }),
  );
  assert.equal(rec.status, 201);
  assert.deepEqual(
    env.DB.writes.map((w) => w.table),
    ["consents", "learners", "records"],
    "consent is the first row that ever exists for the learner",
  );
});
