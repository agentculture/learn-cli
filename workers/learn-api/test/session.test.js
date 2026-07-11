import { test } from "node:test";
import assert from "node:assert/strict";

import { issueSession, verifySession, needsRefresh } from "../src/session.js";

const env = { SESSION_SECRET: "unit-test-secret" };

test("issue -> verify round-trips the learner identity", async () => {
  const { token, payload } = await issueSession(env, { uid: "1001", name: "Grace" });
  assert.match(token, /^[^.]+\.[^.]+$/);
  const verified = await verifySession(env, token);
  assert.equal(verified.uid, "1001");
  assert.equal(verified.name, "Grace");
  assert.equal(verified.exp, payload.exp);
});

test("a tampered token fails verification", async () => {
  const { token } = await issueSession(env, { uid: "1001", name: "Grace" });
  const [body] = token.split(".");
  const forged = `${body}.AAAAdeadbeef`;
  assert.equal(await verifySession(env, forged), null);
});

test("a token signed with a different secret fails", async () => {
  const { token } = await issueSession(env, { uid: "1001", name: "Grace" });
  assert.equal(await verifySession({ SESSION_SECRET: "other" }, token), null);
});

test("an expired token fails verification", async () => {
  const { token, payload } = await issueSession(env, { uid: "1001", name: "Grace" }, -10);
  assert.ok(payload.exp < Math.floor(Date.now() / 1000));
  assert.equal(await verifySession(env, token), null);
});

test("garbage tokens are rejected without throwing", async () => {
  for (const t of [null, undefined, "", "no-dot", "a.b.c", "..", 42]) {
    assert.equal(await verifySession(env, t), null);
  }
});

test("needsRefresh true only inside the refresh window", async () => {
  const now = Math.floor(Date.now() / 1000);
  assert.equal(needsRefresh({ exp: now + 60 }), true);
  assert.equal(needsRefresh({ exp: now + 3600 }), false);
});
