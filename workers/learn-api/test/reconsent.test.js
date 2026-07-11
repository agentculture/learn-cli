// Re-consent on a published terms-version bump (spec c10/h2; plan task t6).
//
// t5 built consentSatisfiesCurrentTerms() to accept ANY recorded consent.
// t6's whole job is extending that SAME predicate to require an EXACT
// `consent.terms_version` match against the currently published version —
// and then making sure both the sign-in paths (t5's territory, index.js
// handleCallback/handleDevice) and requireConsented (auth.js — the wall in
// front of progress/record/tutor) consult it, so a version bump:
//
//   (a) routes a previously-consented learner's NEXT sign-in back to
//       pending-consent, with zero NEW D1 writes (same shape as a first-time
//       sign-in — h1's invariant, extended one level);
//   (b) walls off an EXISTING, still-unexpired full-session token at every
//       requireConsented-gated route with a structured 403, until the
//       learner re-accepts;
//   (c) /api/me reports the requirement (additive field) instead of 403ing,
//       since identity/session info must stay reachable to explain WHY
//       everything else just started rejecting.
//
// Tests simulate the bump with `env.TERMS_VERSION_OVERRIDE` (see
// consent.js#currentTermsVersion) — shared/terms-version.mjs, the actual
// published source, is never touched and stays "1.0.0" throughout.

import { test } from "node:test";
import assert from "node:assert/strict";

import worker from "../src/index.js";
import { GH } from "../src/github.js";
import { TERMS_VERSION } from "../src/terms.js";
import {
  consentSatisfiesCurrentTerms,
  currentTermsVersion,
  consentRequirement,
} from "../src/consent.js";
import { makeEnv, makeFetchStub, mintToken, authedRequest, jsonResp, seedConsent } from "./helpers.js";

const BASE = "https://learn-api.example";
const INFERENCE_URL = "https://inference.example/v1/messages";
const BUMPED = "2.0.0"; // a simulated published-version bump; never the real shared value

function call(env, request) {
  return worker.fetch(request, env, { waitUntil() {} });
}

function envWithGitHubUser(user = { id: 42, login: "ada", name: "Ada" }, overrides = {}) {
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

// --- the predicate + version-resolution seam --------------------------------

test("currentTermsVersion resolves the real published version by default", () => {
  assert.equal(currentTermsVersion(makeEnv()), TERMS_VERSION);
  assert.equal(currentTermsVersion(undefined), TERMS_VERSION);
});

test("currentTermsVersion honors the test-only env override without touching the shared source", () => {
  const env = makeEnv({ TERMS_VERSION_OVERRIDE: BUMPED });
  assert.equal(currentTermsVersion(env), BUMPED);
  // The single source of truth is untouched — production never sets this var.
  assert.equal(TERMS_VERSION, "1.0.0");
});

test("consentSatisfiesCurrentTerms requires an EXACT version match, not just any consent", () => {
  const env = makeEnv({ TERMS_VERSION_OVERRIDE: BUMPED });
  assert.equal(consentSatisfiesCurrentTerms(null, env), false);
  assert.equal(consentSatisfiesCurrentTerms({ terms_version: TERMS_VERSION }, env), false);
  assert.equal(consentSatisfiesCurrentTerms({ terms_version: BUMPED }, env), true);
});

// --- h2 (AC1): accept always stamps the EXACT currently-published version ---

test("h2: accept stamps the row with whatever version is CURRENTLY published, never a hardcoded one", async () => {
  const env = makeEnv({ TERMS_VERSION_OVERRIDE: BUMPED });
  const { token } = await mintToken(env, { uid: "42", name: "Ada" }, 600, { pendingConsent: true });

  const res = await call(env, authedRequest(`${BASE}/api/consent/accept`, token, { method: "POST" }));
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.consent.terms_version, BUMPED);
  assert.equal(env.DB.consents[0].terms_version, BUMPED);
});

// --- AC2(a): fresh sign-in by a previously-consented learner re-routes -----

test("web callback: a learner consented to a NOW-SUPERSEDED version lands pending-consent again, zero NEW D1 writes", async () => {
  const env = envWithGitHubUser({ id: 42, login: "ada", name: "Ada" }, { TERMS_VERSION_OVERRIDE: BUMPED });
  seedConsent(env, "42", TERMS_VERSION); // consented to the OLD version only

  const res = await call(env, webCallbackRequest());

  assert.equal(res.status, 302);
  assert.equal(res.headers.get("Location"), "https://agentculture.org/learn/consent/");
  assert.equal(env.DB.writes.length, 0, "no NEW row — a stale consent routes back to pending, same as first sign-in");
  assert.equal(env.DB.learners.size, 0, "learner row still not (re-)created");

  const me = await (await call(env, authedRequest(`${BASE}/api/me`, sessionCookieFrom(res)))).json();
  assert.equal(me.pending_consent, true);
  assert.equal(me.consent_required.terms_version, BUMPED);
});

test("device poll: a learner consented to a NOW-SUPERSEDED version gets consent_required again, zero NEW D1 writes", async () => {
  const env = envWithGitHubUser({ id: 42, login: "ada", name: "Ada" }, { TERMS_VERSION_OVERRIDE: BUMPED });
  seedConsent(env, "42", TERMS_VERSION);

  const res = await call(env, devicePollRequest());
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.status, "consent_required");
  assert.equal(body.consent_required.terms_version, BUMPED);
  assert.equal(env.DB.writes.length, 0, "no NEW row written before re-acceptance");
});

function sessionCookieFrom(res) {
  const c = res.headers.getSetCookie().find((v) => v.startsWith("session="));
  return c ? decodeURIComponent(c.split(";")[0].slice("session=".length)) : null;
}

// --- AC2(b): an existing, live full-session token gets walled off too ------

test("requireConsented: a live full-session token with stale consent 403s on progress, record, AND tutor — zero inference calls", async () => {
  const fetchStub = makeFetchStub({ [INFERENCE_URL]: () => jsonResp({ reply: "never" }) });
  const env = makeEnv({
    INFERENCE_URL,
    INFERENCE_TOKEN: "secret",
    FETCH: fetchStub,
    TERMS_VERSION_OVERRIDE: BUMPED,
  });
  seedConsent(env, "42", TERMS_VERSION); // consented to the version that is now superseded
  const { token } = await mintToken(env, { uid: "42", name: "Ada" }); // a LIVE, unexpired full session

  const progress = await call(env, authedRequest(`${BASE}/api/progress/french`, token));
  assert.equal(progress.status, 403);
  const progressBody = await progress.json();
  assert.equal(progressBody.error, "consent_required");
  assert.equal(progressBody.reason, "stale_version");
  assert.equal(progressBody.consent_required.terms_version, BUMPED);

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
  assert.equal((await record.json()).reason, "stale_version");

  const tutor = await call(
    env,
    authedRequest(`${BASE}/api/tutor`, token, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ subject: "french", messages: [] }),
    }),
  );
  assert.equal(tutor.status, 403);
  assert.equal((await tutor.json()).reason, "stale_version");

  // The resource-gate invariant holds for stale consent too: zero outbound
  // inference calls, and rejecting a request writes nothing.
  assert.equal(fetchStub.calls.length, 0, "inference endpoint must not be touched");
  assert.equal(env.DB.writes.length, 0, "a rejected stale-consent request writes nothing");
});

// --- AC3: the full cycle — consent v1 -> bump -> 403 -> re-accept -> 200 ---

test("full cycle: consent v1 -> bump TERMS_VERSION -> 403 -> re-accept -> 200 restores access", async () => {
  const env = makeEnv();

  // Step 1 — consent to v1 via the real accept flow.
  const { token: pendingTok } = await mintToken(env, { uid: "42", name: "Ada" }, 600, {
    pendingConsent: true,
  });
  const acceptV1 = await (
    await call(env, authedRequest(`${BASE}/api/consent/accept`, pendingTok, { method: "POST" }))
  ).json();
  assert.equal(acceptV1.consent.terms_version, TERMS_VERSION);
  const fullTokenV1 = acceptV1.token;

  // Sanity: access works pre-bump.
  assert.equal((await call(env, authedRequest(`${BASE}/api/progress/french`, fullTokenV1))).status, 200);

  // Step 2 — the published version bumps.
  env.TERMS_VERSION_OVERRIDE = BUMPED;

  // Step 3 — the SAME still-live token now 403s.
  const blocked = await call(env, authedRequest(`${BASE}/api/progress/french`, fullTokenV1));
  assert.equal(blocked.status, 403);
  const blockedBody = await blocked.json();
  assert.equal(blockedBody.reason, "stale_version");
  assert.equal(blockedBody.consent_required.terms_version, BUMPED);

  // Step 4 — re-accept. POST /api/consent/accept stays reachable throughout
  // (requireAuth, not requireConsented) precisely so this recovery path exists.
  const acceptV2 = await (
    await call(env, authedRequest(`${BASE}/api/consent/accept`, fullTokenV1, { method: "POST" }))
  ).json();
  assert.equal(acceptV2.consent.terms_version, BUMPED);
  const fullTokenV2 = acceptV2.token;

  // Step 5 — access is restored with the newly-issued token.
  const restored = await call(env, authedRequest(`${BASE}/api/progress/french`, fullTokenV2));
  assert.equal(restored.status, 200);

  // The old (v1) token was revoked on upgrade, same as t5's pending->full path.
  assert.equal((await call(env, authedRequest(`${BASE}/api/me`, fullTokenV1))).status, 401);

  // Two distinct version rows recorded for the same learner — the
  // append-only-per-version design from db.js (t2), not an overwrite.
  assert.deepEqual(
    env.DB.consents.map((c) => c.terms_version).sort(),
    [TERMS_VERSION, BUMPED].sort(),
  );
});

// --- AC4: /api/me reports, never walls off ----------------------------------

test("GET /api/me for a full session with stale consent reports reconsent_required (additive), never 403s", async () => {
  const env = makeEnv({ TERMS_VERSION_OVERRIDE: BUMPED });
  seedConsent(env, "42", TERMS_VERSION);
  const { token } = await mintToken(env, { uid: "42", name: "Ada" });

  const res = await call(env, authedRequest(`${BASE}/api/me`, token));
  assert.equal(res.status, 200, "/api/me reports the requirement instead of walling the learner off");
  const body = await res.json();
  assert.equal(body.authenticated, true);
  assert.equal(body.pending_consent, false);
  assert.equal(body.reconsent_required, true);
  assert.deepEqual(body.consent_required, consentRequirement(env));
  assert.equal(body.learner.github_user_id, "42");
});

test("GET /api/me: reconsent_required is false and consent_required is absent when consent is current", async () => {
  const env = makeEnv();
  seedConsent(env, "42", TERMS_VERSION);
  const { token } = await mintToken(env, { uid: "42", name: "Ada" });

  const res = await call(env, authedRequest(`${BASE}/api/me`, token));
  const body = await res.json();
  assert.equal(body.reconsent_required, false);
  assert.equal(body.consent_required, undefined, "additive field must not appear when consent is current");
  // Prior shape (pre-t6 fields) is intact.
  assert.equal(body.authenticated, true);
  assert.equal(body.pending_consent, false);
  assert.equal(body.learner.github_user_id, "42");
  assert.ok(body.session && typeof body.session.expires_at === "number");
});
