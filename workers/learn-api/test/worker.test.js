import { test } from "node:test";
import assert from "node:assert/strict";

import worker from "../src/index.js";
import { GH } from "../src/github.js";
import { TERMS_VERSION } from "../src/terms.js";
import {
  makeEnv,
  makeFetchStub,
  mintToken,
  authedRequest,
  jsonResp,
  seedConsent,
} from "./helpers.js";

const BASE = "https://learn-api.example";
const INFERENCE_URL = "https://inference.example/v1/messages";

function call(env, request) {
  return worker.fetch(request, env, { waitUntil() {} });
}

// --- public health ---------------------------------------------------------

test("GET /api/health is public and healthy", async () => {
  const env = makeEnv();
  const res = await call(env, new Request(`${BASE}/api/health`));
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.ok, true);
  assert.equal(body.service, "learn-api");
});

// --- THE resource-gate invariant -------------------------------------------

test("signed-out POST /api/tutor -> 401 and inference is NEVER called", async () => {
  const fetchStub = makeFetchStub({ [INFERENCE_URL]: () => jsonResp({ reply: "should not happen" }) });
  const env = makeEnv({ INFERENCE_URL, INFERENCE_TOKEN: "secret", FETCH: fetchStub });

  const res = await call(
    env,
    new Request(`${BASE}/api/tutor`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ subject: "french", messages: [{ role: "user", content: "hi" }] }),
    }),
  );

  assert.equal(res.status, 401);
  // The whole point: zero outbound model calls for a signed-out request.
  assert.equal(fetchStub.calls.length, 0, "inference endpoint must not be touched");
});

test("also 401 (no model call) for a tampered/expired token", async () => {
  const fetchStub = makeFetchStub({ [INFERENCE_URL]: () => jsonResp({ reply: "nope" }) });
  const env = makeEnv({ INFERENCE_URL, INFERENCE_TOKEN: "secret", FETCH: fetchStub });
  const { token } = await mintToken(env, { uid: "42", name: "Ada" }, -5); // expired

  const res = await call(
    env,
    authedRequest(`${BASE}/api/tutor`, token, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ subject: "french", messages: [] }),
    }),
  );
  assert.equal(res.status, 401);
  assert.equal(fetchStub.calls.length, 0);
});

test("signed-in POST /api/tutor brokers to INFERENCE_URL exactly once", async () => {
  const fetchStub = makeFetchStub({
    [INFERENCE_URL]: () => jsonResp({ reply: "Bonjour !", tokens: 12 }),
  });
  const env = makeEnv({ INFERENCE_URL, INFERENCE_TOKEN: "infer-token", FETCH: fetchStub });
  const { token } = await mintToken(env, { uid: "42", name: "Ada" });

  const res = await call(
    env,
    authedRequest(`${BASE}/api/tutor`, token, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ subject: "french", messages: [{ role: "user", content: "Hello" }] }),
    }),
  );

  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.reply, "Bonjour !");

  assert.equal(fetchStub.calls.length, 1);
  const outbound = fetchStub.calls[0];
  assert.equal(outbound.url, INFERENCE_URL);
  assert.equal(outbound.init.headers.Authorization, "Bearer infer-token");
  const forwarded = JSON.parse(outbound.init.body);
  assert.equal(forwarded.learner, "42", "broker stamps the learner id");
  assert.ok(Array.isArray(forwarded.messages));
});

test("broker returns 503 when INFERENCE_URL is unset (still auth-gated first)", async () => {
  const env = makeEnv(); // no INFERENCE_URL
  const { token } = await mintToken(env);
  const res = await call(
    env,
    authedRequest(`${BASE}/api/tutor`, token, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ subject: "french", messages: [] }),
    }),
  );
  assert.equal(res.status, 503);
});

// --- record round-trip + progress ------------------------------------------

test("record round-trip: POST /api/record then GET /api/progress reflects it", async () => {
  const env = makeEnv();
  const { token } = await mintToken(env, { uid: "42", name: "Ada" });

  const recorded = {
    item_id: "numbers-money",
    activity: "practice",
    exercise_id: "nm-p1",
    result: "pass",
    correct: 1,
    total: 1,
    duration_seconds: 38,
    at: "2026-07-11T10:00:00Z",
  };

  const recRes = await call(
    env,
    authedRequest(`${BASE}/api/record`, token, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ subject: "french", recorded }),
    }),
  );
  assert.equal(recRes.status, 201);
  const ack = await recRes.json();
  assert.equal(ack.kind, "record_ack");
  assert.equal(ack.schema_version, "1.0");
  assert.equal(ack.subject, "french");
  assert.equal(ack.learner, "42");
  assert.equal(ack.mastery.level, "mastered"); // inferred from pass
  assert.deepEqual(ack.recorded, recorded);

  const progRes = await call(env, authedRequest(`${BASE}/api/progress/french`, token));
  assert.equal(progRes.status, 200);
  const prog = await progRes.json();
  assert.equal(prog.kind, "progress");
  assert.equal(prog.schema_version, "1.0");
  assert.equal(prog.learner, "42");
  assert.equal(prog.items_touched, 1);
  assert.equal(prog.items_mastered, 1);
  assert.equal(prog.mastery["numbers-money"], "mastered");
  assert.deepEqual(prog.completed, ["numbers-money"]);
});

test("ledger is append-only and per-learner isolated", async () => {
  const env = makeEnv();
  const { token: adaTok } = await mintToken(env, { uid: "42", name: "Ada" });
  const { token: linusTok } = await mintToken(env, { uid: "99", name: "Linus" });

  const mk = (item, result) => ({
    item_id: item,
    activity: "practice",
    result,
    at: `2026-07-11T10:0${item.length}:00Z`,
  });

  for (const [tok, item, result] of [
    [adaTok, "a1", "fail"],
    [adaTok, "a1", "pass"], // second record, same item -> append, mastery rises
    [adaTok, "a2", "partial"],
    [linusTok, "b1", "pass"],
  ]) {
    const r = await call(
      env,
      authedRequest(`${BASE}/api/record`, tok, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ subject: "french", recorded: mk(item, result) }),
      }),
    );
    assert.equal(r.status, 201);
  }

  // Two learners, four records total, none overwritten.
  assert.equal(env.DB.records.length, 4);

  const prog = await (await call(env, authedRequest(`${BASE}/api/progress/french`, adaTok))).json();
  assert.equal(prog.items_touched, 2);
  assert.equal(prog.mastery.a1, "mastered"); // rose from introduced -> mastered
  assert.equal(prog.mastery.a2, "practiced");
  const linusProg = await (await call(env, authedRequest(`${BASE}/api/progress/french`, linusTok))).json();
  assert.equal(linusProg.items_touched, 1); // isolation: Ada's rows not visible
});

test("POST /api/record rejects a score field with 400", async () => {
  const env = makeEnv();
  const { token } = await mintToken(env);
  const res = await call(
    env,
    authedRequest(`${BASE}/api/record`, token, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        subject: "french",
        recorded: {
          item_id: "x",
          activity: "practice",
          result: "pass",
          at: "2026-07-11T10:00:00Z",
          score: 100,
        },
      }),
    }),
  );
  assert.equal(res.status, 400);
  const body = await res.json();
  assert.match(body.message, /score/);
  assert.equal(env.DB.records.length, 0, "invalid record must not be persisted");
});

test("signed-out POST /api/record -> 401", async () => {
  const env = makeEnv();
  const res = await call(
    env,
    new Request(`${BASE}/api/record`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ subject: "french", recorded: {} }),
    }),
  );
  assert.equal(res.status, 401);
});

// --- session expiry & /api/me ----------------------------------------------

test("session expiry: expired token -> /api/me 401", async () => {
  const env = makeEnv();
  const { token } = await mintToken(env, { uid: "42", name: "Ada" }, -10);
  const res = await call(env, authedRequest(`${BASE}/api/me`, token));
  assert.equal(res.status, 401);
});

test("GET /api/me returns the learner and refreshes a near-stale session", async () => {
  const env = makeEnv();
  const { token } = await mintToken(env, { uid: "42", name: "Ada" }, 60); // inside refresh window
  const res = await call(env, authedRequest(`${BASE}/api/me`, token));
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.authenticated, true);
  assert.equal(body.learner.github_user_id, "42");
  assert.equal(body.learner.display_name, "Ada");
  assert.equal(body.session.refreshed, true);
  assert.ok(res.headers.getSetCookie().some((c) => c.startsWith("session=")));
});

// --- logout / revocation ----------------------------------------------------

test("logout revokes the session (KV tombstone) so /api/me then 401s", async () => {
  const env = makeEnv();
  const { token } = await mintToken(env, { uid: "42", name: "Ada" });

  assert.equal((await call(env, authedRequest(`${BASE}/api/me`, token))).status, 200);
  const out = await call(env, authedRequest(`${BASE}/api/auth/logout`, token, { method: "POST" }));
  assert.equal(out.status, 200);
  const after = await call(env, authedRequest(`${BASE}/api/me`, token));
  assert.equal(after.status, 401);
});

// --- web OAuth flow ---------------------------------------------------------

test("GET /api/auth/login redirects to GitHub with a state cookie", async () => {
  const env = makeEnv();
  const res = await call(env, new Request(`${BASE}/api/auth/login`));
  assert.equal(res.status, 302);
  const location = res.headers.get("Location");
  assert.ok(location.startsWith(GH.authorize));
  assert.match(location, /client_id=test-client-id/);
  assert.ok(res.headers.getSetCookie().some((c) => c.startsWith("oauth_state=")));
});

test("login redirect_uri carries the /learn mount prefix (matches the GitHub app callback)", async () => {
  // Regression: the callback must include /learn or GitHub rejects the flow
  // (redirect_uri mismatch) AND the bare-origin callback would miss this
  // worker's zone route and hit org's Pages site instead.
  const env = makeEnv({ APP_URL: "https://agentculture.org/learn/" });
  const res = await call(env, new Request(`${BASE}/learn/api/auth/login`));
  assert.equal(res.status, 302);
  const redirectUri = new URL(res.headers.get("Location")).searchParams.get("redirect_uri");
  assert.equal(redirectUri, "https://agentculture.org/learn/api/auth/callback");
});

test("GET /api/auth/callback (consented user) exchanges code, upserts learner, sets session", async () => {
  const fetchStub = makeFetchStub({
    [GH.token]: () => jsonResp({ access_token: "gho_web", token_type: "bearer" }),
    [GH.user]: () => jsonResp({ id: 555, login: "trinity", name: "Trinity" }),
  });
  const env = makeEnv({ FETCH: fetchStub, APP_URL: "https://agentculture.org/learn/" });
  // A returning learner with recorded consent — the unconsented (pending)
  // first sign-in is covered in consent.test.js.
  seedConsent(env, "555", TERMS_VERSION);

  const req = new Request(`${BASE}/api/auth/callback?code=abc&state=xyz`, {
    headers: { Cookie: "oauth_state=xyz" },
  });
  const res = await call(env, req);
  assert.equal(res.status, 302);
  assert.equal(res.headers.get("Location"), "https://agentculture.org/learn/");
  assert.ok(res.headers.getSetCookie().some((c) => c.startsWith("session=")));

  // Learner persisted with id + display name only.
  const learner = env.DB.learners.get("555");
  assert.equal(learner.display_name, "Trinity");
  // No email ever requested/stored.
  const userCall = fetchStub.calls.find((c) => c.url === GH.user);
  assert.ok(userCall, "the user endpoint was queried");
});

test("callback rejects a bad OAuth state (CSRF guard)", async () => {
  const env = makeEnv({ FETCH: makeFetchStub() });
  const req = new Request(`${BASE}/api/auth/callback?code=abc&state=evil`, {
    headers: { Cookie: "oauth_state=xyz" },
  });
  const res = await call(env, req);
  assert.equal(res.status, 400);
});

// --- device flow (CLI/MCP, t12) --------------------------------------------

test("device flow: start returns the user code", async () => {
  const fetchStub = makeFetchStub({
    [GH.deviceCode]: () =>
      jsonResp({
        device_code: "dc_123",
        user_code: "WXYZ-1234",
        verification_uri: "https://github.com/login/device",
        expires_in: 900,
        interval: 5,
      }),
  });
  const env = makeEnv({ FETCH: fetchStub });
  const res = await call(
    env,
    new Request(`${BASE}/api/auth/device`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "start" }),
    }),
  );
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.user_code, "WXYZ-1234");
  assert.equal(body.device_code, "dc_123");
});

test("device flow (consented user): poll pending, then complete issues a Bearer token", async () => {
  let phase = "pending";
  const fetchStub = makeFetchStub({
    [GH.token]: () =>
      phase === "pending"
        ? jsonResp({ error: "authorization_pending" })
        : jsonResp({ access_token: "gho_dev" }),
    [GH.user]: () => jsonResp({ id: 777, login: "neo", name: "Neo" }),
  });
  const env = makeEnv({ FETCH: fetchStub });
  // A returning learner with recorded consent — the unconsented poll
  // (status: consent_required) is covered in consent.test.js.
  seedConsent(env, "777", TERMS_VERSION);

  const poll = () =>
    call(
      env,
      new Request(`${BASE}/api/auth/device`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "poll", device_code: "dc_123" }),
      }),
    );

  const pending = await (await poll()).json();
  assert.equal(pending.status, "pending");

  phase = "done";
  const done = await (await poll()).json();
  assert.equal(done.status, "complete");
  assert.equal(done.token_type, "Bearer");
  assert.ok(done.token);
  assert.equal(done.learner.github_user_id, "777");
  assert.equal(done.learner.display_name, "Neo");
  // The minted token is immediately usable.
  const me = await call(env, authedRequest(`${BASE}/api/me`, done.token));
  assert.equal(me.status, 200);
});

// --- misc -------------------------------------------------------------------

test("unknown route -> 404", async () => {
  const env = makeEnv();
  const res = await call(env, new Request(`${BASE}/api/nope`));
  assert.equal(res.status, 404);
});

test("OPTIONS preflight returns CORS headers when CORS_ORIGIN is set", async () => {
  const env = makeEnv({ CORS_ORIGIN: "https://agentculture.org" });
  const res = await call(
    env,
    new Request(`${BASE}/api/me`, { method: "OPTIONS", headers: { Origin: "https://agentculture.org" } }),
  );
  assert.equal(res.status, 204);
  assert.equal(res.headers.get("Access-Control-Allow-Origin"), "https://agentculture.org");
  assert.equal(res.headers.get("Access-Control-Allow-Credentials"), "true");
});

// --- the /learn zone mount ---------------------------------------------------

test("GET /learn/api/health normalizes the zone-mount prefix", async () => {
  const env = makeEnv();
  const res = await call(env, new Request(`${BASE}/learn/api/health`));
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.service, "learn-api");
});

test("GET /learn/<page> proxies to PAGES_ORIGIN with path preserved", async () => {
  const seen = [];
  const realFetch = globalThis.fetch;
  globalThis.fetch = async (req) => {
    seen.push(req.url);
    return new Response("<html>page</html>", { status: 200, headers: { "content-type": "text/html" } });
  };
  try {
    const env = makeEnv({ PAGES_ORIGIN: "https://agentculture-learn.pages.dev" });
    const res = await call(env, new Request(`${BASE}/learn/french/stories/fr-a1-le-marche/`));
    assert.equal(res.status, 200);
    assert.equal(seen.length, 1);
    assert.equal(seen[0], "https://agentculture-learn.pages.dev/learn/french/stories/fr-a1-le-marche/");
  } finally {
    globalThis.fetch = realFetch;
  }
});

test("POST under the /learn site mount is rejected (read-only proxy)", async () => {
  const env = makeEnv({ PAGES_ORIGIN: "https://agentculture-learn.pages.dev" });
  const res = await call(env, new Request(`${BASE}/learn/french/`, { method: "POST" }));
  assert.equal(res.status, 405);
});

test("proxy to PAGES_ORIGIN strips Cookie and Authorization headers", async () => {
  let seenHeaders = null;
  const realFetch = globalThis.fetch;
  globalThis.fetch = async (req) => {
    seenHeaders = req.headers;
    return new Response("ok", { status: 200 });
  };
  try {
    const env = makeEnv({ PAGES_ORIGIN: "https://agentculture-learn.pages.dev" });
    const req = new Request(`${BASE}/learn/french/`, {
      headers: { Cookie: "session=supersecret", Authorization: "Bearer tok", Accept: "text/html" },
    });
    const res = await call(env, req);
    assert.equal(res.status, 200);
    assert.equal(seenHeaders.get("Cookie"), null);
    assert.equal(seenHeaders.get("Authorization"), null);
    assert.equal(seenHeaders.get("Accept"), "text/html");
  } finally {
    globalThis.fetch = realFetch;
  }
});

test("withCors appends to an existing Vary header instead of overwriting", async () => {
  let called = 0;
  const realFetch = globalThis.fetch;
  globalThis.fetch = async () => {
    called += 1;
    return new Response("ok", { status: 200, headers: { Vary: "Accept-Encoding" } });
  };
  try {
    const env = makeEnv({
      PAGES_ORIGIN: "https://agentculture-learn.pages.dev",
      CORS_ORIGIN: "https://agentculture.org",
    });
    const res = await call(env, new Request(`${BASE}/learn/french/`, { headers: { Origin: "https://agentculture.org" } }));
    assert.equal(called, 1);
    const vary = res.headers.get("Vary");
    assert.ok(vary.includes("Accept-Encoding"), `Vary lost upstream value: ${vary}`);
    assert.ok(vary.includes("Origin"), `Vary missing Origin: ${vary}`);
  } finally {
    globalThis.fetch = realFetch;
  }
});
