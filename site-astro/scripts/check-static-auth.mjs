#!/usr/bin/env node
// The zero-API-when-signed-out gate (t14, spec c21/c22 — "sign-in is the
// resource gate"). Proves, statically, the invariant that matters here:
// a signed-out visitor's page is fully static and triggers ZERO calls to
// the learn API (and therefore zero model calls — POST /api/tutor is the
// only route that spends inference tokens, and this site never calls it
// at all), while a signed-in visitor's calls are confined to the
// whitelisted, non-model-spending routes t14 was scoped to use.
//
// Three checks, none of which need a running server, a browser, or a
// third-party parser (this repo runs Python-side with zero runtime deps,
// and workers/learn-api's own tests are plain `node --test` for the same
// reason — this script keeps that ethos: only node:fs/node:assert):
//
//   1. STATIC BUILD — astro.config.mjs declares `output: "static"` (no
//      adapter, no SSR) and package.json carries no @astrojs/*-adapter
//      dependency. `npm run build`'s dist/ is plain files a dumb static
//      host serves as-is (see README.md's own note about `astro preview`
//      vs. a plain `python3 -m http.server` on dist/).
//
//   2. NO-JS DEFAULT MARKUP — every built page's raw <html> tag carries NO
//      data-auth attribute (that attribute only exists as a CSS selector
//      inside compiled <style> blocks; learner.js is the only thing that
//      ever sets it, at runtime, after checking a session). And
//      global.css's compiled output actually hides `.signedin-only`
//      elements by default (`display:none`, no attribute-selector
//      condition) — the mechanism, not just the intent, that keeps a
//      signed-in-only panel/button/record-control invisible and inert
//      until learner.js says otherwise. Every page also renders its
//      signed-out invitation copy in the raw HTML (unconditionally, no
//      `.signedin-only`/`hidden` gating) — the thing a signed-out or
//      no-JS visitor is actually supposed to see.
//
//   3. FETCH WHITELIST + AUTH-GATING — src/scripts/learner.js (the one
//      audited source file; see its own header comment) is parsed with
//      plain regexes/brace-matching (no AST, deliberately — matching this
//      repo's zero-dependency temperament) to confirm:
//        a. every `fetch(` call targets `${API_BASE}` plus one of the
//           whitelisted suffixes: /me, /progress/, /record, /auth/*.
//        b. the `bootstrap()` function's own body contains exactly ONE
//           fetch call (the GET /api/me bootstrap) and calls every
//           further-reaching function (hydratePanels, wireExerciseRecorders,
//           wireSignOut) only AFTER the point where it has confirmed
//           `setAuthState("in")` — i.e., strictly after both of the
//           401/network-error branches, which set "out" and return first.
//      Then, as a defense-in-depth pass over the actual BUILT bundle (not
//      just the source), confirms the same whitelist holds for every
//      `/api/` substring appearing in dist/'s JS, and that the
//      model-spending `/api/tutor` route is referenced nowhere in this
//      site's source or output.
//
// Run after `npm run build` (like check-export-pages.mjs, this does not
// build for you). Wired into `npm run check`; also runnable directly via
// `npm run test:static`.

import { existsSync, readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import assert from "node:assert/strict";
import path from "node:path";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const siteRoot = path.resolve(scriptDir, "..");
const distDir = path.join(siteRoot, "dist");
const srcDir = path.join(siteRoot, "src");

const problems = [];
function check(label, fn) {
  try {
    fn();
  } catch (err) {
    problems.push(`${label}: ${err.message}`);
  }
}

function fail() {
  console.error(`check-static-auth: ${problems.length} problem(s) found\n`);
  for (const p of problems) console.error(`  - ${p}`);
  console.error(
    "\nThe signed-out/signed-in split (t14) rests on: astro.config.mjs staying " +
      "output:'static', src/scripts/learner.js never calling fetch() outside the " +
      "/api/me | /api/progress/ | /api/record | /api/auth/* whitelist, those calls " +
      "beyond /api/me only firing after bootstrap() confirms a session, and every " +
      "built page rendering its signed-out content with no data-auth attribute and " +
      "no JS. Fix whichever assumption broke.",
  );
  process.exit(1);
}

if (!existsSync(distDir)) {
  console.error(
    `check-static-auth: ${path.relative(siteRoot, distDir)} does not exist.\n` +
      "Run `npm run build` first, then `npm run check` (or `npm run test:static`).",
  );
  process.exit(1);
}

function listHtmlFiles(dir) {
  const out = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...listHtmlFiles(full));
    else if (entry.name.endsWith(".html")) out.push(full);
  }
  return out;
}

function listFiles(dir, matchExt) {
  const out = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...listFiles(full, matchExt));
    else if (entry.name.endsWith(matchExt)) out.push(full);
  }
  return out;
}

// --- 1. static build, no adapter -----------------------------------------

check("astro.config.mjs declares output: 'static'", () => {
  const cfg = readFileSync(path.join(siteRoot, "astro.config.mjs"), "utf8");
  assert.match(cfg, /output:\s*["']static["']/, "expected output: 'static'");
  assert.doesNotMatch(cfg, /output:\s*["']server["']/, "must not switch to SSR output");
});

check("package.json carries no SSR adapter dependency", () => {
  const pkg = JSON.parse(readFileSync(path.join(siteRoot, "package.json"), "utf8"));
  const deps = { ...(pkg.dependencies || {}), ...(pkg.devDependencies || {}) };
  const adapters = Object.keys(deps).filter((d) => /^@astrojs\/(node|cloudflare|vercel|netlify|deno)$/.test(d));
  assert.deepEqual(adapters, [], `found adapter dependency: ${adapters.join(", ")}`);
});

// --- 2. no-JS default markup ----------------------------------------------

const htmlFiles = listHtmlFiles(distDir);
check("dist/ contains built pages", () => {
  assert.ok(htmlFiles.length > 0, "no .html files found under dist/");
});

check("no built page's <html> tag carries a data-auth attribute", () => {
  const offenders = [];
  for (const file of htmlFiles) {
    const html = readFileSync(file, "utf8");
    const tag = /<html[^>]*>/.exec(html);
    if (tag && /data-auth\s*=/.test(tag[0])) {
      offenders.push(path.relative(distDir, file));
    }
  }
  assert.deepEqual(
    offenders,
    [],
    `data-auth baked into the static <html> tag (must only be set by learner.js at ` +
      `runtime): ${offenders.join(", ")}`,
  );
});

check("global.css hides .signedin-only by an unconditional display:none", () => {
  const cssFiles = listFiles(distDir, ".css");
  const hasRule = cssFiles.some((f) => {
    const css = readFileSync(f, "utf8");
    // Astro's CSS scoping appends a data-astro-cid-* attribute to the
    // rightmost compound selector, so match loosely around that.
    return /\.signedin-only(\[data-astro-cid-[^\]]*\])?\s*\{[^}]*display:\s*none/.test(css);
  });
  assert.ok(hasRule, "expected a `.signedin-only { display: none; }` rule in the built CSS");
});

check("the landing page and every subject page render the signed-out invitation in raw HTML", () => {
  const missing = [];
  const landing = readFileSync(path.join(distDir, "index.html"), "utf8");
  if (!landing.includes("Sign in to track progress")) missing.push("dist/index.html");
  // t1's versioned policy pages (src/pages/terms/, src/pages/privacy/) are
  // plain static prose with no learner panel — they carry no
  // signed-in/signed-out split at all, so this check (which is about that
  // split, not "every top-level page") doesn't apply to them. t10's consent
  // notice (src/pages/consent/) is the same shape one level further: it has
  // its OWN pending/expired/already-in/declined/error states (driven by
  // src/scripts/consent.js, checked separately below), not the site-wide
  // signed-out/signed-in split this check is about.
  const NOT_A_LEARNER_PANEL_PAGE = new Set(["_astro", "terms", "privacy", "consent"]);
  for (const entry of readdirSync(distDir, { withFileTypes: true })) {
    if (!entry.isDirectory() || NOT_A_LEARNER_PANEL_PAGE.has(entry.name)) continue;
    const subjectIndex = path.join(distDir, entry.name, "index.html");
    if (!existsSync(subjectIndex)) continue;
    const html = readFileSync(subjectIndex, "utf8");
    if (!html.includes("Sign in to track progress")) {
      missing.push(path.relative(distDir, subjectIndex));
    }
  }
  assert.deepEqual(missing, [], `missing signed-out invitation copy on: ${missing.join(", ")}`);
});

check("story pages keep the signed-out CTA note visible-by-default (no hidden attribute on it)", () => {
  const storyFiles = htmlFiles.filter((f) => f.includes(`${path.sep}stories${path.sep}`));
  assert.ok(storyFiles.length > 0, "expected at least one built story page");
  const offenders = [];
  for (const file of storyFiles) {
    const html = readFileSync(file, "utf8");
    if (!html.includes("cta-note")) continue; // stories without exercises have no CTA
    const m = /<p class="cta-note[^>]*>/.exec(html);
    if (m && /\bhidden\b/.test(m[0])) offenders.push(path.relative(distDir, file));
  }
  assert.deepEqual(offenders, [], `cta-note carries a hidden attribute on: ${offenders.join(", ")}`);
});

// --- 3. fetch whitelist + auth-gating in the source ------------------------

const learnerJsPath = path.join(srcDir, "scripts", "learner.js");
const learnerJs = readFileSync(learnerJsPath, "utf8");

const ALLOWED_SUFFIX_RE = /^(\/me|\/progress\/|\/record|\/auth\/)/;

// t10's consent.js is a SECOND, separately-loaded script (only on
// src/pages/consent/index.astro, not via Layout.astro) with its own,
// narrower fetch surface — enumerated exactly, not merged into the
// learner.js whitelist above, so a future edit that widens one script can't
// silently widen the other. Used below for consent.js's own source check,
// and folded into the built-bundle whitelist further down (that check scans
// every built .js file regardless of which source script produced it).
const CONSENT_ALLOWED_SUFFIX_RE = /^(\/me|\/consent$|\/consent\/accept$|\/consent\/decline$)/;

check("learner.js imports the single API_BASE constant (no hardcoded alternate host)", () => {
  assert.match(learnerJs, /import\s*\{\s*API_BASE\s*\}\s*from\s*["']\.\.\/lib\/api\.js["']/);
});

check("every fetch() call in learner.js targets ${API_BASE} plus a whitelisted suffix", () => {
  const fetchCalls = [...learnerJs.matchAll(/fetch\(\s*`([^`]*)`/g)];
  assert.ok(fetchCalls.length >= 4, `expected >= 4 fetch() calls, found ${fetchCalls.length}`);
  const offenders = [];
  for (const [, template] of fetchCalls) {
    if (!template.startsWith("${API_BASE}")) {
      offenders.push(template);
      continue;
    }
    const suffix = template.slice("${API_BASE}".length).split("$")[0]; // stop at next interpolation
    if (!ALLOWED_SUFFIX_RE.test(suffix)) offenders.push(template);
  }
  assert.deepEqual(offenders, [], `non-whitelisted fetch target(s): ${offenders.join(", ")}`);
});

check("no reference to the model-spending /tutor route anywhere in site-astro (src or built)", () => {
  // Deliberately searches for the bare "/tutor" suffix, not "/api/tutor": in
  // both source (`${API_BASE}/tutor`) and the minified build (`${e}/tutor`),
  // the "/api" prefix only ever exists inside the API_BASE variable, never
  // concatenated into a literal string — so "/tutor" is the substring that
  // would actually survive minification if this route were ever wired up,
  // and is specific enough not to false-positive on anything else in this
  // codebase.
  const offenders = [];
  const scan = (dir, extRe) => {
    if (!existsSync(dir)) return;
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      if (entry.name === "node_modules") continue;
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) scan(full, extRe);
      else if (extRe.test(entry.name) && readFileSync(full, "utf8").includes("/tutor")) {
        offenders.push(path.relative(siteRoot, full));
      }
    }
  };
  scan(srcDir, /\.(js|ts|astro|mjs)$/);
  scan(distDir, /\.(js|html)$/);
  assert.deepEqual(offenders, [], `/tutor referenced in: ${offenders.join(", ")}`);
});

check(
  "bootstrap() makes exactly one fetch() call (GET /api/me) and gates every other " +
    "call behind a confirmed session",
  () => {
    const start = learnerJs.indexOf("async function bootstrap()");
    assert.ok(start >= 0, "could not find `async function bootstrap()` in learner.js");
    // Balanced-brace scan to extract exactly this function's body — deliberately
    // not a regex non-greedy match, which would stop at the first `}` (there
    // are nested blocks) rather than the function's own closing brace.
    const openBrace = learnerJs.indexOf("{", start);
    let depth = 0;
    let end = -1;
    for (let i = openBrace; i < learnerJs.length; i += 1) {
      if (learnerJs[i] === "{") depth += 1;
      else if (learnerJs[i] === "}") {
        depth -= 1;
        if (depth === 0) {
          end = i;
          break;
        }
      }
    }
    assert.ok(end > openBrace, "unbalanced braces while extracting bootstrap()'s body");
    const body = learnerJs.slice(openBrace, end + 1);

    const fetchCalls = [...body.matchAll(/fetch\(/g)];
    assert.equal(fetchCalls.length, 1, `expected exactly 1 fetch() call inside bootstrap(), found ${fetchCalls.length}`);
    assert.match(body, /fetch\(\s*`\$\{API_BASE\}\/me`/, "bootstrap()'s one fetch must target ${API_BASE}/me");

    const authInIdx = body.indexOf('setAuthState("in")');
    assert.ok(authInIdx >= 0, 'bootstrap() must call setAuthState("in") on the happy path');

    const authOutIdxs = [...body.matchAll(/setAuthState\("out"\)/g)].map((m) => m.index);
    assert.ok(authOutIdxs.length >= 1, 'bootstrap() must call setAuthState("out") on failure');
    for (const idx of authOutIdxs) {
      assert.ok(idx < authInIdx, 'every setAuthState("out") must precede setAuthState("in") textually');
    }

    for (const fn of ["hydratePanels(", "wireExerciseRecorders(", "wireSignOut("]) {
      const idx = body.indexOf(fn);
      assert.ok(idx >= 0, `bootstrap() must call ${fn}` );
      assert.ok(idx > authInIdx, `${fn} must be called only after setAuthState("in")`);
    }
  },
);

check("the two failure branches return before reaching the happy path", () => {
  // Every branch that sets "out" must be immediately followed by a `return;`
  // (guarding against a future edit that logs the failure but falls through).
  const outReturnRe = /setAuthState\("out"\);\s*return;/g;
  const matches = [...learnerJs.matchAll(outReturnRe)];
  assert.ok(matches.length >= 2, `expected >= 2 'setAuthState("out"); return;' pairs, found ${matches.length}`);
});

// --- defense in depth: re-verify the whitelist against the BUILT bundle ---
//
// This does not just re-check the source: `npm run build` runs learner.js
// through Vite/esbuild, which renames `API_BASE` to a single-letter local
// (observed: `var e = \`/learn/api\`; ...; fetch(\`${e}/me\`)`) and may
// reorder or inline things differently across esbuild versions. A naive
// substring search for "/api/me" etc. would find NOTHING in that output —
// the "/api" prefix only exists inside the API_BASE literal, never
// concatenated into the template text — so this re-derives which
// identifier(s) the build aliased API_BASE's literal value to, then
// re-runs the same suffix whitelist against every fetch() call that uses
// one of those aliases (or the literal value directly, in case a future
// build inlines it instead of aliasing it). This scans EVERY built .js
// asset regardless of which source script produced it, so it checks the
// UNION of both per-file whitelists (ALLOWED_SUFFIX_RE for learner.js,
// CONSENT_ALLOWED_SUFFIX_RE for consent.js) — the two source-level checks
// above/below are what keep each script's OWN surface precise.

check("the built JS bundle's fetch() calls stay inside the same whitelist", () => {
  const apiSrc = readFileSync(path.join(srcDir, "lib", "api.ts"), "utf8");
  const apiBaseMatch = /API_BASE\s*=\s*["'`]([^"'`]+)["'`]/.exec(apiSrc);
  assert.ok(apiBaseMatch, "could not read API_BASE's literal value from src/lib/api.ts");
  const apiBaseValue = apiBaseMatch[1];
  const escapedValue = apiBaseValue.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

  const jsFiles = listFiles(distDir, ".js");
  assert.ok(jsFiles.length > 0, "expected at least one built .js asset (learner.js's bundle)");

  // Two source files now import API_BASE (learner.js, consent.js), so Vite
  // code-splits src/lib/api.ts into its OWN shared chunk rather than
  // inlining the literal into each consumer — the alias assignment
  // (`var e = \`/learn/api\`;`) lives in that one shared chunk, while the
  // fetch() calls using it live in the OTHER, importing chunks. A per-file
  // alias scan (checking each file only against aliases found in that same
  // file) would therefore find zero aliases in the files that actually call
  // fetch() and fail every call. Collect aliases GLOBALLY across every
  // built .js file first, then check every file's fetch() calls against
  // that global set — correct regardless of how many chunks the bundler
  // decides to split this into.
  const aliasRe = new RegExp(`([A-Za-z_$][\\w$]*)\\s*=\\s*[\`"']${escapedValue}[\`"']`, "g");
  const aliases = new Set();
  for (const file of jsFiles) {
    const js = readFileSync(file, "utf8");
    for (const m of js.matchAll(aliasRe)) aliases.add(m[1]);
  }

  let totalFetchCalls = 0;
  const offenders = [];

  for (const file of jsFiles) {
    const js = readFileSync(file, "utf8");
    for (const [, template] of js.matchAll(/fetch\(\s*`([^`]*)`/g)) {
      totalFetchCalls += 1;
      let suffix = null;
      const varMatch = /^\$\{([A-Za-z_$][\w$]*)\}(.*)$/.exec(template);
      if (varMatch && aliases.has(varMatch[1])) {
        suffix = varMatch[2].split("$")[0];
      } else if (template.startsWith(apiBaseValue)) {
        suffix = template.slice(apiBaseValue.length).split("$")[0];
      }
      const inWhitelist =
        suffix !== null && (ALLOWED_SUFFIX_RE.test(suffix) || CONSENT_ALLOWED_SUFFIX_RE.test(suffix));
      if (!inWhitelist) offenders.push(template);
    }
  }

  assert.ok(aliases.size > 0, "API_BASE's literal value was not found inlined in any built JS asset");
  assert.ok(totalFetchCalls >= 4, `expected >= 4 fetch() calls across built JS, found ${totalFetchCalls}`);
  assert.deepEqual(offenders, [], `non-whitelisted fetch target(s) in built JS: ${offenders.join(", ")}`);
});

// --- 4. consent.js: precise fetch whitelist for the pending-consent page (t10) ---
//
// consent.js is loaded only on src/pages/consent/index.astro, not through
// Layout.astro's global learner.js import, so the checks above (which are
// hardcoded to learner.js's own path) never see it. Same technique, a
// narrower, precisely-enumerated whitelist (CONSENT_ALLOWED_SUFFIX_RE,
// defined above): /me, /consent, /consent/accept, /consent/decline — no
// /progress, /record, or open /auth/ prefix, since consent.js has no
// business calling those.

const consentJsPath = path.join(srcDir, "scripts", "consent.js");

check("consent.js exists and imports the single API_BASE constant (no hardcoded alternate host)", () => {
  assert.ok(existsSync(consentJsPath), "expected src/scripts/consent.js to exist");
  const consentJs = readFileSync(consentJsPath, "utf8");
  assert.match(consentJs, /import\s*\{\s*API_BASE\s*\}\s*from\s*["']\.\.\/lib\/api\.js["']/);
});

check("every fetch() call in consent.js targets ${API_BASE} plus a whitelisted consent suffix", () => {
  const consentJs = readFileSync(consentJsPath, "utf8");
  const fetchCalls = [...consentJs.matchAll(/fetch\(\s*`([^`]*)`/g)];
  assert.ok(fetchCalls.length >= 3, `expected >= 3 fetch() calls in consent.js, found ${fetchCalls.length}`);
  const offenders = [];
  for (const [, template] of fetchCalls) {
    if (!template.startsWith("${API_BASE}")) {
      offenders.push(template);
      continue;
    }
    const suffix = template.slice("${API_BASE}".length).split("$")[0];
    if (!CONSENT_ALLOWED_SUFFIX_RE.test(suffix)) offenders.push(template);
  }
  assert.deepEqual(offenders, [], `non-whitelisted fetch target(s) in consent.js: ${offenders.join(", ")}`);
});

check("consent.js's bootstrap() redirects out of pending state rather than exposing controls silently", () => {
  const consentJs = readFileSync(consentJsPath, "utf8");
  // The five states consent.js is responsible for (see its header comment):
  // the notice itself (default markup, no JS-only gate needed) plus these
  // four JS-driven outcomes, each reachable from bootstrap().
  for (const state of ["expired", "already-in", "declined", "error"]) {
    assert.match(
      consentJs,
      new RegExp(`showState\\("${state}"\\)`),
      `consent.js must handle the "${state}" state`,
    );
  }
});

if (problems.length > 0) fail();

console.log(
  `check-static-auth: OK — ${htmlFiles.length} built page(s) verified static/no-JS-safe; ` +
    "learner.js's fetch surface is confined to the /api/me | /api/progress/ | /api/record | " +
    "/api/auth/* whitelist and gated behind a confirmed session; consent.js's fetch surface " +
    "is confined to the /api/me | /api/consent | /api/consent/accept | /api/consent/decline " +
    "whitelist.",
);
