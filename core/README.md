# Core

Canonical home for organization-agnostic research semantics, validation, workflow, provenance, and versioned interface contracts.

- [`models/research-object.schema.json`](models/research-object.schema.json) — canonical research-object semantic floor.
- [`validators/non-overridable-invariants.yaml`](validators/non-overridable-invariants.yaml) — hard invariants Profiles, Projects, plugins, skills, and implementations may not weaken.
- [`packages/`](packages/) — common Research Capability Descriptor, bounded Context Pack, Invocation, Handoff, provenance, and adoption-boundary contracts established by PR 9.

Core owns shared meaning and cross-component boundaries. It does not own concrete Capability adapters, storage, SQLite/export/publish, or Writer/Publication implementations.
