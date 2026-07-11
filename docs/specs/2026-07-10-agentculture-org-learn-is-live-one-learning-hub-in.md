# agentculture.org/learn is live: one learning hub in org's design where humans and agents learn French, Spanish, and agent-team leadership through stories, scored exercises, and adaptive never-ending lessons — signed-in learners see their cross-subject journey (progress, scores, streaks, what-next); visitors get an elegant tour — and the same experience is served coherently over the learn CLI, MCP server, and web site, with french-cli, spanish-cli, and culture-guide uplifted to that bar.

> agentculture.org/learn is live: one learning hub in org's design where humans and agents learn French, Spanish, and agent-team leadership through stories, scored exercises, and adaptive never-ending lessons — signed-in learners see their cross-subject journey (progress, scores, streaks, what-next); visitors get an elegant tour — and the same experience is served coherently over the learn CLI, MCP server, and web site, with french-cli, spanish-cli, and culture-guide uplifted to that bar.
> instruction: Verify at launch by walking both journeys — signed-out tour, signed-in scored lesson — on agentculture.org/learn, from a phone and a desktop.

## Audience

- Human learners (web/phone and CLI) and AI agents (over MCP) learning subjects step by step; plus the AgentCulture operator who maintains the subject repos and the org site.
  - instruction: One acceptance test per audience: web (Playwright, signed-in and signed-out), CLI (pytest golden --json transcripts), agent (agentfront.testing call_mcp).

## Before → After

- Before: learn-cli is a template scaffold (identity verbs only); french-cli/spanish-cli/culture-guide are standalone tutors with uneven UX and no shared profile; agentculture.org (owned by ../org) has no /learn section; no stories/scores/adaptive loop exists anywhere.
  - instruction: Re-verify sibling repo state at build kickoff (french/spanish/culture-guide/org/agentfront HEAD); amend the spec if any moved.
- Before: Verified by reading the repos: french-cli and spanish-cli are unmodified template scaffolds (6 introspection verbs, --json contract, zero tutor domain — no lesson/story/practice verbs, no content, no learner state, no LLM path). culture-guide's teach noun (5-part/35-concept curriculum, mastery ladder, per-learner JSON state, agent-drives-the-teaching directive pattern) is the mesh's only working tutor engine.
  - instruction: Implement the contract as one shared spec applied identically to french-cli and spanish-cli (byte-consistent modulo language token, like the template siblings); write a culture-guide adapter mapping teach subverbs to contract verbs without breaking existing teach users.
- Before: Verified by reading ../org: the site is Astro output:'static' (no adapter, no auth, no SSR), design system self-contained (global.css tokens + 5 components + Fraunces/Albert Sans fonts, auto dark mode, dawn-mesh motif), content is typed src/data/*.ts + hand-written .astro pages (no markdown/collections), deployed to Cloudflare Pages project 'agentculture-org' via wrangler; no cross-repo content federation exists — sibling coordination is GitHub issues; no /learn route, and org's Agents directory links learn-cli to GitHub.
  - instruction: org's repo changes stay minimal and static: site.ts entry + Header/Footer nav arrays; the /learn route lands as Cloudflare config through the operator-owned cultureflare path — org never gains a build-time dependency on learn-cli.
- Before: Verified by reading ../agentfront: agentfront 0.20.0 is an importable runtime library — one App registry of docs+tools emits the CLI, a stdio MCP server (single 'run' tool), an HTTP face, and a TAUI, with surfaces_agree() proving they enumerate identically. Its HTTP face serves raw markdown + sitemap.xml + llms.txt from a live WSGI app — no HTML, no theming, no static export — and it has zero auth/user-state primitives.
  - instruction: Depend on agentfront>=0.20 in learn-cli's pyproject (with the [mcp] extra); file upstream agentfront issues for any gap hit (remote MCP transport, HTTP-face hooks, static export) instead of forking.
- After: learn-cli is the learner platform: a subject registry fronting french-cli, spanish-cli, and culture-guide, where every subject offers stories, progress tracking, scores, repeatable lessons, and adaptive never-ending progression, behind one cross-subject learner profile.
  - instruction: Build order: subject registry + 'learn subject doctor' conformance gate in learn-cli; implement the contract verbs in french-cli and spanish-cli from one shared spec; adapt culture-guide's teach noun; 'learn subjects --json' must list all three as conformant.
- After: agentculture.org/learn serves the hub in org's existing design language — one sub-page per module — built so org can load it into the site easily and the whole site stays coherent.
  - instruction: File a coordination issue on org (communicate skill) proposing: /learn nav link (Header+Footer, a two-file edit), the site.ts learn-cli entry pointing at /learn/, and the Cloudflare route for agentculture.org/learn → learn-cli's Pages project; land as org-reviewed PRs.
- After: The /learn site looks different signed-in vs signed-out: signed-out visitors get the elegant public tour (subject catalog, sample stories, module pages); signed-in learners get the resource-backed personal experience (their progress, scores, streaks, adaptive next lesson).
  - instruction: Signed-out pages are pure static Astro output; signed-in panels hydrate client-side after a session check against the learn API; add a test that the signed-out network log contains zero API/model calls.

## Why it matters

- Learners get one professional door to every subject with durable motivation loops (stories, streaks, scores, what-next), and the mesh proves the subject interface generalizes beyond languages instead of every tutor reinventing its own experience.
  - instruction: Keep the registry data-driven (a subjects registry file, not code per subject); prove generalization with a dummy fourth-subject fixture in learn-cli's test suite.

## Requirements

- Stories are first-class learning content: the language modules (french, spanish) teach through stories, and culture-guide gains narrative/story-based learning as part of its experience uplift.
  - instruction: Define the story schema in the subject contract; pre-generate starter graded ladders via cloudai-cli in batch; human-review; commit as content files in french-cli and spanish-cli; author 3+ narrative scenarios for culture-guide.
  - honesty: Stories are a contract surface, not prose: each language module ships a level-tagged story library (text + glossary + comprehension exercises) reachable via a registry verb, and culture-guide ships narrative scenarios in the same shape — verified by the same conformance check for all three subjects.
- Progress tracking, scores, repeatable lessons, adaptive difficulty, and never-ending progression are expressed in the subject-plugin contract so every subject exposes them uniformly (adding subject #4 is a registration, not a fork).
  - instruction: Write the subject-plugin contract spec FIRST (learn-cli docs/specs/): verbs, JSON schemas, exit codes, state division; ship 'learn subject doctor <subject>' as the executable conformance gate and wire it into each subject repo's CI.
  - honesty: The subject-plugin contract exists as a written spec plus an executable conformance gate (e.g. 'learn subject doctor <subject>'), and french, spanish, AND culture-guide all pass it — progress/scores/next-lesson/stories return machine-readable JSON that the web, CLI, and MCP faces all consume unchanged.
- The uplift is multi-repo by design: coordinated changes land in learn-cli, french-cli, spanish-cli, culture-guide, and org — every surface is touched to make the experience work end to end.
  - instruction: Open cross-linked tracked issues on french-cli, spanish-cli, culture-guide, and org from the exported spec (communicate skill); sequence: contract spec → subject implementations → learn faces → site + org integration → sign-in layer.
  - honesty: The uplift lands as tracked, cross-linked issues and PRs in learn-cli, french-cli, spanish-cli, culture-guide, and org — and the shipped /learn pages render content actually produced by the subject repos (not copies hand-pasted into org).
- Every subject verb the portal consumes emits stable --json (the contract IS the JSON schemas + exit codes, versioned), so learn-cli can drive subjects as external runtimes without importing their code.
  - instruction: Version the contract schemas (schema_version field); implement 'learn subject doctor' validation against them; subjects pin the contract version they satisfy.
  - honesty: Contract payloads are versioned schemas checked by an executable conformance gate that runs in each subject repo's CI — a subject that drifts fails its own build, not learn-cli's runtime.
- Division of intelligence: subject CLIs own content + per-learner mastery (culture-guide's directive pattern); learn-cli owns the uniform motivation layer — numeric scores per exercise, per-subject and cross-subject streaks, review queues, and adaptive what-next computed deterministically from the contract's recorded results — so every subject gets scores/streaks/adaptivity without reimplementing them.
  - instruction: Implement scoring/streak/what-next as a pure module in learn-cli (deterministic functions over recorded history), unit-tested with golden histories; subjects only report raw results via 'record'.
  - honesty: Scores, streaks, and what-next are deterministic, unit-tested functions of recorded history — the same history yields the same numbers on web, CLI, and MCP; no LLM in the scoring path.
- Never-ending learning: completing a track flips the learner into maintenance+depth mode, never a dead end — review queues driven by time-decayed mastery, repeatable lessons at higher difficulty, and fresh stories rotated in (pre-generated batches) — so there is always a meaningful next action.
  - instruction: Implement time-decayed mastery + review-queue computation in learn-cli's motivation layer; add the completed-track simulation test proving a next action always exists; wire fresh-story rotation to the batch generation pipeline.
  - honesty: A learner who has completed every authored item still receives a concrete next action (review of decayed mastery, a harder repeat, or a fresh story) — proven by a test that simulates a fully-completed track.
- A story is a shared content schema across subjects: id, difficulty level, title, body, glossary/annotations, comprehension exercises (and an audio slot reserved for later). Language stories form a graded-reader ladder (beginner → advanced); culture-guide stories are narrative scenarios (e.g. an agent-team incident the learner reasons through). Stories live as committed content files in each subject repo.
  - instruction: Ship the story JSON schema in the contract; starter content: >=10 stories across >=3 levels per language module, >=3 culture-guide scenarios; validate all content files against the schema in each subject's CI.
  - honesty: One story schema validates for all three subjects, and each language module ships at least a starter graded ladder (e.g. ~10 stories across 3+ levels) while culture-guide ships at least 3 narrative scenarios at launch.
- The /learn surface is served same-origin at agentculture.org/learn (never a separate subdomain or visibly separate site), sharing org's design tokens AND its cross-document view-transition navigation, so moving between org pages and learn pages never reloads the 'whole site' feel — one continuous site to the visitor.
  - instruction: Mount learn-cli's Pages output under the agentculture.org zone via Cloudflare routing (coordinated through org/cultureflare); copy org's @view-transition CSS and Layout so cross-document navigation transitions smoothly; never link /learn as an external-feeling site.
  - honesty: Navigating agentculture.org → /learn and back is same-origin, keeps the shared header/nav, and uses the same @view-transition cross-document fade org uses — verified by a navigation test and manual QA in both themes.

## Honesty conditions

- The announced walk actually works on the live site: a fresh visitor tours a module and reads a sample story; a signed-in learner runs a scored lesson and sees progress move — on phone and desktop.
- Each audience has a first-class path (web human, CLI human, MCP agent) with an acceptance test per path — none is a degraded afterthought.
- Repo-state facts re-verified at build kickoff (siblings move); the spec's before-state matches HEAD of all five repos on the day building starts.
- 'learn subjects' lists all three subjects passing the conformance gate, and a learner can start, score, repeat, and resume a lesson in each of french, spanish, and culture-guide.
- org maintainers can preview /learn as a normal Cloudflare Pages preview and sign off that it reads as one site (same tokens, fonts, nav, motion rules); the /learn nav link and directory entry land as an org PR they approve.
- Signed-out pages are fully static and make zero API or model calls (verifiable in the network log); every learner-specific element has a designed signed-out state (invitation, sample, or lock) — no broken half-empty panels.
- Adding a hypothetical 4th subject requires only: a registry entry, a conformant subject CLI, and content — zero new platform code in learn-cli; the claim is tested by keeping the registry data-driven.
- learn-cli's repo contains no subject-domain content or progression logic; deleting a subject's registry entry cleanly removes it from all three faces.
- No new fonts, palette tokens, or layout primitives are introduced on /learn beyond org's global.css system; any genuinely new component (progress ring, streak flame, story reader) is built from existing tokens and offered back to org.
- The success walk is scripted and repeatable: an end-to-end check (or documented manual QA script) covers signed-out story reading, one scored lesson per subject signed-in, and progress parity across web, 'learn' --json, and MCP — run before declaring launch.
- The subject contract spec is written once and lands in french-cli and spanish-cli as the same implementation (kept consistent the way the template siblings are), and culture-guide's teach verbs map onto it without breaking its existing users.
- Nothing in the /learn integration forces org to adopt SSR, an adapter, or a build-time dependency on learn-cli — org's static-only house style is preserved; coordination lands as reviewable org PRs + issues.
- The hosting choice is recorded with a cost-when-busy note before build: Cloudflare Pages static = free; Workers/Functions paid plan ~$5/mo + per-request beyond free tier; KV/D1 usage-priced; live tutoring tokens per-use via cloudai/ec2bedrock — and signed-out traffic can never trigger a model call.
- agentfront is consumed as a versioned dependency (>=0.20) — gaps learn-cli hits (HTTP-face auth hooks, remote MCP transport, static export) are filed as upstream agentfront issues, never forked or monkey-patched.
- The Astro pages are generated from the same registry/content files the CLI and MCP serve, and a CI check fails when a module exists in the registry without a site page (or vice versa) — coherence is enforced, not hoped for.
- Every number in the launch bar is checked by CI or the scripted launch gate — none is asserted by hand.

## Success signals

- A signed-out visitor reads a sample story and the module tour on agentculture.org/learn; a signed-in learner completes a scored lesson in each of the three subjects from the web, sees their streak/score/what-next update, and the identical progress is readable via 'learn' --json and the MCP tools.
  - instruction: Script the success walk as the launch gate: signed-out story read; one scored lesson per subject signed-in; assert progress parity across web, 'learn' --json, and MCP. Run it before announcing.
- Measurable launch bar (quantifying the confirmed walk): all 3 subjects pass 'learn subject doctor'; >=10 stories x >=3 levels per language module and >=3 culture-guide scenarios ship; the signed-out /learn pages make exactly 0 API/model calls; the E2E success walk passes with progress parity across all 3 faces; /learn page styling introduces 0 new design tokens beyond org's system.
  - instruction: Wire each measurable into automation: conformance in subject CIs; content counts via schema validation; zero-API static check via network-log test; the E2E walk as the launch gate script; token audit via CSS diff against org's global.css.

## Scope / boundaries

- learn-cli hosts and unifies; it does not reimplement tutor logic — progression, lesson content, and subject expertise stay in each subject repo, driven as external runtimes.
  - instruction: Enforce in review: learn-cli never gains subject content or progression logic; subjects are driven only through the subprocess --json contract; deleting a registry entry removes a subject from all faces.
- org's existing elegant design is kept, not redesigned: /learn adopts org's layout, typography, and theme; any new components extend that system rather than fork it.
  - instruction: Copy org's global.css, Layout, and components verbatim into learn-cli/site-astro; extend only with existing tokens; new learning components (progress ring, streak, story reader) reuse the token system and get offered upstream to org; visual QA in both themes.

## Assumptions

- culture-guide's 'teach' directive pattern (the subject CLI stores curriculum + per-learner mastery state and emits a structured teaching directive; the driving agent/LLM does the conversational tutoring and records results back) is a viable spine for the subject-plugin contract — subjects stay LLM-free engines, tutoring intelligence lives in the driver.

## Decisions

- Per the brief, the three faces (CLI 'learn', MCP server, web) derive from one agentfront registry rather than three hand-rolled renderers, so the human page, the agent tool, and the --json answer cannot drift.
- Because french/spanish are empty, the tutor verb surface is DESIGNED FRESH in the subject-plugin contract — canonical verbs: overview, progress, advice, story (list/read), lesson (start/next/repeat), practice, record, doctor — and implemented from one shared spec in french-cli and spanish-cli (kept byte-consistent like siblings), while culture-guide maps its existing teach subverbs onto the same contract.
- Web face shape: learn-cli gets its own site-astro/ (the org/culture-tools house repo shape), copying org's design system verbatim (global.css tokens, Layout, Header/Footer/PageHero/Mark components, both fonts) so /learn is visually indistinguishable from the rest of agentculture.org; it deploys as learn-cli's own Cloudflare Pages project, and is mounted at agentculture.org/learn via Cloudflare routing — coordinated with org (nav link + directory entry pointing to /learn/) and the cultureflare-owned zone, negotiated through GitHub issues.
- Sign-in is the resource gate (the 'since this requires resources' rationale made explicit): signed-out visitors get only pre-built static content — subject catalog, module sub-pages, sample stories, the tour — which costs nothing to serve; LLM-backed live tutoring, progress/score writes, streaks, and adaptive what-next require a signed-in session backed by the learn API.
- The dynamic layer stays thin and Cloudflare-native: a small learn API (Cloudflare Pages Functions/Worker + KV/D1 for learner state) handles auth sessions, progress reads/writes, and brokers lesson/story generation to the model-access sibling; the static shell stays org-house-style, with signed-in panels hydrating client-side.
- The web face splits by consumer, both fed from one registry: agentfront's HTTP face is the agent-readable web (markdown, sitemap, llms.txt); the human web is the Astro static site rendering the SAME registry-sourced content through org's design. A build step ('learn site export' → typed content JSON/markdown consumed by site-astro) plus an extended surfaces-agreement test keep the human pages from drifting — honoring the brief's one-registry rule without asking agentfront to render HTML.
- Model access and cost shape: story/lesson content is pre-generated in batch through cloudai-cli (or ec2bedrock-cli), human-reviewed, and COMMITTED to each subject repo as content files — so the static site and signed-out visitors cost ~zero to serve; only signed-in interactive tutoring (live conversation, grading, generation of fresh personal content) makes live model calls, brokered by the learn API through the same siblings. No bespoke provider client anywhere.
- Learner identity across faces: 'learn auth login' (device-code flow) links the CLI and MCP to the same learner account the web uses; local XDG state acts as an offline cache that syncs through the learn API. Anonymous CLI/MCP use stays local-only and fully functional — sign-in adds cross-device sync, streak continuity, and the web dashboard.
- Identity provider recommendation: GitHub OAuth as the v1 sign-in (the audience is developers and agents; the mesh is GitHub-native; no passwords/PII stored — only the GitHub id, display name, and learner state), implemented in the learn API worker with short-lived session cookies. Email magic-link can be added later; mesh-identity federation is a follow-up.

## Open / follow-up

- Spoken practice (TTS/STT) — french/spanish's 'written and spoken' promise needs an audio pipeline and per-minute cost; defer to a follow-up phase, with the story schema's audio slot reserved.
- culture.dev cross-link via katvan once /learn is live (the brief's offer) — file the cross-link issue at launch.
