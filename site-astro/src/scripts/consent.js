// consent.js — the pending-consent notice, wired to workers/learn-api's
// consent endpoints (t10; spec c9/c19, "the consent UX shape"; see
// workers/learn-api/README.md's "For t10" section for the exact
// request/response contract this file drives). Loaded ONLY on
// src/pages/consent/index.astro's own <script> block — unlike learner.js,
// this is NOT imported by Layout.astro, so no other page pays for it.
//
// This is a second, narrowly-scoped audited surface, checked the same way
// learner.js is: scripts/check-static-auth.mjs parses this exact file and
// asserts its only fetch() targets are ${API_BASE} + /me, /consent,
// /consent/accept, or /consent/decline — nothing wider (no progress or
// record endpoint, and no reference to the inference-spending broker
// route this site never calls at all — see check-static-auth.mjs's
// site-wide scan for that one).
//
// Five states, driven by toggling `hidden` on the matching
// [data-state="..."] block under [data-consent-root] (same technique as
// learner.js's showEmpty()/statsEl toggling — no new design tokens):
//
//   notice      — default, visible with no JS at all (the what/why/
//                 retention/who-sees-it copy is static prose in the .astro
//                 file); once JS confirms a pending session it also wires
//                 the Accept/Decline buttons and overwrites the version
//                 fields with the live GET /api/consent value.
//   expired     — GET /api/me returned 401: the pending session's 10-minute
//                 TTL passed. Nothing was ever stored.
//   already-in  — a full (non-pending) session already exists: redirect
//                 straight into the signed-in hub.
//   declined    — POST /api/consent/decline succeeded: confirm nothing
//                 stored (the response's `stored: false` is that guarantee).
//   error       — an unexpected failure (network, non-401 non-2xx) at any
//                 step; never a silent dead page.
import { API_BASE } from "../lib/api.js";

const root = document.querySelector("[data-consent-root]");

function showState(name) {
  if (!root) return;
  root.querySelectorAll("[data-state]").forEach((el) => {
    el.hidden = el.getAttribute("data-state") !== name;
  });
}

function setField(selector, text) {
  if (!root || !text) return;
  const el = root.querySelector(selector);
  if (el) el.textContent = text;
}

function setLink(selector, href) {
  if (!root || !href) return;
  const el = root.querySelector(selector);
  if (el) el.setAttribute("href", href);
}

/** Render the live consent requirement (version/date/policy links) into the
 * notice, overwriting the build-time TERMS_VERSION/TERMS_EFFECTIVE_DATE
 * fallback already in the markup — the runtime value from the API is
 * authoritative (it is what actually gets recorded on accept). */
function renderRequirement(required) {
  if (!required) return;
  setField('[data-field="version"]', required.terms_version);
  setField('[data-field="effective-date"]', required.effective_date);
  setLink('[data-field="terms-link"]', required.terms_url);
  setLink('[data-field="privacy-link"]', required.privacy_url);
}

/** GET /api/consent is public (no session needed) and returns the same
 * requirement shape as /api/me's `consent_required` — fetched independently
 * so the live version renders even if something about the session check is
 * slow or the visitor is mid-flow, per the "authoritative value" contract. */
async function loadLiveRequirement() {
  try {
    const res = await fetch(`${API_BASE}/consent`);
    if (!res.ok) return;
    renderRequirement(await res.json());
  } catch {
    // The build-time fallback already rendered stays in place.
  }
}

function wireActions() {
  const status = root ? root.querySelector("[data-consent-status]") : null;
  const acceptBtn = root ? root.querySelector("[data-consent-accept]") : null;
  const declineBtn = root ? root.querySelector("[data-consent-decline]") : null;
  const buttons = [acceptBtn, declineBtn].filter(Boolean);

  const setBusy = (busy) => buttons.forEach((b) => { b.disabled = busy; });

  if (acceptBtn) {
    acceptBtn.addEventListener("click", async () => {
      setBusy(true);
      if (status) status.textContent = "Recording your consent…";
      try {
        const res = await fetch(`${API_BASE}/consent/accept`, {
          method: "POST",
          credentials: "include",
        });
        if (!res.ok) throw new Error(`accept failed: ${res.status}`);
        // The response sets the upgraded full-session cookie itself; the
        // body's token is for the CLI/MCP face, ignorable here.
        location.href = "../";
      } catch {
        if (status) status.textContent = "Couldn't record that — try again.";
        setBusy(false);
      }
    });
  }

  if (declineBtn) {
    declineBtn.addEventListener("click", async () => {
      setBusy(true);
      if (status) status.textContent = "Declining…";
      try {
        const res = await fetch(`${API_BASE}/consent/decline`, {
          method: "POST",
          credentials: "include",
        });
        if (!res.ok) throw new Error(`decline failed: ${res.status}`);
        showState("declined");
      } catch {
        if (status) status.textContent = "Couldn't decline — try again.";
        setBusy(false);
      }
    });
  }
}

async function bootstrap() {
  loadLiveRequirement(); // independent of the session check below; never blocks it.

  let me;
  try {
    const res = await fetch(`${API_BASE}/me`, { credentials: "include" });
    if (res.status === 401) {
      showState("expired");
      return;
    }
    if (!res.ok) {
      showState("error");
      return;
    }
    me = await res.json();
  } catch {
    showState("error");
    return;
  }

  if (!me.authenticated) {
    showState("expired");
    return;
  }

  if (!me.pending_consent) {
    showState("already-in");
    location.href = "../";
    return;
  }

  renderRequirement(me.consent_required);
  wireActions();
  showState("notice");
}

bootstrap();
