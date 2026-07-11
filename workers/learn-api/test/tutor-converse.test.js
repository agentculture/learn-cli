// t15 (spec c24/h11): the broker + a Bedrock **Converse**-shaped payload.
//
// Additive proof that the Nova Pro wiring really is CONFIG ONLY: handleTutor's
// forward-verbatim code (unchanged since t9) already carries a native Converse
// request — system:[{text}], messages:[{role, content:[{text}]}],
// inferenceConfig:{maxTokens, temperature} — to INFERENCE_URL untouched, adds
// exactly the `learner` stamp as one extra top-level field (live-verified as
// tolerated by the Converse API on 2026-07-11; see README.md "For t15"), and
// hands the Converse-shaped response (output.message.content[].text,
// stopReason, usage) back to the client byte-for-byte. No provider SDK, no
// shape translation, no new headers.
//
// The URL below is the real production target (commented out in wrangler.toml
// until t17 flips it live); here it is only a stub key — no network happens.

import { test } from "node:test";
import assert from "node:assert/strict";

import worker from "../src/index.js";
import { TERMS_VERSION } from "../src/terms.js";
import {
  makeEnv,
  makeFetchStub,
  mintToken,
  seedConsent,
  jsonResp,
  authedRequest,
} from "./helpers.js";

const BASE = "https://learn-api.example";
const CONVERSE_URL =
  "https://bedrock-runtime.us-east-1.amazonaws.com/model/us.amazon.nova-pro-v1:0/converse";

/** A consented + approved learner env pointing the broker at the Converse URL. */
async function approvedEnv(fetchStub) {
  const env = makeEnv({
    INFERENCE_URL: CONVERSE_URL,
    INFERENCE_TOKEN: "bedrock-api-key",
    FETCH: fetchStub,
  });
  seedConsent(env, "42", TERMS_VERSION);
  env.DB.learners.set("42", {
    github_user_id: "42",
    display_name: "Ada",
    state: JSON.stringify({ approved: true }),
  });
  const { token } = await mintToken(env, { uid: "42", name: "Ada" });
  return { env, token };
}

function call(env, request) {
  return worker.fetch(request, env, { waitUntil() {} });
}

test("broker forwards a Converse-shaped payload verbatim + the learner stamp", async () => {
  const converseResponse = {
    metrics: { latencyMs: 491 },
    output: { message: { content: [{ text: "OK" }], role: "assistant" } },
    stopReason: "end_turn",
    usage: { inputTokens: 11, outputTokens: 2, totalTokens: 13 },
  };
  const fetchStub = makeFetchStub({ [CONVERSE_URL]: () => jsonResp(converseResponse) });
  const { env, token } = await approvedEnv(fetchStub);

  const payload = {
    system: [{ text: "You are the learn tutor." }],
    messages: [{ role: "user", content: [{ text: "Grade my answer: ..." }] }],
    inferenceConfig: { maxTokens: 300, temperature: 0 },
  };
  const res = await call(
    env,
    authedRequest(`${BASE}/api/tutor`, token, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  );

  assert.equal(res.status, 200);
  assert.equal(fetchStub.calls.length, 1);
  const outbound = fetchStub.calls[0];
  assert.equal(outbound.url, CONVERSE_URL);
  assert.equal(outbound.init.headers.Authorization, "Bearer bedrock-api-key");
  assert.equal(outbound.init.headers["Content-Type"], "application/json");

  // Forward-verbatim: the Converse fields pass through UNCHANGED, and the
  // one addition is the broker's top-level learner stamp — nothing else.
  const forwarded = JSON.parse(outbound.init.body);
  assert.deepEqual(forwarded, { ...payload, learner: "42" });

  // The Converse response comes back byte-shape-identical to the client.
  const body = await res.json();
  assert.deepEqual(body, converseResponse);
});

test("a Converse error status passes through the broker untranslated", async () => {
  // Bedrock validation errors (e.g. a malformed inferenceConfig) surface as
  // 4xx JSON — the dumb broker relays status + body rather than inventing
  // its own error vocabulary for upstream failures.
  const fetchStub = makeFetchStub({
    [CONVERSE_URL]: () => jsonResp({ message: "Malformed input request" }, 400),
  });
  const { env, token } = await approvedEnv(fetchStub);

  const res = await call(
    env,
    authedRequest(`${BASE}/api/tutor`, token, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: [] }),
    }),
  );

  assert.equal(res.status, 400);
  const body = await res.json();
  assert.equal(body.message, "Malformed input request");
  assert.equal(fetchStub.calls.length, 1);
});
