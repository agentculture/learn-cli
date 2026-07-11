// Unit tests for src/auth.js#requireAuth's per-uid revocation marker
// (Qodo review finding, BUG 1): POST /api/delete must invalidate EVERY
// session for a uid, not just the one that called it. Exercised directly
// against the KV stub with a controlled `iat` (via session.js#issueSession's
// `opts.now`, mirroring voice.js#mintVoiceToken's own test-only override) so
// the reject/keep boundary is deterministic — no dependency on real
// wall-clock timing between two mints, unlike the higher-level, full-route
// scenarios in test/export-delete.test.js.

import { test } from "node:test";
import assert from "node:assert/strict";

import { requireAuth } from "../src/auth.js";
import { issueSession } from "../src/session.js";
import { nowSeconds } from "../src/util.js";
import { makeEnv, authedRequest } from "./helpers.js";

const BASE = "https://learn-api.example";
// A fixed anchor near "now" so `exp = iat + ttl` never lands in the past —
// verifySession would 401 a token whose `exp` has already elapsed, so every
// `iat` used below is offset from THIS, not from an arbitrary small epoch.
const NOW = nowSeconds();

async function tokenAt(env, uid, iatOffset) {
  const { token } = await issueSession(env, { uid, name: "Ada" }, 3600, { now: NOW + iatOffset });
  return token;
}

test("requireAuth: a token issued BEFORE a uid's revoked_uid marker is rejected", async () => {
  const env = makeEnv();
  const token = await tokenAt(env, "42", -100);
  await env.SESSIONS.put("revoked_uid:42", String(NOW - 50));
  await assert.rejects(
    () => requireAuth(authedRequest(`${BASE}/api/me`, token), env),
    (err) => err.status === 401 && err.code === "session_revoked",
  );
});

test("requireAuth: a token issued AT the same epoch second as the marker is NOT rejected", async () => {
  // Boundary case: iat === revoked epoch must resolve in favor of the token
  // — this is what keeps a resignup landing in the exact same wall-clock
  // second as a prior delete working (see auth.js's own comment).
  const env = makeEnv();
  const token = await tokenAt(env, "42", -50);
  await env.SESSIONS.put("revoked_uid:42", String(NOW - 50));
  const payload = await requireAuth(authedRequest(`${BASE}/api/me`, token), env);
  assert.equal(payload.uid, "42");
});

test("requireAuth: a token issued AFTER the marker is NOT rejected", async () => {
  const env = makeEnv();
  const token = await tokenAt(env, "42", -10);
  await env.SESSIONS.put("revoked_uid:42", String(NOW - 50));
  const payload = await requireAuth(authedRequest(`${BASE}/api/me`, token), env);
  assert.equal(payload.uid, "42");
});

test("requireAuth: no revoked_uid marker at all -> unaffected", async () => {
  const env = makeEnv();
  const token = await tokenAt(env, "42", -100);
  const payload = await requireAuth(authedRequest(`${BASE}/api/me`, token), env);
  assert.equal(payload.uid, "42");
});

test("requireAuth: a DIFFERENT uid's marker never affects this uid's token", async () => {
  const env = makeEnv();
  const token = await tokenAt(env, "42", -100);
  await env.SESSIONS.put("revoked_uid:99", String(NOW - 50));
  const payload = await requireAuth(authedRequest(`${BASE}/api/me`, token), env);
  assert.equal(payload.uid, "42");
});

test("requireAuth: no SESSIONS binding at all -> the per-uid check is skipped, not thrown", async () => {
  const env = { SESSION_SECRET: "x" };
  const token = await tokenAt(env, "42", -100);
  const payload = await requireAuth(authedRequest(`${BASE}/api/me`, token), env);
  assert.equal(payload.uid, "42");
});
