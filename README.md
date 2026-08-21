# research-loom

`research-loom` is a monorepo for a reusable research harness, composable research profiles, writing/publication skills, organization-specific plugins, and project configuration.

## Repository status

The repository is currently in a staged convergence process:

1. **PR 1 — legacy baseline:** imported the two pre-existing implementations unchanged.
2. **PR 2 — target structure:** establishes the canonical monorepo boundaries without moving or reconciling legacy content.
3. **Later PRs — convergence:** migrate and reconcile contracts, models, profiles, skills, publication assets, and runtime behavior incrementally.

The legacy directories remain intentionally untouched during PR 2:

- `research-harness/` — legacy Research Harness implementation
- `research-profile/` — legacy Research Profile implementation

New work should converge toward the target areas below rather than adding new cross-cutting concepts to either legacy tree.

## Target areas

- `core/` — generic research domain, provenance, workflow, validation, and package contracts
- `profiles/` — declarative research, organization, narrative, and publication profiles
- `plugins/` — imperative integration and organization-specific extension code
- `skills/` — writer and publication workflows that consume versioned packages/contracts
- `projects/` — project-specific configuration, inputs, and artifacts

See [`docs/architecture/monorepo-structure.md`](docs/architecture/monorepo-structure.md) for ownership boundaries, dependency direction, and migration rules.
