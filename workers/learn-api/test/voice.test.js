// The voice-token mint (spec c15/h7, task t16).
//
// POST /api/voice/token is the learn-api half of the voice approval gate: the
// serverless bridge (infra/voice_bridge/) only upgrades a WebSocket for a
// token THIS route minted, and this route only mints for a learner who passes
// the SAME two learner-side gates as /api/tutor — requireConsented, then the
// approvedOf() check — so h7 ("no audio byte reaches Bedrock for a session
// that is not both authenticated AND approved") holds at BOTH ends: the
// bridge verifies at $connect (tests/test_voice_bridge_handler.py), and an
// unapproved learner can never obtain a token to present there (this file).
//
// Token format is pinned byte-for-byte against infra/voice_bridge/tokens.py:
// the fixture values below (SECRET/NOW/uid/ttl) mirror
// tests/test_voice_bridge_tokens.py, and the committed cross-language fixture
// (tests/fixtures/voice_token_cross_language.json) is asserted to be exactly
// what src/voice.js mints — the Python side verifies the same file, so the
// two implementations cannot drift without a test going red on one side.
//
// The per-learner monthly budget (t4 handoff #3: "a per-learner monthly
// allowance belongs in learn-api where approval lives") caps MINTED
// session-seconds in learners.state.voice_usage — honest scope: intent, not
// actual streamed seconds (see README).

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import worker from "../src/index.js";
import { TERMS_VERSION } from "../src/terms.js";
import { getLearner } from "../src/db.js";
import { hmacSign, b64urlToStr } from "../src/util.js";
import {
  mintVoiceToken,
  VOICE_TOKEN_TTL_SECONDS,
  DEFAULT_VOICE_MAX_SESSION_SECONDS,
  DEFAULT_VOICE_MONTHLY_SECONDS_CAP,
} from "../src/voice.js";
import { makeEnv, mintToken, authedRequest, seedConsent } from "./helpers.js";

const BASE = "https://learn-api.example";
const BRIDGE_URL = "wss://voice-bridge.example/prod";
const VOICE_SECRET = "spike-shared-secret";

function call(env, request) {
  return worker.fetch(request, env, { waitUntil() {} });
}

function seedLearner(env, uid, name, state = {}) {
  env.DB.learners.set(String(uid), {
    github_user_id: String(uid),
    display_name: name,
    state: JSON.stringify(state),
  });
}

function voiceReq(token) {
  const init = { method: "POST" };
  if (!token) return new Request(`${BASE}/api/voice/token`, init);
  return authedRequest(`${BASE}/api/voice/token`, token, init);
}

/** An env with the bridge fully configured and one approved+consented learner. */
async function voiceEnv(overrides = {}) {
  const env = makeEnv({
    VOICE_BRIDGE_URL: BRIDGE_URL,
    VOICE_TOKEN_SECRET: VOICE_SECRET,
    ...overrides,
  });
  seedConsent(env, "42", overrides.TERMS_VERSION_OVERRIDE || TERMS_VERSION);
  seedLearner(env, "42", "Ada", { approved: true });
  const { token } = await mintToken(env, { uid: "42", name: "Ada" });
  return { env, token };
}

function decodePayload(voiceToken) {
  return JSON.parse(b64urlToStr(voiceToken.split(".")[0]));
}

// --- h7: the gate ordering, both failure levels below "approved" -------------

test("h7: signed-out POST /api/voice/token -> 401, NO token", async () => {
  const { env } = await voiceEnv();
  const res = await call(env, voiceReq());
  assert.equal(res.status, 401);
  const body = await res.json();
  assert.equal(body.error, "not_authenticated");
  assert.equal("token" in body, false, "a 401 body must never carry a token");
});

test("h7: pending-consent session -> 403 consent_required, NO token", async () => {
  const { env } = await voiceEnv();
  const { token } = await mintToken(env, { uid: "7", name: "Eve" }, 600, {
    pendingConsent: true,
  });
  const res = await call(env, voiceReq(token));
  assert.equal(res.status, 403);
  const body = await res.json();
  assert.equal(body.error, "consent_required");
  assert.equal(body.reason, "pending");
  assert.equal("token" in body, false);
});

test("h7: consented but NOT approved -> 403 approval_required, NO token — even fully configured", async () => {
  const { env } = await voiceEnv();
  seedConsent(env, "99", TERMS_VERSION);
  seedLearner(env, "99", "Linus"); // consented learner row, NO approved key
  const { token } = await mintToken(env, { uid: "99", name: "Linus" });
  const res = await call(env, voiceReq(token));
  assert.equal(res.status, 403);
  const body = await res.json();
  assert.equal(body.error, "approval_required");
  assert.equal("token" in body, false);
});

test("approval check runs BEFORE the config 503 — an unapproved learner can't probe bridge config", async () => {
  // Same ordering guarantee as handleTutor: no VOICE_BRIDGE_URL at all, and
  // an unapproved learner still gets 403, never the 503 not_configured.
  const env = makeEnv();
  seedConsent(env, "99", TERMS_VERSION);
  seedLearner(env, "99", "Linus");
  const { token } = await mintToken(env, { uid: "99", name: "Linus" });
  const res = await call(env, voiceReq(token));
  assert.equal(res.status, 403);
  assert.equal((await res.json()).error, "approval_required");
});

test("stale consent walls off the mint even for an APPROVED learner (both gates independent)", async () => {
  const BUMPED = "2.0.0";
  const { env, token } = await voiceEnv({ TERMS_VERSION_OVERRIDE: BUMPED });
  // voiceEnv seeded consent for the OVERRIDE version; replace with a stale one.
  env.DB.consents.length = 0;
  seedConsent(env, "42", TERMS_VERSION); // superseded — the published version moved on
  const res = await call(env, voiceReq(token));
  assert.equal(res.status, 403);
  const body = await res.json();
  assert.equal(body.error, "consent_required");
  assert.equal(body.reason, "stale_version");
  assert.equal("token" in body, false);
});

test("revoke takes effect on the very next mint — the gate reads the learner row per request", async () => {
  const { env, token } = await voiceEnv();
  assert.equal((await call(env, voiceReq(token))).status, 200);
  // Admin revokes (state key deleted, db.js#setLearnerApproved semantics).
  seedLearner(env, "42", "Ada", {});
  const res = await call(env, voiceReq(token));
  assert.equal(res.status, 403);
  assert.equal((await res.json()).error, "approval_required");
});

// --- config gating: 503 not_configured, mirroring INFERENCE_URL -------------

test("no VOICE_BRIDGE_URL -> 503 not_configured for an approved learner, NO token", async () => {
  const { env, token } = await voiceEnv({ VOICE_BRIDGE_URL: undefined });
  const res = await call(env, voiceReq(token));
  assert.equal(res.status, 503);
  const body = await res.json();
  assert.equal(body.error, "not_configured");
  assert.equal("token" in body, false);
});

test("no VOICE_TOKEN_SECRET -> 503 not_configured for an approved learner, NO token", async () => {
  const { env, token } = await voiceEnv({ VOICE_TOKEN_SECRET: undefined });
  const res = await call(env, voiceReq(token));
  assert.equal(res.status, 503);
  assert.equal((await res.json()).error, "not_configured");
});

// --- the happy path: token contract pinned to infra/voice_bridge/tokens.py ---

test("approved + consented mint: token, wss_url, expires_at, limits — the t16 response shape", async () => {
  const { env, token } = await voiceEnv();
  const res = await call(env, voiceReq(token));
  assert.equal(res.status, 200);
  const body = await res.json();

  // wss_url is the configured bridge plus the token as ?token= (t4 handoff #1).
  assert.equal(body.wss_url, `${BRIDGE_URL}?token=${body.token}`);

  // Two unpadded base64url segments, signature = HMAC-SHA256 over the body
  // STRING — exactly what tokens.py's _sign computes and session.js produces.
  assert.equal(body.token.includes("="), false, "segments must be unpadded");
  const [payloadB64, sig] = body.token.split(".");
  assert.equal(sig, await hmacSign(VOICE_SECRET, payloadB64));

  // The exact claim set tokens.py pins (test_token_format_is_symmetric_with_session_js).
  const payload = decodePayload(body.token);
  assert.deepEqual(
    Object.keys(payload).sort(),
    ["approved", "exp", "iat", "scope", "sid", "uid"].concat(["v"]).sort(),
  );
  assert.equal(payload.v, 1);
  assert.equal(payload.scope, "voice");
  assert.equal(payload.uid, "42");
  assert.equal(payload.approved, true);
  assert.equal(payload.exp - payload.iat, VOICE_TOKEN_TTL_SECONDS);
  assert.equal(body.expires_at, payload.exp);

  // limits: what the client renders and the budget books against.
  assert.equal(body.limits.max_session_seconds, DEFAULT_VOICE_MAX_SESSION_SECONDS);
  assert.equal(body.limits.monthly_seconds_cap, DEFAULT_VOICE_MONTHLY_SECONDS_CAP);
  assert.equal(body.limits.monthly_seconds_used, DEFAULT_VOICE_MAX_SESSION_SECONDS);
  assert.equal(
    body.limits.monthly_seconds_remaining,
    DEFAULT_VOICE_MONTHLY_SECONDS_CAP - DEFAULT_VOICE_MAX_SESSION_SECONDS,
  );
});

test("cross-language pin: src/voice.js reproduces the committed fixture token byte-for-byte", async () => {
  // tests/fixtures/voice_token_cross_language.json is verified by the Python
  // side (tests/test_voice_token_cross_language.py) with tokens.py's
  // verify_voice_token; this test proves the JS minter still produces that
  // exact string, so the fixture pins BOTH implementations to one format.
  const fixture = JSON.parse(
    readFileSync(
      new URL("../../../tests/fixtures/voice_token_cross_language.json", import.meta.url),
      "utf8",
    ),
  );
  const { token } = await mintVoiceToken({ VOICE_TOKEN_SECRET: fixture.secret }, fixture.uid, {
    now: fixture.now,
    ttlSeconds: fixture.ttl_seconds,
    sid: fixture.sid,
  });
  assert.equal(token, fixture.token);
});

// --- the per-learner monthly budget (t4 handoff #3) --------------------------

test("budget: each mint books max_session_seconds; the mint that would exceed the cap 429s, NO token", async () => {
  const { env, token } = await voiceEnv();
  // Default cap 1800, booking 300 per mint -> exactly 6 mints fit.
  for (let i = 1; i <= 6; i += 1) {
    const res = await call(env, voiceReq(token));
    assert.equal(res.status, 200, `mint ${i} of 6 must succeed`);
    const body = await res.json();
    assert.equal(body.limits.monthly_seconds_used, i * DEFAULT_VOICE_MAX_SESSION_SECONDS);
  }
  const res = await call(env, voiceReq(token));
  assert.equal(res.status, 429);
  const body = await res.json();
  assert.equal(body.error, "voice_budget_exhausted");
  assert.equal("token" in body, false);
  assert.equal(body.monthly_seconds_cap, DEFAULT_VOICE_MONTHLY_SECONDS_CAP);
  assert.equal(body.monthly_seconds_used, DEFAULT_VOICE_MONTHLY_SECONDS_CAP);
  // The refused mint books nothing: usage stays exactly at the cap.
  const ada = await getLearner(env, "42");
  assert.equal(ada.state.voice_usage.seconds_minted, DEFAULT_VOICE_MONTHLY_SECONDS_CAP);
});

test("budget: VOICE_MONTHLY_SECONDS_CAP is an env var — cap 300 means exactly one session a month", async () => {
  const { env, token } = await voiceEnv({ VOICE_MONTHLY_SECONDS_CAP: "300" });
  assert.equal((await call(env, voiceReq(token))).status, 200);
  const res = await call(env, voiceReq(token));
  assert.equal(res.status, 429);
  assert.equal((await res.json()).error, "voice_budget_exhausted");
});

test("budget: a partial month that cannot fit one more FULL session is refused (no overshoot)", async () => {
  const { env, token } = await voiceEnv();
  const month = new Date().toISOString().slice(0, 7);
  seedLearner(env, "42", "Ada", {
    approved: true,
    voice_usage: { month, seconds_minted: 1600 }, // 200 left < 300 booking
  });
  const res = await call(env, voiceReq(token));
  assert.equal(res.status, 429);
  const ada = await getLearner(env, "42");
  assert.equal(ada.state.voice_usage.seconds_minted, 1600, "a refused mint books nothing");
});

test("budget: month rollover resets the meter — last month's exhaustion doesn't carry over", async () => {
  const { env, token } = await voiceEnv();
  seedLearner(env, "42", "Ada", {
    approved: true,
    voice_usage: { month: "2026-01", seconds_minted: 1800 }, // exhausted, long ago
  });
  const res = await call(env, voiceReq(token));
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.limits.monthly_seconds_used, DEFAULT_VOICE_MAX_SESSION_SECONDS);
  const ada = await getLearner(env, "42");
  assert.equal(ada.state.voice_usage.month, new Date().toISOString().slice(0, 7));
  assert.equal(ada.state.voice_usage.seconds_minted, DEFAULT_VOICE_MAX_SESSION_SECONDS);
});

test("budget bookkeeping merges into state — approved/visibility survive the usage write", async () => {
  const { env, token } = await voiceEnv();
  seedLearner(env, "42", "Ada", { approved: true, visibility: "public", other_pref: "keep" });
  assert.equal((await call(env, voiceReq(token))).status, 200);
  const ada = await getLearner(env, "42");
  assert.equal(ada.state.approved, true);
  assert.equal(ada.state.visibility, "public");
  assert.equal(ada.state.other_pref, "keep");
  assert.equal(typeof ada.state.voice_usage, "object");
});
