# Canonical Profile contracts

PR 4 establishes the Profile-system contract above the Core semantic floor defined by PR 3. It defines **what a Profile is, how Profile versions are selected, and how selected Profiles compose** without introducing concrete organization policy or a general runtime resolver.

## Contract files

- `profile-manifest.schema.json` — common declarative envelope for Research, Organization, Narrative, and Publication Profiles.
- `composition-semantics.yaml` — normative dependency, deterministic version resolution, composition, provenance, serialization, conflict, and Core-invariant-floor semantics.
- `effective-profile-set.schema.json` — canonical resolved boundary, including the pinned candidate universe, lossless dependency provenance, effective constraints, and Core invariant status.
- `invariant-strengthening-validators.yaml` — authoritative binding between Core invariant IDs and versioned Profile-strengthening validators/forms.

The Profile contract version is `0.1.0`. Profiles use SemVer independently from Core and declare compatibility ranges for both Core research and invariant contracts.

## Profile categories

| Type | Owns | Does not own |
| --- | --- | --- |
| `research` | methodology and research-quality policy, method-family gates, non-universal evidence/source policy | organization terminology, narrative ordering, rendering |
| `organization` | organization/domain semantic requirements, terminology, disclosure/confidentiality, organization gates | generic methodology, Writer structure, rendering mechanics |
| `narrative` | argument/narrative stages, semantic ordering, section-purpose semantics | authoritative research decisions, rendering/release |
| `publication` | output, citation, template, rendering, formal document and release constraints | authoritative research state or new research claims |

`extends` is same-type inheritance/refinement. `requires` may cross types and expresses dependency only; it never grants override precedence. Cross-category last-write-wins remains forbidden.

## Deterministic version resolution

One composition invocation receives a **complete finite candidate universe** of manifest byte sequences. Candidate identity is `(profile_type, profile_id, profile_version)` plus SHA-256 of the exact manifest bytes. Supplying different content for the same key/version is `PROFILE-CANDIDATE-IDENTITY-001`.

Direct requests and every active transitive `extends` / `requires` edge contribute version ranges. A valid assignment selects exactly one candidate for every reachable Profile key and satisfies all ranges, Core compatibility, type, closure, and cycle rules.

If several valid assignments exist, the contract chooses one deterministically: build a version vector over all candidate Profile keys in canonical Profile-key order, use `ABSENT` below any SemVer, and select the lexicographically greatest vector. This is only a semantic definition; implementations may use any equivalent solver. It does **not** create layer precedence or LWW behavior.

## Lossless and immutable provenance

The Effective Profile Set retains:

- direct requests as `relation: requested` plus the requested version range;
- each dependency edge as `relation: extends|requires`, the pinned introducing Profile, and the edge's required version range;
- every selected Profile with mandatory `manifest_sha256`;
- the complete candidate universe as pinned Profile refs;
- every constraint/invariant provenance source with the same selected manifest hash.

Therefore a provenance source cannot silently drift to different manifest content while keeping the same Profile ID/version.

## Constraint composition and serialization

`must_equal`, `union`, `intersection`, `max`, `min`, and constrained `replace` retain the PR 4 composition rules. `replace` can choose a winner only through one unique same-type `extends` descendant. Cross-category replacement conflicts are `PROFILE-COMP-REPLACE-001`.

Canonical serialization is defined for reproducibility, not precedence: Profiles use type-rank/id/version order, effective constraints use semantic path, provenance arrays have deterministic tuple orders, Core invariants retain catalog order, and set-like values are de-duplicated and sorted by RFC 8785 canonical JSON bytes.

## Core invariant strengthening

`effect: strengthen` is a **claim**, never proof. Each claim must carry a `validator_binding` with validator ID, validator version, and form ID. That four-part binding with `invariant_id` must resolve in `invariant-strengthening-validators.yaml`.

The registry is authoritative for which validators/forms exist. It currently registers one synthetic contract fixture form for `CORE-TRACE-001`; every other Core invariant explicitly has `no_registered_forms` and therefore fails closed for Profile strengthening in contract `0.1.0`.

A conforming implementation must bind the actual resolved constraints, satisfy the registered form, preserve the original Core predicate unchanged, and obtain a positive result from the bound invariant-specific validator before emitting `status: strengthened`. Missing, mismatched, unavailable, or inconclusive validation is `PROFILE-CORE-STRENGTHENING-001`. The registry defines the connection point and proof obligations without prescribing a resolver implementation or theorem prover.

## Executable contract tests

`tests/contracts/test_profile_contracts.py` is a thin contract oracle for fixtures, not production resolution code. It exercises schema validity and semantic cases including Core compatibility, transitive version resolution, duplicate identities, replacement conflicts, strengthening bindings, lossless provenance, deterministic composition, content pins, and canonical ordering.

`.github/workflows/contracts.yml` runs these checks as the `contract-checks` GitHub Actions workflow.

Concrete MISCO Profiles, concrete research/source-quality matrices, Project Config/CLI override precedence, Writer/Publication runtime behavior, persistence/export/publish behavior, general runtime resolution, and research/manuscript/release package wire formats remain out of scope.
