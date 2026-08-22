# Profiles

Declarative, composable policy separated by concern:

- `research/` — methodology and research-quality rules
- `organization/` — organization/domain constraints and terminology
- `narrative/` — argument and semantic composition patterns
- `publication/` — output, citation, template, rendering, and release rules

PR 4 establishes the implementation-neutral Profile-system contracts while keeping concrete profiles deferred:

- [`contracts/profile-manifest.schema.json`](contracts/profile-manifest.schema.json) — common Profile envelope, versioning, Core compatibility, `extends`, `requires`, constraints, and invariant strengthenings
- [`contracts/composition-semantics.yaml`](contracts/composition-semantics.yaml) — deterministic composition and hard-conflict semantics
- [`contracts/effective-profile-set.schema.json`](contracts/effective-profile-set.schema.json) — resolved `effective_profiles` / `effective_constraints` with provenance
- [`fixtures/`](fixtures/) — synthetic valid/invalid contract fixtures
- [`../docs/architecture/profile-contract-convergence.md`](../docs/architecture/profile-contract-convergence.md) — legacy/inventory comparison and convergence decisions

`extends` is same-profile-type inheritance. Cross-type dependencies use `requires`; `requires` never creates override precedence. Cross-category last-write-wins is forbidden: ambiguous collisions are errors.

Core non-overridable invariants remain the semantic floor. Profiles may preserve or explicitly strengthen them but may not disable, weaken, reinterpret, or replace them.

Concrete MISCO profiles, concrete research-quality/source-quality rules, Project Config, Writer/Publication behavior, persistence/export/publish behavior, and a runtime resolver remain outside this convergence step.
