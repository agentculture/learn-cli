// Identity content for learn-cli's web face. Deliberately thin — unlike
// org/site-astro's src/data/site.ts (which is the *entire* content model for
// agentculture.org), the actual lesson/story content here comes from
// ../content-export/ (the pinned export format a sibling task's `learn site
// export` emits; see src/lib/content.ts). This file only carries the
// identity strings shared by <title>/<meta> tags and the header wordmark.

export interface LearnSiteData {
  /** The org-level brand name shown in the header wordmark ("AgentCulture"). */
  orgTitle: string;
  /** This sub-site's own name, shown after the wordmark separator. */
  title: string;
  /** Sub-line: what learn-cli is, in one breath. */
  tagline: string;
  /** 1-3 short paragraphs answering "what is this" for the landing hero. */
  intro: string[];
}

const site: LearnSiteData = {
  orgTitle: "AgentCulture",
  title: "Learn",
  tagline:
    "Humans and agents learn a subject, step by step — one door in front of French, Spanish, and Culture Guide.",
  intro: [
    "Learn is the front for AgentCulture's tutor CLIs: pick a subject, read a story, practice, and keep a streak — the same content whether you're a human on the web or an agent driving the CLI.",
    "Each subject stays its own sibling project with its own progression logic — french-cli, spanish-cli, culture-guide — and Learn hosts them behind one door, one profile, one site.",
  ],
};

export default site;
