# The subject-plugin contract (v1.0)

**Status:** authoritative for contract version `1.0` · **Owner:** learn-cli ·
**Machine-readable half:** `learn/contract/schemas/*.json` (package data, importable as `learn.contract`)

This is the central design of the learn uplift: the interface a subject CLI must satisfy to be
hosted by learn-cli. It descends from the converged spec
([`docs/specs/2026-07-10-agentculture-org-learn-is-live-one-learning-hub-in.md`](2026-07-10-agentculture-org-learn-is-live-one-learning-hub-in.md),
claims c9, c15/c17, c18, c27/c28, c29) and generalizes culture-guide's proven `teach` engine.
Everything downstream composes on it: the registry + conformance gate (t3), the french/spanish
implementations (t4/t5), the culture-guide adapter (t6), story content (t7/t8), and the
motivation layer (t9).

## 1. The model: portal, subject, driver

Three roles, three kinds of intelligence:

- **The subject CLI** (french, spanish, culture-guide, …) is an **LLM-free engine**. It owns
  committed content (stories, lessons, exercises) and per-learner mastery state, resolves *what*
  to teach next within itself, and emits **structured teaching directives**. It never converses,
  never grades free text, never calls a model, and **never computes scores**.
- **The driver** (an agent or human harness — Claude Code, a colleague backend, the learn API's
  tutoring broker) does the conversational tutoring the directive describes: presents, explains,
  quizzes, grades `pass|partial|fail` against the answer or rubric, and **writes raw results
  back** via the subject's `record` verb.
- **learn-cli** (the portal) drives subjects **as external runtimes over subprocess `--json`** —
  it never imports subject code — and owns the uniform **motivation layer**: numeric scores per
  exercise, per-subject and cross-subject streaks, time-decayed review queues, and adaptive
  what-next, all computed **deterministically** from the recorded-result history. No LLM in the
  scoring path; the same history yields the same numbers on web, CLI, and MCP.

This is the **directive pattern** (culture-guide's `teach` shape, generalized): the subject emits
a directive; the driver tutors; the driver records; the subject updates mastery; learn-cli
ledgers the raw result and derives motivation.

### State division (normative)

| Concern | Owner |
| --- | --- |
| Content: stories, lessons, exercises (committed files) | subject repo |
| Per-learner mastery ladder + item history, per subject | subject CLI (XDG-path state file) |
| Within-subject next-step recommendation | subject CLI (deterministic) |
| Conversational tutoring, grading of answers | driver |
| Raw-result ledger across subjects | learn-cli |
| Numeric scores, streaks, review queues, cross-subject what-next | learn-cli (pure functions of the ledger) |
| Cross-subject learner profile / identity | learn-cli |

Two hard prohibitions fall out of this:

1. **Subjects never emit scores.** The `record` ack's `recorded` object structurally forbids
   `score`/`grade`/`points` fields (a `not` clause in `record.json`). Subjects report raw
   observations only: `result`, optional `correct`/`total` counts, `duration_seconds`.
2. **learn-cli never contains subject content or progression logic.** Deleting a subject's
   registry entry removes it from every face.

## 2. Conventions every verb follows

- **Invocation:** `<subject-command> <verb> [args] --json [--learner <id>]`. The subject command
  is a console script on PATH (e.g. `french`), declared in the registry entry.
- **`--json` everywhere.** learn-cli only consumes `--json` output. Text mode exists for humans
  and is uncontracted (rubric rules still apply inside the subject repo).
- **`--learner <id>`** on every learner-scoped verb. When omitted, the subject resolves a default
  (its own env var, then the OS user) and **must echo the resolved id** in the payload's
  `learner` field. The learner may be a human or an agent.
- **Streams:** results → stdout, errors/diagnostics → stderr, never mixed.
- **Exit codes:** `0` success · `1` user error · `2` environment error · `3+` reserved.
- **Errors:** on any failure, stderr carries the `error.json` shape
  `{code, message, remediation}` in `--json` mode (`error: …` + `hint: …` in text mode), and the
  process exits with `code`. No traceback ever reaches stderr.
- **Versioning:** every payload carries `schema_version` (see §5).
- **Open payloads:** schemas validate required structure but allow extra fields, so subjects can
  extend (e.g. culture-guide's `unclear_questions_for_ori`) and minor contract versions can add
  optional fields without breaking older validators. Consumers must ignore unknown fields.

## 3. The eight verbs

Schema files live in `learn/contract/schemas/`; golden example payloads (validated in CI) in
`tests/fixtures/payloads/`. "Learner-scoped" means the verb reads or writes per-learner state.

| # | Verb | Invocation | Payload schema | `kind` | Learner-scoped | Writes state |
| - | --- | --- | --- | --- | --- | --- |
| 1 | overview | `overview --json` | `overview.json` | `subject_overview` | no | no |
| 2 | progress | `progress --json` | `progress.json` | `progress` | yes | no |
| 3 | advice | `advice --json` | `advice.json` | `advice` | yes | no |
| 4 | story | `story list --json` / `story read <id> --json` | `story_list.json` / `story_read.json` | `story_list` / `story_read` | list: no · read: yes | read: may set current position |
| 5 | lesson | `lesson start [<target>]` / `lesson next` / `lesson repeat [<id>] [--harder]`, all `--json` | `lesson.json` | `lesson_directive` | yes | yes (current lesson; first exposure lifts items to `introduced`) |
| 6 | practice | `practice [<scope>] --json` | `practice.json` | `practice_directive` | yes | no |
| 7 | record | `record --item <id> --result pass\|partial\|fail […] --json` | `record.json` | `record_ack` | yes | yes (history + mastery) |
| 8 | doctor | `doctor --json` | `doctor.json` | `subject_doctor` | no | no |

### 3.1 `overview` — the subject describes itself

Identity, description, ordered **modules** (the web face renders one sub-page per module), and
content counts. Learner-independent and deterministic, so the static site can be built from it
with zero model or state access.

### 3.2 `progress` — where the learner stands

Per-item mastery map on the shared ladder (§4), counters
(`items_total`/`items_touched`/`items_mastered`), completed and weak item lists, timestamps, and
the subject's own `next` recommendation `{done, text, command, item_id?, module_id?}`. `done:
true` never dead-ends the learner: it is the signal for learn-cli to switch to maintenance +
depth mode (review decayed items, `lesson repeat --harder`, fresh stories).

### 3.3 `advice` — deterministic study advice

What to shore up and why, each entry with a runnable `command`. A pure function of stored state —
the "tutor's opinion" a driver can relay verbatim. May be empty for a brand-new learner.

### 3.4 `story` — the shared content surface

`story list` returns level-tagged summaries (id, title, level, exercise count) — enough for the
public catalog. `story read <id>` returns the **full story object exactly as committed**
(`story.json`, §6) wrapped in a directive: present paragraph-at-a-time, use the glossary on
demand, run the comprehension exercises, record each result. Unknown story id → exit 1 with the
error shape.

### 3.5 `lesson` — start / next / repeat

The subject resolves *what* to teach — `start` (optionally targeted at a module or item), `next`
(continue from mastery state), or `repeat [<id>] [--harder]` (re-issue a completed lesson;
`--harder` increments the lesson's integer `difficulty` rung — the repeatable-lessons half of
never-ending progression). The payload carries the lesson's items (each with teachable `points`)
plus the directive (optionally with a `persona`). Item ids in the lesson are exactly what
`record --item` expects back.

### 3.6 `practice` — exercises to run

A batch of exercises scoped to an item, a module, or `review` (no argument: the subject picks its
weakest touched items). Exercise types: `multiple_choice`, `true_false`, `cloze`, `short_answer`,
`translation`, `open`, `discussion`. Checkable types carry `answer`; open types carry `rubric`
(what passes, what is partial). `cloze` has two variants — §3.6.1.

#### 3.6.1 The `cloze` exercise type: two variants, one `type` value

`cloze` (fill-in-the-blank) has shipped since contract 1.0 as a **single-blank, free-text**
exercise: `prompt` writes the blank as `___` and a top-level `answer` is the expected string,
graded conversationally by the driver exactly like `short_answer`/`translation`. That variant is
**unchanged** — it is still valid, still renders the same, and needs no update from any subject.

t3 adds a second, richer variant to the same `type: "cloze"` value: **pick-the-right-word**, a
passage with one or more blanks where the learner (or an unauthenticated site reader) picks from a
closed set of options per blank, checkable without a driver or a model call. It is carried by two
new, OPTIONAL exercise fields — additive to contract family 1.0, so every payload that predates
them keeps validating unchanged (open payloads, §2):

| Field | Type | Meaning |
| --- | --- | --- |
| `text` | string | The passage, with each blank marked as a `{{blank_id}}` placeholder. |
| `blanks` | array | One entry per placeholder in `text`: `{id, options, answer}`. |

Each `blanks[]` entry:

| Field | Req | Meaning |
| --- | --- | --- |
| `id` | ✓ | Matches one `{{id}}` placeholder in `text`; unique within the exercise. |
| `options` | ✓ | ≥2 words the reader picks from: the correct word plus one or more distractors. Must include `answer`. |
| `answer` | ✓ | The correct option for this blank; must be one of `options`. |

`text` and `blanks` are always present **together** — an exercise with only one of them is
malformed. An exercise is the pick-the-right-word variant if and only if it carries `text` or
`blanks`; an exercise with neither is the legacy single-blank form, untouched by anything below.

**Design decision — least invasive shape (spec c16/h8):**

- **No new exercise `type`.** `cloze` already existed and already meant "a fill-in-the-blank";
  pick-the-right-word is a richer *shape* of the same type, not a new kind. A driver/site that
  doesn't understand `text`/`blanks` yet can still fall back to `prompt`/`answer` (both remain
  present on a well-authored pick-the-right-word item, as the driver-facing instruction), since
  every field addition here is optional.
- **No new activity.** `record`'s `recorded.activity` stays `lesson | practice | story` — a cloze
  item's result is recorded exactly like any other exercise's, via whichever activity hosted it
  (typically `practice` for a practice-batch cloze item, `story` for a comprehension cloze item).
  `record.json`'s `recorded` object carries no `type`/exercise-shape field at all, so it was
  **already** forward-compatible with cloze before this change — this is why neither the Python
  contract validator nor the worker's `validate.js` (`workers/learn-api/src/validate.js`) needed
  any code change for acceptance criterion 2. What DOES change: a multi-blank cloze result tallies
  naturally into the pre-existing `recorded.correct`/`recorded.total` counters (already part of
  `record.json`) — e.g. two blanks, one right, records `--correct 1 --total 2`. No new field.
- **`item_id` rules are unchanged.** A pick-the-right-word cloze exercise carries `item_id` exactly
  like every other exercise type: the join key `record --item` expects, the same string other
  exercises MAY legitimately reuse when they evidence the same curriculum item. This contract does
  **not** require cloze `item_id`s to be globally unique — only present. What `learn subject
  doctor` (below) does additionally require unique is the exercise's own `id` (its slug, e.g.
  `"fr-p1-b1"`) among the subject's declared pick-the-right-word cloze items, since that id is what
  a driver/site addresses a specific cloze instance by; `item_id` (the mastery join key) keeps its
  existing, unrestricted reuse semantics.
- **Marker syntax is `{{blank_id}}`**, chosen for being unambiguous in both markdown-flavored
  `body`/`text` content and plain prose, and trivial to parse with one regex
  (`` /\{\{([^{}]+)\}\}/ ``) in Python, JavaScript, or Astro's build-time templating — no parser
  dependency added anywhere in the pipeline.

**Example** (a `practice` exercise; the same shape is legal inside a `story`'s `exercises`):

```json
{
  "id": "fr-p1-b1",
  "type": "cloze",
  "item_id": "numbers-money",
  "prompt": "Fill in each blank with the right word.",
  "text": "Je vais au marché pour acheter {{qty}} pommes.",
  "blanks": [
    { "id": "qty", "options": ["trois", "gris", "trop"], "answer": "trois" }
  ]
}
```

Recording the result once both blanks are graded (one blank here, so `--total 1`):

```bash
french record --learner ori --item numbers-money --activity practice \
  --exercise fr-p1-b1 --result pass --correct 1 --total 1 --json
```

**Validation split** (structural vs. semantic — the mini JSON-Schema validator, §8, only checks
the former):

- **Schema-checkable** (`learn.contract.validate` / a subject's own schema validation): `text` is
  a non-empty string; `blanks` is a non-empty array; each blank is an object with `id` (pattern
  `^[a-z0-9][a-z0-9._-]*$`), `options` (≥2 non-empty strings), and `answer` (non-empty string) —
  all required.
- **Semantic, checked by `learn subject doctor`'s `cloze-items` check** (not expressible in the
  stdlib validator's supported keyword subset, §8): every blank's `answer` is one of its own
  `options`; blank `id`s are unique within the exercise and match a `{{id}}` placeholder in `text`
  1:1 (no orphan placeholder, no blank without one); the exercise carries a non-empty `item_id`;
  the exercise's own `id` is unique among the subject's other declared pick-the-right-word cloze
  items. The check reads every story via `story read` (the one exception to "runtime gate stays
  read-only" in `learn/subjects/conformance.py` — still side-effect-free against the dedicated
  probe learner) and inspects each `type: "cloze"` exercise that carries `text` or `blanks`. **A
  subject that declares none passes trivially** — this never penalizes pre-cloze content or a
  subject using only the legacy single-blank form, satisfying the "existing subject exports
  identically" requirement (spec h8).

**Rendering (`learn site export` + site-astro):** the exporter (`learn/front/_export.py`) needed
**no code change** — it already writes each subject's `story read` output verbatim, so `text` and
`blanks` pass through untouched the moment a subject starts emitting them. `site-astro`'s story
reader page renders a pick-the-right-word cloze exercise (`type: "cloze"` with a non-empty
`blanks` array) as the passage with one button group per blank (one button per option); clicking
an option marks it right/wrong immediately, entirely client-side, against the `answer` already
present in the (public) exported JSON — no fetch, no sign-in required, matching the zero-API-when-
signed-out invariant the rest of the site enforces. A legacy single-blank cloze exercise (no
`blanks`) keeps rendering exactly as before (plain prompt, no picker). See
`site-astro/src/scripts/learner.js`'s `wireClozeExercises()`.

### 3.7 `record` — the write-back (the motivation layer's input)

The driver reports one graded outcome:

```bash
french record --learner ori --item numbers-money --activity practice \
  --exercise nm-p1 --result pass --correct 1 --total 1 --duration-seconds 38 --json
```

The subject appends the raw result to its history, updates the item's mastery (inferred from
`result` unless `--mastery` is given explicitly; inference never regresses a level), and acks
with:

- `recorded` — the normalized raw-result object `{item_id, activity, exercise_id?, story_id?,
  lesson_id?, result, correct?, total?, duration_seconds?, notes?, at}`. **This object is the
  contract's scoring input:** learn-cli appends it verbatim to its cross-subject ledger, and the
  motivation layer (t9) computes scores/streaks/review-queues from the ledger alone. It
  structurally rejects `score`/`grade`/`points`.
- `mastery` — the item's post-record level.
- `next` — the refreshed within-subject recommendation.

Result inference default (culture-guide's proven mapping): `fail → introduced`,
`partial → practiced`, `pass → mastered`, never regressing.

### 3.8 `doctor` — self-check + contract pin

Health checks in the established doctor shape (`{id, passed, severity, message, remediation}`)
plus **`contract_version`** — the contract version this subject pins. `learn subject doctor`
(t3) reads the pin first, then validates the other seven verbs' payloads against that version's
schemas — plus, since t3, a `cloze-items` check verifying every declared pick-the-right-word cloze
exercise (§3.6.1). Exit 0 when healthy, 2 when not. Recommended checks: content files validate
against `story.json`, learner-state dir writable, pinned contract version supported.

## 4. Shared vocabularies

Exported as constants from `learn.contract` and embedded in the schemas (tests assert they
agree):

- **Mastery ladder** (ordered): `unknown → introduced → practiced → mastered`.
- **Raw results:** `pass | partial | fail`.
- **Story/lesson levels:** `beginner | intermediate | advanced` (finer grading goes in
  `level_detail`, e.g. `"A1"`, `"B2"`, `"scenario"`).
- **Ids:** subjects match `^[a-z][a-z0-9-]*$`; items/stories/lessons/exercises/checks match
  `^[a-z0-9][a-z0-9._-]*$`. Item ids are the join key across `lesson`/`practice`/`story`
  exercises, `record`, and `progress.mastery`.

## 5. Versioning (`schema_version`)

- The contract version is a `major.minor` string; this document and the shipped schemas are
  **`1.0`** (`learn.contract.CONTRACT_VERSION`).
- **Every payload** (and every story content file) carries `schema_version`; v1 schemas pin the
  pattern `^1\.[0-9]+$`, so a v2 payload fails v1 validation loudly.
- **Minor bump** (`1.0 → 1.1`): additive only — new optional fields, new enum members at the
  tail. Older consumers keep validating (open payloads, §2).
- **Major bump** (`2.0`): anything breaking — removed/renamed fields, changed semantics, new
  required fields. Requires new schema files and a coordinated subject migration.
- Subjects **pin** the version they satisfy in `doctor.contract_version`; each subject repo runs
  the conformance gate in its own CI, so drift fails the subject's build, not learn-cli's
  runtime.
- The `error.json` stderr shape predates the contract (it is the template chassis's `CliError`)
  and carries no `schema_version`.

## 6. The story schema (`story.json`)

One schema for all subjects (spec c29): language subjects ship **graded-reader ladders**;
culture-guide ships **narrative scenarios** (an agent-team incident the learner reasons through)
in the same shape. Stories are committed content files in each subject repo, validated against
this schema in the subject's CI, and embedded verbatim in `story read` payloads.

| Field | Req | Meaning |
| --- | --- | --- |
| `schema_version` | ✓ | contract version family (`^1\.[0-9]+$`) |
| `kind` | ✓ | const `story` |
| `id` | ✓ | stable slug, unique within the subject |
| `subject` | ✓ | owning subject id |
| `title` | ✓ | display title |
| `level` | ✓ | `beginner \| intermediate \| advanced` |
| `level_detail` | – | finer grading: CEFR tag or `scenario` |
| `language` | – | BCP-47 tag of the body (`fr`, `es`, `en`) |
| `summary` | – | one-line teaser, safe for the signed-out catalog |
| `body` | ✓ | the story text (markdown, blank-line paragraphs) |
| `glossary` | ✓ | glossary/annotations: `[{term, definition, note?}]` (may be empty) |
| `exercises` | ✓ | ≥1 comprehension exercises (same exercise shape as `practice`) |
| `audio` | – | **reserved slot** for the spoken-practice follow-up: `null` or `{url?, format?, voice?, duration_seconds?}`; producers omit/null until the audio pipeline exists |
| `source` | – | provenance for the batch pipeline: `{generator?, model?, reviewed_by?, generated_at?}` |

Three reference fixtures validate against it in this repo's test suite
(`tests/test_story_fixtures.py`), one per launch subject:

- `tests/fixtures/stories/french-beginner-le-marche.json` — French graded story (A1).
- `tests/fixtures/stories/spanish-beginner-la-panaderia.json` — Spanish graded story (A1).
- `tests/fixtures/stories/culture-guide-scenario-overloaded-agent.json` — culture-guide
  narrative scenario.

## 7. How a new subject registers (registration, not a fork)

Adding subject #4 requires **zero new platform code** in learn-cli:

1. **Build a conformant CLI** — implement the eight verbs over the subject's own content and
   state (the french/spanish implementation is the reference; culture-guide's adapter shows the
   wrap-an-existing-engine path: `teach status → progress`, `teach lesson → lesson`,
   `teach quiz → practice`, `teach record → record`).
2. **Add a registry entry** in learn-cli's data-driven subject registry (t3) — no code, just
   data: subject `id`, `display_name`, the executable `command` (console script on PATH), and
   the pinned `contract_version`.
3. **Prove conformance** — `learn subject doctor <subject>` must pass: it spawns the subject's
   verbs as subprocesses, validates each `--json` payload against the pinned version's schemas,
   and checks the exit-code and stream contracts. Wire the same gate into the subject repo's CI.
4. **Ship content** — committed story/lesson files that validate against `story.json` (launch
   bar: ≥10 stories across ≥3 levels for a language, ≥3 scenarios for a non-language subject).

Deleting the registry entry cleanly removes the subject from all three faces.

## 8. Using the machine-readable contract

```python
from learn import contract

contract.CONTRACT_VERSION          # "1.0"
contract.SCHEMA_NAMES              # the 11 shipped schemas
schema = contract.load_schema("story")
errors = contract.validate(payload, "story")   # [] means valid
```

Schemas are package data (`learn/contract/schemas/*.json`) loaded via `importlib.resources`, so
the installed wheel carries them — t3's conformance gate and any subject repo's CI can validate
without this repo checked out. Validation is stdlib-only (`learn/contract/_validate.py`);
runtime dependencies stay empty. The validator supports exactly the keyword subset the schemas
use, and a guard test (`test_schema_uses_only_supported_keywords`) keeps schemas inside that
subset. Cross-file references are limited to sibling schemas (`story_read.json` → `story.json`).
