# Profile contract fixtures

These fixtures exercise PR 4 only. They are synthetic and are **not** concrete MISCO, research-quality, narrative, or publication Profiles.

## Valid fixtures

- `valid/research-base.profile.json` — base Research Profile with a commutative set constraint.
- `valid/research-strict.profile.json` — same-type `extends` plus a registry-bound `CORE-TRACE-001` strengthening claim.
- `valid/organization.profile.json` — cross-type `requires` without override precedence.
- `valid/narrative.profile.json` — independent Narrative Profile.
- `valid/publication.profile.json` — Publication Profile requiring an Organization Profile.
- `valid/effective-profile-set.json` — dependency-closed canonical result with candidate pins, lossless dependency edges, constraint provenance, and validated strengthening provenance.

## Schema-invalid fixtures

- `invalid/cross-type-extends.profile.json` — same-type `extends` violation.
- `invalid/core-invariant-weakening.profile.json` — `effect: weaken` is not representable.
- `invalid/merge-strategy-value-type.profile.json` — `union` with a scalar value.
- `invalid/effective-profile-set-status-provenance.json` — `strengthened` without provenance.
- `invalid/effective-profile-set-invalid-resolution.json` — merge strategy and resolution disagree.

## Schema-valid semantic-invalid fixtures

Machine-readable expectations are in `contract-cases.json`.

- `invalid/incompatible-core.profile.json` → `PROFILE-CORE-COMPAT-001`.
- `invalid/effective-profile-set-duplicate-profile-key.json` → `PROFILE-EFFECTIVE-IDENTITY-001`.
- `invalid/effective-profile-set-duplicate-constraint-path.json` → `PROFILE-EFFECTIVE-IDENTITY-001`.
- `invalid/ambiguous-cross-category-conflict/` → exactly `PROFILE-COMP-REPLACE-001`.
- `invalid/unverifiable-core-strengthening.profile.json` → `PROFILE-CORE-STRENGTHENING-001`; its declared validator binding exists, but the referenced constraint does not match the approved form.

## Semantic resolution fixture

`semantic/version-resolution/` supplies a finite candidate universe with four versions of one Research Profile. A requested Publication Profile contributes one direct range and a transitive Organization dependency contributes another range. Both ranges admit multiple versions; the deterministic rule selects `fixture.version-target@2.4.0`. The expected dependency-edge provenance is also asserted.

`tests/contracts/test_profile_contracts.py` executes these fixtures. Its exhaustive solver is intentionally tiny and test-only; it is an oracle for the canonical semantics, not a general runtime resolver.
