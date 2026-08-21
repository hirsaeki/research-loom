# Canonical Profile contract convergence

## Purpose

PR 4 is the bounded convergence step immediately above PR 3. PR 3 established Core research-object contracts and non-overridable invariants; this PR treats those invariants as the **semantic floor** and canonicalizes only the Profile system itself.

Both legacy trees remain unchanged and continue to serve as migration evidence rather than runtime dependencies.

## Inputs compared

### Legacy `research-harness/`

The Harness already had a separately versioned Profile pack boundary: `profile.manifest.json` carried `profile_id`, `profile_version`, `compatible_harness_api`, and manifest-declared static entries; workspace installation recorded source refs and hashes. It also contains valuable but non-Core policy such as source-quality/support matrices and publication formal-profile hooks.

PR 4 keeps the useful envelope/provenance idea, but does not promote the old copier layout, MISCO roles, source-quality matrix, workspace lock format, or runtime upgrade code into the canonical Profile contract.

### Legacy `research-profile/`

The Profile repository is a declarative MISCO pack with organization guidance and a Human-approved Publication source pack. It demonstrates that Profile content can be static, separately versioned, and provenance-sensitive, while also showing why organization and publication concerns must not be one undifferentiated Profile category.

PR 4 does not migrate that concrete MISCO content.

### Current convergence inventory

The design inventory separates four reusable Profile categories:

1. Research — methodology/research-quality policy;
2. Organization — organization/domain semantic requirements;
3. Narrative — argument and semantic composition pattern;
4. Publication — output, citation, rendering, and release requirements.

It also calls for inheritance/composition and an `effective_constraints` view. PR 4 keeps those goals but rejects a global precedence ladder such as “Organization overrides Research” or “Publication wins later”. Such a ladder would make unrelated categories silently overwrite each other.

## Canonicalization decisions

| Concern | PR 4 decision | Reason |
| --- | --- | --- |
| Common Profile envelope | Canonical schema | Converges legacy identity/version manifest with category/type and Core compatibility. |
| Profile types | `research`, `organization`, `narrative`, `publication` | Matches monorepo boundary and prevents MISCO/publication concerns becoming one profile blob. |
| Profile version | SemVer | Profile lifecycle is independent of Core lifecycle. |
| Core compatibility | Explicit ranges for research + invariant contracts | Replaces the legacy single `compatible_harness_api` with compatibility against the actual semantic floor. |
| `extends` | Same-type inheritance/refinement | Inheritance gives meaningful descendant precedence only inside one concern category. |
| `requires` | Cross-type-capable dependency | Expresses composition/dependency without pretending one category inherits another. |
| Constraint identity | Stable semantic `path` | Allows deterministic collision detection without binding to Python/SQLite layout. |
| Merge semantics | Explicit commutative strategies plus constrained `replace` | Avoids input-order behavior and supports deterministic effective constraints. |
| Cross-category replacement | Error | No implicit cross-category last-write-wins. |
| Same-type replacement | Only unique descendant over ancestor | Makes inheritance refinement deterministic while rejecting sibling ambiguity. |
| Effective Profile Set | Canonical output schema plus semantic identity rules | Downstream consumers get one unambiguous resolved value per identity with provenance. |
| Core invariant modification | Preserve or positively validated strengthening only | PR 3 invariants are a semantic floor; a manifest claim cannot self-authorize `strengthened`. |
| Resources | Optional manifest-declared static resources | Retains the useful static-pack concept without canonicalizing legacy copy targets/runtime. |

## Why the inventory's global precedence ladder is not canonicalized

The inventory explored an `Effective Configuration = Core + Research + Organization + Narrative + Publication + Project` model with a priority ladder. The layer split is useful; the blanket overwrite semantics are not.

A Research Profile and Organization Profile may legitimately constrain the same semantic target for different reasons. Input order cannot tell whether one is stronger, compatible, or contradictory. PR 4 therefore uses explicit merge semantics. Compatible monotone constraints can compose (`union`, `intersection`, `max`, `min`); equal values can coalesce; ambiguous values fail. `requires` never changes that rule.

Project Config and CLI temporary overrides are intentionally deferred, so this PR does not define their precedence.

## Determinism and provenance

Composition is semantic-order independent. A canonical serialization order exists only to make outputs reproducible; it does not choose winners.

Every effective constraint records all contributing Profile refs and constraint IDs. Every effective Profile records whether it was directly requested or introduced by `extends`/`requires`. Normalized output rejects duplicate Profile keys, duplicate semantic constraint paths, and duplicate Core invariant identities.

Conflict classification is deterministic as well: merge-strategy disagreement is `PROFILE-COMP-STRATEGY-001`; a `replace` collision without one unique same-type descendant winner is `PROFILE-COMP-REPLACE-001`; other same-strategy unmergeable values use the generic `PROFILE-COMP-CONFLICT-001`.

This keeps `effective_constraints` suitable as a later package/interface boundary without forcing a resolver architecture now.

## Core invariant validation boundary

The schema-invalid fixture `profiles/fixtures/invalid/core-invariant-weakening.profile.json` deliberately tries to declare `effect: weaken` for `CORE-TRACE-001`; only `strengthen` is representable.

A schema-valid `effect: strengthen` declaration is still only a claim. A conforming composition implementation must keep the original Core invariant predicate unchanged, resolve the referenced Profile constraints as additional predicates, and positively validate a satisfiable strict strengthening before emitting `status: strengthened`. Validation must bind the actual resolved paths and values. Missing or inconclusive validation fails `PROFILE-CORE-STRENGTHENING-001`; an attempted substitution or weakening of the Core rule fails `PROFILE-CORE-INVARIANT-001`.

The semantic-invalid fixture `profiles/fixtures/invalid/unverifiable-core-strengthening.profile.json` covers the case where an unrelated Profile constraint is falsely labeled as a strengthening. This specifies the required boundary without adding a runtime resolver or theorem prover to PR 4.

## Explicit non-goals

PR 4 does not:

- modify/delete either legacy tree;
- create a concrete MISCO Profile;
- canonicalize source-quality matrices, evidence-count thresholds, or other concrete research-quality rules;
- define Project Config or CLI override precedence;
- implement Writer or Publication behavior;
- define SQLite/export/publish/storage behavior;
- implement a general runtime resolver;
- define Research Package / Manuscript Package / Release Manifest wire formats.

Those remain later bounded convergence steps.
