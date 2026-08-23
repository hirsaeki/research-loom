# Desktop Research capability convergence

## Decision

PR 11 converges Desktop Research-specific execution semantics onto the PR 9 Research Capability ABI. It does **not** add `DesktopResearchHandoff`, modify the generic PR 9 Context Pack / Invocation / Handoff schemas, or implement a browser/search/Work adapter.

```text
PR 8 Project Config + PR 4-7 Effective Profile Set + Research Snapshot
                             |
                  PR 9 bounded Context Pack
                             +-- exact-bound Desktop Research Context extension
                             |
                     PR 9 Invocation
                             |
            interactive execution / future adapter
                             |
                     PR 9 Handoff
                             +-- exact-bound Desktop Research result extension
                             |
                  validation / adoption review
                             |
                 canonical Core/Human Decision path
```

The two extension documents are subordinate to exact PR 9 envelope digests. The Context extension cannot authorize a resource; Invocation runtime authorization remains the only runtime authorization evidence. The result extension cannot carry an alternative authoritative result; generic Handoff candidate outputs remain the machine-readable candidate result and its adoption boundary remains unchanged.

## Target and bounded retrieval context

Desktop Research may target either an existing Research Question or a Question Candidate carried through existing project attention/seed context. A candidate is explicitly non-authoritative. Retrieval scope, allowed source **categories**, resource-role bindings, forbidden roles, coverage dimensions, and resource/artifact budgets are declared separately from source-quality policy.

Every PR 9 Context resource receives one Desktop runtime role. Writer/publication material, publication feedback, and archive/provenance roles are fail-closed forbidden in Desktop Research. Project inputs/artifacts that are allowed remain context only under PR 9; merely being discoverable or readable never makes them Evidence.

Allowed source categories are an open vocabulary for retrieval scope. They do not encode `HIGH`, `LOW_TRUST`, causal support, independence, or any legacy source-type → quality-tier default. Those policies remain PR 6 Research Profile semantics.

## Discovery, capture, rendition, and citations

A discovered source is not adopted Evidence. A captured source is still not adopted Evidence. Each PR 9 `source_capture` is supplemented with Desktop provenance requiring an exact locator, UTC acquisition timestamp, original-capture digest, and a separate exact UTF-8 text-rendition digest. Transport/storage is abstract: a content reference and digest are canonical; no Work exchange directory or filesystem convention is.

A Desktop citation back-references both the generic Handoff output and its Source Capture. Capture-integrity and exact excerpt-containment verification are distinct from Research Evidence adoption, which remains false at this boundary. A capture may intentionally have no evidence candidate at all (for example, a retained lead).

## Search trace and negative information

Search trace records strategy, coverage dimensions, outcome, candidate-output references, and capture references without naming a particular search engine or browser. Unsuccessful outcomes (`no_relevant_source`, unavailable, blocked, duplicate, out-of-scope) are preserved explicitly. Null results are projected into PR 9 observations/unknowns instead of disappearing. Counterevidence, conflicts, unknowns, and Evidence Gaps continue to live in the canonical PR 9 Handoff.

## Evidence Gaps, coverage, and stopping

Each PR 9 Evidence Gap receives Desktop materiality and coverage-dimension assessment. Every declared coverage dimension must be assessed. Saturation and remaining information value are explicit. A fixed source count is never a sufficient stopping basis; a material gap or high remaining information value blocks `stop_recommended=true`.

Stopping remains a recommendation about the marginal value of continuing this Desktop Research run. It is neither Research completion, RQ answer adoption, nor a Human Decision. Desktop Research also cannot select Survey, Delphi, Case, or any other next method; the generic PR 9 next-method object remains `status: candidate`, and PR 10 may only present/route it through the existing proposal/Human Decision boundary.

## Execution modes and implementation boundary

The Descriptor supports PR 9 `real`, `virtual`, and `synthetic_test` modes. PR 9 epistemic rules still apply: virtual/synthetic-test evidentiary outputs cannot be relabeled empirical. The Desktop extension adds no alternate epistemic status.

Interactive Work execution and a future adapter therefore differ only in transport/runtime implementation. They must consume the same exact-bound Context extension and return the same PR 9 Handoff plus result extension. Browser automation, a concrete Work API, production search, Survey/Case/Delphi/Virtual Runner behavior, SQLite, Writer, Publication, and MISCO-specific configuration remain outside PR 11.

Legacy `research-harness/contracts/capabilities/desktop-research/` remains untouched as migration/reference material. Its useful provenance and stopping semantics are converged here, while its legacy `DesktopResearchHandoff`, Work filesystem layout, and source-type quality defaults are not promoted.
