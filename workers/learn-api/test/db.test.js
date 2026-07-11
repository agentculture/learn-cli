// Unit tests for the consent data-layer functions in src/db.js
// (getConsent / recordConsent / deleteLearnerData). See schema.sql for the
// `consents` table this exercises: PRIMARY KEY (github_user_id, terms_version).
//
// No route wiring here (that's t5/t7) — these drive db.js directly against
// the D1Stub, the same way session.test.js drives session.js directly.

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  getConsent,
  recordConsent,
  deleteLearnerData,
  listAllRecords,
  listConsents,
  listAllLearners,
  setLearnerVisibility,
  setLearnerVoiceUsage,
  getLearner,
} from "../src/db.js";
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

// --- listAllRecords (t7) ----------------------------------------------

test("listAllRecords returns rows across EVERY subject, oldest first", async () => {
  const env = makeEnv();
  env.DB.records.push(
    { id: 1, github_user_id: "42", subject: "french", item_id: "a1", recorded: '{"item_id":"a1"}',
      mastery_level: "mastered", activity: "practice", result: "pass", at: "2026-01-01T00:00:00Z" },
    { id: 2, github_user_id: "42", subject: "spanish", item_id: "b1", recorded: '{"item_id":"b1"}',
      mastery_level: "practiced", activity: "lesson", result: "partial", at: "2026-02-01T00:00:00Z" },
    { id: 3, github_user_id: "99", subject: "french", item_id: "c1", recorded: '{"item_id":"c1"}',
      mastery_level: "mastered", activity: "practice", result: "pass", at: "2026-01-05T00:00:00Z" },
  );
  const rows = await listAllRecords(env, "42");
  assert.equal(rows.length, 2, "isolated to the requested learner, both subjects included");
  assert.deepEqual(rows.map((r) => r.subject), ["french", "spanish"]);
  assert.deepEqual(rows.map((r) => r.item_id), ["a1", "b1"]);
});

test("listAllRecords returns an empty array for a learner with no records", async () => {
  const env = makeEnv();
  assert.deepEqual(await listAllRecords(env, "42"), []);
});

// --- listConsents (t7) --------------------------------------------------

test("listConsents returns EVERY accepted version, oldest first (unlike getConsent's latest-only)", async () => {
  const env = makeEnv();
  await recordConsent(env, "42", "1.0.0");
  await recordConsent(env, "42", "1.1.0");
  const rows = await listConsents(env, "42");
  assert.equal(rows.length, 2);
  assert.deepEqual(rows.map((r) => r.terms_version), ["1.0.0", "1.1.0"]);
});

test("listConsents is per-learner isolated and empty for an unknown learner", async () => {
  const env = makeEnv();
  await recordConsent(env, "42", "1.0.0");
  assert.deepEqual(await listConsents(env, "99"), []);
});

// --- listAllLearners (t8) -----------------------------------------------

test("listAllLearners: empty when there are no learners", async () => {
  const env = makeEnv();
  assert.deepEqual(await listAllLearners(env), []);
});

test("listAllLearners: default visibility is 'private' when the state has no visibility key", async () => {
  const env = makeEnv();
  env.DB.learners.set("42", { github_user_id: "42", display_name: "Ada", state: "{}" });
  const [row] = await listAllLearners(env);
  assert.equal(row.visibility, "private");
});

test("listAllLearners: reports a learner's OWN visibility field", async () => {
  const env = makeEnv();
  env.DB.learners.set("42", {
    github_user_id: "42",
    display_name: "Ada",
    state: JSON.stringify({ visibility: "public" }),
  });
  const [row] = await listAllLearners(env);
  assert.equal(row.visibility, "public");
});

test("listAllLearners: per-subject record counts, no cross-learner bleed", async () => {
  const env = makeEnv();
  env.DB.learners.set("42", { github_user_id: "42", display_name: "Ada", state: "{}" });
  env.DB.learners.set("99", { github_user_id: "99", display_name: "Linus", state: "{}" });
  env.DB.records.push(
    { id: 1, github_user_id: "42", subject: "french", item_id: "a1" },
    { id: 2, github_user_id: "42", subject: "french", item_id: "a2" },
    { id: 3, github_user_id: "42", subject: "spanish", item_id: "b1" },
    { id: 4, github_user_id: "99", subject: "french", item_id: "c1" },
  );
  const rows = await listAllLearners(env);
  const ada = rows.find((r) => r.github_user_id === "42");
  const linus = rows.find((r) => r.github_user_id === "99");
  assert.deepEqual(ada.records, { french: 2, spanish: 1 });
  assert.equal(ada.records_total, 3);
  assert.deepEqual(linus.records, { french: 1 });
  assert.equal(linus.records_total, 1);
});

test("listAllLearners: reports each learner's most recent consent row, or null", async () => {
  const env = makeEnv();
  env.DB.learners.set("42", { github_user_id: "42", display_name: "Ada", state: "{}" });
  env.DB.learners.set("7", { github_user_id: "7", display_name: "NoConsent", state: "{}" });
  env.DB.consents.push(
    { github_user_id: "42", terms_version: "1.0.0", granted_at: "2026-01-01T00:00:00.000Z" },
    { github_user_id: "42", terms_version: "1.1.0", granted_at: "2026-06-01T00:00:00.000Z" },
  );
  const rows = await listAllLearners(env);
  const ada = rows.find((r) => r.github_user_id === "42");
  const noConsent = rows.find((r) => r.github_user_id === "7");
  assert.deepEqual(ada.consent, { terms_version: "1.1.0", granted_at: "2026-06-01T00:00:00.000Z" });
  assert.equal(noConsent.consent, null);
});

test("listAllLearners: three D1 reads regardless of learner count (no N+1)", async () => {
  const env = makeEnv();
  for (let i = 0; i < 10; i += 1) {
    env.DB.learners.set(String(i), { github_user_id: String(i), display_name: `L${i}`, state: "{}" });
  }
  let prepareCalls = 0;
  const realPrepare = env.DB.prepare.bind(env.DB);
  env.DB.prepare = (sql) => {
    prepareCalls += 1;
    return realPrepare(sql);
  };
  await listAllLearners(env);
  assert.equal(prepareCalls, 3, "one learners read, one grouped records read, one consents read");
});

// --- setLearnerVisibility (t8) --------------------------------------------

test("setLearnerVisibility: sets the field and getLearner reflects it", async () => {
  const env = makeEnv();
  env.DB.learners.set("42", { github_user_id: "42", display_name: "Ada", state: "{}" });
  await setLearnerVisibility(env, "42", "public");
  const learner = await getLearner(env, "42");
  assert.equal(learner.state.visibility, "public");
});

test("setLearnerVisibility: merges into existing state, does not clobber other fields", async () => {
  const env = makeEnv();
  env.DB.learners.set("42", {
    github_user_id: "42",
    display_name: "Ada",
    state: JSON.stringify({ keep: "me" }),
  });
  await setLearnerVisibility(env, "42", "public");
  const learner = await getLearner(env, "42");
  assert.equal(learner.state.keep, "me");
  assert.equal(learner.state.visibility, "public");
});

test("setLearnerVisibility: is per-learner isolated", async () => {
  const env = makeEnv();
  env.DB.learners.set("42", { github_user_id: "42", display_name: "Ada", state: "{}" });
  env.DB.learners.set("99", { github_user_id: "99", display_name: "Linus", state: "{}" });
  await setLearnerVisibility(env, "42", "public");
  const linus = await getLearner(env, "99");
  assert.equal(Object.prototype.hasOwnProperty.call(linus.state, "visibility"), false);
});

// --- getLearner: updated_at (t16 follow-up, Qodo BUG 3) --------------------

test("getLearner exposes updated_at — the version stamp the voice-budget CAS write needs", async () => {
  const env = makeEnv();
  env.DB.learners.set("42", {
    github_user_id: "42",
    display_name: "Ada",
    state: "{}",
    updated_at: "2026-01-01T00:00:00.000Z",
  });
  const learner = await getLearner(env, "42");
  assert.equal(learner.updated_at, "2026-01-01T00:00:00.000Z");
});

// --- setLearnerVoiceUsage: compare-and-swap (Qodo BUG 3) --------------------
//
// The voice-budget race (index.js#handleVoiceToken read `used`, checked the
// cap, then wrote via a plain read-then-write): two concurrent mints could
// both pass the check and both write, exceeding VOICE_MONTHLY_SECONDS_CAP.
// The fix makes the WRITE itself conditional on the row not having changed
// since the caller read it — these tests drive that primitive directly,
// independent of any real concurrency/timing, the same way session.test.js
// drives session.js directly rather than through the route layer.

test("setLearnerVoiceUsage: a matching expectedUpdatedAt writes and reports ok:true", async () => {
  const env = makeEnv();
  const stamp = "2026-07-01T00:00:00.000Z";
  env.DB.learners.set("42", { github_user_id: "42", display_name: "Ada", state: "{}", updated_at: stamp });

  const result = await setLearnerVoiceUsage(
    env,
    "42",
    { month: "2026-07", seconds_minted: 300 },
    {},
    stamp,
  );
  assert.equal(result.ok, true);
  const learner = await getLearner(env, "42");
  assert.equal(learner.state.voice_usage.seconds_minted, 300);
  assert.notEqual(learner.updated_at, stamp, "a successful write stamps a NEW updated_at");
});

test("setLearnerVoiceUsage: a stale expectedUpdatedAt is refused (ok:false) and writes NOTHING — the CAS primitive the race fix relies on", async () => {
  const env = makeEnv();
  const original = "2026-01-01T00:00:00.000Z";
  env.DB.learners.set("42", { github_user_id: "42", display_name: "Ada", state: "{}", updated_at: original });

  // Two concurrent bookers who both read the SAME `updated_at` — simulated
  // directly, no timing/Promise.all needed: this IS the exact primitive
  // index.js#bookVoiceUsage's retry loop depends on.
  const first = await setLearnerVoiceUsage(
    env,
    "42",
    { month: "2026-07", seconds_minted: 300 },
    {},
    original,
  );
  assert.equal(first.ok, true, "the first writer to reach D1 wins");

  const second = await setLearnerVoiceUsage(
    env,
    "42",
    { month: "2026-07", seconds_minted: 600 },
    {},
    original, // still holding the now-STALE updated_at
  );
  assert.equal(second.ok, false, "the second writer loses the race — its expected version is gone");

  // The loser's write never landed: the learner reflects ONLY the winner's
  // booking (300s), never the loser's (600s) and never both summed/clobbered.
  const learner = await getLearner(env, "42");
  assert.equal(learner.state.voice_usage.seconds_minted, 300);
});

test("setLearnerVoiceUsage: merges the usage write into the passed baseState, same merge contract as setLearnerVisibility/setLearnerApproved", async () => {
  const env = makeEnv();
  const stamp = "2026-07-01T00:00:00.000Z";
  env.DB.learners.set("42", {
    github_user_id: "42",
    display_name: "Ada",
    state: JSON.stringify({ approved: true, visibility: "public" }),
    updated_at: stamp,
  });
  const learner = await getLearner(env, "42");

  const result = await setLearnerVoiceUsage(
    env,
    "42",
    { month: "2026-07", seconds_minted: 300 },
    learner.state,
    learner.updated_at,
  );
  assert.equal(result.ok, true);
  const updated = await getLearner(env, "42");
  assert.equal(updated.state.approved, true, "unrelated state fields survive the usage write");
  assert.equal(updated.state.visibility, "public");
  assert.equal(updated.state.voice_usage.seconds_minted, 300);
});

test("setLearnerVoiceUsage: is per-learner isolated", async () => {
  const env = makeEnv();
  const stamp = "2026-07-01T00:00:00.000Z";
  env.DB.learners.set("42", { github_user_id: "42", display_name: "Ada", state: "{}", updated_at: stamp });
  env.DB.learners.set("99", { github_user_id: "99", display_name: "Linus", state: "{}", updated_at: stamp });

  await setLearnerVoiceUsage(env, "42", { month: "2026-07", seconds_minted: 300 }, {}, stamp);

  const linus = await getLearner(env, "99");
  assert.equal(Object.prototype.hasOwnProperty.call(linus.state, "voice_usage"), false);
});

test("getConsent: same-millisecond re-consent tie resolves to the newest row (rowid tiebreak)", async () => {
  const env = makeEnv();
  const now = "2026-07-11T10:00:00.000Z";
  // Two versions granted in the same millisecond — the newer insert must win.
  env.DB.consents.push(
    { github_user_id: "42", terms_version: "1.0.0", granted_at: now },
    { github_user_id: "42", terms_version: "1.1.0", granted_at: now },
  );
  const consent = await getConsent(env, "42");
  assert.strictEqual(consent.terms_version, "1.1.0");
});
