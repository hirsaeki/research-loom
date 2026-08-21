# Canonical Profile contracts

PR 4 establishes the Profile-system contract above the Core semantic floor defined by PR 3. It defines **what a Profile is and how Profiles compose**, without selecting concrete organization policy or implementing a runtime resolver.

## Contracts

- [`profile-manifest.schema.json`](profile-manifest.schema.json) — common declarative envelope for all Profile categories.
- [`composition-semantics.yaml`](composition-semantics.yaml) — normative dependency, composition, conflict, and Core-invariant-floor semantics.
- [`effective-profile-set.schema.json`](effective-profile-set.schema.json) — resolved contract presented to downstream consumers, including `effective_constraints` and provenance.

The Profile contract version is `0.1.0`. A Profile uses SemVer for `profile_version` and separately declares compatibility ranges for the Core research-object and invariant contracts. PR 4 targets Core `0.1.0` as its semantic floor.

## Profile categories

| Type | Owns | Does not own |
| --- | --- | --- |
| `research` | methodology and research-quality policy, method-family gates, non-universal evidence/source policy | organization terminology, narrative ordering, rendering |
| `organization` | organization/domain semantic requirements, terminology, disclosure/confidentiality, organization gates | generic methodology, Writer structure, rendering mechanics |
| `narrative` | argument/narrative stages, semantic ordering, section-purpose semantics | authoritative research decisions, rendering/release |
| `publication` | output, citation, template, rendering, formal document and release constraints | authoritative research state or new research claims |

The category is determined by **why a rule varies**, not merely by which research object it refers to. For example, an organization may impose an organization-specific research requirement; that does not turn it into a generic Research Profile rule.

## `extends` and `requires`

`extends` is inheritance/refinement and is same-type only. It may establish descendant-over-ancestor precedence for an explicit `replace` constraint. Multiple inheritance is allowed, but ambiguous sibling replacement is an error.

`requires` is dependency/composition. It may target any Profile type, including another category, but it never grants override precedence. Cross-type relationships that are dependencies therefore use `requires`, not `extends`.

Both dependency forms are versioned. Dependency cycles, unsatisfied versions, or selection of a Profile incompatible with the active Core contracts are hard errors.

## Constraint composition

Profiles emit declarative constraints identified by stable semantic `path`. The `core.*` namespace is reserved to Core and cannot be used by Profile constraints. A collision is resolved by its explicit `merge_strategy`:

- `must_equal`
- `union`
- `intersection`
- `max`
- `min`
- `replace`

`union` and `intersection` require set-like arrays. `max` and `min` require numeric values. The Effective Profile Set schema also constrains `resolution` to modes compatible with the declared merge strategy.

There is no cross-category or input-order last-write-wins rule. `replace` is legal only when same-type `extends` ancestry yields one unique descendant. Otherwise the collision is `PROFILE-COMP-REPLACE-001`; the generic `PROFILE-COMP-CONFLICT-001` is reserved for same-strategy conflicts without a more specific code. All successful effective constraints retain source Profile and constraint-ID provenance.

## Core invariants are a floor

The Core invariant catalog is not another Profile layer. Profiles may only preserve it or add a conjunctive strengthening. The manifest therefore exposes `core_invariant_strengthenings` with `effect: strengthen`; there is no valid disable/weaken/replace operation.

A strengthening declaration is a **claim**, not proof. A conforming composition implementation must evaluate the original Core invariant unchanged and validate the referenced, fully resolved Profile constraints as additional predicates. The result may be reported as `strengthened` only after invariant-specific validation establishes a satisfiable, strict conjunctive strengthening. Missing, inconclusive, unrelated, or substitutive validation fails closed with `PROFILE-CORE-STRENGTHENING-001` (or `PROFILE-CORE-INVARIANT-001` for an attempted Core substitution).

This defines the validation boundary without prescribing a resolver implementation or theorem prover.

## Effective Profile Set

Downstream components should consume the resolved effective contract rather than infer precedence from raw Profile files. `effective-profile-set.schema.json` carries:

- active Core contract versions;
- requested and dependency-closed Profile refs;
- selection provenance (`requested`, `extends`, `requires`), retaining all applicable reasons;
- normalized `effective_constraints` and merge provenance;
- Core invariant status and strengthening provenance.

The normalized output has exactly one resolved version per Profile key, one effective constraint per semantic path, and one entry per active Core invariant. `strengthened` requires non-empty strengthening provenance; `preserved` requires empty strengthening provenance. These identity rules include semantic validation beyond what JSON Schema `uniqueItems` can express.

The schema does not require a particular resolver implementation, storage engine, package layout, or Writer/Publication runtime.

See [`../fixtures/`](../fixtures/) for synthetic contract fixtures. They are not concrete MISCO or research-quality Profiles.
