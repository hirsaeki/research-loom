# Canonical Profile contract convergence

## Purpose

PR 4 is the bounded convergence step immediately above PR 3. Core research-object contracts and non-overridable invariants remain the semantic floor; this PR canonicalizes only the reusable Profile system.

Both imported legacy trees remain unchanged and serve as migration evidence rather than runtime dependencies.

## Inputs retained and rejected

The legacy Harness demonstrated separately versioned static Profile packs, manifest identity, hashes, and useful non-Core policy. The legacy Profile repository demonstrated static organization/publication guidance and provenance-sensitive source packs. The convergence inventory separated Research, Organization, Narrative, and Publication concerns and called for composable effective constraints.

PR 4 retains separate versioning, static declarative manifests, content provenance, four Profile categories, `extends`/`requires`, and an Effective Profile Set. It does not promote legacy copier/runtime layouts, concrete MISCO content, source-quality matrices, or a blanket layer-priority ladder.

## Stable design

- Research / Organization / Narrative / Publication remain distinct Profile categories.
- `extends` is same-type inheritance/refinement.
- `requires` may cross Profile types but never creates override precedence.
- Cross-category LWW is forbidden.
- `replace` is deterministic only through one unique same-type descendant.
- Core invariants may be preserved or positively validated as strengthened, never weakened or substituted.

## Deterministic dependency version selection

A composition input includes the active Core contract versions, direct Profile requests, and a complete finite candidate universe of manifest byte sequences. Each candidate is pinned by SHA-256 of its exact bytes.

All direct and transitive ranges are constraints on one dependency-closed assignment. If more than one assignment satisfies every active range, Core compatibility requirement, same-type `extends` rule, and cycle rule, the canonical winner is the lexicographically greatest SemVer vector over Profile keys in canonical Profile-key order, with `ABSENT` lower than every version.

This is implementation-neutral: a runtime may use SAT, backtracking, registry APIs, a lockfile, or another equivalent mechanism. The contract defines the result, not the solver. The tie-break has no relationship to cross-category constraint precedence.

## Provenance as a canonical boundary

The original `selection_reasons` plus `introduced_by` arrays were lossy because they could not reconstruct which introducer used which relation. They are replaced by edge-level `selection_provenance` entries:

- `requested` + direct required range; or
- `extends|requires` + pinned introducing Profile + the exact required range carried by that edge.

Every effective Profile now requires `manifest_sha256`. Constraint and invariant provenance repeat the same hash, so each source resolves to exactly one selected immutable manifest. The Effective Profile Set also records the pinned candidate universe, allowing resolution inputs to be audited without importing legacy source-ref formats.

## Core strengthening validator binding

A natural-language Core rule plus generic Profile path/value cannot make `effect: strengthen` self-verifying. PR 4 therefore adds an authoritative, versioned strengthening registry. Each strengthening claim names `(invariant_id, validator_id, validator_version, form_id)` and referenced constraint IDs.

The registry decides which bindings/forms are valid for the active invariant contract. A form may declaratively constrain the path/merge/value shape that a bound validator accepts. The validator still owns the semantic proof obligations: preserve the original Core predicate, add the Profile constraint conjunctively, remain satisfiable, and be strictly stronger. Missing or inconclusive validation fails closed.

This creates a canonical connection point without implementing a runtime resolver or theorem prover.

## Executable semantic regression tests

Schema validation alone cannot catch transitive version resolution, property-level identity duplication, cross-file conflict classification, dependency-edge provenance, or strengthening-registry mismatches. PR 4 therefore includes a thin test-only contract oracle and synthetic fixtures for:

- incompatible Core ranges;
- multiple-candidate and transitive dependency version resolution;
- duplicate effective Profile keys and constraint paths;
- ambiguous cross-category `replace` conflicts;
- invalid/unverifiable Core strengthening;
- lossless dependency provenance and immutable manifest pins;
- input-order-independent composition and canonical serialization.

The `contract-checks` GitHub Actions workflow runs these checks. This is intentionally not production resolution code.

## Explicit non-goals

PR 4 still does not:

- modify or delete `research-harness/` or `research-profile/`;
- create a concrete MISCO Profile;
- canonicalize concrete research/source-quality policy;
- define Project Config or CLI override precedence;
- implement Writer or Publication runtime behavior;
- implement SQLite/export/publish/storage behavior;
- implement a general runtime resolver;
- define Research Package, Manuscript Package, or Release Manifest wire formats.
