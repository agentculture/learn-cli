# learn-cli site (site-astro/)

The static web face of learn-cli — the `/learn/` landing page, one sub-page
per subject, and a story reader per story — served at
`agentculture.org/learn` (see the repo root [`CLAUDE.md`](../CLAUDE.md), "The
web face"). It copies
[`org/site-astro`](https://github.com/agentculture/org)'s design system
verbatim (tokens, `Layout`, `Header`/`Footer`/`PageHero`/`Mark`, both fonts) so
this reads as the *same site* as the rest of agentculture.org, not a
differently-themed satellite.

Everything here is still `output: 'static'`, no adapter, no hydration
framework — but signed-in panels (progress, streaks, adaptive next lesson,
practice-checking) now hydrate client-side after a session check against
[`workers/learn-api`](../workers/learn-api/), through exactly one small JS
module (`src/scripts/learner.js`). See "Auth: the signed-out/signed-in
split" below.

## Commands

```bash
npm install         # install deps (astro, the two @fontsource-variable fonts)
npm run dev          # local dev server
npm run build         # astro build -> dist/
npm run check         # export/page consistency + the zero-API static-auth gate (run after build)
npm run check:pages   # just the export/page consistency check
npm run check:static-auth  # just the zero-API static-auth gate (alias: npm run test:static)
npm run preview       # serve the built dist/ locally
```

CI (`.github/workflows/deploy-site.yml`) runs `npm ci`, `npm run build`,
`npm run check`, then deploys `dist/` to Cloudflare Pages with
`npx wrangler@4 pages deploy` — gated on the `CLOUDFLARE_API_TOKEN` /
`CLOUDFLARE_ACCOUNT_ID` secrets being configured (a token-less run still
builds and checks, so PRs stay green before the secrets exist). Pushes to
`main` deploy to the **production** branch of the `agentculture-learn`
Cloudflare Pages project; any other branch/PR deploys a **preview** alias.
`agentculture-learn` is a new project, separate from org's
`agentculture-org` one.

## Content: the pinned export format

`src/content-export/` holds the input this site builds pages from:

```text
meta.json                  {"contract_version","schema_version","subjects":[...]}
subjects.json               [{"name","display_name","description","repo","available","modules":[{"id","title","summary","lessons"}]}]
stories-<subject>.json      {"subject":"...","stories":[<full story objects>]}
```

Today these are **fixtures authored from the real merged content** (the
`fr-*`/`es-*`/`cg-*` stories in french-cli, spanish-cli, and culture-guide's
`content/stories/`, plus french-cli's and culture-guide's curriculum
modules) — hand-built to the shape a sibling task ("`learn site export`") is
building to emit for real. When that CLI verb lands, replace the fixture
files with its generated output; `src/lib/content.ts` (the typed loader every
page imports through) and the page templates should not need to change, only
the JSON.

Two content notes for whoever wires up the real exporter (also written as
comments in `src/lib/content.ts`):

- **`modules[].lessons`** means different things per subject today: french's
  curriculum groups items into `Lesson`s, so it's the Lesson count (2, 2, 1).
  culture-guide's curriculum has no lesson grouping, only `Concept`s directly
  on a `Part`, so it's the Concept count instead (10, 6, 5, 10, 4). Neither is
  wrong, but they're not the same unit — the real exporter should either pick
  one canonical meaning or add a field that says which.
- **spanish has `available: false`** and no modules: it has 11 real,
  committed stories but no curriculum/tutor content yet (spanish-cli's own
  README says the domain "is not built"). Its subject page and story ladder
  still render — the stories are real — just with no module list and a note
  that structured lessons aren't there yet.

`dev-*`-prefixed files in french-cli's `content/stories/` were excluded from
the fixture as scaffolding/dev fixtures, not the subject's real story set
(hence 11 french stories here, not 14).

## The consistency check

`scripts/check-export-pages.mjs` loads `src/content-export/` and the built
`dist/`, and fails (nonzero exit) if:

- a subject has no `dist/<subject>/index.html` page,
- a subject's module doesn't appear anywhere on that subject's page,
- a story has no `dist/<subject>/stories/<id>/index.html` reader page,
- or the reverse — `dist/` has a subject or story directory nothing in the
  export backs (an orphan page).

Run it locally with `npm run check` *after* `npm run build` (it does not
build for you). It's wired into `deploy-site.yml` right after the build step,
before the Cloudflare deploy.

## Auth: the signed-out/signed-in split

The resource gate (spec c21/c22, mirrored in
[`workers/learn-api/README.md`](../workers/learn-api/README.md)'s own
invariant): **signed-out visitors get a pure static site — zero calls to the
learn API, and therefore zero model calls** (the only route that spends
inference tokens, `POST /api/tutor`, is never referenced by this site at
all). Signed-in visitors get personal panels — progress, a streak-ish "last
active" chip, an adaptive next-lesson pointer, and per-exercise result
recording — hydrated client-side after a session check.

### API base

`src/lib/api.ts` exports one constant, `API_BASE`, imported everywhere this
site talks to the API (both the static "Sign in" href in `Header.astro` and
every `fetch()` in `src/scripts/learner.js`) — the single place to repoint
this site at a different API origin. Default: `/learn/api`, a same-origin,
domain-root-relative path (deliberately *not* relative-to-page-depth like
this site's other internal links — see "Base path and relative links"
below) — production mounts `workers/learn-api` at
`agentculture.org/learn/api/*`, right alongside the static Pages site at
`agentculture.org/learn/*`, so cookies (`fetch(..., {credentials:
"include"})`) work same-origin with no CORS preflight. The Worker still
needs `CORS_ORIGIN` set (see its README) for any deployment where the site
and the API *don't* share an origin (e.g. a Pages preview domain calling a
`workers.dev` API host during early rollout, or local `wrangler dev`) —
`API_BASE` and `CORS_ORIGIN` are two ends of the same knob and must agree.

### The `data-auth` pattern

`src/scripts/learner.js` is the one piece of client-side JS beyond org's
inline scroll-reveal helper, loaded on every page via a `<script>` import in
`Layout.astro` (bundled by Vite like the fonts/CSS already are — no
relative-path bookkeeping needed, unlike page-to-page links). It calls
`GET /api/me` exactly once:

- **401 or any network error** → stamps `data-auth="out"` on `<html>` and
  stops. No further request of any kind fires.
- **200** → stamps `data-auth="in"`, fills every `[data-auth-name]` element
  with the learner's display name, wires "Sign out" buttons
  (`POST /api/auth/logout`), and only *then* fetches
  `GET /api/progress/:subject` for each learner panel on the page and wires
  the story reader's per-exercise recording buttons (`POST /api/record`).

Every signed-in-only element carries the `signedin-only` class, which
`global.css` hides by an unconditional `display: none` — the default, no-JS
state. Each component that uses it (`Header.astro`'s signed-in slot,
`LearnerPanelSubject.astro`/`LearnerPanelOverview.astro`'s hydrated view, the
story reader's `.record` buttons) pairs it with its own
`html[data-auth="in"] .signedin-only { display: ...; }` /
`html[data-auth="in"] .signedout-only { display: none; }` override — the
"shown" value is context-specific (inline-flex for a header slot, block for
a card), so there's no single generic "shown" rule to centralize.
Consequence: **the built static HTML never contains a `data-auth` attribute
at all** — it only appears inside compiled `<style>` selectors — so a no-JS
visit and a "checked, and you're signed out" visit render byte-for-byte the
same signed-out markup, satisfying "default (no-JS, pre-hydration) shows the
signed-out variant."

Every learner-specific element has a designed signed-out state — never a
broken half-empty panel:

- **Header** — a quiet "Sign in" link (a real, working anchor to
  `${API_BASE}/auth/login`, functional with zero JS) vs. display name +
  "Sign out".
- **`LearnerPanelOverview.astro`** (landing page) / **`LearnerPanelSubject.astro`**
  (subject pages) — one `.card` in both states, so there's no dramatic
  reflow: signed-out renders an invitation ("Sign in to track progress,
  streaks, and get your next lesson" + what you get); signed-in renders
  mastered/touched counts, a progress bar, a "last active" chip, and the
  subject's own next-step recommendation (`next.text` + `next.command`).
  Within the signed-in view there's a second-order empty state too (`hidden`
  by default) for a signed-in learner who hasn't recorded anything yet.
- **Story reader exercises** — the signed-out CTA line t13 left ("Practice
  with the CLI ... or sign in") stays exactly as before, now wrapped in
  `signedout-only`; signed-in swaps in pass/partial/fail recording buttons
  per exercise (only for exercises with an `item_id` — required by the
  `record.json` contract) that POST optimistically and report a quiet
  inline status on both success and failure, never a blocking dialog.

Two honesty notes worth knowing before touching these panels (documented
at length in `LearnerPanelSubject.astro`'s header comment):

- **"Mastered"/"touched" are ledger coverage, not curriculum totals.**
  `GET /api/progress/:subject`'s `items_total`/`items_touched` count items
  *this learner has recorded a result for*, not the subject's full
  curriculum size (workers/learn-api's own README says so explicitly) — so
  these panels only ever say "N mastered of M touched," never "N of the
  subject's Y items."
- **There is no real streak count to show.** The motivation layer's
  day-based `Streak` (`learn/motivation/_streaks.py` — current/longest
  days, `active_today`) is Python-only, computed from the *local* ledger;
  `workers/learn-api`'s `deriveProgress()` does not compute or expose it,
  only `last_seen_at`. Rather than inventing a number the API can't back,
  the "streak chip" shows an honest "Active today" / "Active yesterday" /
  "Last active N days ago" derived from that timestamp. If a future API wave
  adds a real `streak` field to the progress payload, `learner.js`'s
  `hydrateSubjectPanel`/`hydrateOverviewPanel` are the only two places that
  would need to read it.

### The zero-API static-auth test

`scripts/check-static-auth.mjs` (`npm run check:static-auth`, alias
`npm run test:static`, and part of the default `npm run check`) is the
automated proof, not just an assertion, that a signed-out visit makes zero
API calls and every page is servable as plain static files. It reads the
already-built `dist/` and `src/scripts/learner.js` (no server, no browser,
no third-party parser — plain `node:fs`/`node:assert`, matching this repo's
and `workers/learn-api`'s own zero-dependency test style) and checks:

1. **Static build** — `astro.config.mjs` still says `output: "static"`, and
   no `@astrojs/*` SSR adapter has snuck into `package.json`.
2. **No-JS default markup** — no built page's raw `<html>` tag carries a
   `data-auth` attribute; the compiled CSS actually hides `.signedin-only`
   by an unconditional `display: none` (the mechanism, not just the intent);
   every page renders its signed-out invitation copy unconditionally; the
   story reader's signed-out CTA note never carries a `hidden` attribute.
3. **Fetch whitelist + auth-gating** — every `fetch()` call in
   `learner.js` targets `${API_BASE}` plus one of `/me`, `/progress/`,
   `/record`, `/auth/*`; `bootstrap()`'s own body contains *exactly one*
   `fetch()` call (the `/api/me` bootstrap), and every further-reaching call
   (`hydratePanels`, `wireExerciseRecorders`, `wireSignOut`) is lexically
   positioned after the point where `setAuthState("in")` has already run —
   found via balanced-brace extraction of `bootstrap()`'s body against the
   *source*, since minification would otherwise scramble line/brace
   assumptions. As a defense-in-depth pass, the *built* JS bundle is then
   re-checked the same way, discovering whatever identifier the minifier
   aliased `API_BASE`'s literal value to (the minified source never spells
   out `/api/me` as one contiguous string — only `${aliasedVar}/me`) and
   re-validating the whitelist against that. Nothing in `src/` or the built
   `dist/` ever references `/tutor` at all.

Run `npm run build` first — this test does not build for you (same
convention as `check-export-pages.mjs`).

## Base path and relative links

`astro.config.mjs` sets `site: 'https://agentculture.org'` and
`base: '/learn'`, matching where this site is meant to live. But **every
hand-written internal link in the page templates and in `Header`/`Footer` is
a relative path** (`stories/${id}/`, `../`, `../../../`, …), computed per page
depth and passed down through `Layout`'s `homeHref` prop — not a
`base`-prefixed absolute path. That part of the site doesn't care where in
the URL tree it's mounted; the same relative links resolve correctly however
deep the site's root sits.

Astro's *own* generated asset links (the bundled per-page CSS, the two
preloaded font files) are **not** relative — `astro build` always emits them
as absolute, base-prefixed hrefs (`/learn/_astro/xxx.css`), because `base` is
meant for exactly this. The catch: `astro build`'s physical `dist/` tree
stays flat regardless of `base` (`dist/_astro/xxx.css`, no `dist/learn/`
nesting) — only Astro's own `astro dev`/`astro preview` server understands
`base` and rewrites around that mismatch. A plain static host doesn't, and
Cloudflare Pages is a plain static host: it maps a request path straight onto
`dist/`'s physical layout. Requesting `/learn/_astro/xxx.css` against an
unwrapped `dist/` 404s (verified locally with `python3 -m http.server` on the
built output — no Astro server in front of it).

The fix lives in `.github/workflows/deploy-site.yml`, not in the site code:
right before the Cloudflare deploy, a "Prepare deploy directory" step copies
`site-astro/dist/` into `site-astro/dist-deploy/learn/` (plus a
`_redirects` sending the bare root to `/learn/`), and it's that
`dist-deploy/` directory wrangler uploads. That makes the deployed tree's
*physical* layout match Astro's base-prefixed asset hrefs — which also means
the Pages preview domain serves the site at
`<branch>.agentculture-learn.pages.dev/learn/`, not its bare root. Preview
and the eventual `agentculture.org/learn/` production mount share the exact
same URL shape as a result, so nothing here needs to change once the
production routing decision (still open — see "Notes for later waves" below)
lands. `npm run build` / `npm run check` / `npm run preview` all keep working
against the plain, unwrapped `dist/` — only the CI deploy step wraps it.

## Design system provenance

Copied verbatim from `org/site-astro` (byte-identical unless noted):

- `src/styles/global.css` — unmodified.
- `src/components/Mark.astro`, `src/components/PageHero.astro` — unmodified.
- `src/components/Header.astro`, `src/components/Footer.astro` — same
  classes/tokens, adapted nav: the org wordmark always links to
  `https://agentculture.org/` (leaving this sub-site), a second "Learn"
  wordmark segment plus a "Subjects" nav item link back to this site's own
  landing page (relative, via `homeHref`), and `Framework`/`Agents`/`Engage`
  point at the corresponding absolute `https://agentculture.org/...` pages
  rather than local routes. `org`'s home-page-only `HeroMesh` component was
  not copied — it's org's homepage centerpiece and didn't fit the `/learn`
  landing's own hero (a subject catalog, not a mesh diagram); reuse it later
  if a future redesign wants it. `Header.astro` also carries t14's auth slot
  (a "Sign in" link / display-name-plus-sign-out toggle) — org's own header
  has no equivalent, so this is a learn-cli-only addition, still built
  entirely from existing tokens (see "Auth" above).
- `package.json` deps (`astro` `7.0.7`, both `@fontsource-variable/*`
  packages), `.nvmrc` (Node 24), `tsconfig.json` — unmodified versions/pins.
- `astro.config.mjs` — same `output: 'static'`, no adapter; `site` matches,
  `base` added (org's own site has no base since it lives at the domain
  root).

No new CSS custom properties were introduced anywhere in this site — every
component here, including t14's additions (`LearnerPanelSubject.astro`,
`LearnerPanelOverview.astro`, `Header.astro`'s auth slot, the story reader's
`.record` buttons), only reads existing `global.css` tokens (`--ink`,
`--ink-soft`, `--accent`, `--accent-strong`, `--on-accent`, `--surface`,
`--line`, `--line-soft`, `--radius`, `--shadow`, `--section-pad`,
`--font-display`, `--font-body`, `--ease-out`, …) plus the
`.card`/`.container`/`.prose`/`.section`/`.lede`/`.muted`/`.eyebrow`
primitives and the `[data-reveal]` scroll-reveal convention. The one shared
addition to `global.css` itself is the `.signedin-only { display: none; }`
default (see "Auth" above) — a visibility primitive, not a new token.

## Notes for later waves

- **t14 (signed-in hydration) — done:** the signed-out/signed-in split
  described in "Auth" above is built: `learner.js`'s `/api/me` bootstrap,
  the `data-auth` CSS pattern, hydrated progress/streak/next-lesson panels
  on the landing and subject pages, and per-exercise result recording on
  the story reader. `npm run check` (which now also runs
  `check-static-auth.mjs`) and `npm run build` are green.
- **For t16 (E2E):** exercising the signed-in path end-to-end needs a real
  or stubbed `workers/learn-api` reachable at `API_BASE` (`/learn/api` by
  default — see "Auth" above) with `CORS_ORIGIN` covering wherever the site
  is served from during the test, and a way to seed a `session` cookie (or
  drive the real GitHub OAuth flow via `GET /api/auth/login`). Useful DOM
  hooks: `html[data-auth]` for "which state did it land in," `[data-learner-panel]`
  (value `"overview"` on the landing page, the subject `name` on subject
  pages) for panel hydration, `[data-record]`/`button[data-result]` +
  `[data-record-status]` for the story-exercise recorder, and
  `[data-sign-out]` for sign-out. `check-static-auth.mjs` already proves the
  signed-out path in isolation (no server needed); an E2E pass is the
  complementary proof that the signed-in path actually round-trips against
  a live API.
- **t15 (org integration):** the routing decision above (`agentculture.org/learn/*`
  → this Pages project) is unresolved by design; this site's relative-link
  approach means it doesn't need to change once that's decided, but the org
  side (DNS/Worker/route config) still needs to point at
  `agentculture-learn`'s Pages deployment. The same applies to t14's auth
  split: `API_BASE`'s same-origin default (`/learn/api`, in
  `src/lib/api.ts`) assumes `workers/learn-api` ends up mounted at
  `agentculture.org/learn/api/*` right alongside this Pages site, whatever
  the final routing mechanism turns out to be. If the API instead ends up on
  a separate origin, two things need to change together: `API_BASE` here,
  and `CORS_ORIGIN` on the Worker (see `workers/learn-api/README.md`) — two
  ends of the same knob.
