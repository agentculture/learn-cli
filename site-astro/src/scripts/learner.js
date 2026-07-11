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
// whitelisted /api/me, /api/progress/:subject, /api/record, and
// /api/auth/* paths, and (b) the progress/record/logout calls are lexically
// nested inside the post-200 branch, never reachable from the 401/error
// branch.
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
  const name = (me.learner && me.learner.display_name) || "your account";
  document.querySelectorAll("[data-auth-name]").forEach((el) => {
    el.textContent = name;
  });

  wireSignOut();
  await Promise.all([hydratePanels(), Promise.resolve(wireExerciseRecorders())]);
}

bootstrap();
