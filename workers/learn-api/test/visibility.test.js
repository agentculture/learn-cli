// Default-private learner visibility + the self-serve toggle (spec c12,
// task t8), plus the "no authed route ever returns another learner's data
// to a non-admin" half of h4.
//
// Visibility lives in learners.state (the existing JSON profile blob) —
// deliberately NOT a schema change: an absent `visibility` key means
// "private" for every existing AND new learner, asserted directly below.
// Nothing public-facing consumes "public" visibility yet (no leaderboards
// exist anywhere in this repo) — the toggle is forward-looking state; see
// README.md for the honest "not wired to anything yet" note.

import { test } from "node:test";
import assert from "node:assert/strict";

import worker from "../src/index.js";
import { TERMS_VERSION } from "../src/terms.js";
import { getLearner } from "../src/db.js";
import { makeEnv, mintToken, authedRequest, seedConsent } from "./helpers.js";

const BASE = "https://learn-api.example";

function call(env, request) {
  return worker.fetch(request, env, { waitUntil() {} });
}

function visibilityReq(token, visibility) {
  return authedRequest(`${BASE}/api/me/visibility`, token, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(visibility === undefined ? {} : { visibility }),
  });
}

// --- default-private, no migration -------------------------------------

test("visibility: a freshly-consented learner's state has NO visibility key at all (absent == private)", async () => {
  const env = makeEnv();
  seedConsent(env, "42", TERMS_VERSION);
  env.DB.learners.set("42", { github_user_id: "42", display_name: "Ada", state: "{}" });
  const learner = await getLearner(env, "42");
  assert.equal(Object.prototype.hasOwnProperty.call(learner.state, "visibility"), false);
});

test("visibility: GET /api/me reports 'private' for a learner with no visibility key set", async () => {
  const env = makeEnv();
  seedConsent(env, "42", TERMS_VERSION);
  env.DB.learners.set("42", { github_user_id: "42", display_name: "Ada", state: "{}" });
  const { token } = await mintToken(env, { uid: "42", name: "Ada" });
  const me = await (await call(env, authedRequest(`${BASE}/api/me`, token))).json();
  assert.equal(me.learner.visibility, "private");
});

test("visibility: an EXISTING learner row seeded before this field existed also defaults to private", async () => {
  // No `visibility` key anywhere in state — simulates a learner row written
  // before task t8 shipped. No migration touches it; the default read path
  // alone must treat the absence as private.
  const env = makeEnv();
  seedConsent(env, "7", TERMS_VERSION);
  env.DB.learners.set("7", {
    github_user_id: "7",
    display_name: "PreExisting",
    state: JSON.stringify({ some_other_pref: true }),
  });
  const { token } = await mintToken(env, { uid: "7", name: "PreExisting" });
  const me = await (await call(env, authedRequest(`${BASE}/api/me`, token))).json();
  assert.equal(me.learner.visibility, "private");
});

// --- POST /api/me/visibility ---------------------------------------------

test("visibility: POST /api/me/visibility {public} then GET /api/me reflects it", async () => {
  const env = makeEnv();
  seedConsent(env, "42", TERMS_VERSION);
  env.DB.learners.set("42", { github_user_id: "42", display_name: "Ada", state: "{}" });
  const { token } = await mintToken(env, { uid: "42", name: "Ada" });

  const res = await call(env, visibilityReq(token, "public"));
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.ok, true);
  assert.equal(body.visibility, "public");

  const me = await (await call(env, authedRequest(`${BASE}/api/me`, token))).json();
  assert.equal(me.learner.visibility, "public");
});

test("visibility: toggling back to private round-trips and preserves other state fields", async () => {
  const env = makeEnv();
  seedConsent(env, "42", TERMS_VERSION);
  env.DB.learners.set("42", {
    github_user_id: "42",
    display_name: "Ada",
    state: JSON.stringify({ some_other_pref: "keep-me" }),
  });
  const { token } = await mintToken(env, { uid: "42", name: "Ada" });

  await call(env, visibilityReq(token, "public"));
  await call(env, visibilityReq(token, "private"));

  const learner = await getLearner(env, "42");
  assert.equal(learner.state.visibility, "private");
  assert.equal(learner.state.some_other_pref, "keep-me", "merge, not clobber");
});

test("visibility: an invalid value is rejected with 400 and nothing is written", async () => {
  const env = makeEnv();
  seedConsent(env, "42", TERMS_VERSION);
  env.DB.learners.set("42", { github_user_id: "42", display_name: "Ada", state: "{}" });
  const { token } = await mintToken(env, { uid: "42", name: "Ada" });

  const res = await call(env, visibilityReq(token, "everyone"));
  assert.equal(res.status, 400);
  assert.equal((await res.json()).error, "invalid_visibility");

  const missing = await call(env, visibilityReq(token, undefined));
  assert.equal(missing.status, 400);

  const learner = await getLearner(env, "42");
  assert.equal(Object.prototype.hasOwnProperty.call(learner.state, "visibility"), false);
});

test("visibility: signed-out request -> 401", async () => {
  const env = makeEnv();
  const res = await call(
    env,
    new Request(`${BASE}/api/me/visibility`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ visibility: "public" }),
    }),
  );
  assert.equal(res.status, 401);
});

test("visibility: pending-consent session -> 403 consent_required, same gate as progress/record/export", async () => {
  const env = makeEnv();
  const { token } = await mintToken(env, { uid: "42", name: "Ada" }, 3600, { pendingConsent: true });
  const res = await call(env, visibilityReq(token, "public"));
  assert.equal(res.status, 403);
  assert.equal((await res.json()).error, "consent_required");
});

// --- /api/me additive fields: visibility + is_admin -----------------------

test("/api/me: is_admin is additive — false for a non-admin, true for an allow-listed uid", async () => {
  const env = makeEnv({ ADMIN_GITHUB_IDS: "20955789" });
  seedConsent(env, "42", TERMS_VERSION);
  env.DB.learners.set("42", { github_user_id: "42", display_name: "Ada", state: "{}" });
  seedConsent(env, "20955789", TERMS_VERSION);
  env.DB.learners.set("20955789", { github_user_id: "20955789", display_name: "OriNachum", state: "{}" });

  const { token: adaTok } = await mintToken(env, { uid: "42", name: "Ada" });
  const { token: adminTok } = await mintToken(env, { uid: "20955789", name: "OriNachum" });

  const adaMe = await (await call(env, authedRequest(`${BASE}/api/me`, adaTok))).json();
  assert.equal(adaMe.is_admin, false);

  const adminMe = await (await call(env, authedRequest(`${BASE}/api/me`, adminTok))).json();
  assert.equal(adminMe.is_admin, true);
});

// --- h4 second half: no authed route ever returns another learner's data ---

test("isolation audit: /api/me never reflects another learner's identity or visibility", async () => {
  const env = makeEnv();
  seedConsent(env, "42", TERMS_VERSION);
  seedConsent(env, "99", TERMS_VERSION);
  env.DB.learners.set("42", { github_user_id: "42", display_name: "Ada", state: "{}" });
  env.DB.learners.set("99", {
    github_user_id: "99",
    display_name: "Linus",
    state: JSON.stringify({ visibility: "public" }),
  });
  const { token: adaTok } = await mintToken(env, { uid: "42", name: "Ada" });

  const me = await (await call(env, authedRequest(`${BASE}/api/me`, adaTok))).json();
  assert.equal(me.learner.github_user_id, "42");
  assert.equal(me.learner.display_name, "Ada");
  assert.equal(me.learner.visibility, "private");
  assert.notEqual(me.learner.display_name, "Linus");
});

test("isolation audit: /api/progress/:subject never includes another learner's rows", async () => {
  const env = makeEnv();
  seedConsent(env, "42", TERMS_VERSION);
  seedConsent(env, "99", TERMS_VERSION);
  const { token: adaTok } = await mintToken(env, { uid: "42", name: "Ada" });
  const { token: linusTok } = await mintToken(env, { uid: "99", name: "Linus" });

  await call(
    env,
    authedRequest(`${BASE}/api/record`, linusTok, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        subject: "french",
        recorded: { item_id: "linus-1", activity: "practice", result: "pass", at: "2026-07-11T10:00:00Z" },
      }),
    }),
  );

  const prog = await (await call(env, authedRequest(`${BASE}/api/progress/french`, adaTok))).json();
  assert.equal(prog.items_touched, 0, "Ada's progress must not include Linus's record");
});

test("isolation audit: /api/export never includes another learner's records or consents", async () => {
  const env = makeEnv();
  seedConsent(env, "42", TERMS_VERSION, "2026-01-01T00:00:00.000Z");
  seedConsent(env, "99", TERMS_VERSION, "2026-02-01T00:00:00.000Z");
  const { token: adaTok } = await mintToken(env, { uid: "42", name: "Ada" });
  const { token: linusTok } = await mintToken(env, { uid: "99", name: "Linus" });

  await call(
    env,
    authedRequest(`${BASE}/api/record`, linusTok, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        subject: "french",
        recorded: { item_id: "linus-1", activity: "practice", result: "pass", at: "2026-07-11T10:00:00Z" },
      }),
    }),
  );

  const exported = await (await call(env, authedRequest(`${BASE}/api/export`, adaTok))).json();
  assert.equal(exported.records.length, 0);
  assert.equal(exported.learner.github_user_id, "42");
});

test("isolation audit: a non-admin's visibility toggle never mutates another learner's state", async () => {
  const env = makeEnv();
  seedConsent(env, "42", TERMS_VERSION);
  seedConsent(env, "99", TERMS_VERSION);
  env.DB.learners.set("42", { github_user_id: "42", display_name: "Ada", state: "{}" });
  env.DB.learners.set("99", { github_user_id: "99", display_name: "Linus", state: "{}" });
  const { token: adaTok } = await mintToken(env, { uid: "42", name: "Ada" });

  await call(env, visibilityReq(adaTok, "public"));

  const linus = await getLearner(env, "99");
  assert.equal(
    Object.prototype.hasOwnProperty.call(linus.state, "visibility"),
    false,
    "Ada's toggle must not touch Linus's row",
  );
});

test("isolation audit: a non-admin can never reach the admin learner list, even to read their own row via it", async () => {
  const env = makeEnv({ ADMIN_GITHUB_IDS: "20955789" });
  seedConsent(env, "42", TERMS_VERSION);
  env.DB.learners.set("42", { github_user_id: "42", display_name: "Ada", state: "{}" });
  const { token } = await mintToken(env, { uid: "42", name: "Ada" });
  const res = await call(env, authedRequest(`${BASE}/api/admin/learners`, token));
  assert.equal(res.status, 403);
});
