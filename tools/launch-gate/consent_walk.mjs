// consent_walk.mjs — the consent → approval → tutoring → deletion success
// signals (t17), end-to-end over a REAL origin.
//
// This is the launch-gate half that walk.mjs (the signed-in/out progress walk)
// does not cover: the uplift's four new guarantees exercised as HTTP flows,
// not unit-mocked. It runs in two modes, and the SAME check ids appear in both
// so the pre/post-deploy diff is legible:
//
//   LOCAL (default) — stands up the real production topology in-process
//   (api-server.mjs: the actual Worker default export + the built site behind
//   one origin) and drives the FULL authed flows with real tokens: a fresh
//   sign-in writes zero D1 rows until consent is accepted (consent row before
//   the learner row); a version bump forces re-consent; self-serve delete
//   erases every row and revokes the session; a consented-but-unapproved
//   /api/tutor call gets 403 with the inference endpoint called ZERO times;
//   an admin approve flips the tutoring tier and revoke withdraws it; the
//   voice-token mint enforces the same gate in the same order; and the policy
//   / consent / voice pages plus cloze story content are actually served.
//   This is the "passes now" evidence (spec h17).
//
//   LIVE (LIVE_ORIGIN=https://agentculture.org) — probes the deployed origin's
//   UNAUTHENTICATED surface only (the gate cannot mint a prod session): the new
//   routes must answer 401 (not 404), and the new pages must exist and carry
//   their markers. Against TODAY's pre-uplift prod these FAIL (routes/pages
//   404) — that failure IS the h17 baseline; after the supervised deploy the
//   same probes pass. The authed flows stay proven by the LOCAL run above and
//   by the Worker's own 168 unit tests (run as a separate run.sh step).
//
// Emits one NDJSON line {audience, check, status, detail} per check to
// $LAUNCH_GATE_RESULTS (folded into report.py's table); exits non-zero on any
// FAIL. Detail strings are kept quote/backslash-free for the NDJSON.

import { appendFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { startTopology, mintToken } from "./api-server.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "..", "..");

const liveOrigin = process.env.LIVE_ORIGIN || "";
const resultsFile = process.env.LAUNCH_GATE_RESULTS || "";
const distDeploy = process.env.LAUNCH_GATE_DIST_DEPLOY || resolve(repoRoot, "site-astro", "dist-deploy");

const results = [];
function emit(audience, check, status, detail = "") {
  const clean = String(detail).replace(/["\\\n\r]/g, " ").slice(0, 180);
  results.push({ audience, check, status, detail: clean });
  const mark = status === "PASS" ? "PASS " : status === "SKIP" ? "SKIP " : "FAIL ";
  console.log(`  [${mark}] (${audience}) ${check}${clean ? " — " + clean : ""}`);
}

// A check helper: run `fn`, PASS if it does not throw, FAIL with the message.
async function check(audience, id, fn) {
  try {
    const detail = (await fn()) || "";
    emit(audience, id, "PASS", detail);
  } catch (err) {
    emit(audience, id, "FAIL", String(err && err.message ? err.message : err).split("\n")[0]);
  }
}

function assert(cond, msg) {
  if (!cond) throw new Error(msg);
}

const bearer = (token) => ({ headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" } });

async function jget(url, token) {
  const res = await fetch(url, token ? bearer(token) : {});
  let body = {};
  try {
    body = await res.json();
  } catch {
    body = {};
  }
  return { status: res.status, body };
}

async function jpost(url, token, payload) {
  const init = { method: "POST", ...(token ? bearer(token) : { headers: { "Content-Type": "application/json" } }) };
  init.body = JSON.stringify(payload || {});
  const res = await fetch(url, init);
  let body = {};
  try {
    body = await res.json();
  } catch {
    body = {};
  }
  return { status: res.status, body };
}

// ============================================================================
// LOCAL mode — the full authed flows against the in-process topology.
// ============================================================================

async function localFlows() {
  const topo = await startTopology({ distDeployDir: distDeploy });
  const api = topo.origin + "/learn/api";
  const site = topo.origin + "/learn";
  // A known admin id for the admin-surface checks (the topology's makeEnv has
  // no ADMIN_GITHUB_IDS; set one so isAdmin has an allow-list to enforce).
  topo.env.ADMIN_GITHUB_IDS = "999";

  try {
    // --- consent gate: zero writes before accept, consent row before learner --
    await check("consent", "consent_zero_writes_until_accept", async () => {
      const uid = "1001";
      const { token: pending } = await mintToken(topo.env, { uid, name: "Ada Pending" }, 600, {
        pendingConsent: true,
      });
      const writesBefore = topo.db.writes.length;
      const me = await jget(api + "/me", pending);
      assert(me.status === 200 && me.body.pending_consent === true, "GET /api/me must report pending_consent");
      const prog = await jget(api + "/progress/french", pending);
      assert(prog.status === 403 && prog.body.error === "consent_required", "pending progress must 403 consent_required");
      assert(topo.db.writes.length === writesBefore, "NO D1 write may occur before consent is accepted");
      return "pending session: /api/me pending, /progress 403, zero writes";
    });

    await check("consent", "consent_accept_writes_consent_before_learner", async () => {
      const uid = "1001b";
      const { token: pending } = await mintToken(topo.env, { uid, name: "Ada Accept" }, 600, {
        pendingConsent: true,
      });
      const from = topo.db.writes.length;
      const acc = await jpost(api + "/consent/accept", pending, {});
      assert(acc.status === 200 && acc.body.status === "consented", "accept must return consented + full token");
      const newWrites = topo.db.writes.slice(from);
      const consentIdx = newWrites.findIndex((w) => w.table === "consents" && w.op === "insert");
      const learnerIdx = newWrites.findIndex((w) => w.table === "learners" && w.op === "insert");
      assert(consentIdx >= 0 && learnerIdx >= 0, "accept must insert both a consent and a learner row");
      assert(consentIdx < learnerIdx, "the consent row must be written BEFORE the learner row");
      // And a record write now succeeds under the full token.
      const rec = await jpost(api + "/record", acc.body.token, {
        subject: "french",
        recorded: { item_id: "fr.greetings.bonjour", result: "pass", activity: "lesson", at: "2026-07-11T00:00:00Z" },
      });
      assert(rec.status === 200 || rec.status === 201, `record after consent must succeed (got ${rec.status})`);
      return "consent row precedes learner row; record works post-consent";
    });

    // --- re-consent on a published-version bump ------------------------------
    await check("consent", "reconsent_on_version_bump", async () => {
      const uid = "1002";
      const { token: pending } = await mintToken(topo.env, { uid, name: "Bo Reconsent" }, 600, {
        pendingConsent: true,
      });
      const acc = await jpost(api + "/consent/accept", pending, {});
      assert(acc.status === 200, "initial consent must succeed");
      const full = acc.body.token;
      // A working consented request first.
      const ok = await jget(api + "/progress/french", full);
      assert(ok.status === 200, `consented progress must 200 (got ${ok.status})`);
      // Publish a new terms version → the SAME token is now stale.
      topo.env.TERMS_VERSION_OVERRIDE = "999.0.0";
      try {
        const stale = await jget(api + "/progress/french", full);
        assert(stale.status === 403 && stale.body.error === "consent_required", "stale token must 403 consent_required");
        assert(stale.body.reason === "stale_version", "the 403 must carry reason stale_version");
        // Re-accept (reachable on requireAuth, not requireConsented).
        const re = await jpost(api + "/consent/accept", full, {});
        assert(re.status === 200 && re.body.status === "consented", "re-accept must succeed");
      } finally {
        delete topo.env.TERMS_VERSION_OVERRIDE;
      }
      return "version bump routes the live token back to consent; re-accept clears it";
    });

    // --- self-serve delete erases every row and revokes the session ----------
    await check("delete", "self_serve_delete_erases_and_revokes", async () => {
      const uid = "1003";
      const { token: pending } = await mintToken(topo.env, { uid, name: "Cy Delete" }, 600, {
        pendingConsent: true,
      });
      const acc = await jpost(api + "/consent/accept", pending, {});
      const full = acc.body.token;
      await jpost(api + "/record", full, {
        subject: "french",
        recorded: { item_id: "fr.greetings.bonjour", result: "pass", activity: "lesson", at: "2026-07-11T00:00:00Z" },
      });
      const del = await jpost(api + "/delete", full, { confirm: uid });
      assert(del.status === 200, `delete must 200 (got ${del.status})`);
      // No row anywhere carries the id.
      const inLearners = topo.db.learners.has(uid);
      const inRecords = topo.db.records.some((r) => r.github_user_id === uid);
      const inConsents = topo.db.consents.some((c) => c.github_user_id === uid);
      assert(!inLearners && !inRecords && !inConsents, "delete must leave no learners/records/consents row");
      // The old token is revoked.
      const after = await jget(api + "/me", full);
      assert(after.status === 401, `revoked token must 401 (got ${after.status})`);
      return "all three tables cleared for the id; old token 401s";
    });

    // --- approval gate: 403 with ZERO outbound inference ---------------------
    await check("approval", "tutor_403_zero_inference_when_unapproved", async () => {
      // A counting inference endpoint; the gate must never reach it for a
      // consented-but-unapproved learner (spec h5).
      let inferenceCalls = 0;
      topo.env.FETCH = async (url, init) => {
        inferenceCalls += 1;
        return new Response(JSON.stringify({ echo: true }), { status: 200, headers: { "Content-Type": "application/json" } });
      };
      topo.env.INFERENCE_URL = "http://inference.invalid/v1";
      try {
        const uid = "1004";
        const { token: pending } = await mintToken(topo.env, { uid, name: "Di Unapproved" }, 600, {
          pendingConsent: true,
        });
        const acc = await jpost(api + "/consent/accept", pending, {});
        const tut = await jpost(api + "/tutor", acc.body.token, { messages: [] });
        assert(tut.status === 403 && tut.body.error === "approval_required", "unapproved tutor must 403 approval_required");
        assert(inferenceCalls === 0, `ZERO inference calls expected, got ${inferenceCalls}`);
        return "consented+unapproved /api/tutor 403; inference endpoint hit 0 times";
      } finally {
        delete topo.env.FETCH;
        delete topo.env.INFERENCE_URL;
      }
    });

    // --- admin approve/revoke flips the tutoring tier ------------------------
    await check("approval", "admin_approve_and_revoke_flip_tutoring", async () => {
      const adminUid = "999";
      const learnerUid = "1005";
      // Admin must itself be a consented learner to use authed routes.
      const { token: adminPending } = await mintToken(topo.env, { uid: adminUid, name: "Admin" }, 600, {
        pendingConsent: true,
      });
      const adminAcc = await jpost(api + "/consent/accept", adminPending, {});
      const adminTok = adminAcc.body.token;
      // The learner consents (c20: approve 409s unless the target's consent is current).
      const { token: lp } = await mintToken(topo.env, { uid: learnerUid, name: "El Approved" }, 600, {
        pendingConsent: true,
      });
      const lAcc = await jpost(api + "/consent/accept", lp, {});
      const learnerTok = lAcc.body.token;
      // Non-admin cannot list learners.
      const forbidden = await jget(api + "/admin/learners", learnerTok);
      assert(forbidden.status === 403, `non-admin admin route must 403 (got ${forbidden.status})`);
      // Admin can.
      const roster = await jget(api + "/admin/learners", adminTok);
      assert(roster.status === 200, `admin roster must 200 (got ${roster.status})`);
      // Approve the learner.
      const appr = await jpost(api + "/admin/approve", adminTok, { github_user_id: learnerUid });
      assert(appr.status === 200, `approve must 200 (got ${appr.status}: ${appr.body.error || ""})`);
      // The approved learner's tutor call now passes the approval gate — it
      // reaches the config check (503 no_inference, since INFERENCE_URL unset),
      // NOT the 403 approval_required wall.
      const tutApproved = await jpost(api + "/tutor", learnerTok, { messages: [] });
      assert(tutApproved.status !== 403, `approved tutor must clear the 403 gate (got ${tutApproved.status})`);
      assert(tutApproved.status === 503, `approved tutor with no INFERENCE_URL should 503 (got ${tutApproved.status})`);
      // Revoke → back to 403.
      const rev = await jpost(api + "/admin/revoke", adminTok, { github_user_id: learnerUid });
      assert(rev.status === 200, `revoke must 200 (got ${rev.status})`);
      const tutRevoked = await jpost(api + "/tutor", learnerTok, { messages: [] });
      assert(tutRevoked.status === 403 && tutRevoked.body.error === "approval_required", "revoked tutor must 403 again");
      return "non-admin 403; approve reaches config gate; revoke restores 403";
    });

    // --- voice-token mint enforces the same gate in the same order -----------
    await check("voice", "voice_token_same_gate_same_order", async () => {
      // Unapproved → 403 approval_required (BEFORE any 503 not_configured).
      const uid = "1006";
      const { token: pending } = await mintToken(topo.env, { uid, name: "Fi Voice" }, 600, {
        pendingConsent: true,
      });
      const acc = await jpost(api + "/consent/accept", pending, {});
      const learnerTok = acc.body.token;
      const unappr = await jpost(api + "/voice/token", learnerTok, {});
      assert(
        unappr.status === 403 && unappr.body.error === "approval_required",
        `unapproved voice must 403 approval_required (got ${unappr.status})`,
      );
      // Approve, then the mint reaches the config check: 503 not_configured
      // (VOICE_BRIDGE_URL unset) — proving the approval gate precedes config.
      const adminUid = "999";
      const { token: ap } = await mintToken(topo.env, { uid: adminUid, name: "Admin" }, 600, { pendingConsent: true });
      const adminTok = (await jpost(api + "/consent/accept", ap, {})).body.token;
      await jpost(api + "/admin/approve", adminTok, { github_user_id: uid });
      const approved = await jpost(api + "/voice/token", learnerTok, {});
      assert(
        approved.status === 503 && approved.body.error === "not_configured",
        `approved voice with no bridge must 503 not_configured (got ${approved.status}: ${approved.body.error})`,
      );
      return "unapproved 403 approval_required; approved 503 not_configured — approval before config";
    });

    // --- the new pages + cloze content are actually served -------------------
    await check("policy", "policy_consent_voice_pages_served", async () => {
      for (const path of ["/terms/", "/privacy/", "/consent/", "/voice/"]) {
        const res = await fetch(site + path);
        assert(res.status === 200, `GET /learn${path} must 200 (got ${res.status})`);
      }
      const privacy = await fetch(site + "/privacy/").then((r) => r.text());
      const lc = privacy.toLowerCase();
      for (const proc of ["github", "cloudflare", "bedrock"]) {
        assert(lc.includes(proc), `privacy page must name the ${proc} processor`);
      }
      return "terms/privacy/consent/voice served; privacy names github, cloudflare, bedrock";
    });

    await check("policy", "policy_pages_linked_from_learn_footer", async () => {
      const landing = await fetch(site + "/").then((r) => r.text());
      assert(/href="[^"]*\/terms\/?"/.test(landing), "the /learn footer must link Terms");
      assert(/href="[^"]*\/privacy\/?"/.test(landing), "the /learn footer must link Privacy");
      return "footer links Terms + Privacy";
    });

    await check("cloze", "tutor_panel_and_cloze_content_served", async () => {
      // The subject page carries the (signed-in-only) tutor panel markup.
      const subjectPage = await fetch(site + "/french/").then((r) => r.text());
      assert(subjectPage.includes("data-tutor-panel"), "the french subject page must carry the tutor panel");
      // A story known to ship a cloze exercise renders the pick-the-word widget.
      const storyPage = await fetch(site + "/french/stories/fr-b1-le-covoiturage/").then((r) => r.text());
      assert(storyPage.includes("data-cloze-blank"), "the cloze story must render a data-cloze-blank widget");
      return "subject page has the tutor panel; cloze story renders data-cloze-blank";
    });
  } finally {
    await topo.close();
  }
}

// ============================================================================
// LIVE mode — unauthenticated probes against the deployed origin.
//   Against pre-uplift prod these FAIL (404s) = the h17 baseline; post-deploy
//   they pass. State-safe: GETs + unauthenticated POSTs (rejected before any
//   write), never a real session, never a mutation.
// ============================================================================

async function liveProbes(origin) {
  const api = origin + "/learn/api";
  const site = origin + "/learn";

  // New routes must exist and reject the unauthenticated caller (401), not 404.
  const routeProbes = [
    ["GET", "/export"],
    ["POST", "/consent/accept"],
    ["GET", "/admin/learners"],
    ["POST", "/voice/token"],
  ];
  for (const [method, path] of routeProbes) {
    await check("uplift-live", `route_exists_${path.replace(/\//g, "_")}`, async () => {
      const res = method === "GET" ? await jget(api + path, "") : await jpost(api + path, "", {});
      assert(res.status === 401, `${method} /api${path} must exist + 401 unauthenticated (got ${res.status})`);
      return `${method} /api${path} -> 401 (route live)`;
    });
  }

  // The signed-out /api/tutor never spends inference (401, no session).
  await check("uplift-live", "tutor_signed_out_401", async () => {
    const res = await jpost(api + "/tutor", "", { messages: [] });
    assert(res.status === 401, `signed-out /api/tutor must 401 (got ${res.status})`);
    return "signed-out /api/tutor -> 401 (zero inference)";
  });

  // New pages must exist and carry their markers.
  const pageProbes = [
    ["/terms/", ["terms"]],
    ["/privacy/", ["github", "cloudflare", "bedrock"]],
    ["/consent/", ["consent"]],
    ["/voice/", ["voice"]],
  ];
  for (const [path, markers] of pageProbes) {
    await check("uplift-live", `page_live_${path.replace(/\//g, "_")}`, async () => {
      const res = await fetch(site + path);
      assert(res.status === 200, `GET /learn${path} must 200 (got ${res.status})`);
      const lc = (await res.text()).toLowerCase();
      for (const m of markers) assert(lc.includes(m), `/learn${path} must mention ${m}`);
      return `/learn${path} -> 200 with markers [${markers.join(", ")}]`;
    });
  }

  // The subject + cloze story content is live.
  await check("uplift-live", "tutor_panel_and_cloze_live", async () => {
    const subj = await fetch(site + "/french/").then((r) => r.text());
    assert(subj.includes("data-tutor-panel"), "french subject page must carry the tutor panel");
    const story = await fetch(site + "/french/stories/fr-b1-le-covoiturage/").then((r) => r.text());
    assert(story.includes("data-cloze-blank"), "cloze story must render data-cloze-blank");
    return "subject tutor panel + cloze widget live";
  });
}

// ============================================================================

async function main() {
  if (liveOrigin) {
    console.log(`\nconsent walk: LIVE mode against ${liveOrigin}`);
    console.log("  (pre-uplift prod is EXPECTED to fail these — that is the h17 baseline)");
    await liveProbes(liveOrigin);
  } else {
    console.log("\nconsent walk: LOCAL mode (in-process real topology)");
    await localFlows();
  }

  if (resultsFile) {
    for (const r of results) appendFileSync(resultsFile, JSON.stringify(r) + "\n");
  }
  const failed = results.filter((r) => r.status === "FAIL");
  const skipped = results.filter((r) => r.status === "SKIP");
  console.log(
    `\nconsent walk: ${results.length} checks — ${results.length - failed.length - skipped.length} PASS, ` +
      `${failed.length} FAIL, ${skipped.length} SKIP`,
  );
  process.exit(failed.length ? 1 : 0);
}

main().catch((err) => {
  console.error("consent walk crashed:", err);
  if (resultsFile) {
    appendFileSync(
      resultsFile,
      JSON.stringify({ audience: "uplift", check: "consent walk harness", status: "FAIL", detail: String(err).split("\n")[0] }) + "\n",
    );
  }
  process.exit(1);
});
