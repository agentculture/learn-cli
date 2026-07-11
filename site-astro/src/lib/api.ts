// The single source of truth for the learn API's base URL — imported by
// both server-rendered Astro components (the static, no-JS "Sign in" href
// in Header.astro) and the client-side hydration module
// (src/scripts/learner.js), so there is exactly one place to repoint this
// site at a different API host (a local `wrangler dev` origin, a preview
// deployment, a future dedicated API subdomain, ...).
//
// Production default: same-origin, path-based. workers/learn-api is meant
// to be mounted at agentculture.org/learn/api/* right alongside the static
// Pages site at agentculture.org/learn/* (see workers/learn-api/README.md
// and this site's README.md "Auth" section) — so the API and the page that
// calls it always share an origin and `fetch(..., {credentials:"include"})`
// cookies just work, no CORS preflight games.
//
// This is an ABSOLUTE, domain-root-relative path — unlike the rest of this
// site's page links, which are relative-to-page-depth on purpose (see
// README.md "Base path and relative links"). The API's mount point doesn't
// move with page depth the way `stories/${id}/` does, so a fixed path is
// the correct choice here, not a bug.
export const API_BASE = "/learn/api";
