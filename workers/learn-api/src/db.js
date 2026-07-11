// D1 data access — the cross-subject learner ledger.
//
// Three tables (see schema.sql):
//   learners  — one row per GitHub user: id, display name, learner-state JSON.
//               NO password, NO email. This is the entire persisted identity.
//   records   — APPEND-ONLY ledger of recorded results, keyed by
//               (github_user_id, subject, item_id). Never UPDATEd, never
//               DELETEd — the motivation layer (t9) reduces over the full
//               history, so every raw observation is kept.
//   consents  — one row per (github_user_id, terms_version) accepted, with a
//               server-time granted_at. This is the resource gate: no other
//               table is written for a learner until a consent row exists
//               for the currently published terms_version (t5 wires the
//               gate; this module only provides the data-layer functions).
//
// All access goes through the D1 binding `env.DB` (prepare/bind/run/all/first,
// plus batch for the multi-statement delete), so tests swap in an in-memory
// D1 stub with the same surface.

/** Upsert a learner's identity. Only id + display name are written on login. */
export async function upsertLearner(env, learner) {
  const now = new Date().toISOString();
  await env.DB.prepare(
    `INSERT INTO learners (github_user_id, display_name, state, created_at, updated_at)
     VALUES (?, ?, '{}', ?, ?)
     ON CONFLICT(github_user_id) DO UPDATE SET display_name = ?, updated_at = ?`,
  )
    .bind(String(learner.uid), learner.name, now, now, learner.name, now)
    .run();
}

/** Read a learner's identity + state, or null if unknown. */
export async function getLearner(env, uid) {
  const row = await env.DB.prepare(
    `SELECT github_user_id, display_name, state FROM learners WHERE github_user_id = ?`,
  )
    .bind(String(uid))
    .first();
  if (!row) return null;
  let state = {};
  try {
    state = row.state ? JSON.parse(row.state) : {};
  } catch {
    state = {};
  }
  return { github_user_id: row.github_user_id, display_name: row.display_name, state };
}

/** Append one recorded result to the ledger. Insert-only. */
export async function insertRecord(env, { uid, subject, recorded, masteryLevel }) {
  const now = new Date().toISOString();
  const res = await env.DB.prepare(
    `INSERT INTO records
       (github_user_id, subject, item_id, recorded, mastery_level, activity, result, at, created_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
  )
    .bind(
      String(uid),
      subject,
      recorded.item_id,
      JSON.stringify(recorded),
      masteryLevel || null,
      recorded.activity,
      recorded.result,
      recorded.at,
      now,
    )
    .run();
  return res && res.meta ? res.meta.last_row_id : undefined;
}

/** List every recorded result for a learner+subject, oldest first. */
export async function listRecords(env, uid, subject) {
  const out = await env.DB.prepare(
    `SELECT recorded, mastery_level, item_id, activity, result, at
       FROM records
      WHERE github_user_id = ? AND subject = ?
      ORDER BY id ASC`,
  )
    .bind(String(uid), subject)
    .all();
  return (out && out.results) || [];
}

/** Read a learner's most recent consent row (by granted_at), or null. */
export async function getConsent(env, uid) {
  const row = await env.DB.prepare(
    `SELECT github_user_id, terms_version, granted_at
       FROM consents
      WHERE github_user_id = ?
      ORDER BY granted_at DESC
      LIMIT 1`,
  )
    .bind(String(uid))
    .first();
  if (!row) return null;
  return {
    github_user_id: row.github_user_id,
    terms_version: row.terms_version,
    granted_at: row.granted_at,
  };
}

/**
 * Record a learner's consent to a terms version (server time, ISO-8601).
 * Re-granting the SAME version updates granted_at in place rather than
 * inserting a duplicate row; a different terms_version always inserts a new
 * row (re-consent, t6).
 */
export async function recordConsent(env, uid, termsVersion) {
  const now = new Date().toISOString();
  await env.DB.prepare(
    `INSERT INTO consents (github_user_id, terms_version, granted_at)
     VALUES (?, ?, ?)
     ON CONFLICT(github_user_id, terms_version) DO UPDATE SET granted_at = ?`,
  )
    .bind(String(uid), termsVersion, now, now)
    .run();
  return { github_user_id: String(uid), terms_version: termsVersion, granted_at: now };
}

/**
 * Erase everything persisted for a learner in one D1 batch: records and
 * consents first, the learners row last (records/consents reference the
 * learner, so deleting them first keeps the batch FK-safe even though this
 * table's FK isn't declared — see schema.sql). Withdrawal of consent means
 * deletion (spec c18): this is the sole override of the records table's
 * append-only rule, at whole-learner-exit granularity.
 * Returns how many rows were removed from each table.
 */
export async function deleteLearnerData(env, uid) {
  const id = String(uid);
  const [recordsResult, consentsResult, learnersResult] = await env.DB.batch([
    env.DB.prepare(`DELETE FROM records WHERE github_user_id = ?`).bind(id),
    env.DB.prepare(`DELETE FROM consents WHERE github_user_id = ?`).bind(id),
    env.DB.prepare(`DELETE FROM learners WHERE github_user_id = ?`).bind(id),
  ]);
  return {
    records: (recordsResult && recordsResult.meta && recordsResult.meta.changes) || 0,
    consents: (consentsResult && consentsResult.meta && consentsResult.meta.changes) || 0,
    learners: (learnersResult && learnersResult.meta && learnersResult.meta.changes) || 0,
  };
}
