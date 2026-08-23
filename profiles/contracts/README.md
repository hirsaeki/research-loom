# Canonical Profile contracts

PR 4 establishes the Profile-system contract above the Core semantic floor defined by PR 3. It defines **what a Profile is, how Profile versions are selected, and how selected Profiles compose** without introducing concrete organization policy or a general runtime resolver. PR 6 adds the canonical reusable Research Profile quality-policy vocabulary on top of those composition semantics. PR 7 adds the canonical reusable Narrative Profile semantics for argument stages, minimum semantic dependencies, section purposes, preservation, and read-only projection boundaries.

## Contract files

- `profile-manifest.schema.json` — common declarative envelope for Research, Organization, Narrative, and Publication Profiles.
- `composition-semantics.yaml` — normative dependency, deterministic version resolution, composition, provenance, serialization, conflict, and Core-invariant-floor semantics.
- `effective-profile-set.schema.json` — canonical resolved boundary, including the pinned candidate universe, lossless dependency provenance, effective constraints, and Core invariant status.
- `invariant-strengthening-validators.yaml` — authoritative binding between Core invariant IDs and versioned Profile-strengthening validators/forms.
- `research-quality-policy.schema.json` — structural contract for the canonical Research quality-policy catalog.
- `research-quality-policy.yaml` — Research-owned quality vocabulary, typed constraint paths, monotone merge semantics, quality-gate meanings, and stable error codes.
- `narrative-semantics.schema.json` — structural contract for the canonical Narrative semantics catalog.
- `narrative-semantics.yaml` — Narrative-owned semantic stages, partial-order dependencies, section purposes, preservation/connection rules, non-normative hints, and stable error codes.

The Profile contract version is `0.1.0`. Profiles use SemVer independently from Core and declare compatibility ranges for both Core research and invariant contracts. The Research quality-policy and Narrative-semantics catalogs are independently versioned at `0.1.0`.

## Profile categories

| Type | Owns | Does not own |
| --- | --- | --- |
| `research` | methodology and research-quality policy, method-family gates, non-universal evidence/source policy | organization terminology, narrative ordering, rendering |
| `organization` | organization/domain semantic requirements, terminology, disclosure/confidentiality, organization gates | generic methodology, Writer structure, rendering mechanics |
| `narrative` | argument/narrative stages, minimum semantic dependencies, section-purpose and preservation semantics | authoritative research decisions, Project Research Attention, literal chapter tree, rendering/release |
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

## Research quality-policy namespace

`research_quality.*` is a canonical **Research Profile-only** constraint namespace. The catalog closes this namespace: each path has one value shape, one merge strategy, and a documented strengthening meaning. Organization, Narrative, and Publication Profiles cannot declare these paths.

The contract deliberately separates semantic rules from numeric thresholds:

- semantic requirements use `union` to add requirements/prohibitions or `intersection` to narrow allowed sets;
- numeric thresholds live only under `research_quality.thresholds.*` and use `max` or `min`.

The catalog defines Profile-level assessment vocabulary such as source quality tier, Evidence directness/support scope, Claim family, method family, and quality gates without adding those as new Core fields. Core invariants remain unchanged. A future runtime may derive the assessment labels, but PR 6 does not define that runtime representation.

The generic fixture under `profiles/fixtures/research-quality/` demonstrates source/evidence admissibility, verification, independence, causal support, Finding limitations/boundary conditions, Counter Review, evidence sufficiency, method-family requirements, and quality gates. It is synthetic and contains no MISCO, organization, narrative, publication, or Project Config rules.

## Narrative semantics namespace

`narrative.*` is a canonical **Narrative Profile-only** namespace. It describes a read-only semantic projection over authoritative Research State rather than a new research state or a literal document structure.

The catalog distinguishes:

- semantic stage definitions from literal chapters;
- `consumes` / `requires` authoritative research inputs from `produces` reader-facing Narrative products;
- minimum acyclic partial-order dependencies from fixed total ordering;
- semantic section purposes from literal headings or chapter numbers;
- preservation of counter-findings, `Argument.qualifier`, `Finding.limitations`, counterevidence effects, and traceable Contribution/Recommendation support from creating new research links;
- provisional outline / publication-location / Primary Exposition hints from normative Narrative semantics.

Structured Narrative identities fail closed on divergent definitions, dangling stage references fail, and dependency cycles fail. A Writer/Project projection may later linearize the graph, but PR 7 does not define a Writer runtime or Outline/Manuscript wire format. Project-specific Research Attention remains deferred to Project Config.

The synthetic generic fixture under `profiles/fixtures/narrative/` branches after validation into unordered synthesis and implication stages, demonstrating that the contract preserves only minimum semantic dependencies rather than a mandatory chapter order.

## Core invariant strengthening

`effect: strengthen` is a **claim**, never proof. Each claim must carry a `validator_binding` with validator ID, validator version, and form ID. That four-part binding with `invariant_id` must resolve in `invariant-strengthening-validators.yaml`.

The registry is authoritative for which validators/forms exist. It currently registers one synthetic contract fixture form for `CORE-TRACE-001`; every other Core invariant explicitly has `no_registered_forms` and therefore fails closed for Profile strengthening in contract `0.1.0`.

A conforming implementation must bind the actual resolved constraints, satisfy the registered form, preserve the original Core predicate unchanged, and obtain a positive result from the bound invariant-specific validator before emitting `status: strengthened`. Missing, mismatched, unavailable, or inconclusive validation is `PROFILE-CORE-STRENGTHENING-001`. The registry defines the connection point and proof obligations without prescribing a resolver implementation or theorem prover.

## Executable contract tests

`tests/contracts/test_profile_contracts.py` remains the PR 4 Profile-system oracle. `tests/contracts/test_research_quality_policy.py` / `research_quality_oracle.py` add fixture-only executable semantics for PR 6. `tests/contracts/test_narrative_semantics.py` / `narrative_semantic_oracle.py` add fixture-only executable semantics for PR 7, including structured identity/ref/cycle checks and projection regressions for preservation, authority, connections, and non-normative hints. None of these are production resolvers or research/Writer validators.

`.github/workflows/contracts.yml` runs all of these checks as the stable `contract-checks` GitHub Actions workflow.

Concrete MISCO Profiles, organization-specific source-quality defaults/matrices, Project Config/Research Attention, Writer/Outline/Manuscript runtime behavior, Publication rendering/citation/template behavior, persistence/export/publish behavior, general runtime resolution, and research/manuscript/release package wire formats remain out of scope.
