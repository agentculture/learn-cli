// Admin allow-list + admin list-all surface (spec c12/h4, task t8).
//
// h4 verbatim: "Admin capability is enforced server-side against the
// GitHub-id allow-list (a non-allow-listed session calling an admin route
// gets 403 regardless of any client claim), and no authed route ever
// returns another learner's data to a non-admin". This file proves the
// first half; test/visibility.test.js's isolation tests (plus the existing
// per-learner scoping already proven in worker.test.js/export-delete.test.js)
// prove the second.

import { test } from "node:test";
import assert from "node:assert/strict";

import worker from "../src/index.js";
import { TERMS_VERSION } from "../src/terms.js";
import { isAdmin } from "../src/admin.js";
import { makeEnv, mintToken, authedRequest, seedConsent } from "./helpers.js";

const BASE = "https://learn-api.example";

function call(env, request) {
  return worker.fetch(request, env, { waitUntil() {} });
}

// --- isAdmin() unit tests ---------------------------------------------------

test("isAdmin: true for a uid present in ADMIN_GITHUB_IDS", () => {
  const env = makeEnv({ ADMIN_GITHUB_IDS: "20955789" });
  assert.equal(isAdmin(env, "20955789"), true);
  assert.equal(isAdmin(env, 20955789), true, "coerces a numeric uid");
});

test("isAdmin: false for a uid not on the list", () => {
  const env = makeEnv({ ADMIN_GITHUB_IDS: "20955789" });
  assert.equal(isAdmin(env, "1"), false);
});

test("isAdmin: parses a comma-separated list with incidental whitespace", () => {
  const env = makeEnv({ ADMIN_GITHUB_IDS: " 1, 2 ,3" });
  assert.equal(isAdmin(env, "1"), true);
  assert.equal(isAdmin(env, "2"), true);
  assert.equal(isAdmin(env, "3"), true);
  assert.equal(isAdmin(env, "4"), false);
});

test("isAdmin: false when ADMIN_GITHUB_IDS is unset/empty", () => {
  assert.equal(isAdmin(makeEnv(), "20955789"), false);
  assert.equal(isAdmin(makeEnv({ ADMIN_GITHUB_IDS: "" }), "20955789"), false);
});

// --- GET /api/admin/learners: the allow-list gate ---------------------------

test("admin route: signed-out request -> 401 (no admin check even reached)", async () => {
  const env = makeEnv({ ADMIN_GITHUB_IDS: "1" });
  const res = await call(env, new Request(`${BASE}/api/admin/learners`));
  assert.equal(res.status, 401);
});

test("admin route: pending-consent session -> 403 consent_required, never reaches the admin check", async () => {
  const env = makeEnv({ ADMIN_GITHUB_IDS: "42" });
  const { token } = await mintToken(env, { uid: "42", name: "Ada" }, 3600, { pendingConsent: true });
  const res = await call(env, authedRequest(`${BASE}/api/admin/learners`, token));
  assert.equal(res.status, 403);
  assert.equal((await res.json()).error, "consent_required");
});

test("admin route: consented but NOT on the allow-list -> 403 admin_required", async () => {
  const env = makeEnv({ ADMIN_GITHUB_IDS: "20955789" });
  seedConsent(env, "42", TERMS_VERSION);
  const { token } = await mintToken(env, { uid: "42", name: "Ada" });
  const res = await call(env, authedRequest(`${BASE}/api/admin/learners`, token));
  assert.equal(res.status, 403);
  const body = await res.json();
  assert.equal(body.error, "admin_required");
});

test("admin route: a forged client-side admin claim (body flag, header) is IGNORED — still 403 (h4)", async () => {
  const env = makeEnv({ ADMIN_GITHUB_IDS: "20955789" });
  seedConsent(env, "42", TERMS_VERSION);
  const { token } = await mintToken(env, { uid: "42", name: "Ada" });

  const req = authedRequest(`${BASE}/api/admin/learners?admin=true`, token, {
    headers: { "X-Admin": "true", "X-Is-Admin": "1" },
  });
  const res = await call(env, req);
  assert.equal(res.status, 403, "query string / header claims must not grant admin");
  assert.equal((await res.json()).error, "admin_required");
});

test("admin route: allow-listed AND consented -> 200", async () => {
  const env = makeEnv({ ADMIN_GITHUB_IDS: "20955789" });
  seedConsent(env, "20955789", TERMS_VERSION);
  const { token } = await mintToken(env, { uid: "20955789", name: "OriNachum" });
  const res = await call(env, authedRequest(`${BASE}/api/admin/learners`, token));
  assert.equal(res.status, 200);
});

test("admin route: stale-consent admin session is walled off same as any other requireConsented route", async () => {
  const BUMPED = "2.0.0";
  const env = makeEnv({ ADMIN_GITHUB_IDS: "20955789", TERMS_VERSION_OVERRIDE: BUMPED });
  seedConsent(env, "20955789", TERMS_VERSION); // stale — consented to the superseded version
  const { token } = await mintToken(env, { uid: "20955789", name: "OriNachum" });
  const res = await call(env, authedRequest(`${BASE}/api/admin/learners`, token));
  assert.equal(res.status, 403);
  const body = await res.json();
  assert.equal(body.error, "consent_required");
  assert.equal(body.reason, "stale_version");
});

// --- GET /api/admin/learners: the payload shape -----------------------------

test("admin route: lists every learner with a per-subject record-count summary, no N+1", async () => {
  const env = makeEnv({ ADMIN_GITHUB_IDS: "1" });
  seedConsent(env, "1", TERMS_VERSION, "2026-01-01T00:00:00.000Z");
  seedConsent(env, "2", TERMS_VERSION, "2026-02-01T00:00:00.000Z");
  env.DB.learners.set("1", {
    github_user_id: "1",
    display_name: "Admin",
    state: "{}",
    created_at: "2026-01-01T00:00:00.000Z",
  });
  env.DB.learners.set("2", {
    github_user_id: "2",
    display_name: "Ada",
    state: JSON.stringify({ visibility: "public" }),
    created_at: "2026-02-01T00:00:00.000Z",
  });
  env.DB.records.push(
    { id: 1, github_user_id: "2", subject: "french", item_id: "a1" },
    { id: 2, github_user_id: "2", subject: "french", item_id: "a2" },
    { id: 3, github_user_id: "2", subject: "spanish", item_id: "b1" },
  );
  const { token } = await mintToken(env, { uid: "1", name: "Admin" });

  const res = await call(env, authedRequest(`${BASE}/api/admin/learners`, token));
  assert.equal(res.status, 200);
  const body = await res.json();

  assert.equal(body.kind, "admin_learners");
  assert.equal(body.schema_version, "1.0");
  assert.equal(body.count, 2);
  assert.equal(body.learners.length, 2);

  const ada = body.learners.find((l) => l.github_user_id === "2");
  assert.equal(ada.display_name, "Ada");
  assert.equal(ada.visibility, "public");
  assert.equal(ada.consent.terms_version, TERMS_VERSION);
  assert.equal(ada.consent_status, "current");
  assert.deepEqual(ada.records, { french: 2, spanish: 1 });
  assert.equal(ada.records_total, 3);

  const admin = body.learners.find((l) => l.github_user_id === "1");
  assert.equal(admin.visibility, "private", "default-private, absent field");
  assert.deepEqual(admin.records, {}, "no records recorded for this learner");
  assert.equal(admin.records_total, 0);
});

test("admin route: a learner with no consent row on file is reported consent_status 'none'", async () => {
  const env = makeEnv({ ADMIN_GITHUB_IDS: "1" });
  seedConsent(env, "1", TERMS_VERSION);
  env.DB.learners.set("1", { github_user_id: "1", display_name: "Admin", state: "{}" });
  // A learner row with no matching consents row (shouldn't normally happen
  // given the consent-gate invariant, but the admin read must not crash).
  env.DB.learners.set("3", { github_user_id: "3", display_name: "Orphan", state: "{}" });
  const { token } = await mintToken(env, { uid: "1", name: "Admin" });

  const body = await (await call(env, authedRequest(`${BASE}/api/admin/learners`, token))).json();
  const orphan = body.learners.find((l) => l.github_user_id === "3");
  assert.equal(orphan.consent, null);
  assert.equal(orphan.consent_status, "none");
});

test("admin route: a stale (superseded-version) consent is reported consent_status 'stale'", async () => {
  const BUMPED = "2.0.0";
  const env = makeEnv({ ADMIN_GITHUB_IDS: "1", TERMS_VERSION_OVERRIDE: BUMPED });
  seedConsent(env, "1", BUMPED);
  seedConsent(env, "2", TERMS_VERSION); // superseded
  env.DB.learners.set("1", { github_user_id: "1", display_name: "Admin", state: "{}" });
  env.DB.learners.set("2", { github_user_id: "2", display_name: "Ada", state: "{}" });
  const { token } = await mintToken(env, { uid: "1", name: "Admin" });

  const body = await (await call(env, authedRequest(`${BASE}/api/admin/learners`, token))).json();
  const ada = body.learners.find((l) => l.github_user_id === "2");
  assert.equal(ada.consent_status, "stale");
});
