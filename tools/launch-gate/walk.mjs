// walk.mjs — the scripted success walk (web audience test + parity bridge).
//
// Runs the whole thing against the REAL local topology (api-server.mjs: the
// production worker + its /learn zone-mount proxy in front of the built static
// site) at BOTH a phone viewport (390x844) and a desktop viewport (1280x800):
//
//   Signed-out visitor  — loads /learn/, sees three subject cards, opens a
//     french story (asserts story body + glossary), asserts html[data-auth="out"]
//     + the invitation card, and asserts the network invariant: a signed-out
//     story visit fires exactly ONE /learn/api/* call (GET /api/me) and NOTHING
//     else — no /progress, /record, /tutor. (spec c21/c22, the resource gate.)
//
//   Signed-in learner   — a context carrying a minted session cookie: loads
//     /learn/, asserts html[data-auth="in"] + the display name; then, per subject
//     (french, spanish, culture-guide), records a pass by CLICKING the story
//     exercise's record button (the real web write path), and asserts the
//     subject page's learner panel hydrates to reflect it — cross-checked against
//     the raw GET /api/progress/:subject the panel reads from (parity a: web == API).
//
//   Parity bridge (c)   — the SAME session token is written into a `learn` CLI
//     profile (auth.json) pointed at this local API; `learn record <subject>` then
//     syncs a DIFFERENT item to the API, and the subject page is reloaded to prove
//     that CLI-synced row appears IDENTICALLY in the browser-rendered panel and the
//     raw API view (web count == API count, and the CLI item_id is present in both).
//
// Degrades gracefully: if the browser can't launch, browser-level checks are
// marked SKIPPED and a fetch/DOM fallback still exercises the API-level walk so
// the gate never silently passes on an un-run browser check.

import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { mkdtempSync, mkdirSync, writeFileSync, appendFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { startTopology } from "./api-server.mjs";

const execFileAsync = promisify(execFile);

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "..", "..");
const distDeploy =
  process.env.LAUNCH_GATE_DIST_DEPLOY || join(repoRoot, "site-astro", "dist-deploy");
const resultsFile = process.env.LAUNCH_GATE_RESULTS || "";
const liveOrigin = process.env.LIVE_ORIGIN || ""; // documented live-mode override

const SUBJECT_BINS = (
  process.env.LAUNCH_GATE_SUBJECT_BIN ||
  "/home/spark/git/french-cli/.venv/bin:" +
    "/home/spark/git/spanish-cli/.venv/bin:" +
    "/home/spark/git/culture-guide/.venv/bin"
).split(":");

const VIEWPORTS = [
  { label: "phone", width: 390, height: 844 },
  { label: "desktop", width: 1280, height: 800 },
];

// Per subject: the story page that carries a recordable exercise (+glossary),
// its story-exercise item id (the web write), and a DIFFERENT lesson item id
// (the CLI write, to prove a synced row is distinct + visible).
const SUBJECTS = [
  {
    name: "french",
    storyPath: "/learn/french/stories/fr-b1-le-covoiturage/",
    subjectPath: "/learn/french/",
    lessonItem: "fr.greetings.bonjour",
  },
  {
    name: "spanish",
    storyPath: "/learn/spanish/stories/es-b1-el-tren-perdido/",
    subjectPath: "/learn/spanish/",
    lessonItem: "es.saludos.hola",
  },
  {
    name: "culture-guide",
    storyPath: "/learn/culture-guide/stories/cg-scenario-the-confident-intern/",
    subjectPath: "/learn/culture-guide/",
    lessonItem: "tokens",
  },
];

// --- results plumbing --------------------------------------------------------

const results = [];
function record(check, status, detail = "") {
  results.push({ audience: "web", check, status, detail });
  const tag = status.padEnd(5);
  console.log(`  [${tag}] ${check}${detail ? " — " + detail : ""}`);
}
function assert(cond, check, detailPass = "", detailFail = "") {
  if (cond) record(check, "PASS", detailPass);
  else record(check, "FAIL", detailFail || "assertion failed");
  return !!cond;
}

// --- CLI bridge (parity c) ---------------------------------------------------

function cliEnv(origin, homeDir) {
  return {
    ...process.env,
    PATH: SUBJECT_BINS.join(":") + ":" + process.env.PATH,
    LEARN_API_URL: origin + "/learn/api",
    LEARN_CLI_HOME: homeDir,
    XDG_DATA_HOME: join(homeDir, "xdg"),
  };
}

function writeAuthJson(homeDir, token, learner) {
  mkdirSync(homeDir, { recursive: true });
  writeFileSync(
    join(homeDir, "auth.json"),
    JSON.stringify({
      token,
      token_type: "Bearer",
      expires_at: Math.floor(Date.now() / 1000) + 3600,
      learner: { github_user_id: String(learner.uid), display_name: learner.name },
    }),
  );
}

async function learnRecord(env, subject, item) {
  // Async on purpose: the api-server the CLI child POSTs to shares THIS node
  // process's event loop, so a synchronous execFileSync would deadlock (the
  // loop can't serve the CLI's /record while blocked waiting for the child).
  // Returns the parsed --json payload; rejects on non-zero exit.
  const { stdout } = await execFileAsync("uv", ["run", "learn", "record", subject,
    "--item", item, "--result", "pass", "--activity", "lesson", "--json"], {
    cwd: repoRoot, env, encoding: "utf8", timeout: 60000,
  });
  return JSON.parse(stdout);
}

// --- browser walk ------------------------------------------------------------

async function apiProgress(page, subject) {
  return page.evaluate(async (s) => {
    const r = await fetch(`/learn/api/progress/${s}`, { credentials: "include" });
    if (!r.ok) return { ok: false, status: r.status };
    return { ok: true, ...(await r.json()) };
  }, subject);
}

async function signedOutWalk(browser, topo, vp) {
  const context = await browser.newContext({ viewport: { width: vp.width, height: vp.height } });
  const page = await context.newPage();
  const apiCalls = [];
  page.on("request", (req) => {
    const u = new URL(req.url());
    if (u.pathname.startsWith("/learn/api")) apiCalls.push(u.pathname);
  });

  // Landing: three subject cards + the signed-out invitation card.
  await page.goto(topo.origin + "/learn/", { waitUntil: "load" });
  await page.waitForFunction(() => document.documentElement.getAttribute("data-auth") === "out");
  const cards = await page.$$eval("a.subject-card", (els) => els.length);
  assert(cards === 3, `[${vp.label}] signed-out landing shows 3 subject cards`, `${cards} cards`,
    `expected 3 subject cards, saw ${cards}`);
  const invitationVisible = await page.evaluate(() => {
    const el = [...document.querySelectorAll(".panel-out .lede, .lede")].find((e) =>
      e.textContent.includes("Sign in to track progress"));
    return !!el && el.offsetParent !== null;
  });
  assert(invitationVisible, `[${vp.label}] signed-out landing invitation card visible`, "",
    "invitation card not visible");

  // Open a french story — reset the network log so the assertion is per-visit.
  apiCalls.length = 0;
  await page.goto(topo.origin + SUBJECTS[0].storyPath, { waitUntil: "load" });
  await page.waitForFunction(() => document.documentElement.getAttribute("data-auth") === "out");

  const hasBody = await page.$$eval(".story-body .prose p", (ps) => ps.length);
  assert(hasBody >= 3, `[${vp.label}] signed-out story renders its body`, `${hasBody} paragraphs`,
    `expected story body paragraphs, saw ${hasBody}`);
  const hasGlossary = await page.$$eval(".glossary .glossary-entry", (es) => es.length);
  assert(hasGlossary >= 1, `[${vp.label}] signed-out story renders its glossary`,
    `${hasGlossary} glossary entries`, "no glossary entries found");

  const authState = await page.evaluate(() => document.documentElement.getAttribute("data-auth"));
  assert(authState === "out", `[${vp.label}] signed-out html[data-auth="out"]`, "", `data-auth=${authState}`);

  const ctaVisible = await page.evaluate(() => {
    const el = document.querySelector(".cta-note");
    return !!el && el.offsetParent !== null; // sign-in CTA on the story page
  });
  assert(ctaVisible, `[${vp.label}] signed-out story sign-in CTA visible`, "", "story CTA not visible");

  // The network invariant: exactly one /learn/api call, and it is /api/me.
  await page.waitForTimeout(250); // let any stray call surface
  const nonMe = apiCalls.filter((p) => p !== "/learn/api/me");
  const meCount = apiCalls.filter((p) => p === "/learn/api/me").length;
  assert(nonMe.length === 0 && meCount === 1,
    `[${vp.label}] signed-out story fires ONLY GET /api/me (no progress/record/tutor)`,
    `api calls: ${JSON.stringify(apiCalls)}`,
    `unexpected api calls: ${JSON.stringify(apiCalls)}`);

  await context.close();
}

async function signedInWalk(browser, topo, vp) {
  const learner = { uid: "42", name: "Ada Gate" };
  const { token } = await topo.mintToken(learner);
  const context = await browser.newContext({
    viewport: { width: vp.width, height: vp.height },
  });
  await context.addCookies([
    { url: topo.origin, name: "session", value: token, httpOnly: true, secure: false, sameSite: "Lax" },
  ]);
  const page = await context.newPage();

  // Landing: signed-in state + display name.
  await page.goto(topo.origin + "/learn/", { waitUntil: "load" });
  await page.waitForFunction(() => document.documentElement.getAttribute("data-auth") === "in",
    null, { timeout: 15000 });
  assert(true, `[${vp.label}] signed-in html[data-auth="in"]`);
  const name = await page.$eval(".auth-signedin .auth-name", (el) => el.textContent.trim())
    .catch(() => "");
  assert(name === learner.name, `[${vp.label}] signed-in header shows display name`,
    `"${name}"`, `expected "${learner.name}", saw "${name}"`);

  // Isolated CLI profile for the parity bridge, sharing this run's token.
  const cliHome = mkdtempSync(join(tmpdir(), "learn-gate-cli-"));
  writeAuthJson(cliHome, token, learner);
  const env = cliEnv(topo.origin, cliHome);

  for (const subj of SUBJECTS) {
    // 1. WEB write: click the story exercise's "Got it" (pass) button.
    await page.goto(topo.origin + subj.storyPath, { waitUntil: "load" });
    await page.waitForFunction(() => document.documentElement.getAttribute("data-auth") === "in",
      null, { timeout: 15000 });
    const btn = page.locator('[data-record] button[data-result="pass"]').first();
    await btn.waitFor({ state: "visible", timeout: 10000 });
    const webItem = await page.locator("[data-record]").first().getAttribute("data-item-id");
    await btn.click();
    await page.waitForFunction(
      () => {
        const s = document.querySelector("[data-record-status]");
        return s && /Recorded/.test(s.textContent);
      },
      null,
      { timeout: 10000 },
    );
    record(`[${vp.label}] ${subj.name}: web records a pass (story exercise button)`, "PASS", webItem);

    // API view right after the web write.
    const afterWeb = await apiProgress(page, subj.name);
    assert(afterWeb.ok && afterWeb.items_touched === 1 && (afterWeb.mastery || {})[webItem] === "mastered",
      `[${vp.label}] ${subj.name}: web write lands in /api/progress`,
      `touched=${afterWeb.items_touched}`,
      `progress=${JSON.stringify(afterWeb)}`);

    // 2. CLI write (parity bridge): sync a DIFFERENT item via `learn record`.
    let cliPayload;
    try {
      cliPayload = await learnRecord(env, subj.name, subj.lessonItem);
    } catch (err) {
      record(`[${vp.label}] ${subj.name}: CLI 'learn record' syncs to the API`, "FAIL",
        String(err).split("\n")[0]);
      continue;
    }
    const synced = cliPayload.sync && cliPayload.sync.signed_in && cliPayload.sync.ok &&
      cliPayload.sync.synced >= 1;
    assert(synced, `[${vp.label}] ${subj.name}: CLI 'learn record' syncs to the API`,
      `sync=${JSON.stringify(cliPayload.sync)}`, `sync did not report a push: ${JSON.stringify(cliPayload.sync)}`);

    // 3. Reload the subject page → panel must show the CLI-synced row too.
    await page.goto(topo.origin + subj.subjectPath, { waitUntil: "load" });
    await page.waitForFunction(() => document.documentElement.getAttribute("data-auth") === "in",
      null, { timeout: 15000 });
    await page.waitForSelector(`[data-learner-panel="${subj.name}"] [data-slot="stats"]:not([hidden])`,
      { timeout: 15000 });
    const panel = await page.evaluate((s) => {
      const root = document.querySelector(`[data-learner-panel="${s}"]`);
      return {
        touched: Number(root.querySelector('[data-slot="touched"]').textContent),
        mastered: Number(root.querySelector('[data-slot="mastered"]').textContent),
      };
    }, subj.name);
    const api = await apiProgress(page, subj.name);
    const cliItemInApi = !!(api.mastery || {})[subj.lessonItem];

    assert(
      panel.touched === api.items_touched && panel.mastered === api.items_mastered &&
        api.items_touched === 2 && cliItemInApi,
      `[${vp.label}] ${subj.name}: PARITY web panel == API, CLI-synced row visible`,
      `panel(touched=${panel.touched},mastered=${panel.mastered}) == api(touched=${api.items_touched},mastered=${api.items_mastered}); CLI item '${subj.lessonItem}' present`,
      `panel=${JSON.stringify(panel)} api=${JSON.stringify({ t: api.items_touched, m: api.items_mastered })} cliItemInApi=${cliItemInApi}`,
    );
  }

  rmSync(cliHome, { recursive: true, force: true });
  await context.close();
}

// --- fetch/DOM fallback (no browser) -----------------------------------------

async function fetchFallback(topo) {
  console.log("  (browser unavailable — running fetch/DOM fallback; browser-level checks SKIPPED)");
  const skips = [
    'signed-out landing shows 3 subject cards',
    'signed-out landing invitation card visible',
    'signed-out story renders its body',
    'signed-out story renders its glossary',
    'signed-out html[data-auth="out"]',
    'signed-out story sign-in CTA visible',
    'signed-out story fires ONLY GET /api/me (no progress/record/tutor)',
    'signed-in html[data-auth="in"]',
    'signed-in header shows display name',
    'signed-in web records a pass (story exercise button)',
    'PARITY web panel == API, CLI-synced row visible',
  ];
  for (const s of skips) record(`[browser] ${s}`, "SKIP", "browser could not launch");

  // Still prove the API-level walk works end to end (no rendering).
  const landing = await fetch(topo.origin + "/learn/").then((r) => r.text());
  assert((landing.match(/subject-card/g) || []).length >= 3,
    "[fetch] landing HTML carries 3 subject cards", "", "cards missing in raw HTML");
  const story = await fetch(topo.origin + SUBJECTS[0].storyPath).then((r) => r.text());
  assert(story.includes("Glossary") && story.length > 5000,
    "[fetch] french story HTML carries body + glossary", "", "story body/glossary missing");
  const meOut = await fetch(topo.origin + "/learn/api/me");
  assert(meOut.status === 401, "[fetch] signed-out /api/me is 401", "", `status=${meOut.status}`);

  const { token } = await topo.mintToken({ uid: "42", name: "Ada Gate" });
  const cookie = { headers: { Cookie: "session=" + token } };
  const meIn = await fetch(topo.origin + "/learn/api/me", cookie).then((r) => r.json());
  assert(meIn.authenticated === true, "[fetch] signed-in /api/me authenticated", "", JSON.stringify(meIn));
  const rec = await fetch(topo.origin + "/learn/api/record", {
    method: "POST",
    headers: { Cookie: "session=" + token, "Content-Type": "application/json" },
    body: JSON.stringify({ subject: "french", recorded: { item_id: "fr.demo.1", activity: "story", result: "pass", at: new Date().toISOString() } }),
  });
  assert(rec.status === 201, "[fetch] signed-in POST /api/record 201", "", `status=${rec.status}`);
  const prog = await fetch(topo.origin + "/learn/api/progress/french", cookie).then((r) => r.json());
  assert(prog.items_touched === 1, "[fetch] /api/progress reflects the record", "", JSON.stringify(prog));
}

// --- main --------------------------------------------------------------------

async function main() {
  let chromium = null;
  try {
    ({ chromium } = await import("playwright"));
  } catch {
    chromium = null;
  }

  let browser = null;
  if (chromium) {
    try {
      browser = await chromium.launch({ headless: true });
    } catch (err) {
      console.log("  browser launch failed:", String(err).split("\n")[0]);
      browser = null;
    }
  }

  if (browser) {
    for (const vp of VIEWPORTS) {
      console.log(`\n== viewport: ${vp.label} (${vp.width}x${vp.height}) ==`);
      const topo = liveOrigin
        ? { origin: liveOrigin, mintToken: async () => ({ token: process.env.LIVE_SESSION_TOKEN || "" }) }
        : await startTopology({ distDeployDir: distDeploy });
      try {
        await signedOutWalk(browser, topo, vp);
        if (!liveOrigin) await signedInWalk(browser, topo, vp);
      } finally {
        if (!liveOrigin) await topo.close();
      }
    }
    await browser.close();
  } else {
    const topo = await startTopology({ distDeployDir: distDeploy });
    try {
      await fetchFallback(topo);
    } finally {
      await topo.close();
    }
  }

  if (resultsFile) {
    for (const r of results) appendFileSync(resultsFile, JSON.stringify(r) + "\n");
  }
  const failed = results.filter((r) => r.status === "FAIL");
  const skipped = results.filter((r) => r.status === "SKIP");
  console.log(`\nwalk: ${results.length} checks — ${results.length - failed.length - skipped.length} PASS, ${failed.length} FAIL, ${skipped.length} SKIP`);
  process.exit(failed.length ? 1 : 0);
}

main().catch((err) => {
  console.error("walk crashed:", err);
  if (resultsFile) appendFileSync(resultsFile, JSON.stringify({ audience: "web", check: "walk harness", status: "FAIL", detail: String(err).split("\n")[0] }) + "\n");
  process.exit(1);
});
