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
//
// Self-serve export + delete (spec c11/h3, decision c18, task t7):
// listAllRecords/listConsents are the ALL-subjects / full-history reads the
// export route needs (listRecords/getConsent stay scoped to one
// subject/the-latest-row for their existing callers). deleteLearnerData is
// the sole erasure path — see its own doc comment below.

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

/**
 * Read a learner's identity + state, or null if unknown. Carries `updated_at`
 * (task t16 follow-up, Qodo BUG 3) alongside the usual fields — not because
 * ordinary callers need it, but because it's the version stamp
 * setLearnerVoiceUsage's compare-and-swap write needs, and re-reading it
 * separately for that one caller would defeat the "read once, CAS against
 * exactly what you read" property the fix relies on.
 */
export async function getLearner(env, uid) {
  const row = await env.DB.prepare(
    `SELECT github_user_id, display_name, state, updated_at FROM learners WHERE github_user_id = ?`,
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
  return {
    github_user_id: row.github_user_id,
    display_name: row.display_name,
    state,
    updated_at: row.updated_at,
  };
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

/**
 * List every recorded result for a learner across ALL subjects, oldest
 * first — the full-ledger view self-serve export (t7) needs. Unlike
 * listRecords, this is not subject-scoped, so each returned row carries its
 * own `subject` to keep a multi-subject export attributable.
 */
export async function listAllRecords(env, uid) {
  const out = await env.DB.prepare(
    `SELECT subject, item_id, recorded, mastery_level, activity, result, at
       FROM records
      WHERE github_user_id = ?
      ORDER BY id ASC`,
  )
    .bind(String(uid))
    .all();
  return (out && out.results) || [];
}

/** Read a learner's most recent consent row (by granted_at), or null. */
export async function getConsent(env, uid) {
  const row = await env.DB.prepare(
    `SELECT github_user_id, terms_version, granted_at
       FROM consents
      WHERE github_user_id = ?
      ORDER BY granted_at DESC, rowid DESC
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
 * List EVERY consent row a learner has ever accepted (not just the most
 * recent one, unlike getConsent) — the full accept-history self-serve
 * export (t7) reports. Oldest first.
 */
export async function listConsents(env, uid) {
  const out = await env.DB.prepare(
    `SELECT terms_version, granted_at
       FROM consents
      WHERE github_user_id = ?
      ORDER BY granted_at ASC`,
  )
    .bind(String(uid))
    .all();
  return (out && out.results) || [];
}

/**
 * List every learner for the admin surface (spec c12/h4, task t8), each
 * carrying a cheap per-subject record-count summary and their most recent
 * consent row. THREE total queries, always — a learner scan, one GROUP BY
 * over records, and a full scan of the (typically small) consents table —
 * regardless of how many learners exist, so this stays N+1-free as the
 * roster grows. Policy ("is this consent CURRENT?") is the caller's job
 * (consent.js#consentSatisfiesCurrentTerms in index.js's admin route) — this
 * function only returns the raw most-recently-granted consent per learner,
 * same data getConsent's single-learner query already exposes.
 */
export async function listAllLearners(env) {
  const [learnersOut, countsOut, consentsOut] = await Promise.all([
    env.DB.prepare(
      `SELECT github_user_id, display_name, state, created_at
         FROM learners
        ORDER BY created_at ASC`,
    ).all(),
    env.DB.prepare(
      `SELECT github_user_id, subject, COUNT(*) as count
         FROM records
        GROUP BY github_user_id, subject`,
    ).all(),
    env.DB.prepare(
      `SELECT github_user_id, terms_version, granted_at
         FROM consents
        ORDER BY github_user_id ASC, granted_at DESC`,
    ).all(),
  ]);

  const recordsByUser = new Map();
  for (const row of (countsOut && countsOut.results) || []) {
    const uid = String(row.github_user_id);
    if (!recordsByUser.has(uid)) recordsByUser.set(uid, {});
    recordsByUser.get(uid)[row.subject] = row.count;
  }

  // ORDER BY user, then granted_at DESC: the FIRST row seen for a given
  // user is their most recent consent (same trick getConsent's single-row
  // query relies on, done once for every learner instead of per-learner).
  const latestConsentByUser = new Map();
  for (const row of (consentsOut && consentsOut.results) || []) {
    const uid = String(row.github_user_id);
    if (!latestConsentByUser.has(uid)) {
      latestConsentByUser.set(uid, {
        terms_version: row.terms_version,
        granted_at: row.granted_at,
      });
    }
  }

  return ((learnersOut && learnersOut.results) || []).map((row) => {
    const uid = String(row.github_user_id);
    let state = {};
    try {
      state = row.state ? JSON.parse(row.state) : {};
    } catch {
      state = {};
    }
    const records = recordsByUser.get(uid) || {};
    return {
      github_user_id: uid,
      display_name: row.display_name,
      created_at: row.created_at,
      // Absent field means "private" — same default getLearner/handleMe use
      // (spec c12: default-private, no migration needed for existing rows).
      visibility: state.visibility === "public" ? "public" : "private",
      // Absent key means NOT approved (spec c13, t9) — reported as a literal
      // false so the admin surface never has to distinguish undefined/false.
      approved: state.approved === true,
      consent: latestConsentByUser.get(uid) || null,
      records,
      records_total: Object.values(records).reduce((a, b) => a + b, 0),
    };
  });
}

/**
 * Set a learner's visibility flag inside their `state` blob (spec c12,
 * task t8). Read-then-write, merging into whatever else already lives in
 * `state` rather than clobbering it — the same defensive parse getLearner
 * already does. A learner who never calls this route simply has no
 * `visibility` key in their state, which every reader treats as "private"
 * (see getLearner's callers / listAllLearners above) — no migration touches
 * existing rows.
 */
export async function setLearnerVisibility(env, uid, visibility) {
  const learner = await getLearner(env, uid);
  const state = { ...(learner ? learner.state : {}), visibility };
  const now = new Date().toISOString();
  await env.DB.prepare(`UPDATE learners SET state = ?, updated_at = ? WHERE github_user_id = ?`)
    .bind(JSON.stringify(state), now, String(uid))
    .run();
  return visibility;
}

/**
 * Set (or clear) a learner's tutoring-tier approval flag inside their
 * `state` blob (spec c13, decision c20's flag half; task t9). Same
 * no-schema-change pattern as setLearnerVisibility directly above:
 * read-then-write, merging into whatever else lives in `state`. Approving
 * stores a literal `approved: true`; revoking DELETES the key rather than
 * writing `false`, so a revoked learner's state is indistinguishable from a
 * never-approved one and every reader keeps one rule — absent means not
 * approved, no migration for pre-t9 rows. POLICY is the caller's job: the
 * c20 "consent must be current" precondition lives in index.js's
 * handleAdminApprove, not here (mirroring how listAllLearners leaves
 * consent_status policy to its caller).
 */
export async function setLearnerApproved(env, uid, approved) {
  const learner = await getLearner(env, uid);
  const state = { ...(learner ? learner.state : {}) };
  if (approved) state.approved = true;
  else delete state.approved;
  const now = new Date().toISOString();
  await env.DB.prepare(`UPDATE learners SET state = ?, updated_at = ? WHERE github_user_id = ?`)
    .bind(JSON.stringify(state), now, String(uid))
    .run();
  return !!approved;
}

/**
 * Persist a learner's monthly voice-budget meter inside their `state` blob
 * (task t16): `voice_usage = { month: "2026-07", seconds_minted: n }`.
 *
 * Unlike setLearnerVisibility / setLearnerApproved's plain read-then-write,
 * this is a COMPARE-AND-SWAP on the learner row's `updated_at` (Qodo review
 * finding, BUG 3): the naive read-then-write here let two concurrent voice
 * mints both read the same `used`, both pass index.js#handleVoiceToken's cap
 * check, and both overwrite the same counter — silently exceeding
 * VOICE_MONTHLY_SECONDS_CAP. `baseState` is the state blob the CALLER
 * already read (index.js#bookVoiceUsage) — merged in here rather than
 * re-read, so the write is scoped to exactly the row version the cap was
 * checked against, not whatever happens to be there by the time this runs.
 * `expectedUpdatedAt` is REQUIRED (no unconditional fallback): the `UPDATE
 * ... WHERE updated_at = ?` only touches the row if it still matches, so a
 * concurrent winner's write invalidates every loser's stamp and their CAS
 * simply reports `ok: false` instead of clobbering the winner's booking.
 *
 * An absent `voice_usage` key means "nothing minted" (unchanged from
 * before), so pre-t16 rows still need no migration and month rollover is
 * still just the reader (src/voice.js#voiceSecondsUsed) treating a stale
 * month as zero. POLICY (the cap check itself, and the bounded retry-on-
 * conflict loop) is the caller's job — see index.js#bookVoiceUsage — mirroring
 * how the c20 precondition stays out of setLearnerApproved.
 *
 * @returns {Promise<{ ok: boolean, usage: object }>} `ok: false` means the
 *   row's `updated_at` no longer matched `expectedUpdatedAt` — another
 *   booking won the race; the caller must re-read and retry, never treat
 *   this as a successful booking.
 */
export async function setLearnerVoiceUsage(env, uid, usage, baseState, expectedUpdatedAt) {
  const state = { ...(baseState || {}), voice_usage: usage };
  const now = new Date().toISOString();
  const res = await env.DB.prepare(
    `UPDATE learners SET state = ?, updated_at = ? WHERE github_user_id = ? AND updated_at = ?`,
  )
    .bind(JSON.stringify(state), now, String(uid), expectedUpdatedAt)
    .run();
  const changed = !!(res && res.meta && res.meta.changes);
  return { ok: changed, usage };
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
