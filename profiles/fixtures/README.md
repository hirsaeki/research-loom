# Profile contract fixtures

These fixtures exercise the PR 4 contract only. They are intentionally synthetic and are **not** concrete MISCO, research-quality, narrative, or publication Profiles.

## Valid

- `research-base.profile.json` — base Research Profile with a commutative set constraint.
- `research-strict.profile.json` — same-type `extends` plus a Core-invariant strengthening claim whose fixture semantics are intended to satisfy the required invariant-specific validation.
- `organization.profile.json` — cross-type `requires` without override precedence.
- `narrative.profile.json` — independent Narrative Profile.
- `publication.profile.json` — Publication Profile requiring an Organization Profile.
- `effective-profile-set.json` — expected dependency-closed result with `effective_constraints`, validated strengthening status, and provenance.

Every valid `*.profile.json` conforms to `../contracts/profile-manifest.schema.json`; the effective fixture conforms to `../contracts/effective-profile-set.schema.json`.

## Invalid

Schema-invalid fixtures:

- `cross-type-extends.profile.json` — `organization` attempts to `extends` a `research` Profile. Use `requires` for this relationship.
- `core-invariant-weakening.profile.json` — `effect` is `weaken`; only `strengthen` exists in the contract.
- `merge-strategy-value-type.profile.json` — `union` is given a scalar instead of a set-like array.
- `effective-profile-set-status-provenance.json` — `strengthened` has no strengthening provenance.
- `effective-profile-set-invalid-resolution.json` — a `union` constraint reports an incompatible `max` resolution.

Schema-valid but semantic-invalid fixtures:

- `incompatible-core.profile.json` — composition with Core `0.1.0` fails `PROFILE-CORE-COMPAT-001` because its compatibility range starts at `0.2.0`.
- `unverifiable-core-strengthening.profile.json` — an unrelated constraint self-declares a Core strengthening; invariant-specific validation cannot establish a strict conjunctive strengthening, so composition fails `PROFILE-CORE-STRENGTHENING-001`.
- `effective-profile-set-duplicate-profile-key.json` — repeats one `[profile_type, profile_id]` with two versions and fails `PROFILE-EFFECTIVE-IDENTITY-001`.
- `effective-profile-set-duplicate-constraint-path.json` — repeats one normalized semantic path and fails `PROFILE-EFFECTIVE-IDENTITY-001`.
- `ambiguous-cross-category-conflict/` — both Profile manifests are schema-valid individually, but cross-category differing `replace` values have no unique same-type descendant winner and must fail exactly `PROFILE-COMP-REPLACE-001`.

The fixtures specify contract behavior; they do not require or prescribe a runtime resolver implementation in PR 4.
