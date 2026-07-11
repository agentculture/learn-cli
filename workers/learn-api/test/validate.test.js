import { test } from "node:test";
import assert from "node:assert/strict";

import {
  validateRecorded,
  validateSubject,
  inferMastery,
  FORBIDDEN_RECORDED_FIELDS,
} from "../src/validate.js";

const goodRecorded = {
  item_id: "numbers-money",
  activity: "practice",
  exercise_id: "nm-p1",
  result: "pass",
  correct: 1,
  total: 1,
  duration_seconds: 38,
  at: "2026-07-11T10:00:00Z",
};

test("a well-formed recorded object validates", () => {
  assert.deepEqual(validateRecorded(goodRecorded), []);
});

test("subject pattern is enforced", () => {
  assert.deepEqual(validateSubject("french"), []);
  assert.deepEqual(validateSubject("culture-guide"), []);
  assert.ok(validateSubject("French").length > 0);
  assert.ok(validateSubject("1subject").length > 0);
  assert.ok(validateSubject(42).length > 0);
});

test("score / grade / points are structurally forbidden (record.json `not`)", () => {
  for (const field of FORBIDDEN_RECORDED_FIELDS) {
    const errors = validateRecorded({ ...goodRecorded, [field]: 99 });
    assert.ok(
      errors.some((e) => e.includes(field)),
      `expected ${field} to be rejected, got: ${JSON.stringify(errors)}`,
    );
  }
});

test("missing required fields are reported", () => {
  const errors = validateRecorded({ activity: "practice" });
  assert.ok(errors.some((e) => e.includes("item_id")));
  assert.ok(errors.some((e) => e.includes("result")));
  assert.ok(errors.some((e) => e.includes("at")));
});

test("enums are checked", () => {
  assert.ok(validateRecorded({ ...goodRecorded, activity: "quiz" }).length > 0);
  assert.ok(validateRecorded({ ...goodRecorded, result: "A+" }).length > 0);
});

test("numeric bounds match the schema (total >= 1, correct >= 0)", () => {
  assert.ok(validateRecorded({ ...goodRecorded, total: 0 }).length > 0);
  assert.ok(validateRecorded({ ...goodRecorded, correct: -1 }).length > 0);
  assert.ok(validateRecorded({ ...goodRecorded, duration_seconds: -1 }).length > 0);
});

test("non-object recorded is rejected", () => {
  assert.ok(validateRecorded(null).length > 0);
  assert.ok(validateRecorded("nope").length > 0);
  assert.ok(validateRecorded([]).length > 0);
});

test("mastery inference matches culture-guide's mapping", () => {
  assert.equal(inferMastery("pass"), "mastered");
  assert.equal(inferMastery("partial"), "practiced");
  assert.equal(inferMastery("fail"), "introduced");
  assert.equal(inferMastery("???"), "unknown");
});

// --- t3: cloze exercises (docs/specs/subject-plugin-contract.md §3.6.1) -----
//
// `recorded` carries no exercise-type/shape field, so a cloze item's result —
// whether the legacy single-blank free-text form or the new pick-the-right-
// word form (`text` + `blanks` live only on the PRACTICE/STORY exercise
// payload, never on `recorded`) — is an ORDINARY contract-valid record. No
// code change to this module was needed for cloze support; these tests prove
// it rather than assert it.

test("a cloze-originated record validates unchanged (no code change needed)", () => {
  // A 2-blank pick-the-right-word cloze exercise, one blank right: the driver
  // tallies into the pre-existing correct/total counters, exactly as any
  // other countable exercise would.
  const clozeRecorded = {
    item_id: "numbers-money",
    activity: "practice",
    exercise_id: "fr-p1-b1",
    result: "partial",
    correct: 1,
    total: 2,
    at: "2026-07-11T10:00:00Z",
  };
  assert.deepEqual(validateRecorded(clozeRecorded), []);
});

test("a legacy single-blank cloze record (no correct/total) also validates unchanged", () => {
  const legacyClozeRecorded = {
    item_id: "food-vocab",
    activity: "story",
    story_id: "fr-beg-le-marche-du-samedi",
    exercise_id: "marche-q3",
    result: "pass",
    at: "2026-07-11T10:05:00Z",
  };
  assert.deepEqual(validateRecorded(legacyClozeRecorded), []);
});
