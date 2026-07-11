-- learn API — D1 schema (learner ledger).
--
-- Two tables. Privacy invariant: the ONLY persisted identity is the GitHub
-- numeric id + a display name. No password, no email, no PII beyond the id and
-- the name the learner already shows publicly on GitHub.
--
-- Apply with:  wrangler d1 execute learn-ledger --file schema.sql
--    (add --local for the wrangler-dev SQLite; omit it for the remote D1).

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
