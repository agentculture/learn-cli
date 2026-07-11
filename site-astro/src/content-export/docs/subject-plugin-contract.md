# The subject-plugin contract

Contract version **1.0** (`learn.contract.CONTRACT_VERSION`). This is the interface a subject CLI must satisfy to be hosted by learn-cli. The full narrative spec lives at `docs/specs/subject-plugin-contract.md`; this page is generated from the machine-readable schemas that ship in the package.

## The model

- **The subject CLI** is an LLM-free engine: it owns committed content and per-learner mastery, resolves what to teach next, and emits structured teaching directives. It never converses, grades free text, or computes scores.
- **The driver** (an agent or human harness) does the conversational tutoring the directive describes and writes graded results back via `record`.
- **learn-cli** drives subjects as external `--json` subprocesses (never importing them) and owns the deterministic motivation layer.

## The eight verbs

| Verb | Invocation | What it does |
| --- | --- | --- |
| overview | `overview` | the subject describes itself: identity, modules, content counts |
| progress | `progress` | where the learner stands on the mastery ladder |
| advice | `advice` | deterministic study advice, each with a runnable command |
| story | `story list / story read <id>` | the shared content surface (graded readers) |
| lesson | `lesson start|next|repeat` | the subject resolves what to teach next |
| practice | `practice [<scope>]` | a batch of exercises to run and grade |
| record | `record --item <id> --result <r>` | the driver's graded write-back |
| doctor | `doctor` | self-check plus the pinned contract version |

Invocation is always `<subject-command> <verb> [args] --json [--learner <id>]`. Errors emit `{code, message, remediation}` on stderr and exit with that code.

## Shared vocabularies

- **Mastery ladder** (ordered): unknown → introduced → practiced → mastered.
- **Raw results**: pass | partial | fail (subjects never emit scores).
- **Story/lesson levels**: beginner | intermediate | advanced.

## Schemas

Every payload carries `schema_version` (family `1.x`). The shipped schemas (`learn.contract.SCHEMA_NAMES`):

- **`overview`** — Subject overview payload
- **`progress`** — Progress payload
- **`advice`** — Advice payload
- **`story`** — Story content schema
- **`story_list`** — Story list payload
- **`story_read`** — Story read payload
- **`lesson`** — Lesson directive payload
- **`practice`** — Practice directive payload
- **`record`** — Record acknowledgement payload
- **`doctor`** — Subject doctor payload
- **`error`** — Error payload (stderr)
