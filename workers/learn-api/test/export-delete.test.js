// Self-serve export + delete (spec c11/h3, decision c18; plan task t7).
//
// h3 verbatim: after self-serve delete, a D1 query finds NO row in
// learners/records/consents carrying that github_user_id, and the OLD
// session token is rejected. c18: withdrawal of consent = whole-learner
// erasure is the ONLY deletion path — the ledger stays append-only for
// everyone else (isolation, proven below), and there is no update/individual
// -delete API anywhere in this Worker.
//
// GET /api/export and POST /api/delete are exercised at the route layer
// here (worker.fetch), same style as consent.test.js/reconsent.test.js;
// db.js's own listAllRecords/listConsents/deleteLearnerData unit behavior is
// covered directly in db.test.js.

import { test } from "node:test";
import assert from "node:assert/strict";

import worker from "../src/index.js";
import { GH } from "../src/github.js";
import { TERMS_VERSION } from "../src/terms.js";
import {
  makeEnv,
  makeFetchStub,
  mintToken,
  authedRequest,
  jsonResp,
  seedConsent,
} from "./helpers.js";

const BASE = "https://learn-api.example";

function call(env, request) {
  return worker.fetch(request, env, { waitUntil() {} });
}

function envWithGitHubUser(user, overrides = {}) {
  const fetchStub = makeFetchStub({
    [GH.token]: () => jsonResp({ access_token: "gho_x", token_type: "bearer" }),
    [GH.user]: () => jsonResp(user),
  });
  return makeEnv({ FETCH: fetchStub, APP_URL: "https://agentculture.org/learn/", ...overrides });
}

function devicePollRequest() {
  return new Request(`${BASE}/api/auth/device`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "poll", device_code: "dc_123" }),
  });
}

function recordReq(token, subject, item_id, result = "pass") {
  return authedRequest(`${BASE}/api/record`, token, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      subject,
      recorded: { item_id, activity: "practice", result, at: "2026-07-11T10:00:00Z" },
    }),
  });
}

function deleteReq(token, confirm) {
  return authedRequest(`${BASE}/api/delete`, token, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(confirm === undefined ? {} : { confirm }),
  });
}

// --- GET /api/export ---------------------------------------------------

test("export: a consented session gets learner + records across ALL subjects + full consent history", async () => {
  const env = makeEnv();
  seedConsent(env, "42", TERMS_VERSION, "2026-01-01T00:00:00.000Z");
  const { token } = await mintToken(env, { uid: "42", name: "Ada" });

  await call(env, recordReq(token, "french", "fr-1"));
  await call(env, recordReq(token, "spanish", "es-1", "partial"));

  const res = await call(env, authedRequest(`${BASE}/api/export`, token));
  assert.equal(res.status, 200);
  const body = await res.json();

  assert.equal(body.kind, "export");
  assert.equal(body.schema_version, "1.0");
  assert.ok(body.exported_at, "exported_at timestamp present");
  assert.ok(typeof body.schema_note === "string" && body.schema_note.length > 0);

  assert.equal(body.learner.github_user_id, "42");
  assert.equal(body.learner.display_name, "Ada");

  assert.equal(body.records.length, 2, "records span every subject, not just one");
  assert.deepEqual(
    body.records.map((r) => r.subject).sort(),
    ["french", "spanish"],
  );
  const fr = body.records.find((r) => r.subject === "french");
  assert.equal(fr.item_id, "fr-1");
  assert.equal(fr.recorded.item_id, "fr-1", "recorded is a parsed object, not a JSON string");
  assert.equal(typeof fr.recorded, "object");

  assert.equal(body.consents.length, 1);
  assert.equal(body.consents[0].terms_version, TERMS_VERSION);
});

test("export: pending-consent session gets 403 consent_required — nothing exists to export", async () => {
  const env = envWithGitHubUser({ id: 900, login: "fresh", name: "Fresh" });
  const poll = await (await call(env, devicePollRequest())).json();
  assert.equal(poll.status, "consent_required");

  const res = await call(env, authedRequest(`${BASE}/api/export`, poll.token));
  assert.equal(res.status, 403);
  assert.equal((await res.json()).error, "consent_required");

  // The h1 guarantee, restated: there was never anything to export.
  assert.equal(env.DB.learners.size, 0);
  assert.equal(env.DB.records.length, 0);
  assert.equal(env.DB.consents.length, 0);
});

test("export: a stale-consent (reconsent_required) full session is walled off same as progress/record/tutor", async () => {
  const BUMPED = "2.0.0";
  const env = makeEnv({ TERMS_VERSION_OVERRIDE: BUMPED });
  seedConsent(env, "42", TERMS_VERSION); // consented to the now-superseded version
  const { token } = await mintToken(env, { uid: "42", name: "Ada" });

  const res = await call(env, authedRequest(`${BASE}/api/export`, token));
  assert.equal(res.status, 403);
  const body = await res.json();
  assert.equal(body.error, "consent_required");
  assert.equal(body.reason, "stale_version");
});

test("export: signed-out request -> 401", async () => {
  const env = makeEnv();
  const res = await call(env, new Request(`${BASE}/api/export`));
  assert.equal(res.status, 401);
});

// --- POST /api/delete ----------------------------------------------------

test("delete: erases learner+records+consents, revokes the session, clears the cookie, returns counts", async () => {
  const env = makeEnv();
  seedConsent(env, "42", TERMS_VERSION);
  env.DB.learners.set("42", { github_user_id: "42", display_name: "Ada", state: "{}" });
  const { token } = await mintToken(env, { uid: "42", name: "Ada" });
  await call(env, recordReq(token, "french", "fr-1"));
  await call(env, recordReq(token, "french", "fr-2", "fail"));

  const res = await call(env, deleteReq(token, "42"));
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.ok, true);
  assert.equal(body.status, "deleted");
  assert.deepEqual(body.deleted, { records: 2, consents: 1, learners: 1 });
  assert.ok(
    res.headers.getSetCookie().some((c) => c.startsWith("session=;") && c.includes("Max-Age=0")),
    "session cookie cleared",
  );

  // h3 verbatim: a D1 query finds NO row in ANY of the three tables.
  assert.equal(env.DB.learners.has("42"), false);
  assert.equal(env.DB.records.some((r) => r.github_user_id === "42"), false);
  assert.equal(env.DB.consents.some((c) => c.github_user_id === "42"), false);

  // h3 verbatim: the OLD session token is rejected on any subsequent authed call.
  assert.equal((await call(env, authedRequest(`${BASE}/api/me`, token))).status, 401);
  assert.equal((await call(env, authedRequest(`${BASE}/api/export`, token))).status, 401);
});

test("delete: wrong or missing confirm is rejected with 400 and deletes nothing", async () => {
  const env = makeEnv();
  seedConsent(env, "42", TERMS_VERSION);
  env.DB.learners.set("42", { github_user_id: "42", display_name: "Ada", state: "{}" });
  const { token } = await mintToken(env, { uid: "42", name: "Ada" });
  await call(env, recordReq(token, "french", "fr-1"));

  const wrong = await call(env, deleteReq(token, "not-my-id"));
  assert.equal(wrong.status, 400);
  assert.equal((await wrong.json()).error, "confirmation_required");

  const missing = await call(
    env,
    authedRequest(`${BASE}/api/delete`, token, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    }),
  );
  assert.equal(missing.status, 400);

  // Nothing was touched — the learner is intact and the session still works.
  assert.equal(env.DB.learners.has("42"), true);
  assert.equal(env.DB.records.length, 1);
  assert.equal((await call(env, authedRequest(`${BASE}/api/me`, token))).status, 200);
});

test("delete: signed-out request -> 401 (and confirm cannot bypass auth)", async () => {
  const env = makeEnv();
  const res = await call(
    env,
    new Request(`${BASE}/api/delete`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirm: "42" }),
    }),
  );
  assert.equal(res.status, 401);
});

test("delete: a stale-consent (reconsent_required) session can STILL erase its data without re-accepting", async () => {
  const BUMPED = "2.0.0";
  const env = makeEnv({ TERMS_VERSION_OVERRIDE: BUMPED });
  seedConsent(env, "42", TERMS_VERSION); // consented to the now-superseded version only
  const { token } = await mintToken(env, { uid: "42", name: "Ada" });

  // Confirms requireConsented WOULD reject this session (the catch-22 this
  // route design avoids)...
  assert.equal((await call(env, authedRequest(`${BASE}/api/export`, token))).status, 403);

  // ...but delete (requireAuth, not requireConsented) still works.
  const res = await call(env, deleteReq(token, "42"));
  assert.equal(res.status, 200);
  assert.equal(env.DB.learners.has("42"), false);
  assert.equal(env.DB.consents.some((c) => c.github_user_id === "42"), false);
});

test("delete: a pending-consent session is a documented no-op (nothing was ever written) and still revokes", async () => {
  const env = envWithGitHubUser({ id: 901, login: "neverwrote", name: "Never Wrote" });
  const poll = await (await call(env, devicePollRequest())).json();
  assert.equal(poll.status, "consent_required");

  const res = await call(env, deleteReq(poll.token, "901"));
  assert.equal(res.status, 200);
  assert.deepEqual((await res.json()).deleted, { records: 0, consents: 0, learners: 0 });
  assert.equal((await call(env, authedRequest(`${BASE}/api/me`, poll.token))).status, 401);
});

// --- c18: isolation — the ledger stays append-only and unaffected for others -

test("delete: isolation — OTHER learners' data and the ability to /api/record survive one learner's deletion", async () => {
  const env = makeEnv();
  seedConsent(env, "42", TERMS_VERSION);
  seedConsent(env, "99", TERMS_VERSION);
  env.DB.learners.set("42", { github_user_id: "42", display_name: "Ada", state: "{}" });
  env.DB.learners.set("99", { github_user_id: "99", display_name: "Linus", state: "{}" });
  const { token: adaTok } = await mintToken(env, { uid: "42", name: "Ada" });
  const { token: linusTok } = await mintToken(env, { uid: "99", name: "Linus" });

  await call(env, recordReq(adaTok, "french", "a1"));
  await call(env, recordReq(linusTok, "french", "b1"));

  const del = await call(env, deleteReq(adaTok, "42"));
  assert.equal(del.status, 200);

  // Linus's learner row, consent, and record all survive untouched.
  assert.equal(env.DB.learners.has("99"), true);
  assert.equal(env.DB.records.some((r) => r.github_user_id === "99"), true);
  assert.equal(env.DB.consents.some((c) => c.github_user_id === "99"), true);

  // The append-only ledger keeps appending normally for Linus after Ada's erasure.
  const again = await call(env, recordReq(linusTok, "french", "b2", "partial"));
  assert.equal(again.status, 201);
  assert.equal(env.DB.records.filter((r) => r.github_user_id === "99").length, 2);

  const prog = await (await call(env, authedRequest(`${BASE}/api/progress/french`, linusTok))).json();
  assert.equal(prog.items_touched, 2);
});

// --- full cycle: delete -> sign in again is a brand-new learner --------------

test("full cycle: consent -> record -> delete -> sign in again lands pending-consent -> re-accept starts with an EMPTY ledger", async () => {
  const env = envWithGitHubUser({ id: 42, login: "ada", name: "Ada" });

  // 1. First-ever sign-in via device poll, accept, record something.
  const poll1 = await (await call(env, devicePollRequest())).json();
  assert.equal(poll1.status, "consent_required");
  const accept1 = await (
    await call(env, authedRequest(`${BASE}/api/consent/accept`, poll1.token, { method: "POST" }))
  ).json();
  assert.equal(accept1.status, "consented");
  await call(env, recordReq(accept1.token, "french", "fr-1"));
  assert.equal(env.DB.records.length, 1);

  // 2. Self-serve delete.
  const del = await call(env, deleteReq(accept1.token, "42"));
  assert.equal(del.status, 200);
  assert.equal(env.DB.learners.size, 0);
  assert.equal(env.DB.records.length, 0);
  assert.equal(env.DB.consents.length, 0);

  // 3. Signing in again is indistinguishable from a brand-new learner: no
  // consent row survives, so it lands pending-consent again, zero NEW writes
  // (env.DB.writes is cumulative across this whole test — steps 1-2 already
  // logged real inserts/deletes — so the assertion is a delta, same pattern
  // as reconsent.test.js's "zero NEW D1 writes" checks).
  const writesBeforePoll2 = env.DB.writes.length;
  const poll2 = await (await call(env, devicePollRequest())).json();
  assert.equal(poll2.status, "consent_required");
  assert.equal(env.DB.writes.length, writesBeforePoll2, "no NEW D1 writes just from signing back in");

  // 4. Re-consent starts with a totally empty ledger.
  const accept2 = await (
    await call(env, authedRequest(`${BASE}/api/consent/accept`, poll2.token, { method: "POST" }))
  ).json();
  assert.equal(accept2.status, "consented");
  const prog = await (
    await call(env, authedRequest(`${BASE}/api/progress/french`, accept2.token))
  ).json();
  assert.equal(prog.items_touched, 0);
  assert.deepEqual(prog.mastery, {});

  const exported = await (
    await call(env, authedRequest(`${BASE}/api/export`, accept2.token))
  ).json();
  assert.equal(exported.records.length, 0);
  assert.equal(exported.consents.length, 1, "only the new post-delete consent exists");
});
