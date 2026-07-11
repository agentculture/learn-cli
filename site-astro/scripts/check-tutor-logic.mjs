#!/usr/bin/env node
// Unit suite for src/scripts/tutor-core.js — the PURE half of the t15 tutor
// surface (prompt/payload builders, Converse parsers, the §3.6.1 cloze
// validator, the record builder).
//
// site-astro has no test-runner dependency by design (same zero-dependency
// ethos as check-static-auth.mjs / check-export-pages.mjs: node:assert
// only), so this IS the JS test rig: it imports the module and executes it,
// which the Python source-shape tests (tests/test_tutor_page.py) cannot do.
// Wired into `npm run check` (after `npm run build`, though this particular
// script needs no build — tutor-core.js is plain ESM).
//
// What this deliberately does NOT cover (t17's live gate drives it): real
// Nova Pro output quality — whether the model actually honors the strict-
// JSON instruction and the rubric. Everything around that live call —
// building the exact Converse payload, surviving malformed/fenced/prose-
// wrapped replies, refusing contract-invalid cloze stories, tallying and
// shaping the ledger record — is executed here.

import assert from "node:assert/strict";

import {
  CLOZE_SYSTEM_PROMPT,
  GRADE_SYSTEM_PROMPT,
  NEXT_STEP_SYSTEM_PROMPT,
  buildClozePayload,
  buildClozeRecord,
  buildGradePayload,
  buildNextStepPayload,
  clozeResult,
  converseText,
  extractJson,
  parseClozeResponse,
  parseGradeResponse,
  parseNextStepResponse,
  placeholderIds,
  splitClozeText,
  validateClozeStory,
  weakestItems,
} from "../src/scripts/tutor-core.js";

const problems = [];
let checks = 0;
function check(label, fn) {
  checks += 1;
  try {
    fn();
  } catch (err) {
    problems.push(`${label}: ${err.message}`);
  }
}

/** A Converse response whose one text block is `text`. */
function converse(text) {
  return {
    output: { message: { content: [{ text }], role: "assistant" } },
    stopReason: "end_turn",
    usage: { inputTokens: 1, outputTokens: 1 },
  };
}

// --- payload builders: Converse-shaped, rubric pinned -----------------------

check("buildGradePayload is Converse-shaped with the rubric pinned at temperature 0", () => {
  const payload = buildGradePayload({
    subject: "french",
    exercise: {
      type: "translation",
      prompt: "Translate: I would like three apples.",
      answer: "Je voudrais trois pommes.",
      story: "Au marché",
    },
    answer: "Je veux trois pommes",
  });
  assert.deepEqual(Object.keys(payload).sort(), ["inferenceConfig", "messages", "system"]);
  assert.equal(payload.system.length, 1);
  assert.equal(payload.system[0].text, GRADE_SYSTEM_PROMPT);
  assert.match(GRADE_SYSTEM_PROMPT, /"pass" ONLY when/);
  assert.match(GRADE_SYSTEM_PROMPT, /strict JSON/i);
  assert.equal(payload.messages.length, 1);
  assert.equal(payload.messages[0].role, "user");
  const user = payload.messages[0].content[0].text;
  for (const fragment of [
    "Subject: french",
    "Translate: I would like three apples.",
    "Expected answer: Je voudrais trois pommes.",
    "Learner's answer: Je veux trois pommes",
  ]) {
    assert.ok(user.includes(fragment), `grade user text must include: ${fragment}`);
  }
  assert.equal(payload.inferenceConfig.temperature, 0, "grading must be deterministic");
  assert.ok(Number.isInteger(payload.inferenceConfig.maxTokens));
});

check("buildGradePayload omits absent fields (no 'undefined' leaking into the prompt)", () => {
  const payload = buildGradePayload({
    subject: "culture-guide",
    exercise: { type: "open", prompt: "Why lead with consent?" },
    answer: "Because trust.",
  });
  const user = payload.messages[0].content[0].text;
  assert.ok(!user.includes("undefined"));
  assert.ok(!user.includes("Expected answer:"));
  assert.ok(!user.includes("Rubric:"));
});

check("buildNextStepPayload feeds the weak items weakest-first", () => {
  const progress = {
    items_touched: 5,
    items_mastered: 2,
    weak: [
      { item_id: "greetings", mastery: "practiced" },
      { item_id: "numbers-money", mastery: "unknown" },
      { item_id: "directions", mastery: "introduced" },
    ],
    next: { text: "Continue this subject." },
  };
  const payload = buildNextStepPayload({ subject: "french", progress });
  assert.equal(payload.system[0].text, NEXT_STEP_SYSTEM_PROMPT);
  const user = payload.messages[0].content[0].text;
  const order = ["numbers-money", "directions", "greetings"].map((id) => user.indexOf(id));
  assert.ok(order[0] < order[1] && order[1] < order[2], "weakest item must come first");
  assert.ok(user.includes("Items touched: 5"));
  assert.ok(user.includes("Subject's generic hint: Continue this subject."));
});

check("weakestItems sorts by mastery rank and caps the list", () => {
  const progress = {
    weak: [
      { item_id: "a", mastery: "practiced" },
      { item_id: "b", mastery: "unknown" },
      { item_id: "c", mastery: "introduced" },
      { item_id: "d", mastery: "unknown" },
      { item_id: "e", mastery: "practiced" },
    ],
  };
  const top = weakestItems(progress, 3);
  assert.equal(top.length, 3);
  assert.deepEqual(
    top.map((w) => w.mastery),
    ["unknown", "unknown", "introduced"],
  );
  assert.deepEqual(weakestItems({}, 3), [], "missing weak list means no items, not a throw");
});

check("buildClozePayload pins the verbatim join key and creative temperature", () => {
  const payload = buildClozePayload({
    subject: "spanish",
    weakItems: [{ item_id: "ordering-food", mastery: "introduced" }],
  });
  assert.equal(payload.system[0].text, CLOZE_SYSTEM_PROMPT);
  assert.match(CLOZE_SYSTEM_PROMPT, /verbatim/);
  assert.match(CLOZE_SYSTEM_PROMPT, /\{\{blank_id\}\}/);
  assert.ok(payload.messages[0].content[0].text.includes("ordering-food"));
  assert.ok(payload.inferenceConfig.temperature > 0, "story generation should vary");
});

// --- Converse parsers: defensive against real-world model output ------------

check("converseText concatenates text blocks and tolerates malformed responses", () => {
  assert.equal(converseText(converse("OK")), "OK");
  assert.equal(
    converseText({ output: { message: { content: [{ text: "a" }, { text: "b" }] } } }),
    "ab",
  );
  assert.equal(converseText({}), "");
  assert.equal(converseText(null), "");
  assert.equal(converseText({ output: { message: { content: "nope" } } }), "");
});

check("extractJson survives fences, prose, and rejects junk", () => {
  assert.deepEqual(extractJson('{"a":1}'), { a: 1 });
  assert.deepEqual(extractJson('```json\n{"a":1}\n```'), { a: 1 });
  assert.deepEqual(extractJson('Here you go:\n{"a":1}\nHope that helps!'), { a: 1 });
  assert.equal(extractJson("no json here"), null);
  assert.equal(extractJson('{"broken":'), null);
  assert.equal(extractJson("[1,2,3]"), null, "an array is not the object shape we asked for");
  assert.equal(extractJson(undefined), null);
});

check("parseGradeResponse accepts only real grades", () => {
  const good = parseGradeResponse(
    converse('{"result":"PARTIAL","explanation":"Right verb, wrong tense."}'),
  );
  assert.deepEqual(good, { result: "partial", explanation: "Right verb, wrong tense." });
  assert.equal(parseGradeResponse(converse('{"result":"excellent","explanation":"x"}')), null);
  assert.equal(parseGradeResponse(converse("I would grade this a pass!")), null);
  assert.equal(parseGradeResponse({}), null);
});

check("parseNextStepResponse requires prose and normalizes item_id", () => {
  const step = parseNextStepResponse(
    converse('{"item_id":"numbers-money","recommendation":"Reread the market story."}'),
  );
  assert.deepEqual(step, { item_id: "numbers-money", recommendation: "Reread the market story." });
  const noItem = parseNextStepResponse(converse('{"item_id":null,"recommendation":"New story."}'));
  assert.equal(noItem.item_id, null);
  assert.equal(parseNextStepResponse(converse('{"item_id":"x","recommendation":"  "}')), null);
});

// --- the §3.6.1 validator: every gate the contract + t15 demand -------------

const VALID_STORY = {
  title: "Au marché",
  item_id: "numbers-money",
  prompt: "Pick the right word for each blank.",
  answer: "trois, marché",
  text: "Je vais au {{place}} pour acheter {{qty}} pommes.",
  blanks: [
    { id: "place", options: ["marché", "musée", "manteau"], answer: "marché" },
    { id: "qty", options: ["trois", "gris"], answer: "trois" },
  ],
};
const WEAK_IDS = ["numbers-money", "greetings"];

check("a conformant generated story validates clean", () => {
  assert.deepEqual(validateClozeStory(VALID_STORY, WEAK_IDS), []);
});

check("parseClozeResponse -> validate round-trip on a fenced reply", () => {
  const story = parseCloze(`\`\`\`json\n${JSON.stringify(VALID_STORY)}\n\`\`\``);
  assert.deepEqual(validateClozeStory(story, WEAK_IDS), []);
  function parseCloze(text) {
    return parseClozeResponse(converse(text));
  }
});

check("every §3.6.1 violation is caught", () => {
  const cases = [
    [null, /not an object/],
    [{ ...VALID_STORY, prompt: " " }, /prompt/],
    [{ ...VALID_STORY, answer: "" }, /answer/],
    [{ ...VALID_STORY, text: "" }, /text/],
    [{ ...VALID_STORY, blanks: [] }, /blanks/],
    // < 2 options
    [
      { ...VALID_STORY, blanks: [VALID_STORY.blanks[0], { id: "qty", options: ["trois"], answer: "trois" }] },
      /qty.*options/,
    ],
    // answer not among options
    [
      { ...VALID_STORY, blanks: [VALID_STORY.blanks[0], { id: "qty", options: ["gris", "trop"], answer: "trois" }] },
      /not one of its options/,
    ],
    // malformed blank id
    [
      { ...VALID_STORY, blanks: [VALID_STORY.blanks[0], { id: "Qty!", options: ["trois", "gris"], answer: "trois" }] },
      /malformed/,
    ],
    // duplicate blank ids
    [
      {
        ...VALID_STORY,
        text: "Je vais au {{place}} pour acheter {{place}} pommes.",
        blanks: [VALID_STORY.blanks[0], { id: "place", options: ["trois", "gris"], answer: "trois" }],
      },
      /duplicate/,
    ],
    // orphan placeholder in text
    [{ ...VALID_STORY, text: "Je vais au {{place}} avec {{who}} pour {{qty}}." }, /orphan/],
    // blank without a placeholder
    [{ ...VALID_STORY, text: "Je vais au {{place}} sans blancs." }, /has no \{\{qty\}\}/],
  ];
  for (const [story, expected] of cases) {
    const errors = validateClozeStory(story, WEAK_IDS);
    assert.ok(errors.length > 0, `expected errors for: ${JSON.stringify(story)}`);
    assert.ok(
      errors.some((e) => expected.test(e)),
      `expected an error matching ${expected} in: ${errors.join(" | ")}`,
    );
  }
});

check("the t15 join-key rule: item_id must reuse an EXISTING weak item id", () => {
  const invented = { ...VALID_STORY, item_id: "totally-new-item" };
  const errors = validateClozeStory(invented, WEAK_IDS);
  assert.ok(errors.some((e) => e.includes("not one of the learner's weak items")));
  assert.deepEqual(validateClozeStory(VALID_STORY, []), [
    'item_id "numbers-money" is not one of the learner\'s weak items',
  ]);
});

// --- playing + recording -----------------------------------------------------

check("placeholderIds and splitClozeText agree with the story reader's split", () => {
  assert.deepEqual(placeholderIds(VALID_STORY.text), ["place", "qty"]);
  const segments = splitClozeText(VALID_STORY.text, VALID_STORY.blanks);
  assert.deepEqual(
    segments.map((s) => s.kind),
    ["text", "blank", "text", "blank", "text"],
  );
  assert.equal(segments[1].blank.id, "place");
  assert.equal(segments[4].value, " pommes.");
  // Unmatched placeholders render as literal text, never a crash.
  const loose = splitClozeText("a {{ghost}} b", VALID_STORY.blanks);
  assert.deepEqual(loose.map((s) => s.kind), ["text", "text", "text"]);
});

check("clozeResult maps tallies to the contract's result values", () => {
  assert.equal(clozeResult(2, 2), "pass");
  assert.equal(clozeResult(1, 2), "partial");
  assert.equal(clozeResult(0, 2), "fail");
  assert.equal(clozeResult(0, 0), "fail");
  assert.equal(clozeResult("2", 2), "fail", "non-integers never sneak a pass");
});

check("buildClozeRecord is contract-valid with existing fields only", () => {
  const body = buildClozeRecord({
    subject: "french",
    story: VALID_STORY,
    correct: 1,
    total: 2,
    at: "2026-07-11T12:00:00Z",
  });
  assert.deepEqual(body, {
    subject: "french",
    recorded: {
      item_id: "numbers-money",
      activity: "practice",
      result: "partial",
      at: "2026-07-11T12:00:00Z",
      correct: 1,
      total: 2,
    },
  });
  // The worker rejects derived numbers — they must never appear.
  for (const forbidden of ["score", "grade", "points"]) {
    assert.ok(!(forbidden in body.recorded));
  }
  assert.match(buildClozeRecord({ subject: "s", story: VALID_STORY, correct: 2, total: 2 }).recorded.at, /^\d{4}-\d{2}-\d{2}T/);
});

// --- verdict -----------------------------------------------------------------

if (problems.length > 0) {
  console.error(`check-tutor-logic: ${problems.length} problem(s) found\n`);
  for (const p of problems) console.error(`  - ${p}`);
  process.exit(1);
}

console.log(`check-tutor-logic: OK — ${checks} check(s) over tutor-core.js's pure logic.`);
