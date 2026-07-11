// tutor-core.js — the PURE half of the tutor surface (t15, spec c24/h11).
//
// Prompt/payload builders, Converse response parsers, the §3.6.1 cloze
// validator, and the record builder. No fetch, no DOM, no globals — this
// module is importable by plain node (scripts/check-tutor-logic.mjs unit-
// tests it, wired into `npm run check`) and by src/scripts/tutor.js alike.
// Keeping every risky transformation here (prompt text, defensive JSON
// parsing, contract validation) is what makes the DOM half thin and the
// logic actually testable without a browser or live inference.
//
// Payloads are Bedrock **Converse**-shaped — the live-verified target
// (workers/learn-api/README.md "For t15": Bedrock's OpenAI-compat surface
// does NOT serve Nova Pro; the native Converse API does):
//   request:  { system:[{text}], messages:[{role, content:[{text}]}],
//               inferenceConfig:{maxTokens, temperature} }
//   response: { output:{message:{content:[{text}]}}, stopReason, usage }
// The Worker broker forwards these verbatim (plus its `learner` stamp), so
// what this module builds is exactly what Nova Pro receives.

export const GRADE_RESULTS = ["pass", "partial", "fail"];

// Ledger mastery levels, weakest first (mirrors the worker's MASTERY_LEVELS
// minus "mastered", which never appears in progress.weak).
const WEAKNESS_ORDER = ["unknown", "introduced", "practiced"];

// --- system prompts ---------------------------------------------------------
// Each prompt pins two things Nova Pro must not improvise: the RUBRIC (what
// counts as pass — strict) and the RESPONSE FORMAT (one strict JSON object,
// no fences, no prose), because the parsers below only accept that shape.

export const GRADE_SYSTEM_PROMPT =
  "You are the learn tutor grading ONE exercise answer from a learner. " +
  "Grade STRICTLY against the exercise's expected answer or rubric: " +
  '"pass" ONLY when the answer is fully correct — every required element present, ' +
  "no meaning-changing error (a minor typo that cannot be read as a different word " +
  "is acceptable; a wrong word, wrong form, missing half, or reversed meaning is not). " +
  '"partial" when the answer shows real understanding but has at least one substantive ' +
  'error or omission. "fail" when the answer is wrong, empty, off-topic, or answers a ' +
  "different question. When in doubt between two grades, give the LOWER one. " +
  "Respond with ONE strict JSON object and NOTHING else — no markdown fences, no prose " +
  'before or after: {"result":"pass|partial|fail","explanation":"at most two short ' +
  'sentences naming what was right and what was wrong"}';

export const NEXT_STEP_SYSTEM_PROMPT =
  "You are the learn tutor recommending the single best next step for a learner, from " +
  "their real progress ledger. You are given the subject, their touched/mastered counts, " +
  "their weak items (weakest first — lowest mastery), and the subject's own generic hint. " +
  "Pick ONE concrete next action. Prefer shoring up the weakest item over new material; " +
  "name the item id you targeted and say in one sentence why, then phrase the action as " +
  "something doable right now (which story to reread, what to practice). " +
  "Respond with ONE strict JSON object and NOTHING else — no markdown fences: " +
  '{"item_id":"the weak item id you target, or null when recommending new material",' +
  '"recommendation":"one to three short sentences: what to do next and why"}';

export const CLOZE_SYSTEM_PROMPT =
  "You are the learn tutor writing ONE personalized pick-the-right-word cloze story for a " +
  "learner. You are given the subject and the learner's weak items, weakest first. Target " +
  'the FIRST weak item: the story must practice it, and your "item_id" field must be that ' +
  "item's id copied verbatim — it is a stable join key into the learner's ledger; never " +
  "invent, translate, or reword it. Requirements: " +
  '"text" is a short story (two to four sentences) practicing the weak items, with two to ' +
  "four blanks written as {{blank_id}} placeholders (each blank_id lowercase letters/" +
  'digits/hyphens, unique). "blanks" has EXACTLY one entry per placeholder, in order: ' +
  '{"id":"blank_id","options":["three plausible options"],"answer":"the correct option"} — ' +
  'every "answer" MUST be copied from its own "options", and distractors must be plausible ' +
  'but clearly wrong in context. "prompt" is one instruction line for the learner and ' +
  '"answer" is every blank answer joined with ", " (the legacy fallback fields — always ' +
  'present). "title" is a two-to-six-word title. ' +
  "Respond with ONE strict JSON object and NOTHING else — no markdown fences: " +
  '{"title":"...","item_id":"...","prompt":"...","answer":"...","text":"...",' +
  '"blanks":[{"id":"...","options":["..."],"answer":"..."}]}';

// --- Converse payload builders ----------------------------------------------

/** The one Converse request constructor every flow goes through. */
export function converseRequest(systemText, userText, { maxTokens, temperature }) {
  return {
    system: [{ text: systemText }],
    messages: [{ role: "user", content: [{ text: userText }] }],
    inferenceConfig: { maxTokens, temperature },
  };
}

/** GRADE: the learner answered `exercise` free-form with `answer`. */
export function buildGradePayload({ subject, exercise, answer }) {
  const lines = [
    `Subject: ${subject}`,
    `Exercise type: ${exercise.type || "open"}`,
    exercise.story ? `From the story: ${exercise.story}` : null,
    `Exercise prompt: ${exercise.prompt}`,
    exercise.choices && exercise.choices.length > 0
      ? `Choices offered: ${exercise.choices.join(" | ")}`
      : null,
    exercise.answer ? `Expected answer: ${exercise.answer}` : null,
    exercise.rubric ? `Rubric: ${exercise.rubric}` : null,
    `Learner's answer: ${answer}`,
  ].filter(Boolean);
  // temperature 0: grading must be reproducible, never creative.
  return converseRequest(GRADE_SYSTEM_PROMPT, lines.join("\n"), {
    maxTokens: 300,
    temperature: 0,
  });
}

/** Weak items from a progress payload, weakest mastery first, capped. */
export function weakestItems(progress, limit = 4) {
  const weak = Array.isArray(progress && progress.weak) ? progress.weak : [];
  return weak
    .slice()
    .sort(
      (a, b) => WEAKNESS_ORDER.indexOf(String(a.mastery)) - WEAKNESS_ORDER.indexOf(String(b.mastery)),
    )
    .slice(0, limit);
}

function weakLines(weakItems) {
  return weakItems.map((w) => `- ${w.item_id} (mastery: ${w.mastery})`).join("\n");
}

/** NEXT-STEP: adaptive recommendation from the learner's own progress. */
export function buildNextStepPayload({ subject, progress }) {
  const weak = weakestItems(progress);
  const lines = [
    `Subject: ${subject}`,
    `Items touched: ${progress.items_touched || 0}`,
    `Items mastered: ${progress.items_mastered || 0}`,
    weak.length > 0 ? `Weak items, weakest first:\n${weakLines(weak)}` : "Weak items: none",
    progress.next && progress.next.text ? `Subject's generic hint: ${progress.next.text}` : null,
  ].filter(Boolean);
  return converseRequest(NEXT_STEP_SYSTEM_PROMPT, lines.join("\n"), {
    maxTokens: 300,
    temperature: 0.2,
  });
}

/** CLOZE-GEN: a new story personalized to the learner's weak items. */
export function buildClozePayload({ subject, weakItems }) {
  const lines = [
    `Subject: ${subject}`,
    `Weak items, weakest first (use the FIRST as item_id, verbatim):\n${weakLines(weakItems)}`,
  ];
  // Higher temperature: story writing should vary run to run; the validator
  // below (not the prompt alone) is what enforces the contract shape.
  return converseRequest(CLOZE_SYSTEM_PROMPT, lines.join("\n"), {
    maxTokens: 900,
    temperature: 0.7,
  });
}

// --- Converse response parsers (defensive, never throwing) -------------------

/** Concatenated text blocks from a Converse response; "" when malformed. */
export function converseText(data) {
  const content =
    data && data.output && data.output.message && Array.isArray(data.output.message.content)
      ? data.output.message.content
      : [];
  return content.map((c) => (c && typeof c.text === "string" ? c.text : "")).join("");
}

/** First JSON object embedded in `text` (fences/prose tolerated); null when none parses. */
export function extractJson(text) {
  if (typeof text !== "string") return null;
  const unfenced = text.replace(/```(?:json)?/gi, "");
  const start = unfenced.indexOf("{");
  const end = unfenced.lastIndexOf("}");
  if (start < 0 || end <= start) return null;
  try {
    const parsed = JSON.parse(unfenced.slice(start, end + 1));
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

/** {result, explanation} or null — result must be a real grade. */
export function parseGradeResponse(data) {
  const obj = extractJson(converseText(data));
  if (!obj) return null;
  const result = typeof obj.result === "string" ? obj.result.trim().toLowerCase() : "";
  if (!GRADE_RESULTS.includes(result)) return null;
  return {
    result,
    explanation: typeof obj.explanation === "string" ? obj.explanation.trim() : "",
  };
}

/** {item_id, recommendation} or null — recommendation is required prose. */
export function parseNextStepResponse(data) {
  const obj = extractJson(converseText(data));
  if (!obj || typeof obj.recommendation !== "string" || !obj.recommendation.trim()) return null;
  const itemId = typeof obj.item_id === "string" && obj.item_id.trim() ? obj.item_id.trim() : null;
  return { item_id: itemId, recommendation: obj.recommendation.trim() };
}

/** The raw generated story object (unvalidated) or null. */
export function parseClozeResponse(data) {
  return extractJson(converseText(data));
}

// --- §3.6.1 cloze validation (client-side, BEFORE showing or recording) ------

const BLANK_ID_RE = /^[a-z0-9][a-z0-9._-]*$/;
const PLACEHOLDER_RE = /\{\{([^{}]+)\}\}/g;

/** Ordered placeholder ids found in a cloze `text`. */
export function placeholderIds(text) {
  return [...String(text).matchAll(PLACEHOLDER_RE)].map((m) => m[1]);
}

/**
 * Validate a GENERATED cloze story against the pick-the-right-word contract
 * (docs/specs/subject-plugin-contract.md §3.6.1) plus t15's join-key rule.
 * Returns a list of human-readable errors; empty means valid. Deliberately a
 * superset of the schema-checkable rules AND the `learn subject doctor`
 * semantic rules, because generated content gets no doctor pass:
 *   - "text" non-empty, "blanks" non-empty; each blank {id, options, answer};
 *   - blank ids match the pattern, are unique, and pair 1:1 with {{id}}
 *     placeholders (no orphan placeholder, no blank without one);
 *   - >= 2 non-empty options per blank, and answer is one of its own options;
 *   - the legacy "prompt"/"answer" fallback fields are present (the
 *     driver-facing instruction §3.6.1 keeps on well-authored items);
 *   - item_id is copied verbatim from an EXISTING weak item (`weakItemIds`) —
 *     the stable ledger join key; a Nova-invented id would corrupt mastery.
 */
export function validateClozeStory(story, weakItemIds) {
  const errors = [];
  if (!story || typeof story !== "object" || Array.isArray(story)) {
    return ["story is not an object"];
  }
  if (typeof story.prompt !== "string" || !story.prompt.trim()) {
    errors.push("missing prompt (the legacy fallback instruction)");
  }
  if (typeof story.answer !== "string" || !story.answer.trim()) {
    errors.push("missing answer (the legacy fallback field)");
  }
  if (typeof story.item_id !== "string" || !story.item_id.trim()) {
    errors.push("missing item_id");
  } else if (!Array.isArray(weakItemIds) || !weakItemIds.includes(story.item_id)) {
    errors.push(`item_id "${story.item_id}" is not one of the learner's weak items`);
  }
  if (typeof story.text !== "string" || !story.text.trim()) {
    errors.push("missing text");
  }
  if (!Array.isArray(story.blanks) || story.blanks.length === 0) {
    errors.push("missing blanks");
  }
  if (errors.length > 0) return errors;

  const seen = new Set();
  for (const blank of story.blanks) {
    if (!blank || typeof blank !== "object") {
      errors.push("blank is not an object");
      continue;
    }
    const id = String(blank.id || "");
    if (!BLANK_ID_RE.test(id)) errors.push(`blank id "${id}" is malformed`);
    if (seen.has(id)) errors.push(`duplicate blank id "${id}"`);
    seen.add(id);
    const options = Array.isArray(blank.options) ? blank.options : [];
    const clean = options.filter((o) => typeof o === "string" && o.trim());
    if (clean.length !== options.length || options.length < 2) {
      errors.push(`blank "${id}" needs >= 2 non-empty options`);
    }
    if (typeof blank.answer !== "string" || !blank.answer.trim()) {
      errors.push(`blank "${id}" has no answer`);
    } else if (!options.includes(blank.answer)) {
      errors.push(`blank "${id}" answer is not one of its options`);
    }
  }

  const inText = placeholderIds(story.text);
  const inTextSet = new Set(inText);
  if (inText.length !== inTextSet.size) errors.push("duplicate {{placeholder}} in text");
  for (const id of inTextSet) {
    if (!seen.has(id)) errors.push(`orphan placeholder {{${id}}} has no blanks entry`);
  }
  for (const id of seen) {
    if (!inTextSet.has(id)) errors.push(`blank "${id}" has no {{${id}}} placeholder in text`);
  }
  return errors;
}

// --- playing + recording ------------------------------------------------------

/** Split a cloze `text` into ordered text/blank segments for rendering —
 * the same split the story reader does at build time, here at runtime. */
export function splitClozeText(text, blanks) {
  const byId = new Map(blanks.map((b) => [b.id, b]));
  const segments = [];
  let lastIndex = 0;
  for (const match of String(text).matchAll(PLACEHOLDER_RE)) {
    if (match.index > lastIndex) {
      segments.push({ kind: "text", value: text.slice(lastIndex, match.index) });
    }
    const blank = byId.get(match[1]);
    if (blank) segments.push({ kind: "blank", blank });
    else segments.push({ kind: "text", value: match[0] });
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < String(text).length) {
    segments.push({ kind: "text", value: text.slice(lastIndex) });
  }
  return segments;
}

/** pass/partial/fail from a blanks tally (all right / some / none). */
export function clozeResult(correct, total) {
  if (!Number.isInteger(correct) || !Number.isInteger(total) || total < 1) return "fail";
  if (correct >= total) return "pass";
  return correct > 0 ? "partial" : "fail";
}

/**
 * The POST /api/record body for a played generated story — contract-valid
 * with EXISTING fields only (item_id/activity/result/at + the pre-existing
 * correct/total tallies §3.6.1 points at; never the derived score/grade/
 * points the worker rejects, and no new field inventions).
 */
export function buildClozeRecord({ subject, story, correct, total, at }) {
  return {
    subject,
    recorded: {
      item_id: story.item_id,
      activity: "practice",
      result: clozeResult(correct, total),
      at: at || new Date().toISOString(),
      correct,
      total,
    },
  };
}
