# Core

Canonical home for organization-agnostic research semantics, services, validation, workflow, provenance, and versioned package contracts.

PR 3 begins convergence by establishing implementation-neutral research object contracts and non-overridable research invariants while leaving both legacy implementations intact.

- [`models/research-object.schema.json`](models/research-object.schema.json) — canonical research object schema
- [`validators/non-overridable-invariants.yaml`](validators/non-overridable-invariants.yaml) — hard invariants that profiles and implementations may not weaken
- [`../docs/architecture/research-contract-convergence.md`](../docs/architecture/research-contract-convergence.md) — comparison, scope decisions, and deferred concerns

Runtime models, storage, profiles, Writer/Publication package contracts, and migration of legacy callers are intentionally deferred to later PRs.
