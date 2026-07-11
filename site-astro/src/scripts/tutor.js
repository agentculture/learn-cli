// tutor.js — the tutor surface for APPROVED learners (t15, spec c24/h11).
//
// A dedicated script, loaded ONLY by TutorPanel.astro's own import (never by
// Layout.astro — learner.js stays the one global script and gains exactly a
// two-line hook: it publishes the /api/me payload it already fetched as
// `window.__learnMe` + a "learn:me" event, so this file needs no /api/me
// call of its own). All prompt construction, response parsing, and contract
// validation live in the PURE sibling module ./tutor-core.js, unit-tested by
// scripts/check-tutor-logic.mjs; this file is only DOM wiring.
//
// THE GATE, honored end-to-end: hydrateTutorPanel() checks
// `me.learner.approved` FIRST and returns before wiring anything when the
// learner is not approved — the "tutoring is admin-approved" note (visible
// by default in the signed-in markup) stays, the controls stay hidden, and
// this script makes ZERO fetch() calls. The Worker enforces the same gate
// server-side regardless (403 approval_required, zero inference) — this is
// UI honesty, not the security boundary.
//
// Fetch surface (audited by scripts/check-static-auth.mjs against an exact,
// anchored whitelist): POST /api/tutor (the broker — the only route that
// spends inference), GET /api/progress/:subject (weak items for next-step +
// cloze-gen), POST /api/record (the played story's tally, contract-valid,
// existing fields only). Nothing else, ever.
import { API_BASE } from "../lib/api.js";
import {
  buildClozePayload,
  buildClozeRecord,
  buildGradePayload,
  buildNextStepPayload,
  parseClozeResponse,
  parseGradeResponse,
  parseNextStepResponse,
  splitClozeText,
  validateClozeStory,
  weakestItems,
} from "./tutor-core.js";

const PARSE_FAILED = "The tutor's reply didn't parse — try again.";
const CALL_FAILED = "Couldn't reach the tutor — try again.";

async function callTutor(payload) {
  const res = await fetch(`${API_BASE}/tutor`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(`tutor call failed: ${res.status}`);
  return res.json();
}

async function fetchProgress(subject) {
  const res = await fetch(`${API_BASE}/progress/${encodeURIComponent(subject)}`, {
    credentials: "include",
  });
  if (!res.ok) throw new Error(`progress fetch failed: ${res.status}`);
  return res.json();
}

function setStatus(el, text) {
  if (el) el.textContent = text;
}

// --- GRADE: free-form answer -> pass/partial/fail + explanation -------------

function wireGrade(panel, subject) {
  const block = panel.querySelector("[data-tutor-grade]");
  if (!block) return;
  const dataEl = panel.querySelector("[data-tutor-exercises]");
  let exercises;
  try {
    exercises = JSON.parse(dataEl ? dataEl.textContent || "[]" : "[]");
  } catch {
    exercises = [];
  }
  const select = block.querySelector("[data-grade-exercise]");
  const promptEl = block.querySelector("[data-grade-prompt]");
  const answerEl = block.querySelector("[data-grade-answer]");
  const submit = block.querySelector("[data-grade-submit]");
  const result = block.querySelector("[data-grade-result]");
  if (!select || !answerEl || !submit || exercises.length === 0) {
    block.hidden = true;
    return;
  }

  exercises.forEach((ex, i) => {
    const opt = document.createElement("option");
    opt.value = String(i);
    opt.textContent = ex.story ? `${ex.story} — ${ex.prompt}` : ex.prompt;
    select.appendChild(opt);
  });
  const paintPrompt = () => {
    const ex = exercises[Number(select.value)] || exercises[0];
    if (promptEl) promptEl.textContent = ex.prompt;
  };
  paintPrompt();
  select.addEventListener("change", paintPrompt);

  submit.addEventListener("click", async () => {
    const exercise = exercises[Number(select.value)] || exercises[0];
    const answer = answerEl.value.trim();
    if (!answer) {
      setStatus(result, "Write an answer first.");
      return;
    }
    submit.disabled = true;
    setStatus(result, "Grading…");
    try {
      const data = await callTutor(buildGradePayload({ subject, exercise, answer }));
      const grade = parseGradeResponse(data);
      setStatus(result, grade ? `${grade.result.toUpperCase()} — ${grade.explanation}` : PARSE_FAILED);
    } catch {
      setStatus(result, CALL_FAILED);
    } finally {
      submit.disabled = false;
    }
  });
}

// --- NEXT-STEP: adaptive recommendation from the learner's progress ---------

function wireNextStep(panel, subject) {
  const block = panel.querySelector("[data-tutor-next]");
  if (!block) return;
  const submit = block.querySelector("[data-next-submit]");
  const result = block.querySelector("[data-next-result]");
  if (!submit) return;

  submit.addEventListener("click", async () => {
    submit.disabled = true;
    setStatus(result, "Asking the tutor…");
    try {
      const progress = await fetchProgress(subject);
      if (!progress.items_touched) {
        setStatus(result, "Nothing recorded yet — read a story and record a result first.");
        return;
      }
      const data = await callTutor(buildNextStepPayload({ subject, progress }));
      const step = parseNextStepResponse(data);
      if (!step) {
        setStatus(result, PARSE_FAILED);
        return;
      }
      setStatus(
        result,
        step.item_id ? `${step.recommendation} (targets: ${step.item_id})` : step.recommendation,
      );
    } catch {
      setStatus(result, CALL_FAILED);
    } finally {
      submit.disabled = false;
    }
  });
}

// --- CLOZE-GEN: a personalized story, played inline, recorded to the ledger --

/** Render a validated story with the same pick-the-right-word interaction the
 * story reader uses (.cloze-blank / .cloze-option / lock-on-first-pick), and
 * record the tally through the existing POST /api/record once every blank is
 * answered — correct/total, existing contract fields only. */
function renderClozeStory(container, status, subject, story) {
  container.textContent = "";
  container.hidden = false;

  if (story.title) {
    const title = document.createElement("h4");
    title.className = "tutor-story-title";
    title.textContent = story.title;
    container.appendChild(title);
  }
  const prompt = document.createElement("p");
  prompt.className = "muted tutor-story-prompt";
  prompt.textContent = story.prompt;
  container.appendChild(prompt);

  const passage = document.createElement("p");
  passage.className = "cloze-passage";
  const total = story.blanks.length;
  let answered = 0;
  let correct = 0;

  const finish = async () => {
    const body = buildClozeRecord({ subject, story, correct, total });
    setStatus(status, "Recording…");
    try {
      const res = await fetch(`${API_BASE}/record`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error(`record failed: ${res.status}`);
      setStatus(status, `${correct}/${total} right — recorded to your ledger.`);
    } catch {
      setStatus(status, `${correct}/${total} right — couldn't record it, though.`);
    }
  };

  for (const segment of splitClozeText(story.text, story.blanks)) {
    if (segment.kind === "text") {
      passage.appendChild(document.createTextNode(segment.value));
      continue;
    }
    const blank = segment.blank;
    const wrap = document.createElement("span");
    wrap.className = "cloze-blank";
    const group = document.createElement("span");
    group.className = "cloze-options";
    group.setAttribute("role", "group");
    group.setAttribute("aria-label", "Pick the right word");
    const buttons = blank.options.map((option) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "cloze-option";
      btn.textContent = option;
      btn.addEventListener("click", () => {
        if (buttons.some((b) => b.disabled)) return; // locked to the first pick
        buttons.forEach((b) => {
          b.disabled = true;
        });
        answered += 1;
        if (option === blank.answer) {
          correct += 1;
          btn.classList.add("is-correct");
        } else {
          btn.classList.add("is-incorrect");
          const right = buttons.find((b) => b.textContent === blank.answer);
          if (right) right.classList.add("is-correct");
        }
        if (answered === total) finish();
      });
      group.appendChild(btn);
      return btn;
    });
    wrap.appendChild(group);
    passage.appendChild(wrap);
  }
  container.appendChild(passage);
}

function wireClozeGen(panel, subject) {
  const block = panel.querySelector("[data-tutor-cloze]");
  if (!block) return;
  const submit = block.querySelector("[data-cloze-submit]");
  const status = block.querySelector("[data-cloze-status]");
  const container = block.querySelector("[data-cloze-story]");
  if (!submit || !container) return;

  submit.addEventListener("click", async () => {
    submit.disabled = true;
    setStatus(status, "Writing your story…");
    try {
      const progress = await fetchProgress(subject);
      const weak = weakestItems(progress);
      if (weak.length === 0) {
        setStatus(
          status,
          progress.items_touched
            ? "Every touched item is mastered — nothing weak to practice. Impressive."
            : "Nothing recorded yet — read a story and record a result first.",
        );
        return;
      }
      const data = await callTutor(buildClozePayload({ subject, weakItems: weak }));
      const story = parseClozeResponse(data);
      const errors = validateClozeStory(
        story,
        weak.map((w) => w.item_id),
      );
      if (errors.length > 0) {
        // Invalid generations are DROPPED, never shown or recorded — the
        // §3.6.1 validator is the gate, not the prompt's good intentions.
        setStatus(status, "The generated story didn't validate — try again.");
        return;
      }
      setStatus(status, "Pick the right word for each blank.");
      renderClozeStory(container, status, subject, story);
    } catch {
      setStatus(status, CALL_FAILED);
    } finally {
      submit.disabled = false;
    }
  });
}

// --- the gate + bootstrap -----------------------------------------------------

function hydrateTutorPanel(me) {
  const panel = document.querySelector("[data-tutor-panel]");
  if (!panel) return;
  const approved = !!(me && me.learner && me.learner.approved);
  if (!approved) {
    // Not approved: the admin-approved note (visible by default) stands,
    // the controls stay hidden, and NOTHING below runs — zero fetches.
    return;
  }
  const note = panel.querySelector("[data-tutor-gate-note]");
  const surface = panel.querySelector("[data-tutor-surface]");
  if (note) note.hidden = true;
  if (surface) surface.hidden = false;
  const subject = panel.getAttribute("data-tutor-subject");
  if (!subject) return;
  wireGrade(panel, subject);
  wireNextStep(panel, subject);
  wireClozeGen(panel, subject);
}

// learner.js publishes the /api/me payload after its own auth check; take it
// from wherever we are in that race (already published, or still pending).
if (window.__learnMe) {
  hydrateTutorPanel(window.__learnMe);
} else {
  document.addEventListener("learn:me", (event) => hydrateTutorPanel(event.detail), {
    once: true,
  });
}
