// Derive a contract `progress.json`-shaped payload from the ledger rows.
//
// The API does NOT own subject content, so it cannot know `items_total` (the
// authoritative count is the subject CLI's own `progress`/`overview`). What the
// API owns is the recorded-result ledger, so it reports LEDGER COVERAGE: which
// items the learner has touched and their highest mastery so far. Consumers
// that need the authoritative totals read the subject CLI directly; this
// endpoint is the cross-device, signed-in view of what the learner has done.
//
// Mirrors learn/contract/schemas/progress.json (kind "progress", schema 1.0).

import { CONTRACT_VERSION, MASTERY_LEVELS, inferMastery } from "./validate.js";

const RANK = Object.fromEntries(MASTERY_LEVELS.map((lvl, i) => [lvl, i]));

/** Higher of two mastery levels (mastery never regresses across the ledger). */
function maxMastery(a, b) {
  if (!a) return b;
  if (!b) return a;
  return (RANK[a] ?? 0) >= (RANK[b] ?? 0) ? a : b;
}

/**
 * Build the progress payload for one learner + subject from ledger rows.
 * @param {string} subject
 * @param {string} learner  resolved learner id (the GitHub user id)
 * @param {Array}  rows     ledger rows from db.listRecords()
 */
export function deriveProgress(subject, learner, rows) {
  const mastery = {};
  let started_at;
  let last_seen_at;
  let current = null;

  for (const row of rows) {
    const item = row.item_id;
    const level = row.mastery_level || inferMastery(row.result);
    mastery[item] = maxMastery(mastery[item], level);
    if (!started_at || row.at < started_at) started_at = row.at;
    if (!last_seen_at || row.at >= last_seen_at) {
      last_seen_at = row.at;
      current = { item_id: item };
    }
  }

  const touched = Object.keys(mastery);
  const completed = touched.filter((id) => mastery[id] === "mastered");
  const weak = touched
    .filter((id) => mastery[id] !== "mastered")
    .map((id) => ({ item_id: id, mastery: mastery[id] }));

  const done = touched.length > 0 && weak.length === 0;
  const next = done
    ? {
        done: true,
        text: "Every touched item is mastered here — switch to review + depth mode.",
        command: `learn progress ${subject}`,
      }
    : {
        done: false,
        text: "Continue this subject; the subject CLI resolves the exact next step.",
        command: `learn lesson ${subject} next`,
      };

  return {
    schema_version: CONTRACT_VERSION,
    kind: "progress",
    subject,
    learner: String(learner),
    started_at,
    last_seen_at,
    current,
    // Ledger coverage — authoritative totals come from the subject CLI.
    items_total: touched.length,
    items_touched: touched.length,
    items_mastered: completed.length,
    completed,
    mastery,
    weak,
    next,
  };
}
