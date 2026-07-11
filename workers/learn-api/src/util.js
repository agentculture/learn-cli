// Small dependency-free helpers shared across the Worker.
//
// Everything here uses only globals available in BOTH the Cloudflare Workers
// runtime and Node >=18 (fetch, Request/Response/Headers, crypto.subtle,
// btoa/atob, TextEncoder/TextDecoder). No `Buffer`, no npm packages — so the
// same code runs in `wrangler dev`, in production, and under `node --test`.

/** Encode raw bytes as base64url (no padding). */
export function b64urlBytes(bytes) {
  let bin = "";
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/** Encode a UTF-8 string as base64url. */
export function b64urlStr(str) {
  return b64urlBytes(new TextEncoder().encode(str));
}

/** Decode a base64url string back to a UTF-8 string. */
export function b64urlToStr(b64url) {
  const b64 = b64url.replace(/-/g, "+").replace(/_/g, "/");
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return new TextDecoder().decode(bytes);
}

/** Import a shared secret as an HMAC-SHA256 key. */
async function hmacKey(secret) {
  return crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
}

/** HMAC-SHA256 sign `data` with `secret`, returning a base64url digest. */
export async function hmacSign(secret, data) {
  const key = await hmacKey(secret);
  const sig = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(data));
  return b64urlBytes(new Uint8Array(sig));
}

/** Constant-time string compare (equal length assumed for the digests). */
export function constantTimeEqual(a, b) {
  if (typeof a !== "string" || typeof b !== "string") return false;
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

/** Outbound fetch seam. Tests inject `env.FETCH` so no real network is hit. */
export function outboundFetch(env) {
  return (env && env.FETCH) || fetch;
}

/** Current unix time in seconds. */
export function nowSeconds() {
  return Math.floor(Date.now() / 1000);
}

/** A structured HTTP error that the router turns into a JSON response. */
export class HttpError extends Error {
  constructor(status, code, message, hint = "") {
    super(message);
    this.status = status;
    this.code = code;
    this.hint = hint;
  }

  toResponse() {
    return jsonResponse(this.status, {
      error: this.code,
      message: this.message,
      hint: this.hint,
    });
  }
}

/** JSON response helper with optional extra headers. */
export function jsonResponse(status, body, headers = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

/** 302 redirect helper. */
export function redirect(location, headers = {}) {
  return new Response(null, { status: 302, headers: { Location: location, ...headers } });
}

/** Parse a Cookie header into a plain object. */
export function parseCookies(request) {
  const raw = request.headers.get("Cookie") || "";
  const out = {};
  for (const part of raw.split(";")) {
    const idx = part.indexOf("=");
    if (idx < 0) continue;
    const k = part.slice(0, idx).trim();
    const v = part.slice(idx + 1).trim();
    if (k) out[k] = decodeURIComponent(v);
  }
  return out;
}

/** Serialize a Set-Cookie header value. */
export function cookie(name, value, opts = {}) {
  const parts = [`${name}=${encodeURIComponent(value)}`];
  parts.push(`Path=${opts.path || "/"}`);
  if (opts.maxAge != null) parts.push(`Max-Age=${opts.maxAge}`);
  if (opts.httpOnly !== false) parts.push("HttpOnly");
  if (opts.secure !== false) parts.push("Secure");
  parts.push(`SameSite=${opts.sameSite || "Lax"}`);
  return parts.join("; ");
}
