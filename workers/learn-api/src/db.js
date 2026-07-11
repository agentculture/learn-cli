// D1 data access — the cross-subject learner ledger.
//
// Two tables (see schema.sql):
//   learners  — one row per GitHub user: id, display name, learner-state JSON.
//               NO password, NO email. This is the entire persisted identity.
//   records   — APPEND-ONLY ledger of recorded results, keyed by
//               (github_user_id, subject, item_id). Never UPDATEd, never
//               DELETEd — the motivation layer (t9) reduces over the full
//               history, so every raw observation is kept.
//
// All access goes through the D1 binding `env.DB` (prepare/bind/run/all/first),
// so tests swap in an in-memory D1 stub with the same surface.

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
