-- learn API — D1 schema (learner ledger).
--
-- Three tables. Privacy invariant: the ONLY persisted identity is the GitHub
-- numeric id + a display name. No password, no email, no PII beyond the id and
-- the name the learner already shows publicly on GitHub. The `consents` table
-- (below) is the one exception to "nothing is written before it's decided" —
-- it exists so that everything else CAN be gated on it (t5): no learner row,
-- no record, is written for a github_user_id until a consent row for the
-- currently published terms_version exists for them.
--
-- Apply with:  wrangler d1 execute learn-ledger --file schema.sql
--    (add --local for the wrangler-dev SQLite; omit it for the remote D1).
-- Every statement below is idempotent (CREATE ... IF NOT EXISTS), so
-- re-running this file against the existing remote database is a safe no-op
-- for tables/indexes that already exist and only adds what's new.

-- One row per learner. `state` is the cross-subject learner profile blob
-- (preferences, streak anchors, etc.) — small JSON, owned by learn-cli.
CREATE TABLE IF NOT EXISTS learners (
  github_user_id TEXT PRIMARY KEY,
  display_name   TEXT NOT NULL,
  state          TEXT NOT NULL DEFAULT '{}',
  created_at     TEXT NOT NULL,
  updated_at     TEXT NOT NULL
);

-- Append-only ledger of recorded results. Every POST /api/record inserts one
-- row; rows are NEVER updated or deleted. The motivation layer (t9) reduces
-- over the full history, so each raw observation is preserved verbatim in
-- `recorded` (the exact contract `record.json` recorded object). Derived
-- numbers (score/grade/points) are structurally rejected at the API before
-- insert and are never stored here.
CREATE TABLE IF NOT EXISTS records (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  github_user_id TEXT NOT NULL,
  subject        TEXT NOT NULL,
  item_id        TEXT NOT NULL,
  recorded       TEXT NOT NULL,       -- JSON: the normalized recorded object, verbatim
  mastery_level  TEXT,                -- post-record mastery (explicit or inferred)
  activity       TEXT NOT NULL,       -- lesson | practice | story
  result         TEXT NOT NULL,       -- pass | partial | fail
  at             TEXT NOT NULL,       -- ISO-8601 from the recorded object
  created_at     TEXT NOT NULL,       -- server insert time
  FOREIGN KEY (github_user_id) REFERENCES learners(github_user_id)
);

CREATE INDEX IF NOT EXISTS idx_records_user_subject
  ON records (github_user_id, subject);

CREATE INDEX IF NOT EXISTS idx_records_user_subject_item
  ON records (github_user_id, subject, item_id);

-- Consent ledger. One row per learner per terms_version they've accepted —
-- re-granting the SAME version updates granted_at in place (idempotent
-- accept, no duplicate row); a NEW published terms_version always inserts a
-- fresh row (re-consent, t6). "Current" consent for a learner is the row with
-- the latest granted_at (see db.js getConsent). No FOREIGN KEY to learners
-- on purpose: consent can be recorded before a learners row exists (the
-- pending-consent flow, t5, writes nothing to `learners` until accept).
--
-- Withdrawal (t7) hard-deletes every row here for the learner — an explicit,
-- narrow override of the records table's append-only rule above. Erasure
-- beats immutability at the whole-learner-exit granularity; the two rules
-- don't conflict because they operate at different scopes (per-row edits vs
-- a learner's full exit).
CREATE TABLE IF NOT EXISTS consents (
  github_user_id TEXT NOT NULL,
  terms_version  TEXT NOT NULL,
  granted_at     TEXT NOT NULL,
  PRIMARY KEY (github_user_id, terms_version)
);

CREATE INDEX IF NOT EXISTS idx_consents_user
  ON consents (github_user_id);
