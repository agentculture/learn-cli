# learn-cli — the learning portal

learn-cli is the **learning front** for the AgentCulture mesh: one product with
three faces over a single registry — a **CLI** (`learn`), an **MCP server**, and
an agent-readable **HTTP site** — so humans and agents learn a subject, step by
step. It is **not a tutor**. It is the portal that fronts per-subject tutor CLIs
(`french`, `spanish`, `culture-guide`), driving them as external subprocesses
over `--json`; it never imports subject code and holds no subject content.

## The three faces, one registry

All three faces are derived from one `agentfront.App` (see `learn.front`), so the
human page, the agent's MCP tool, and the `--json` answer cannot drift:

- **CLI** — `learn subjects`, `learn subject doctor <name>`, plus `learn mcp
  serve`, `learn site serve`, and `learn site export`.
- **MCP** — `learn mcp serve` runs a single-dispatch `run` tool over stdio whose
  catalog is every tool below, so an agent can drive a full learning loop.
- **HTTP** — `learn site serve` serves these docs as markdown (`/<slug>`,
  `/sitemap.xml`, `/llms.txt`, `/front`); `learn site export` writes a static
  content bundle the site build consumes.

## Tools (the learning loop)

`subjects_list`, `subject_doctor`, `story_list`, `story_read`, `progress`,
`advice`, `lesson_next`, `practice`, `record` — each drives the matching subject
contract verb. `record` is the write-back that closes the loop and feeds
learn-cli's motivation layer (scores, streaks, review queues).

## Exit-code policy

`0` success · `1` user error · `2` environment error (e.g. a subject not
installed) · `3+` reserved. Every command supports `--json`; results go to
stdout, errors/diagnostics to stderr, never mixed.

## See also

- `subject-plugin-contract` — the interface a subject CLI must satisfy.
- `subjects` — the catalog of registered subjects.
