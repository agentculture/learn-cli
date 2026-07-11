// Payload validation mirroring the subject-plugin contract v1.0 schemas.
//
// The API stores exactly the `recorded` object that `record.json` defines and
// applies the SAME structural rules the schema does — most importantly the
// `not` clause that forbids `score`/`grade`/`points`. Subjects report raw
// observations only; derived numbers (scores, streaks) are learn-cli's
// motivation layer, computed later from the ledger. Rejecting these fields at
// the door keeps the ledger clean.
//
// Kept deliberately in sync (by hand + by test) with:
//   learn/contract/schemas/record.json  ->  properties.recorded
//
// Cloze exercises (t3, docs/specs/subject-plugin-contract.md §3.6.1): this
// file needs NO change for the pick-the-right-word cloze variant. `recorded`
// carries no exercise-type/shape field at all — a cloze result is recorded
// exactly like any other exercise's result, via `activity` (unchanged:
// lesson|practice|story) plus the pre-existing `correct`/`total` counters,
// which a multi-blank cloze tallies into naturally (e.g. one right of two
// blanks records `correct: 1, total: 2`). See validate.test.js's
// "a cloze-originated record validates unchanged" for the proof.

export const CONTRACT_VERSION = "1.0";
export const SCHEMA_VERSION_RE = /^1\.[0-9]+$/;
export const SUBJECT_RE = /^[a-z][a-z0-9-]*$/;
export const ACTIVITIES = ["lesson", "practice", "story"];
export const RESULTS = ["pass", "partial", "fail"];
export const MASTERY_LEVELS = ["unknown", "introduced", "practiced", "mastered"];
export const FORBIDDEN_RECORDED_FIELDS = ["score", "grade", "points"];

/**
 * Validate a subject id against the contract's `^[a-z][a-z0-9-]*$` pattern.
 * @returns {string[]} error messages (empty === valid).
 */
export function validateSubject(subject) {
  if (typeof subject !== "string" || !SUBJECT_RE.test(subject)) {
    return [`subject must match ${SUBJECT_RE} (got ${JSON.stringify(subject)})`];
  }
  return [];
}

/**
 * Validate the `recorded` object exactly as record.json's sub-schema does.
 * @returns {string[]} error messages (empty === valid).
 */
export function validateRecorded(recorded) {
  const errors = [];
  if (recorded === null || typeof recorded !== "object" || Array.isArray(recorded)) {
    return ["recorded must be an object"];
  }

  // Structural prohibition (record.json `not.anyOf` required score/grade/points).
  for (const field of FORBIDDEN_RECORDED_FIELDS) {
    if (Object.prototype.hasOwnProperty.call(recorded, field)) {
      errors.push(
        `recorded.${field} is forbidden — subjects report raw results only, ` +
          "never derived numbers (score/grade/points)",
      );
    }
  }

  // Required fields.
  for (const key of ["item_id", "activity", "result", "at"]) {
    if (!Object.prototype.hasOwnProperty.call(recorded, key)) {
      errors.push(`recorded.${key} is required`);
    }
  }

  // Field-level checks (only when present).
  if (recorded.item_id !== undefined && !isNonEmptyString(recorded.item_id)) {
    errors.push("recorded.item_id must be a non-empty string");
  }
  if (recorded.activity !== undefined && !ACTIVITIES.includes(recorded.activity)) {
    errors.push(`recorded.activity must be one of ${ACTIVITIES.join("|")}`);
  }
  if (recorded.result !== undefined && !RESULTS.includes(recorded.result)) {
    errors.push(`recorded.result must be one of ${RESULTS.join("|")}`);
  }
  if (recorded.at !== undefined && !isNonEmptyString(recorded.at)) {
    errors.push("recorded.at must be a non-empty (ISO-8601) string");
  }
  if (recorded.correct !== undefined && !isNonNegativeInt(recorded.correct)) {
    errors.push("recorded.correct must be an integer >= 0");
  }
  if (recorded.total !== undefined && !(isNonNegativeInt(recorded.total) && recorded.total >= 1)) {
    errors.push("recorded.total must be an integer >= 1");
  }
  if (
    recorded.duration_seconds !== undefined &&
    !(typeof recorded.duration_seconds === "number" && recorded.duration_seconds >= 0)
  ) {
    errors.push("recorded.duration_seconds must be a number >= 0");
  }
  for (const key of ["exercise_id", "story_id", "lesson_id", "notes"]) {
    if (recorded[key] !== undefined && typeof recorded[key] !== "string") {
      errors.push(`recorded.${key} must be a string`);
    }
  }
  return errors;
}

/** Infer post-record mastery from a raw result (never regresses on inference). */
export function inferMastery(result) {
  switch (result) {
    case "pass":
      return "mastered";
    case "partial":
      return "practiced";
    case "fail":
      return "introduced";
    default:
      return "unknown";
  }
}

function isNonEmptyString(v) {
  return typeof v === "string" && v.length > 0;
}

function isNonNegativeInt(v) {
  return typeof v === "number" && Number.isInteger(v) && v >= 0;
}
