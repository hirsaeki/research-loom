# research-loom

`research-loom` is a monorepo for a reusable research harness, composable research profiles, writing/publication skills, organization-specific plugins, and project configuration.

## Repository status

The canonical production path has converged through PR26: Core research semantics and Profiles/Project Config, Capability ABI and Research Method contracts, Desktop Research external execution, lineage/recovery, production State transitions and SQLite persistence, execution/artifact/resource persistence, Work Conversation coordination, and the Human Decision Gate with atomic Decision-bound commits are connected end to end.

PR27 adds the production-local operator boundary: fresh local workspace bootstrap/reopen, exact Project Config + Effective Profile Set binding, a transport-neutral application facade, and a machine-oriented JSON CLI. ChatGPT Desktop App Work is the first intended human-facing consumer, but Work/ChatGPT semantics are not part of the Harness itself.

The legacy directories remain reference material only:

- `research-harness/` — legacy Research Harness implementation
- `research-profile/` — legacy Research Profile implementation

New work should converge toward the canonical areas below rather than adding new cross-cutting concepts to either legacy tree.

## Target areas

- `core/` — generic research domain, provenance, workflow, validation, and package contracts
- `profiles/` — declarative research, organization, narrative, and publication profiles
- `plugins/` — imperative integration and organization-specific extension code
- `skills/` — writer and publication workflows that consume versioned packages/contracts
- `projects/` — project-specific configuration, inputs, and artifacts

See [`docs/architecture/monorepo-structure.md`](docs/architecture/monorepo-structure.md) for ownership boundaries and [`docs/architecture/production-local-workspace-application-cli.md`](docs/architecture/production-local-workspace-application-cli.md) for the PR27 local application boundary.
