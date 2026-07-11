# learn-cli site (site-astro/)

The static web face of learn-cli — the `/learn/` landing page, one sub-page
per subject, and a story reader per story — served at
`agentculture.org/learn` (see the repo root [`CLAUDE.md`](../CLAUDE.md), "The
web face"). It copies
[`org/site-astro`](https://github.com/agentculture/org)'s design system
verbatim (tokens, `Layout`, `Header`/`Footer`/`PageHero`/`Mark`, both fonts) so
this reads as the *same site* as the rest of agentculture.org, not a
differently-themed satellite.

Signed-in panels (progress, streaks, practice-checking) are a later wave —
everything here is `output: 'static'`, no adapter, no client JS beyond the
inline scroll-reveal script org already ships.

## Commands

```bash
npm install        # install deps (astro, the two @fontsource-variable fonts)
npm run dev         # local dev server
npm run build        # astro build -> dist/
npm run check        # verify dist/ matches src/content-export/ (run after build)
npm run preview      # serve the built dist/ locally
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
  if a future redesign wants it.
- `package.json` deps (`astro` `7.0.7`, both `@fontsource-variable/*`
  packages), `.nvmrc` (Node 24), `tsconfig.json` — unmodified versions/pins.
- `astro.config.mjs` — same `output: 'static'`, no adapter; `site` matches,
  `base` added (org's own site has no base since it lives at the domain
  root).

No new CSS custom properties were introduced anywhere in this site — every
component here (`index.astro`, `[subject]/index.astro`,
`[subject]/stories/[id]/index.astro`) only reads existing `global.css` tokens
(`--ink`, `--ink-soft`, `--accent`, `--surface`, `--line`, `--radius`,
`--shadow`, `--section-pad`, `--font-display`, `--font-body`, …) plus the
`.card`/`.container`/`.prose`/`.section`/`.lede`/`.muted`/`.eyebrow`
primitives and the `[data-reveal]` scroll-reveal convention.

## Notes for later waves

- **t14 (signed-in hydration):** every page here is fully static; there's no
  client JS to hook into beyond org's inline reveal script. Exercises render
  as a static preview (prompt + choices, no `<form>`/`<input>`) with a line
  pointing at the CLI or a future sign-in — that's the seam to build on.
- **t15 (org integration):** the routing decision above (`agentculture.org/learn/*`
  → this Pages project) is unresolved by design; this site's relative-link
  approach means it doesn't need to change once that's decided, but the org
  side (DNS/Worker/route config) still needs to point at
  `agentculture-learn`'s Pages deployment.
