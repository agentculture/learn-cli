// Voice-session tokens + the per-learner monthly voice budget (t16, spec c15/h7).
//
// The mint half of infra/voice_bridge/tokens.py: the serverless bridge only
// upgrades a WebSocket at $connect for a token this module minted with the
// SHARED secret (Worker secret VOICE_TOKEN_SECRET here == the SAM template's
// VoiceTokenSecretValue there). Format is byte-for-byte the session.js shape:
//
//     token     = base64url(JSON payload) + "." + base64url(signature)
//     signature = HMAC-SHA256(secret, base64url(JSON payload))
//
// both segments unpadded, the HMAC computed over the ENCODED body string.
// The payload carries exactly {v, scope, uid, approved, iat, exp, sid} —
// tokens.py's verify_voice_token rejects anything else, and three claims
// distinguish a voice token from the session tokens whose format it shares:
//
//   scope: "voice"   — a learn-api SESSION token must never open the bridge
//                      (no session-cookie reuse; tokens.py enforces this);
//   approved: true   — minted only for admin-approved learners; the route
//                      (index.js#handleVoiceToken) enforces the gate, and
//                      this module refuses to sign anything else;
//   a short exp      — VOICE_TOKEN_TTL_SECONDS covers mint -> $connect only;
//                      session LENGTH is the bridge's MaxSessionSeconds cap,
//                      enforced server-side after the token verified.
//
// Cross-language drift protection: tests/fixtures/voice_token_cross_language.json
// is a committed token this module minted with deterministic inputs;
// test/voice.test.js asserts the mint still reproduces it byte-for-byte and
// tests/test_voice_token_cross_language.py asserts tokens.py still verifies
// it — one fixture, both sides pinned.

import { b64urlStr, hmacSign, nowSeconds } from "./util.js";

export const VOICE_TOKEN_VERSION = 1;
export const VOICE_TOKEN_SCOPE = "voice";

// Mint-to-connect window, not session length ("minutes, not the session's
// hour" — tokens.py's own words). 120 s is generous for one client-side hop:
// POST /api/voice/token -> new WebSocket(wss_url).
export const VOICE_TOKEN_TTL_SECONDS = 120;

// Mirrors infra/voice_bridge/config.py DEFAULT_MAX_SESSION_SECONDS — the
// bridge's own per-session cap, which every mint books against the monthly
// budget below (the worst case: the learner uses the whole session). If the
// SAM stack deploys with a different MaxSessionSeconds, set the Worker var
// VOICE_MAX_SESSION_SECONDS to match.
export const DEFAULT_VOICE_MAX_SESSION_SECONDS = 300;

// Per-learner monthly cap on MINTED session-seconds, overridable via the
// VOICE_MONTHLY_SECONDS_CAP var. Default 1800 s = 30 min/month = 6 max-length
// sessions. Sizing against the $20/month AWS Budgets ceiling the SAM template
// pins (infra/template.yaml), using the spike-measured Nova Sonic rate of
// ~$0.01-0.02 per conversation-minute (infra/SPIKE.md "Cost observations"):
// one learner exhausting the cap costs ~$0.30-0.60 of speech tokens plus
// ~$0.12 of plumbing (6 x ~$0.02/session) — so even TEN fully-saturating
// approved learners stay near ~$3-7/month, well inside the ceiling, and the
// bridge's global MaxConcurrentVoiceSessions=2 bounds the burn RATE
// (~$2.4/hour worst case) independently of how many learners hold budget.
export const DEFAULT_VOICE_MONTHLY_SECONDS_CAP = 1800;

/**
 * Mint a voice token for an APPROVED learner — the JS twin of
 * infra/voice_bridge/tokens.py#mint_voice_token (which exists only so the
 * Python verify side can be tested; THIS is the production minter).
 *
 * `opts.now` / `opts.ttlSeconds` / `opts.sid` exist for deterministic tests
 * (the cross-language fixture); production callers pass none of them.
 *
 * @returns {Promise<{ token: string, payload: object }>}
 */
export async function mintVoiceToken(env, uid, opts = {}) {
  if (!env || !env.VOICE_TOKEN_SECRET) {
    throw new Error("VOICE_TOKEN_SECRET is not configured");
  }
  const iat = opts.now == null ? nowSeconds() : Math.floor(opts.now);
  const ttl = opts.ttlSeconds == null ? VOICE_TOKEN_TTL_SECONDS : Math.floor(opts.ttlSeconds);
  const payload = {
    v: VOICE_TOKEN_VERSION,
    scope: VOICE_TOKEN_SCOPE,
    uid: String(uid),
    approved: true,
    iat,
    exp: iat + ttl,
    sid: opts.sid || crypto.randomUUID(),
  };
  const body = b64urlStr(JSON.stringify(payload));
  const sig = await hmacSign(env.VOICE_TOKEN_SECRET, body);
  return { token: `${body}.${sig}`, payload };
}

/** The budget month key ("2026-07") for a unix-seconds timestamp, UTC. */
export function voiceMonthKey(unixSeconds) {
  return new Date(unixSeconds * 1000).toISOString().slice(0, 7);
}

/**
 * Seconds already MINTED against `month` from a learner's state blob.
 * A different (or absent) stored month means the meter reset — month
 * rollover needs no cron and no migration, exactly like the other
 * `learners.state` keys (visibility, approved): stale data is simply
 * read as zero. Malformed values degrade to 0 defensively.
 */
export function voiceSecondsUsed(learner, month) {
  const usage = learner && learner.state ? learner.state.voice_usage : null;
  if (!usage || usage.month !== month) return 0;
  const n = Number(usage.seconds_minted);
  return Number.isFinite(n) && n > 0 ? n : 0;
}

/** Parse a positive-integer env var with a fallback (vars arrive as strings). */
export function positiveIntVar(value, fallback) {
  const n = Number(value);
  return Number.isFinite(n) && n > 0 ? Math.floor(n) : fallback;
}
