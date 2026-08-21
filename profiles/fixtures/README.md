# Profile contract fixtures

These fixtures exercise the PR 4 contract only. They are intentionally synthetic and are **not** concrete MISCO, research-quality, narrative, or publication Profiles.

## Valid

- `research-base.profile.json` — base Research Profile with a commutative set constraint.
- `research-strict.profile.json` — same-type `extends` plus an explicit Core-invariant strengthening.
- `organization.profile.json` — cross-type `requires` without override precedence.
- `narrative.profile.json` — independent Narrative Profile.
- `publication.profile.json` — Publication Profile requiring an Organization Profile.
- `effective-profile-set.json` — expected dependency-closed result with `effective_constraints` and provenance.

Every valid `*.profile.json` conforms to `../contracts/profile-manifest.schema.json`; the effective fixture conforms to `../contracts/effective-profile-set.schema.json`.

## Invalid

- `cross-type-extends.profile.json` — schema-invalid because `organization` attempts to `extends` a `research` Profile. Use `requires` for this relationship.
- `core-invariant-weakening.profile.json` — schema-invalid because `effect` is `weaken`; only `strengthen` exists in the contract.
- `incompatible-core.profile.json` — schema-valid in isolation, but composition with Core `0.1.0` fails `PROFILE-CORE-COMPAT-001` because its compatibility range starts at `0.2.0`.
- `ambiguous-cross-category-conflict/` — both Profile manifests are schema-valid individually, but composition must fail because unrelated categories declare different `replace` values for the same path. No last-write-wins behavior is permitted.

The fixtures specify contract behavior; they do not require or prescribe a runtime resolver implementation in PR 4.
