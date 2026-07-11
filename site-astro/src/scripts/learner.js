// learner.js — the ONE piece of client-side JS beyond org's inline
// scroll-reveal helper (Layout.astro). Loaded on every page. Progressive
// enhancement over a fully static build: every page renders complete and
// correct with this script absent — every signed-in-only element is
// hidden by the `.signedin-only` CSS default (see global.css), and the
// signed-out invitation/lock states are ordinary, always-visible markup
// with no JS dependency (Header.astro's "Sign in" link is a real anchor;
// LearnerPanel*.astro's invitation card is plain prose).
//
// Zero-API-when-signed-out invariant (spec c21, mirrored in
// workers/learn-api/README.md's own load-bearing invariant for the Worker
// side): the bootstrap below makes exactly ONE call, GET /api/me. A 401 or
// any network failure is treated as "signed out" and the function returns
// immediately — no /api/progress/*, no /api/record, nothing else fires.
// Only a 200 response (a real session) reaches the code path that issues
// any further request. This file is the audited surface for that
// guarantee: scripts/check-static-auth.mjs statically parses this exact
// source file to confirm (a) the only fetch targets anywhere in it are the
// whitelisted /api/me, /api/progress/:subject, /api/record, /api/export,
// /api/delete, /api/me/visibility, /api/admin/learners, and /api/auth/*
// paths, and (b) the progress/record/logout/account calls are lexically
// nested inside the post-200 branch, never reachable from the 401/error
// branch.
//
// Account panel (task t8): hydrateAccountPanel() below wires the visibility
// toggle (POST /api/me/visibility), the data-export/data-delete flow
// (GET /api/export, POST /api/delete — CLI-ready since t7, this is their
// first web affordance), and — admin-only, gated on the `is_admin` field
// GET /api/me now carries — the all-learners list (GET /api/admin/learners).
// All of it is called from bootstrap() only after the session check
// succeeds, same discipline as hydratePanels()/wireExerciseRecorders().
//
// Approval tier (task t9): the same account panel shows the caller's OWN
// tutoring-tier status (the additive `learner.approved` field on GET
// /api/me — display only; the Worker enforces the gate on its tutor broker
// route independently, and this site still never calls that route), and the
// admin list gains per-learner approve/revoke buttons (POST
// /api/admin/approve, POST /api/admin/revoke). As everywhere else here,
// admin-ness is a server decision; `is_admin` only decides what to RENDER.
import { API_BASE } from "../lib/api.js";

const html = document.documentElement;

function setAuthState(state) {
  html.setAttribute("data-auth", state);
}

function setText(root, selector, text) {
  const el = root.querySelector(selector);
  if (el) el.textContent = text;
}

/** "today" / "yesterday" / "5 days ago" / "" (unknown) from an ISO timestamp. */
function formatLastActive(iso) {
  if (!iso) return "No activity yet";
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return "No activity yet";
  const startOfDay = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const days = Math.round((startOfDay(new Date()) - startOfDay(then)) / 86400000);
  if (days <= 0) return "Active today";
  if (days === 1) return "Active yesterday";
  try {
    const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
    return `Last active ${rtf.format(-days, "day")}`;
  } catch {
    return `Last active ${days} days ago`;
  }
}

function masteredPct(progress) {
  const touched = progress.items_touched || 0;
  const mastered = progress.items_mastered || 0;
  return touched > 0 ? Math.round((mastered / touched) * 100) : 0;
}

// --- panel hydration --------------------------------------------------

/** A single subject's detail panel (subject pages): src/components/LearnerPanelSubject.astro. */
async function hydrateSubjectPanel(panel, subjectName) {
  const emptyEl = panel.querySelector('[data-slot="empty"]');
  const statsEl = panel.querySelector('[data-slot="stats"]');
  const showEmpty = () => {
    if (emptyEl) emptyEl.hidden = false;
    if (statsEl) statsEl.hidden = true;
  };

  let progress;
  try {
    const res = await fetch(`${API_BASE}/progress/${encodeURIComponent(subjectName)}`, {
      credentials: "include",
    });
    if (!res.ok) return showEmpty();
    progress = await res.json();
  } catch {
    return showEmpty();
  }

  if (!progress.items_touched) return showEmpty();

  if (emptyEl) emptyEl.hidden = true;
  if (statsEl) statsEl.hidden = false;
  setText(panel, '[data-slot="mastered"]', String(progress.items_mastered || 0));
  setText(panel, '[data-slot="touched"]', String(progress.items_touched || 0));
  setText(panel, '[data-slot="last-active"]', formatLastActive(progress.last_seen_at));
  const fill = panel.querySelector('[data-slot="progress-fill"]');
  if (fill) fill.style.width = `${masteredPct(progress)}%`;
  setText(panel, '[data-slot="next-text"]', (progress.next && progress.next.text) || "");
  setText(panel, '[data-slot="next-command"]', (progress.next && progress.next.command) || "");
}

/** The cross-subject overview panel (landing page): src/components/LearnerPanelOverview.astro. */
async function hydrateOverviewPanel(panel) {
  const dataEl = panel.querySelector("[data-subjects]");
  const rowsEl = panel.querySelector('[data-slot="subject-rows"]');
  const emptyEl = panel.querySelector('[data-slot="empty"]');
  // The rows list IS the "stats" region here (unlike the single-subject
  // panel, there's no separate wrapper) — showing/hiding it directly keeps
  // one fewer element to keep in sync with the markup.
  const statsEl = rowsEl;
  if (!dataEl || !rowsEl) return;

  let subjects;
  try {
    subjects = JSON.parse(dataEl.textContent || "[]");
  } catch {
    subjects = [];
  }

  const results = await Promise.all(
    subjects.map(async (s) => {
      try {
        const res = await fetch(`${API_BASE}/progress/${encodeURIComponent(s.name)}`, {
          credentials: "include",
        });
        if (!res.ok) return { ...s, progress: null };
        return { ...s, progress: await res.json() };
      } catch {
        return { ...s, progress: null };
      }
    })
  );

  const touchedRows = results.filter((r) => r.progress && r.progress.items_touched > 0);
  if (touchedRows.length === 0) {
    if (emptyEl) emptyEl.hidden = false;
    if (statsEl) statsEl.hidden = true;
    return;
  }

  if (emptyEl) emptyEl.hidden = true;
  if (statsEl) statsEl.hidden = false;
  rowsEl.textContent = "";
  for (const r of touchedRows) {
    const li = document.createElement("li");
    li.className = "subject-row";

    const link = document.createElement("a");
    link.href = r.href;
    link.textContent = r.display_name;
    li.appendChild(link);

    const stat = document.createElement("span");
    stat.className = "subject-row-stat muted";
    stat.textContent = `${r.progress.items_mastered || 0} mastered · ${
      r.progress.items_touched || 0
    } touched`;
    li.appendChild(stat);

    const bar = document.createElement("span");
    bar.className = "progress-bar";
    bar.setAttribute("aria-hidden", "true");
    const fill = document.createElement("span");
    fill.className = "progress-bar-fill";
    fill.style.width = `${masteredPct(r.progress)}%`;
    bar.appendChild(fill);
    li.appendChild(bar);

    const chip = document.createElement("span");
    chip.className = "streak-chip";
    chip.textContent = formatLastActive(r.progress.last_seen_at);
    li.appendChild(chip);

    rowsEl.appendChild(li);
  }
}

async function hydratePanels() {
  const panels = document.querySelectorAll("[data-learner-panel]");
  await Promise.all(
    Array.from(panels).map((panel) => {
      const kind = panel.getAttribute("data-learner-panel");
      return kind === "overview" ? hydrateOverviewPanel(panel) : hydrateSubjectPanel(panel, kind);
    })
  );
}

// --- story-exercise recording -------------------------------------------

/** Wire the pass/partial/fail buttons the story reader renders per exercise
 * (signed-in-only; see [subject]/stories/[id]/index.astro). Optimistic: the
 * button row disables immediately and reports a quiet inline status —
 * never a blocking dialog — on both success and failure. */
function wireExerciseRecorders() {
  document.querySelectorAll("[data-record]").forEach((group) => {
    const itemId = group.getAttribute("data-item-id");
    const exerciseId = group.getAttribute("data-exercise-id");
    const section = group.closest("[data-subject]");
    const subject = section ? section.getAttribute("data-subject") : null;
    const storyId = section ? section.getAttribute("data-story-id") : null;
    const status = group.querySelector("[data-record-status]");
    const buttons = Array.from(group.querySelectorAll("button[data-result]"));
    if (!itemId || !subject) return;

    buttons.forEach((btn) => {
      btn.addEventListener("click", async () => {
        const result = btn.getAttribute("data-result");
        buttons.forEach((b) => {
          b.disabled = true;
        });
        if (status) status.textContent = "Recording…";
        try {
          const res = await fetch(`${API_BASE}/record`, {
            method: "POST",
            credentials: "include",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              subject,
              recorded: {
                item_id: itemId,
                activity: "story",
                result,
                at: new Date().toISOString(),
                exercise_id: exerciseId || undefined,
                story_id: storyId || undefined,
              },
            }),
          });
          if (!res.ok) throw new Error(`record failed: ${res.status}`);
          if (status) status.textContent = "Recorded to your ledger.";
        } catch {
          if (status) status.textContent = "Couldn't record that — try again.";
          buttons.forEach((b) => {
            b.disabled = false;
          });
        }
      });
    });
  });
}

// --- pick-the-right-word cloze exercises (§3.6.1) -----------------------

/** Wire the pick-the-right-word cloze blanks the story reader renders inline
 * in the passage (see [subject]/stories/[id]/index.astro's `.cloze-blank`
 * markup). Purely client-side: the answer is already public in this page's
 * own exported data, so checking it makes ZERO network calls and needs no
 * sign-in — unlike wireExerciseRecorders(), this runs unconditionally,
 * before bootstrap()'s auth check, so it works on a fully signed-out page
 * too. Locks the blank to its first pick and reveals the correct option when
 * the pick was wrong. */
function wireClozeExercises() {
  document.querySelectorAll("[data-cloze-blank]").forEach((blank) => {
    const answer = blank.getAttribute("data-answer");
    const status = blank.querySelector("[data-cloze-status]");
    const buttons = Array.from(blank.querySelectorAll(".cloze-option"));
    if (!answer || buttons.length === 0) return;

    buttons.forEach((btn) => {
      btn.addEventListener("click", () => {
        if (buttons.some((b) => b.disabled)) return; // already answered
        const chosen = btn.getAttribute("data-option");
        buttons.forEach((b) => {
          b.disabled = true;
        });
        if (chosen === answer) {
          btn.classList.add("is-correct");
          if (status) status.textContent = "Correct!";
        } else {
          btn.classList.add("is-incorrect");
          const correctBtn = buttons.find((b) => b.getAttribute("data-option") === answer);
          if (correctBtn) correctBtn.classList.add("is-correct");
          if (status) status.textContent = `Not quite — "${answer}" is right.`;
        }
      });
    });
  });
}

function wireSignOut() {
  document.querySelectorAll("[data-sign-out]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      try {
        await fetch(`${API_BASE}/auth/logout`, { method: "POST", credentials: "include" });
      } catch {
        // Quiet — reload happens regardless, which re-runs the /api/me
        // check and settles on whatever the server-side session actually is.
      }
      location.reload();
    });
  });
}

// --- account panel: visibility, export, delete, admin list (task t8) ------

/** The private/public toggle (POST /api/me/visibility), seeded from the
 * `me.learner.visibility` field GET /api/me already carried this call. */
function wireVisibilityToggle(panel, me) {
  const buttons = Array.from(panel.querySelectorAll("[data-visibility-option]"));
  const status = panel.querySelector("[data-visibility-status]");
  if (buttons.length === 0) return;
  let current = (me.learner && me.learner.visibility) || "private";

  const paint = () => {
    buttons.forEach((b) => {
      b.setAttribute("aria-pressed", b.getAttribute("data-visibility-option") === current ? "true" : "false");
    });
  };
  paint();

  buttons.forEach((btn) => {
    btn.addEventListener("click", async () => {
      const value = btn.getAttribute("data-visibility-option");
      if (value === current) return;
      buttons.forEach((b) => {
        b.disabled = true;
      });
      if (status) status.textContent = "Saving…";
      try {
        const res = await fetch(`${API_BASE}/me/visibility`, {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ visibility: value }),
        });
        if (!res.ok) throw new Error(`visibility update failed: ${res.status}`);
        current = value;
        paint();
        if (status) status.textContent = "Saved.";
      } catch {
        if (status) status.textContent = "Couldn't save — try again.";
      } finally {
        buttons.forEach((b) => {
          b.disabled = false;
        });
      }
    });
  });
}

/** "Export my data" (GET /api/export, t7): downloads the JSON as a file
 * rather than linking directly — the route needs the session cookie
 * (credentials:"include"), which a plain <a href> can't send cross-context
 * as a download, so this fetches, then hands the browser a Blob URL. */
function wireExport(panel) {
  const btn = panel.querySelector("[data-export]");
  const status = panel.querySelector("[data-export-status]");
  if (!btn) return;
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    if (status) status.textContent = "Preparing your export…";
    try {
      const res = await fetch(`${API_BASE}/export`, { credentials: "include" });
      if (!res.ok) throw new Error(`export failed: ${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "learn-export.json";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      if (status) status.textContent = "Downloaded.";
    } catch {
      if (status) status.textContent = "Couldn't export — try again.";
    } finally {
      btn.disabled = false;
    }
  });
}

/** "Delete my data" (POST /api/delete, t7): the confirm-field guard mirrored
 * in the UI — the learner must TYPE their own github_user_id (from `me`,
 * already fetched) before the delete button un-disables, matching the API's
 * own one-extra-step guard against a stray click. On success the account is
 * gone; reload settles on the now-signed-out state. */
function wireDelete(panel, me) {
  const revealBtn = panel.querySelector("[data-delete-reveal]");
  const form = panel.querySelector("[data-delete-form]");
  const input = panel.querySelector("[data-delete-confirm-input]");
  const confirmBtn = panel.querySelector("[data-delete-confirm]");
  const cancelBtn = panel.querySelector("[data-delete-cancel]");
  const status = panel.querySelector("[data-delete-status]");
  if (!revealBtn || !form || !input || !confirmBtn) return;

  const uid = String((me.learner && me.learner.github_user_id) || "");
  panel.querySelectorAll("[data-auth-uid]").forEach((el) => {
    el.textContent = uid;
  });

  revealBtn.addEventListener("click", () => {
    form.hidden = false;
    revealBtn.hidden = true;
    input.focus();
  });

  if (cancelBtn) {
    cancelBtn.addEventListener("click", () => {
      form.hidden = true;
      revealBtn.hidden = false;
      input.value = "";
      confirmBtn.disabled = true;
      if (status) status.textContent = "";
    });
  }

  input.addEventListener("input", () => {
    confirmBtn.disabled = input.value.trim() !== uid;
  });

  confirmBtn.addEventListener("click", async () => {
    if (input.value.trim() !== uid) return;
    confirmBtn.disabled = true;
    if (status) status.textContent = "Deleting…";
    try {
      const res = await fetch(`${API_BASE}/delete`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirm: input.value.trim() }),
      });
      if (!res.ok) throw new Error(`delete failed: ${res.status}`);
      location.reload();
    } catch {
      if (status) status.textContent = "Couldn't delete — try again.";
      confirmBtn.disabled = false;
    }
  });
}

/** Admin-only "every learner" list (GET /api/admin/learners) — rendered
 * ONLY when `me.is_admin` is true (the additive /api/me field, t8); the
 * server enforces the allow-list independently, this is purely a UI show/
 * hide, never a source of truth. t9 adds each learner's tutoring-tier
 * `approved` state plus an approve/revoke button per learner; a successful
 * toggle re-hydrates the whole list from the server rather than patching
 * the DOM, so what's shown is always what the Worker actually stored. */
async function hydrateAdminList(section) {
  const listEl = section.querySelector("[data-admin-list]");
  const status = section.querySelector("[data-admin-status]");
  if (!listEl) return;
  try {
    const res = await fetch(`${API_BASE}/admin/learners`, { credentials: "include" });
    if (!res.ok) throw new Error(`admin list failed: ${res.status}`);
    const data = await res.json();
    listEl.textContent = "";
    (data.learners || []).forEach((l) => {
      const li = document.createElement("li");
      const label = document.createElement("span");
      label.textContent =
        `${l.display_name} (github:${l.github_user_id}) — ${l.visibility}, ` +
        `consent: ${l.consent_status}, records: ${l.records_total}, ` +
        `tutoring: ${l.approved ? "approved" : "not approved"}`;
      li.appendChild(label);

      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "admin-tutor-btn";
      btn.textContent = l.approved ? "Revoke tutoring" : "Approve tutoring";
      btn.addEventListener("click", async () => {
        btn.disabled = true;
        if (status) status.textContent = l.approved ? "Revoking…" : "Approving…";
        try {
          // Two static templates (not one with an interpolated verb) so the
          // check-static-auth whitelist can enumerate both routes exactly.
          const url = l.approved ? `${API_BASE}/admin/revoke` : `${API_BASE}/admin/approve`;
          const res2 = await fetch(url, {
            method: "POST",
            credentials: "include",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ github_user_id: l.github_user_id }),
          });
          if (!res2.ok) {
            // The one expected structured failure: approve on a learner whose
            // consent isn't current (409 consent_stale, decision c20).
            const body = await res2.json().catch(() => ({}));
            if (status) {
              status.textContent =
                body.error === "consent_stale"
                  ? "Can't approve: their consent isn't current — they must re-accept the terms first."
                  : "Couldn't update — try again.";
            }
            btn.disabled = false;
            return;
          }
          await hydrateAdminList(section); // re-render from the server's truth
        } catch {
          if (status) status.textContent = "Couldn't update — try again.";
          btn.disabled = false;
        }
      });
      li.appendChild(btn);

      listEl.appendChild(li);
    });
    if (status) status.textContent = `${data.count} learner(s).`;
  } catch {
    if (status) status.textContent = "Couldn't load the admin list.";
  }
}

async function hydrateAccountPanel(me) {
  const panel = document.querySelector("[data-account-panel]");
  if (!panel) return;

  // Tutoring tier (t9): the caller's own approved state, display only —
  // the Worker gates its tutor broker route server-side regardless.
  const tierEl = panel.querySelector("[data-tutor-tier]");
  if (tierEl) {
    tierEl.textContent =
      me.learner && me.learner.approved
        ? "Tutoring: approved — the admin has enabled the tutoring tier for your account."
        : "Tutoring: not approved — the tutoring tier is enabled per learner by the admin.";
  }

  wireVisibilityToggle(panel, me);
  wireExport(panel);
  wireDelete(panel, me);

  const adminSection = panel.querySelector("[data-admin-only]");
  if (adminSection) {
    adminSection.hidden = !me.is_admin;
    if (me.is_admin) await hydrateAdminList(adminSection);
  }
}

// --- bootstrap -----------------------------------------------------------

async function bootstrap() {
  let me;
  try {
    const res = await fetch(`${API_BASE}/me`, { credentials: "include" });
    if (!res.ok) {
      setAuthState("out");
      return;
    }
    me = await res.json();
  } catch {
    // API unreachable (offline, worker down, CORS misconfigured, ...): the
    // signed-out state is the only safe default, and it's already fully
    // rendered — nothing else to do.
    setAuthState("out");
    return;
  }

  setAuthState("in");
  // t15 hook (the ONLY tutor-related line here): publish the /api/me payload
  // for sibling scripts — src/scripts/tutor.js gates its approved-only
  // surface on this instead of fetching /api/me a second time.
  window.__learnMe = me;
  document.dispatchEvent(new CustomEvent("learn:me", { detail: me }));
  const name = (me.learner && me.learner.display_name) || "your account";
  document.querySelectorAll("[data-auth-name]").forEach((el) => {
    el.textContent = name;
  });

  wireSignOut();
  await Promise.all([
    hydratePanels(),
    Promise.resolve(wireExerciseRecorders()),
    hydrateAccountPanel(me),
  ]);
}

// Sign-in independent: wired before bootstrap() and its auth check, so cloze
// blanks are interactive even fully signed-out (see wireClozeExercises()'s
// own header comment). Makes zero fetch() calls; the whitelist check in
// scripts/check-static-auth.mjs only inspects bootstrap()'s body.
wireClozeExercises();

bootstrap();
