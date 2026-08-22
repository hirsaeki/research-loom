# Canonical Research Profile quality-policy convergence

## Purpose

PR 6 converges the reusable research-method and research-quality policy that PR 3 deliberately left above the Core semantic floor and PR 4 assigned to `profile_type: research`. PR 5 already made the Core/Profile contracts executable in `contract-checks`; this PR adds Research quality policy to that same regression boundary without introducing a runtime resolver or validator.

The two legacy trees remain migration sources and are not modified.

## Inputs compared

### Legacy `research-harness/`

The legacy Harness contains a strong but implementation-coupled quality policy:

- `source_quality` tiers (`HIGH`, `MEDIUM`, `LOW_CONFIDENCE`, `LOW_TRUST`);
- support-scope restrictions for low-confidence, low-trust, and company-primary material;
- explicit Evidence verification status and immutable Source/Evidence locator capture;
- `independent_support_source_ids`, synthesis overlap, and a warning that a review is not an independent copy of every included primary study;
- claim families including independent-effect and causal-effect claims;
- restrictions against inferring causality from correlation, self-report, small cases, narrative/scoping review, or authority alone;
- preservation of counterevidence, nulls, conflicts, limitations, unknowns, and material Evidence Gaps;
- coverage/stopping semantics in which a fixed Source count is never sufficient and stopping is forbidden while material gaps or high remaining information value remain;
- method/study-role boundaries such as protocol/design requirements and method-specific support limits.

These semantics are useful, but the Pydantic enums, concrete worker orchestration, Writer-use modes, quotation checks, and source-capture storage shape are not canonicalized here.

### Legacy `research-profile/`

The legacy Profile is predominantly MISCO/publication material. Its important contribution to this convergence is a boundary: Publication/Writer rules explicitly refuse to decide whether causality, generalization, support, or research limitations are valid. Those decisions belong on the Research side. Chapter order, formal rendering, quotation/citation presentation, and MISCO-specific content remain excluded from PR 6.

### Current convergence inventory

The inventory places reusable quality rules in Research Profile, including Finding limitations, Evidence reliability/directness/independence, causal-support constraints, Counter Review, and configurable evidence/gate thresholds. It also requires numeric thresholds to remain policy parameters rather than hidden inside semantic definitions.

## Canonicalization decisions

### 1. Quality assessment vocabulary is Profile-level, not a Core schema expansion

`profiles/contracts/research-quality-policy.yaml` defines canonical labels for source quality tier, support scope, Evidence directness, Claim family, method family, Counter Review lens, and quality gate.

These are **derived quality-assessment vocabulary**. PR 6 does not add `quality`, `directness`, `support_scope`, or `method_family` fields to Core objects. Core continues to own Source/Evidence identity and provenance, Evidence verification status and independence group, Finding limitations/boundary conditions, CounterReview state, Method state, and Human Decision invariants.

A future runtime may derive the Profile-level assessment vocabulary from Core objects plus method/source metadata, but its storage model is intentionally not defined in this PR.

### 2. Numeric thresholds are separate from semantic requirements

Every numeric threshold lives under `research_quality.thresholds.*` and uses a numeric merge strategy (`max` or `min`). Every semantic quality rule lives outside that namespace and uses a set-valued monotone merge (`union` for additional requirements/prohibitions, `intersection` for narrowing allowed sets).

For example:

- `research_quality.thresholds.material_finding.min_supporting_evidence_count` is a configurable numeric floor and composes with `max`;
- `research_quality.evidence_sufficiency.required_checks` is the semantic sufficiency contract and composes with `union`.

A Source count can therefore never be mistaken for the complete stopping/sufficiency rule.

### 3. Constraint paths are typed and have one canonical merge strategy

Within the `research_quality.*` namespace, the catalog is closed: a path must be declared by the canonical catalog, owned by a Research Profile, use the cataloged merge strategy, and match the cataloged value vocabulary/bounds.

This gives deterministic strengthening semantics without introducing last-write-wins or a new resolver. Existing PR 4 composition remains authoritative.

### 4. Evidence independence means provenance independence

Multiple citations are not automatically independent Evidence. `distinct_independence_group`, `synthesis_overlap_accounted`, and `same_evidence_not_self_validate` express the reusable semantics:

- shared-origin Evidence is not double-counted merely because it appears in multiple files/citations;
- evidence synthesis must account for overlap in included primary studies;
- the same Evidence used to form a proposition cannot by itself make that proposition independently validated.

Configured numeric independent-group minima are separate threshold constraints.

### 5. Causal and effect support is a Research quality decision

Research Profiles may narrow the support scopes admitted for independent-effect and causal Claims and add prohibited causal inference bases. Publication may faithfully render an already-approved causal conclusion, but it does not make this decision.

### 6. Finding qualification and Counter Review remain semantic gates

Research Profiles may require canonical Finding fields such as `limitations` and `boundary_conditions`, required Counter Review lenses, and blocking severities. The policy does not prescribe a chapter named “Limitations” or any reader-facing rendering.

### 7. Method-family and quality-gate vocabulary does not prescribe workflow order

Method families let Research Profiles attach reusable protocol/limitation requirements without making Survey, Delphi, Case Study, experiment, or any other method mandatory. Quality gates (`evidence_admissibility`, `claim_support`, `finding_sufficiency`, `counter_review`, `research_freeze`) express predicates over research state, not narrative order or an orchestration phase machine.

## Executable contract fixtures

`profiles/fixtures/research-quality/` contains only synthetic generic fixtures. The minimal generic profile deliberately contains no MISCO terminology, organization rule, chapter structure, citation/rendering rule, Project Config, or publication behavior. Its numeric values (`2` in the threshold fixtures) are synthetic regression values, not canonical defaults; only the path, type, merge direction, and configured-value semantics are canonical.

The fixture suite proves:

- `research_quality.*` ownership is Research-only;
- unknown quality paths, wrong merge strategies, invalid enums, and invalid numeric thresholds fail with stable quality-policy error codes;
- a stricter Research Profile composes monotonically by `intersection`, `union`, and `max` using the existing PR 4 composition oracle;
- schema-valid Core objects exercise source tier, Evidence verification/directness, independence, causal support, Finding qualification, Counter Review, evidence sufficiency, method-family, and quality-gate semantics;
- numeric Evidence counts remain insufficient by themselves to satisfy semantic sufficiency.

The executable evaluator in `tests/contracts/research_quality_oracle.py` is fixture-only. It is not a production research validator.

## Deliberate exclusions

PR 6 does not:

- move any Research Profile rule into the Core invariant catalog;
- create a concrete MISCO Research or Organization Profile;
- define source-type-to-quality-tier defaults as a universal matrix;
- require a particular research method or method order;
- define chapter/narrative structure;
- define citation, quotation, Writer, rendering, or Publication behavior;
- define Project Config;
- define SQLite, export, publish, package, or storage behavior;
- implement runtime Profile resolution, quality evaluation, orchestration, or persistence.
