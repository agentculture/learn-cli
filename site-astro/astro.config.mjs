// @ts-check
import { defineConfig } from 'astro/config';

// https://astro.build/config
export default defineConfig({
  site: 'https://agentculture.org',
  // learn-cli's web face is served under the /learn path prefix (org owns
  // the domain root; see ../CLAUDE.md "The web face"). `base` keeps Astro's
  // own bookkeeping (canonical URLs, `import.meta.env.BASE_URL`) honest, but
  // every internal link in this site is written as a *relative* path (see
  // src/lib/paths.ts) rather than base-prefixed, so the same dist/ works
  // unmodified whether it's served at a Cloudflare Pages preview domain root
  // (…agentculture-learn.pages.dev/) or nested at agentculture.org/learn/ —
  // neither case is decided yet (org integration is a separate task); see
  // README.md for the routing note.
  base: '/learn',
  // Pure static output — no adapter, no SSR. `astro build` emits a static
  // dist/ deployable as-is (Cloudflare Pages, matching org/site-astro).
  output: 'static',
});
