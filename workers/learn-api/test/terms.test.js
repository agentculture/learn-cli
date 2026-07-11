import { test } from "node:test";
import assert from "node:assert/strict";

import { TERMS_VERSION, TERMS_EFFECTIVE_DATE } from "../src/terms.js";

// Proves the worker side of the "single source of truth" design (spec #11,
// plan task t1): src/terms.js resolves through to shared/terms-version.mjs
// under Node's own module loader — the same loader `node --test` uses for
// every other file in this suite, no bundler involved. The Astro site's
// half of this same proof lives in the Python cross-check
// (tests/test_policy_pages.py at the repo root), which reads
// shared/terms-version.mjs directly since there's no Node toolchain in the
// Python test job.

test("TERMS_VERSION resolves through to the shared source", () => {
  assert.equal(TERMS_VERSION, "1.0.0");
  assert.match(TERMS_VERSION, /^\d+\.\d+\.\d+$/, "expected a semver string");
});

test("TERMS_EFFECTIVE_DATE is an ISO-8601 date matching the version", () => {
  assert.equal(TERMS_EFFECTIVE_DATE, "2026-07-11");
  assert.match(TERMS_EFFECTIVE_DATE, /^\d{4}-\d{2}-\d{2}$/);
});
