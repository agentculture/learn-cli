// The tutoring approval gate (spec c13/h5, decisions c20 + c18; plan task t9).
//
// h5 verbatim: "A signed-in, non-approved learner POSTing /api/tutor receives
// 403 and the Worker makes ZERO outbound inference requests — proven by
// extending the existing signed-out-never-calls-inference ordering test to
// the approval level." This file is that extension: the resource-gate
// ordering invariant grows one level — signed-out < signed-in < consented <
// APPROVED — and every level below "approved" is proven to spend zero
// inference, using the same counting fetch stub worker.test.js's original
// signed-out proof uses.
//
// c20 (sequencing decision) in code: approve FAILS (409 consent_stale)
// unless the target learner's consent is CURRENT — no learner is approved
// for the Bedrock tier until they have consented to the terms that disclose
// Bedrock processing. Defense in depth for the reverse direction: a
// previously-approved learner whose consent goes stale keeps
// `state.approved`, but requireConsented (t6) already walls the tutor route
// off independently — both gates hold on their own, proven below.
//
// The `approved` flag lives in `learners.state` (the same no-schema-change
// pattern as t8's `visibility`): an absent key means NOT approved for every
// existing and new learner, no migration.

import { test } from "node:test";
import assert from "node:assert/strict";

import worker from "../src/index.js";
import { GH } from "../src/github.js";
import { TERMS_VERSION } from "../src/terms.js";
import { getLearner } from "../src/db.js";
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
const ADMIN_UID = "20955789";

function call(env, request) {
  return worker.fetch(request, env, { waitUntil() {} });
}

/** Seed a learner row directly (same direct-set pattern the t8 suites use).
 * `state` is the parsed object; stored as the JSON TEXT column D1 holds. */
function seedLearner(env, uid, name, state = {}) {
  env.DB.learners.set(String(uid), {
    github_user_id: String(uid),
    display_name: name,
    state: JSON.stringify(state),
  });
}

function tutorReq(token) {
  return authedRequest(`${BASE}/api/tutor`, token, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ subject: "french", messages: [{ role: "user", content: "hi" }] }),
  });
}

function adminMutateReq(path, token, body) {
  return authedRequest(`${BASE}${path}`, token, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** An env with an admin (consented, allow-listed) and a counting inference stub. */
function approvalEnv(overrides = {}) {
  const fetchStub = makeFetchStub({
    [INFERENCE_URL]: () => jsonResp({ reply: "Bonjour !", tokens: 12 }),
  });
  const env = makeEnv({
    INFERENCE_URL,
    INFERENCE_TOKEN: "secret",
    ADMIN_GITHUB_IDS: ADMIN_UID,
    FETCH: fetchStub,
    ...overrides,
  });
  seedConsent(env, ADMIN_UID, overrides.TERMS_VERSION_OVERRIDE || TERMS_VERSION);
  seedLearner(env, ADMIN_UID, "OriNachum");
  return { env, fetchStub };
}

// --- h5: the ordering invariant, one level up --------------------------------

test("h5: signed-in, CONSENTED but non-approved POST /api/tutor -> 403 approval_required, ZERO inference calls", async () => {
  const { env, fetchStub } = approvalEnv();
  seedConsent(env, "42", TERMS_VERSION);
  seedLearner(env, "42", "Ada"); // consented learner row, NO approved key
  const { token } = await mintToken(env, { uid: "42", name: "Ada" });

  const res = await call(env, tutorReq(token));
  assert.equal(res.status, 403);
  const body = await res.json();
  assert.equal(body.error, "approval_required");
  assert.match(body.hint, /admin/i, "the hint must say approval is admin-granted");
  // The whole point (h5): zero outbound model calls below the approved level.
  assert.equal(fetchStub.calls.length, 0, "inference endpoint must not be touched");
});

test("approval check runs BEFORE the INFERENCE_URL 503 — an unapproved learner can't probe broker config", async () => {
  // No INFERENCE_URL at all: an unapproved learner still gets 403, never the
  // 503 no_inference — they must not even learn whether inference is wired up.
  const env = makeEnv({ ADMIN_GITHUB_IDS: ADMIN_UID });
  seedConsent(env, "42", TERMS_VERSION);
  seedLearner(env, "42", "Ada");
  const { token } = await mintToken(env, { uid: "42", name: "Ada" });

  const res = await call(env, tutorReq(token));
  assert.equal(res.status, 403);
  assert.equal((await res.json()).error, "approval_required");
});

test("absent approved key == not approved: a pre-t9 learner row needs no migration to be gated", async () => {
  const { env, fetchStub } = approvalEnv();
  seedConsent(env, "7", TERMS_VERSION);
  // A learner row written before t9 shipped — state carries other keys only.
  seedLearner(env, "7", "PreExisting", { visibility: "public", some_other_pref: true });
  const { token } = await mintToken(env, { uid: "7", name: "PreExisting" });

  const res = await call(env, tutorReq(token));
  assert.equal(res.status, 403);
  assert.equal((await res.json()).error, "approval_required");
  assert.equal(fetchStub.calls.length, 0);
});

// --- approve / revoke: effect on the tutor gate, no re-login ----------------

test("approve takes effect WITHOUT re-login: a token minted BEFORE approval tutors right after it", async () => {
  const { env, fetchStub } = approvalEnv();
  seedConsent(env, "42", TERMS_VERSION);
  seedLearner(env, "42", "Ada");
  const { token: adaTok } = await mintToken(env, { uid: "42", name: "Ada" }); // pre-approval token
  const { token: adminTok } = await mintToken(env, { uid: ADMIN_UID, name: "OriNachum" });

  assert.equal((await call(env, tutorReq(adaTok))).status, 403);
  assert.equal(fetchStub.calls.length, 0);

  const approve = await call(
    env,
    adminMutateReq("/api/admin/approve", adminTok, { github_user_id: "42" }),
  );
  assert.equal(approve.status, 200);
  const approved = await approve.json();
  assert.equal(approved.ok, true);
  assert.equal(approved.github_user_id, "42");
  assert.equal(approved.approved, true);

  // Same pre-approval token — the gate reads the learner row per request.
  const res = await call(env, tutorReq(adaTok));
  assert.equal(res.status, 200);
  assert.equal((await res.json()).reply, "Bonjour !");
  assert.equal(fetchStub.calls.length, 1);
  assert.equal(JSON.parse(fetchStub.calls[0].init.body).learner, "42");
});

test("revoke takes effect WITHOUT re-login: the very next tutor call on a live token 403s, zero new inference", async () => {
  const { env, fetchStub } = approvalEnv();
  seedConsent(env, "42", TERMS_VERSION);
  seedLearner(env, "42", "Ada", { approved: true });
  const { token: adaTok } = await mintToken(env, { uid: "42", name: "Ada" });
  const { token: adminTok } = await mintToken(env, { uid: ADMIN_UID, name: "OriNachum" });

  assert.equal((await call(env, tutorReq(adaTok))).status, 200);
  assert.equal(fetchStub.calls.length, 1);

  const revoke = await call(
    env,
    adminMutateReq("/api/admin/revoke", adminTok, { github_user_id: "42" }),
  );
  assert.equal(revoke.status, 200);
  assert.equal((await revoke.json()).approved, false);

  const res = await call(env, tutorReq(adaTok));
  assert.equal(res.status, 403);
  assert.equal((await res.json()).error, "approval_required");
  assert.equal(fetchStub.calls.length, 1, "no inference call after revoke");
});

test("approve/revoke preserve the rest of the state blob (merge, not clobber)", async () => {
  const { env } = approvalEnv();
  seedConsent(env, "42", TERMS_VERSION);
  seedLearner(env, "42", "Ada", { visibility: "public", some_other_pref: "keep-me" });
  const { token: adminTok } = await mintToken(env, { uid: ADMIN_UID, name: "OriNachum" });

  await call(env, adminMutateReq("/api/admin/approve", adminTok, { github_user_id: "42" }));
  let ada = await getLearner(env, "42");
  assert.equal(ada.state.approved, true);
  assert.equal(ada.state.visibility, "public");
  assert.equal(ada.state.some_other_pref, "keep-me");

  await call(env, adminMutateReq("/api/admin/revoke", adminTok, { github_user_id: "42" }));
  ada = await getLearner(env, "42");
  assert.equal(
    Object.prototype.hasOwnProperty.call(ada.state, "approved"),
    false,
    "revoke clears the key entirely — absent == not approved, same as never-approved",
  );
  assert.equal(ada.state.some_other_pref, "keep-me");
});

// --- the admin gate on approve/revoke (reuses t8's requireAdmin) -------------

test("approve/revoke: signed-out -> 401; consented non-admin (with forged claims) -> 403 admin_required", async () => {
  const { env } = approvalEnv();
  seedConsent(env, "42", TERMS_VERSION);
  seedLearner(env, "42", "Ada");
  const { token: adaTok } = await mintToken(env, { uid: "42", name: "Ada" });

  for (const path of ["/api/admin/approve", "/api/admin/revoke"]) {
    const signedOut = await call(
      env,
      new Request(`${BASE}${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ github_user_id: "42" }),
      }),
    );
    assert.equal(signedOut.status, 401, `${path} must 401 signed-out`);

    // Forged client-side admin claims (h4's pattern from admin.test.js).
    const forged = authedRequest(`${BASE}${path}?admin=true`, adaTok, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Admin": "true" },
      body: JSON.stringify({ github_user_id: "42" }),
    });
    const res = await call(env, forged);
    assert.equal(res.status, 403, `${path} must ignore forged admin claims`);
    assert.equal((await res.json()).error, "admin_required");
  }
});

test("approve/revoke: missing github_user_id -> 400; unknown learner -> 404", async () => {
  const { env } = approvalEnv();
  const { token: adminTok } = await mintToken(env, { uid: ADMIN_UID, name: "OriNachum" });

  for (const path of ["/api/admin/approve", "/api/admin/revoke"]) {
    const missing = await call(env, adminMutateReq(path, adminTok, {}));
    assert.equal(missing.status, 400, `${path} must 400 without github_user_id`);
    assert.equal((await missing.json()).error, "missing_github_user_id");

    const unknown = await call(env, adminMutateReq(path, adminTok, { github_user_id: "424242" }));
    assert.equal(unknown.status, 404, `${path} must 404 for an unknown learner`);
    assert.equal((await unknown.json()).error, "learner_not_found");
  }
});

// --- c20: approval requires a CURRENT consent --------------------------------

test("c20: approve FAILS 409 consent_stale when the target has NO consent row", async () => {
  const { env } = approvalEnv();
  // Learner row exists (edge state) but no consent row at all.
  seedLearner(env, "42", "Ada");
  const { token: adminTok } = await mintToken(env, { uid: ADMIN_UID, name: "OriNachum" });

  const res = await call(env, adminMutateReq("/api/admin/approve", adminTok, { github_user_id: "42" }));
  assert.equal(res.status, 409);
  const body = await res.json();
  assert.equal(body.error, "consent_stale");
  assert.equal(body.reason, "none");

  const ada = await getLearner(env, "42");
  assert.equal(Object.prototype.hasOwnProperty.call(ada.state, "approved"), false);
});

test("c20: approve FAILS 409 consent_stale when the target consented to a SUPERSEDED version", async () => {
  const BUMPED = "2.0.0";
  const { env } = approvalEnv({ TERMS_VERSION_OVERRIDE: BUMPED });
  seedConsent(env, "42", TERMS_VERSION); // stale — the published version moved on
  seedLearner(env, "42", "Ada");
  const { token: adminTok } = await mintToken(env, { uid: ADMIN_UID, name: "OriNachum" });

  const res = await call(env, adminMutateReq("/api/admin/approve", adminTok, { github_user_id: "42" }));
  assert.equal(res.status, 409);
  const body = await res.json();
  assert.equal(body.error, "consent_stale");
  assert.equal(body.reason, "stale_version");
  assert.equal(body.terms_version, BUMPED, "the body names the version the learner must accept");
});

test("c20 defense in depth: a version bump blocks tutoring EVEN IF approved — both gates independent", async () => {
  const BUMPED = "2.0.0";
  const { env, fetchStub } = approvalEnv({ TERMS_VERSION_OVERRIDE: BUMPED });
  // Approved back when their consent was current; then the published version bumped.
  seedConsent(env, "42", TERMS_VERSION);
  seedLearner(env, "42", "Ada", { approved: true });
  const { token } = await mintToken(env, { uid: "42", name: "Ada" });

  const res = await call(env, tutorReq(token));
  assert.equal(res.status, 403);
  const body = await res.json();
  assert.equal(body.error, "consent_required", "the consent gate fires first, independently");
  assert.equal(body.reason, "stale_version");
  assert.equal(fetchStub.calls.length, 0, "zero inference for stale consent, approved or not");

  // The approved flag is KEPT (revocation is an admin act, not a side effect
  // of a terms bump) — re-accepting the new terms restores tutoring alone.
  const ada = await getLearner(env, "42");
  assert.equal(ada.state.approved, true);
});

// --- additive surfaces: /api/me + the admin list ------------------------------

test("/api/me: additive learner.approved — false by default, true after approve, same token throughout", async () => {
  const { env } = approvalEnv();
  seedConsent(env, "42", TERMS_VERSION);
  seedLearner(env, "42", "Ada");
  const { token } = await mintToken(env, { uid: "42", name: "Ada" });
  const { token: adminTok } = await mintToken(env, { uid: ADMIN_UID, name: "OriNachum" });

  const before = await (await call(env, authedRequest(`${BASE}/api/me`, token))).json();
  assert.equal(before.learner.approved, false);

  await call(env, adminMutateReq("/api/admin/approve", adminTok, { github_user_id: "42" }));

  const after = await (await call(env, authedRequest(`${BASE}/api/me`, token))).json();
  assert.equal(after.learner.approved, true, "read per-request, no re-login needed");
});

test("GET /api/admin/learners surfaces approved per learner (additive)", async () => {
  const { env } = approvalEnv();
  seedConsent(env, "42", TERMS_VERSION);
  seedLearner(env, "42", "Ada", { approved: true });
  seedConsent(env, "99", TERMS_VERSION);
  seedLearner(env, "99", "Linus");
  const { token: adminTok } = await mintToken(env, { uid: ADMIN_UID, name: "OriNachum" });

  const body = await (await call(env, authedRequest(`${BASE}/api/admin/learners`, adminTok))).json();
  const ada = body.learners.find((l) => l.github_user_id === "42");
  const linus = body.learners.find((l) => l.github_user_id === "99");
  assert.equal(ada.approved, true);
  assert.equal(linus.approved, false, "absent key reported as false, not undefined");
});

// --- isolation (the visibility.test.js audit template) -----------------------

test("isolation: approving one learner never touches another learner's state", async () => {
  const { env } = approvalEnv();
  seedConsent(env, "42", TERMS_VERSION);
  seedLearner(env, "42", "Ada");
  seedConsent(env, "99", TERMS_VERSION);
  seedLearner(env, "99", "Linus");
  const { token: adminTok } = await mintToken(env, { uid: ADMIN_UID, name: "OriNachum" });

  await call(env, adminMutateReq("/api/admin/approve", adminTok, { github_user_id: "42" }));

  const linus = await getLearner(env, "99");
  assert.equal(
    Object.prototype.hasOwnProperty.call(linus.state, "approved"),
    false,
    "Ada's approval must not touch Linus's row",
  );
});

// --- deletion interaction (c18/t7): erasure removes approval -----------------

test("delete erases state.approved with the learner row — a re-signup is NOT approved", async () => {
  const fetchStub = makeFetchStub({
    [GH.token]: () => jsonResp({ access_token: "gho_x", token_type: "bearer" }),
    [GH.user]: () => jsonResp({ id: 42, login: "ada", name: "Ada" }),
    [INFERENCE_URL]: () => jsonResp({ reply: "Bonjour !" }),
  });
  const env = makeEnv({
    INFERENCE_URL,
    INFERENCE_TOKEN: "secret",
    ADMIN_GITHUB_IDS: ADMIN_UID,
    FETCH: fetchStub,
    APP_URL: "https://agentculture.org/learn/",
  });
  seedConsent(env, "42", TERMS_VERSION);
  seedLearner(env, "42", "Ada", { approved: true });
  const { token } = await mintToken(env, { uid: "42", name: "Ada" });

  // Approved and tutoring...
  assert.equal((await call(env, tutorReq(token))).status, 200);
  const inferenceCallsBeforeDelete = fetchStub.calls.filter((c) => c.url === INFERENCE_URL).length;

  // ...then self-serve delete (t7): the whole row — approved flag included — goes.
  const del = await call(
    env,
    authedRequest(`${BASE}/api/delete`, token, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirm: "42" }),
    }),
  );
  assert.equal(del.status, 200);
  assert.equal(env.DB.learners.size, 0);

  // Re-signup via device flow: pending-consent, accept, fresh learner row.
  const poll = await (
    await call(
      env,
      new Request(`${BASE}/api/auth/device`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "poll", device_code: "dc_123" }),
      }),
    )
  ).json();
  assert.equal(poll.status, "consent_required");
  const accept = await (
    await call(env, authedRequest(`${BASE}/api/consent/accept`, poll.token, { method: "POST" }))
  ).json();
  assert.equal(accept.status, "consented");

  // The fresh account is consented but NOT approved: tutor 403s, zero new inference.
  const res = await call(env, tutorReq(accept.token));
  assert.equal(res.status, 403);
  assert.equal((await res.json()).error, "approval_required");
  const inferenceCallsAfter = fetchStub.calls.filter((c) => c.url === INFERENCE_URL).length;
  assert.equal(inferenceCallsAfter, inferenceCallsBeforeDelete, "no inference after re-signup");
});
