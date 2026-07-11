# Subjects catalog

The subjects learn-cli hosts. This set is pure registry data (`learn/subjects/registry.json`, overridable via `LEARN_SUBJECTS_REGISTRY`); adding a subject is a data entry plus a conformant CLI, and deleting the entry removes it from every face. Install status is intentionally omitted here (it is environment-dependent) — query it live with `learn subjects`.

## French (`french`)

Written and spoken French through graded stories, from A1 upward.

- Repo: https://github.com/agentculture/french-cli
- Driven as: `french <verb> --json`
- Contract: 1.0

## Spanish (`spanish`)

Spanish for real conversations through graded stories, from A1 upward.

- Repo: https://github.com/agentculture/spanish-cli
- Driven as: `spanish <verb> --json`
- Contract: 1.0

## Culture Guide (`culture-guide`)

Learning to build and lead teams of agents — the non-language proof the subject interface generalizes.

- Repo: https://github.com/agentculture/culture-guide
- Driven as: `culture-guide subject <verb> --json`
- Contract: 1.0
