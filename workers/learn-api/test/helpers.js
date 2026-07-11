// Test doubles: an in-memory KV + D1 stub and a counting fetch stub.
//
// No wrangler, no network, no miniflare — the Worker's default export is
// `{ fetch(request, env, ctx) }`, so tests invoke it directly with a fake
// `env` whose bindings are these stubs. This keeps the "signed-out never calls
// inference" proof airtight: the inference stub literally counts its calls.

import { issueSession } from "../src/session.js";

/** Minimal Cloudflare KV stub (get/put/delete) with TTL support. */
export class KVStub {
  constructor() {
    this.map = new Map();
  }

  async get(key) {
    const entry = this.map.get(key);
    if (!entry) return null;
    if (entry.expireAt && Date.now() > entry.expireAt) {
      this.map.delete(key);
      return null;
    }
    return entry.value;
  }

  async put(key, value, opts = {}) {
    const expireAt = opts.expirationTtl ? Date.now() + opts.expirationTtl * 1000 : null;
    this.map.set(key, { value, expireAt });
  }

  async delete(key) {
    this.map.delete(key);
  }
}

/**
 * Minimal Cloudflare D1 stub. Recognizes exactly the statements db.js issues
 * (matched by keyword), backing them with a Map of learners, an array of
 * append-only records, and an array of consent rows.
 */
export class D1Stub {
  constructor() {
    this.learners = new Map();
    this.records = [];
    this.consents = [];
    // Every write statement (insert/delete, any table) appends one entry here,
    // in execution order. This is what makes "zero D1 writes before consent"
    // (spec h1) literal: tests assert on `db.writes`, not just on table sizes,
    // and can also assert ORDER (consent row recorded before the learner row).
    this.writes = [];
    this._id = 0;
  }

  prepare(sql) {
    return new D1Prepared(this, sql);
  }

  _norm(sql) {
    return sql.replace(/\s+/g, " ").trim().toLowerCase();
  }

  /** Cloudflare D1's batch API: run already-bound statements in order,
   * returning their results array. The real D1 wraps this in a transaction;
   * the stub just runs sequentially, which is enough to test statement order
   * and aggregate results. */
  async batch(statements) {
    const results = [];
    for (const stmt of statements) {
      results.push(await stmt.run());
    }
    return results;
  }
}

class D1Prepared {
  constructor(db, sql) {
    this.db = db;
    this.sql = db._norm(sql);
    this.args = [];
  }

  bind(...args) {
    this.args = args;
    return this;
  }

  _logWrite(table, op) {
    this.db.writes.push({ table, op });
  }

  async run() {
    if (this.sql.includes("insert into learners")) {
      this._logWrite("learners", "insert");
      // args: uid, name, now, now, name(update), now(update)
      const [uid, name] = this.args;
      const existing = this.db.learners.get(String(uid));
      this.db.learners.set(String(uid), {
        github_user_id: String(uid),
        display_name: name,
        state: existing ? existing.state : "{}",
      });
      return { success: true, meta: { changes: 1, last_row_id: 0 } };
    }
    if (this.sql.includes("insert into records")) {
      this._logWrite("records", "insert");
      const [uid, subject, item_id, recorded, mastery_level, activity, result, at] = this.args;
      const id = ++this.db._id;
      this.db.records.push({
        id,
        github_user_id: String(uid),
        subject,
        item_id,
        recorded,
        mastery_level,
        activity,
        result,
        at,
      });
      return { success: true, meta: { changes: 1, last_row_id: id } };
    }
    if (this.sql.includes("insert into consents")) {
      this._logWrite("consents", "insert");
      // args: uid, terms_version, granted_at, granted_at(on-conflict update)
      const [uid, termsVersion, grantedAt] = this.args;
      const id = String(uid);
      const existing = this.db.consents.find(
        (c) => c.github_user_id === id && c.terms_version === termsVersion,
      );
      if (existing) {
        existing.granted_at = grantedAt;
      } else {
        this.db.consents.push({ github_user_id: id, terms_version: termsVersion, granted_at: grantedAt });
      }
      return { success: true, meta: { changes: 1 } };
    }
    if (this.sql.includes("delete from records")) {
      this._logWrite("records", "delete");
      const [uid] = this.args;
      const before = this.db.records.length;
      this.db.records = this.db.records.filter((r) => r.github_user_id !== String(uid));
      return { success: true, meta: { changes: before - this.db.records.length } };
    }
    if (this.sql.includes("delete from consents")) {
      this._logWrite("consents", "delete");
      const [uid] = this.args;
      const before = this.db.consents.length;
      this.db.consents = this.db.consents.filter((c) => c.github_user_id !== String(uid));
      return { success: true, meta: { changes: before - this.db.consents.length } };
    }
    if (this.sql.includes("delete from learners")) {
      this._logWrite("learners", "delete");
      const [uid] = this.args;
      const existed = this.db.learners.delete(String(uid));
      return { success: true, meta: { changes: existed ? 1 : 0 } };
    }
    return { success: true, meta: {} };
  }

  async first() {
    if (this.sql.includes("from learners")) {
      const [uid] = this.args;
      return this.db.learners.get(String(uid)) || null;
    }
    if (this.sql.includes("from consents")) {
      const [uid] = this.args;
      const rows = this.db.consents
        .filter((c) => c.github_user_id === String(uid))
        .sort((a, b) => (a.granted_at < b.granted_at ? 1 : a.granted_at > b.granted_at ? -1 : 0));
      return rows[0] || null;
    }
    const { results } = await this.all();
    return results[0] || null;
  }

  async all() {
    if (this.sql.includes("from records")) {
      const [uid, subject] = this.args;
      const results = this.db.records
        .filter((r) => r.github_user_id === String(uid) && r.subject === subject)
        .sort((a, b) => a.id - b.id);
      return { results };
    }
    return { results: [] };
  }
}

/** A counting fetch stub. `routes` maps URL -> handler(url, init) -> Response. */
export function makeFetchStub(routes = {}) {
  const calls = [];
  async function stub(url, init) {
    calls.push({ url: String(url), init });
    const handler = routes[String(url)] || routes.default;
    if (!handler) {
      return jsonResp({ error: "no_stub", url: String(url) }, 599);
    }
    return handler(String(url), init);
  }
  stub.calls = calls;
  return stub;
}

/** Build a fake env with sensible defaults; override any binding/var. */
export function makeEnv(overrides = {}) {
  return {
    SESSION_SECRET: "test-secret-key-please-override-in-prod",
    GITHUB_CLIENT_ID: "test-client-id",
    GITHUB_CLIENT_SECRET: "test-client-secret",
    DB: new D1Stub(),
    SESSIONS: new KVStub(),
    ...overrides,
  };
}

/** Mint a valid (or, with ttl<0, expired) session token for a learner.
 * Pass `opts = { pendingConsent: true }` for a pending-consent token. */
export async function mintToken(env, learner = { uid: "42", name: "Ada" }, ttl = 3600, opts = {}) {
  const { token, payload } = await issueSession(env, learner, ttl, opts);
  return { token, payload };
}

/** Seed a consent row directly into the D1 stub (an already-consented
 * learner), bypassing the write log — tests that assert "zero writes during
 * the flow under test" must not count their own fixtures. */
export function seedConsent(env, uid, termsVersion, grantedAt = "2026-07-11T00:00:00Z") {
  env.DB.consents.push({
    github_user_id: String(uid),
    terms_version: termsVersion,
    granted_at: grantedAt,
  });
}

/** JSON Response helper for stubs. */
export function jsonResp(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** Build a Request with a Bearer token. */
export function authedRequest(url, token, init = {}) {
  const headers = new Headers(init.headers || {});
  headers.set("Authorization", `Bearer ${token}`);
  return new Request(url, { ...init, headers });
}
