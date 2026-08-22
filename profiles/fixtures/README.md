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

Machine-readable expectations for the core cases are in `contract-cases.json`.

- `invalid/incompatible-core.profile.json` → `PROFILE-CORE-COMPAT-001`.
- `invalid/effective-profile-set-duplicate-profile-key.json` → `PROFILE-EFFECTIVE-IDENTITY-001`.
- `invalid/effective-profile-set-duplicate-constraint-path.json` → `PROFILE-EFFECTIVE-IDENTITY-001`.
- `invalid/effective-profile-set-missing-requested.json` → `PROFILE-EFFECTIVE-REQUEST-001`; a direct request is omitted from the selected Effective Profile Set.
- `invalid/effective-profile-set-bad-provenance.json` → `PROFILE-EFFECTIVE-PROVENANCE-001`; a dependency edge points at the right Profile identity/version but the wrong immutable manifest pin.
- `invalid/ambiguous-cross-category-conflict/` → exactly `PROFILE-COMP-REPLACE-001`.
- `invalid/unverifiable-core-strengthening.profile.json` → `PROFILE-CORE-STRENGTHENING-001`; its declared validator binding exists, but the referenced constraint does not match the approved form.

## Semantic regression fixtures

- `semantic/version-resolution/case.json` supplies a finite candidate universe with four versions of one Research Profile. A requested Publication Profile contributes one range and its transitive Organization dependency contributes another. Both ranges admit multiple versions; the deterministic rule selects `fixture.version-target@2.4.0`. The expected dependency-edge provenance is also asserted.
- `semantic/version-resolution/conflict-case.json` adds a direct target range incompatible with the transitive range and must fail exactly `PROFILE-VERSION-001`.
- `semantic/provenance/forged-dependency-relation.json` mutates a valid dependency edge to the wrong relation and must fail `PROFILE-EFFECTIVE-PROVENANCE-001`.
- `semantic/provenance/forged-dependency-range.json` mutates a valid dependency edge to an undeclared/unsatisfied exact range and must fail `PROFILE-EFFECTIVE-PROVENANCE-001`.
- `semantic/provenance/fabricated-request.json` adds a `relation=requested` provenance entry with no corresponding direct request and must fail `PROFILE-EFFECTIVE-REQUEST-001`.
- `semantic/canonical-serialization.json` covers RFC 8785 set-member ordering and de-duplication for numeric aliases, object key order, composed Unicode, and decomposed Unicode.

`tests/contracts/semantic_oracle.py` is the shared test-only oracle. `test_profile_contracts.py`, `test_version_conflict.py`, `test_provenance_failure.py`, and `test_requested_presence.py` execute these fixtures. The exhaustive version solver remains intentionally tiny and test-only; it is an oracle for canonical semantics, not a general runtime resolver.
