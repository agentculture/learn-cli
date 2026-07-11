# Build Plan — agentculture.org/learn is live: one learning hub in org's design where humans and agents learn French, Spanish, and agent-team leadership through stories, scored exercises, and adaptive never-ending lessons — signed-in learners see their cross-subject journey (progress, scores, streaks, what-next); visitors get an elegant tour — and the same experience is served coherently over the learn CLI, MCP server, and web site, with french-cli, spanish-cli, and culture-guide uplifted to that bar.

slug: `agentculture-org-learn-is-live-one-learning-hub-in` · status: `exported` · from frame: `agentculture-org-learn-is-live-one-learning-hub-in`

> agentculture.org/learn is live: one learning hub in org's design where humans and agents learn French, Spanish, and agent-team leadership through stories, scored exercises, and adaptive never-ending lessons — signed-in learners see their cross-subject journey (progress, scores, streaks, what-next); visitors get an elegant tour — and the same experience is served coherently over the learn CLI, MCP server, and web site, with french-cli, spanish-cli, and culture-guide uplifted to that bar.

## Tasks

### t1 — Kickoff: re-verify sibling repo state and open the cross-repo coordination lane

- covers: c3, h12, c10, h3
- acceptance:
  - HEADs of french-cli, spanish-cli, culture-guide, org, and agentfront recorded and diffed against the spec's before-state; any divergence amended in the spec before build tasks start
  - Cross-linked tracked issues exist on french-cli, spanish-cli, culture-guide, and org, each referencing the exported spec and its siblings (communicate skill, signed)

### t2 — Author the subject-plugin contract spec + story schema in learn-cli docs/specs/

- covers: c9, c16, c18, c29
- acceptance:
  - Contract doc defines the eight tutor verbs (overview, progress, advice, story, lesson, practice, record, doctor) with versioned JSON schemas (schema_version field), exit codes, and the state division: subjects own content + per-learner mastery (directive pattern), learn owns the motivation layer
  - Story JSON schema included and shown to validate a french graded story, a spanish graded story, and a culture-guide narrative scenario fixture

### t3 — learn-cli: data-driven subject registry + 'learn subject doctor' conformance gate

- depends on: t2
- covers: c4, c7, h16, c11, h17, h2, h4, c18
- acceptance:
  - 'learn subject doctor <subject>' validates a subject CLI's verbs, schema_version, JSON payloads, and exit codes against the contract and fails on drift
  - A dummy fourth-subject fixture registers and passes with zero new platform code (test proves registration-not-fork)
  - Deleting a registry entry removes the subject from all faces; learn-cli contains no subject content or progression logic (enforced by test + review rule)

### t4 — french-cli: implement the contract — tutor verbs, content store, per-learner state

- depends on: t2
- covers: c4, h2, h4, h13
- acceptance:
  - french passes 'learn subject doctor' (all eight verbs, schema-valid --json, contractual exit codes)
  - Learner state persists (XDG path) and resumes across sessions; 'record' updates mastery; conformance gate wired into french-cli CI

### t5 — spanish-cli: port french's contract implementation, byte-consistent modulo the language token

- depends on: t4
- covers: h19, h2, h13
- acceptance:
  - spanish passes 'learn subject doctor'; implementation diff vs french-cli is language-token-only (checked mechanically)
  - Conformance gate wired into spanish-cli CI

### t6 — culture-guide: adapter mapping the teach noun onto the contract verbs without breaking existing users

- depends on: t2
- covers: h19, h13, c4
- acceptance:
  - culture-guide passes 'learn subject doctor' via the adapter (teach status→progress, teach lesson→lesson, teach quiz→practice, plus story/advice/record)
  - Existing teach subverbs and their tests remain green (no breaking change for current users)

### t7 — Story pipeline + starter graded ladders for french and spanish (cloudai-cli batch, human-reviewed, committed)

- depends on: t2
- covers: c8, h1, c29, h7
- acceptance:
  - >=10 stories across >=3 difficulty levels per language, each with glossary + comprehension exercises, committed as schema-valid content files (validated in each repo's CI)
  - Generation pipeline is reproducible (documented cloudai-cli batch command + review checklist); no live model calls at serve time

### t8 — culture-guide: >=3 narrative scenarios in the shared story schema

- depends on: t2
- covers: c8, h1, h7
- acceptance:
  - >=3 scenarios (e.g. agent-team incidents to reason through) committed, schema-valid, wired to the story verb via the adapter

### t9 — learn-cli motivation layer: deterministic scores, streaks, review queues, adaptive what-next

- depends on: t2
- covers: c27, h5, c28, h6, c9
- acceptance:
  - Pure module: identical recorded history yields identical scores/streaks/what-next (golden-history unit tests; no LLM in the scoring path)
  - Time-decayed mastery feeds review queues; a completed-track simulation test proves a meaningful next action always exists (never-ending mode)

### t10 — learn-cli three faces through agentfront: registry-driven CLI verbs, MCP server, HTTP face + agreement tests

- depends on: t3
- covers: c23, h21, c4
- acceptance:
  - learn depends on agentfront>=0.20 [mcp]; CLI/MCP/HTTP surfaces enumerate identically (surfaces_agree in CI); 'learn subjects --json' lists conformant subjects
  - Any agentfront gap hit (remote MCP transport, HTTP hooks, static export) is filed as an upstream issue, not forked

### t11 — learn API worker: GitHub OAuth sessions, learner state (KV/D1), tutoring broker via cloudai-cli/ec2bedrock-cli

- depends on: t2
- acceptance:
  - GitHub OAuth device+web flows issue short-lived sessions; only GitHub id, display name, and learner state stored (no passwords/PII)
  - Progress read/write endpoints implement the contract schemas; live tutoring endpoint brokers to cloudai-cli/ec2bedrock-cli; cost-when-busy note committed (static free; Worker ~$5/mo + usage; tokens per-use); signed-out requests can never trigger a model call

### t12 — Cross-subject learner profile + 'learn auth login' sync across CLI/MCP/web

- depends on: t9, t11
- covers: c4
- acceptance:
  - 'learn auth login' (device flow) links CLI/MCP to the same account the web uses; local XDG state works offline and syncs through the learn API when linked
  - Anonymous CLI/MCP use stays fully functional local-only

### t13 — learn-cli site-astro/: org's design system verbatim, module sub-pages from registry export, story reader, deploy workflow

- depends on: t3, t7
- covers: c12, h18, c5
- acceptance:
  - site-astro/ copies org's global.css, Layout, components, and both fonts verbatim; zero new design tokens (CSS diff audit vs org); output:'static', no adapter
  - 'learn site export' emits registry content the Astro build consumes; CI fails when a registry module lacks a site page or vice versa; one sub-page per module with story reader; @view-transition CSS matches org's
  - deploy.yml (wrangler direct-upload, modeled on org's) publishes to learn-cli's own Cloudflare Pages project with branch previews

### t14 — Signed-out/in split on the site: static public tour + client-hydrated learner panels

- depends on: t13, t11
- covers: c6, h15
- acceptance:
  - Signed-out pages are pure static output: a network-log test proves zero API/model calls; every learner-specific element has a designed signed-out state (invitation, sample, or lock)
  - Signed-in panels (progress, scores, streaks, adaptive next lesson) hydrate client-side after a session check against the learn API

### t15 — org + Cloudflare integration: /learn nav, directory entry, same-origin route, seamless-navigation QA

- depends on: t13
- covers: c5, h14, c19, h20, c31, h22
- acceptance:
  - org PRs land: Header+Footer nav link, site.ts learn-cli entry pointing at /learn/; org maintainers sign off on a Pages preview that /learn reads as one site in both themes
  - agentculture.org/learn/* routes same-origin to learn-cli's Pages project (via org/cultureflare operator lane); org gains no SSR, adapter, or build-time dependency on learn-cli; org→/learn navigation keeps the cross-document view-transition fade (navigation test + manual QA)

### t16 — E2E launch gate: scripted success walk + measurable launch bar, automated

- depends on: t5, t6, t8, t10, t12, t14, t15
- covers: c1, h10, c2, h11, c14, h23, c32, h24, h13
- acceptance:
  - Scripted walk passes: signed-out story read; signed-in scored lesson in each of french, spanish, culture-guide; progress parity asserted across web, 'learn' --json, and MCP — run from phone-viewport and desktop
  - One acceptance test per audience is green: web (Playwright signed-in/out), CLI (pytest golden --json), agent (agentfront.testing call_mcp)
  - Every launch-bar number is machine-checked: 3 subjects conformant, content counts via schema validation, zero-API static check, zero new design tokens

## Risks

- [follow_up] Spoken practice (TTS/STT) deferred — story schema reserves the audio slot; own spec later (per frame follow-up v4)
- [unknown_nonblocking] Remote/HTTP MCP transport — agentfront is stdio-only today; hosted agent-learning endpoint needs upstream transport work (frame v5)
- [follow_up] culture.dev cross-link via katvan at launch (frame v6)
- [unknown_nonblocking] Agent-learner identity semantics (own profile vs on-behalf-of) — v1 treats any authenticated account as a learner (frame v7)
- [unknown_nonblocking] Cloudflare route + Pages project provisioning needs operator-owned credentials (cultureflare lane) — schedule with the operator; org maintainer review time gates t15 (task t15)
- [unknown_nonblocking] Story generation quality depends on cloudai-cli batch access + human review bandwidth for ~2x10+ stories and 3 scenarios (task t7)
