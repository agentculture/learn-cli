// Unit tests for the consent data-layer functions in src/db.js
// (getConsent / recordConsent / deleteLearnerData). See schema.sql for the
// `consents` table this exercises: PRIMARY KEY (github_user_id, terms_version).
//
// No route wiring here (that's t5/t7) — these drive db.js directly against
// the D1Stub, the same way session.test.js drives session.js directly.

import { test } from "node:test";
import assert from "node:assert/strict";

import { getConsent, recordConsent, deleteLearnerData } from "../src/db.js";
import { makeEnv } from "./helpers.js";

// --- getConsent --------------------------------------------------------

test("getConsent returns null when the learner has no consent on file", async () => {
  const env = makeEnv();
  assert.equal(await getConsent(env, "42"), null);
});

test("getConsent returns the recorded consent after recordConsent", async () => {
  const env = makeEnv();
  await recordConsent(env, "42", "v1");
  const consent = await getConsent(env, "42");
  assert.equal(consent.github_user_id, "42");
  assert.equal(consent.terms_version, "v1");
  assert.match(
    consent.granted_at,
    /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/,
    "granted_at is server-time ISO-8601",
  );
});

test("getConsent coerces a numeric uid the same as a string uid", async () => {
  const env = makeEnv();
  await recordConsent(env, 42, "v1");
  const consent = await getConsent(env, "42");
  assert.equal(consent.github_user_id, "42");
});

test("getConsent returns the most recent row when multiple terms_versions are recorded", async () => {
  const env = makeEnv();
  // Seeded directly (not via recordConsent) so ordering is deterministic
  // rather than racing wall-clock granularity within one test.
  env.DB.consents.push(
    { github_user_id: "42", terms_version: "v1", granted_at: "2026-01-01T00:00:00.000Z" },
    { github_user_id: "42", terms_version: "v2", granted_at: "2026-06-01T00:00:00.000Z" },
  );
  const consent = await getConsent(env, "42");
  assert.equal(consent.terms_version, "v2", "most recent by granted_at, not insertion order");
});

test("getConsent is per-learner isolated", async () => {
  const env = makeEnv();
  await recordConsent(env, "42", "v1");
  assert.equal(await getConsent(env, "99"), null);
});

// --- recordConsent -------------------------------------------------------

test("recordConsent inserts one row per distinct (uid, terms_version)", async () => {
  const env = makeEnv();
  await recordConsent(env, "42", "v1");
  await recordConsent(env, "42", "v2");
  assert.equal(env.DB.consents.length, 2);
});

test("recordConsent re-granting the SAME version updates in place, does not duplicate", async () => {
  const env = makeEnv();
  await recordConsent(env, "42", "v1");
  await recordConsent(env, "42", "v1");
  assert.equal(env.DB.consents.length, 1, "same (uid, terms_version) must not duplicate the row");
});

test("recordConsent returns the recorded consent shape", async () => {
  const env = makeEnv();
  const result = await recordConsent(env, "42", "v1");
  assert.equal(result.github_user_id, "42");
  assert.equal(result.terms_version, "v1");
  assert.match(result.granted_at, /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/);
});

test("recordConsent is per-learner isolated", async () => {
  const env = makeEnv();
  await recordConsent(env, "42", "v1");
  await recordConsent(env, "99", "v1");
  assert.equal(env.DB.consents.length, 2);
  assert.equal((await getConsent(env, "42")).github_user_id, "42");
  assert.equal((await getConsent(env, "99")).github_user_id, "99");
});

// --- deleteLearnerData -----------------------------------------------------

test("deleteLearnerData removes the learner's records, consents, and learner row", async () => {
  const env = makeEnv();
  env.DB.learners.set("42", { github_user_id: "42", display_name: "Ada", state: "{}" });
  env.DB.records.push(
    { id: 1, github_user_id: "42", subject: "french", item_id: "a1" },
    { id: 2, github_user_id: "42", subject: "french", item_id: "a2" },
  );
  env.DB.consents.push({
    github_user_id: "42",
    terms_version: "v1",
    granted_at: "2026-01-01T00:00:00.000Z",
  });

  const result = await deleteLearnerData(env, "42");

  assert.deepEqual(result, { records: 2, consents: 1, learners: 1 });
  assert.equal(env.DB.learners.has("42"), false);
  assert.equal(env.DB.records.length, 0);
  assert.equal(env.DB.consents.length, 0);
});

test("deleteLearnerData is per-learner isolated: another learner's rows survive", async () => {
  const env = makeEnv();
  env.DB.learners.set("42", { github_user_id: "42", display_name: "Ada", state: "{}" });
  env.DB.learners.set("99", { github_user_id: "99", display_name: "Linus", state: "{}" });
  env.DB.records.push(
    { id: 1, github_user_id: "42", subject: "french", item_id: "a1" },
    { id: 2, github_user_id: "99", subject: "french", item_id: "b1" },
  );
  env.DB.consents.push(
    { github_user_id: "42", terms_version: "v1", granted_at: "2026-01-01T00:00:00.000Z" },
    { github_user_id: "99", terms_version: "v1", granted_at: "2026-01-01T00:00:00.000Z" },
  );

  const result = await deleteLearnerData(env, "42");

  assert.deepEqual(result, { records: 1, consents: 1, learners: 1 });
  assert.equal(env.DB.learners.has("99"), true);
  assert.equal(env.DB.records.length, 1);
  assert.equal(env.DB.records[0].github_user_id, "99");
  assert.equal(env.DB.consents.length, 1);
  assert.equal(env.DB.consents[0].github_user_id, "99");
});

test("deleteLearnerData on an unknown learner is a no-op that returns zero counts", async () => {
  const env = makeEnv();
  const result = await deleteLearnerData(env, "does-not-exist");
  assert.deepEqual(result, { records: 0, consents: 0, learners: 0 });
});

test("deleteLearnerData deletes records and consents before the learners row (FK-safe order)", async () => {
  const env = makeEnv();
  const order = [];
  const realBatch = env.DB.batch.bind(env.DB);
  env.DB.batch = async (statements) => {
    for (const stmt of statements) order.push(stmt.sql);
    return realBatch(statements);
  };
  env.DB.learners.set("42", { github_user_id: "42", display_name: "Ada", state: "{}" });

  await deleteLearnerData(env, "42");

  const learnersIdx = order.findIndex((s) => s.includes("delete from learners"));
  const recordsIdx = order.findIndex((s) => s.includes("delete from records"));
  const consentsIdx = order.findIndex((s) => s.includes("delete from consents"));
  assert.ok(recordsIdx >= 0 && recordsIdx < learnersIdx, "records deleted before learners");
  assert.ok(consentsIdx >= 0 && consentsIdx < learnersIdx, "consents deleted before learners");
});

test("deleteLearnerData revokes nothing beyond D1 rows (session revocation is t7's job)", async () => {
  // Documents the boundary: this function only ever touches env.DB. Session
  // tombstoning (env.SESSIONS) on withdrawal is wired by t7 at the route
  // layer, not here.
  const env = makeEnv();
  env.DB.learners.set("42", { github_user_id: "42", display_name: "Ada", state: "{}" });
  const sessionsBefore = env.SESSIONS.map.size;
  await deleteLearnerData(env, "42");
  assert.equal(env.SESSIONS.map.size, sessionsBefore, "deleteLearnerData does not touch KV");
});
