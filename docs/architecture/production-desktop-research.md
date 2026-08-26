# PR24 — production Desktop Research

The production path is:

```text
PR9 Invocation
  -> generic PR9 validation + current State pins
  -> registered capability Context-extension validation
  -> runtime authorization
  -> EXTERNAL Run
  -> append-only retrieval attempts + PR23 source-capture artifacts
  -> PR9 Handoff + PR11 desktop-research-result-extension
  -> generic Handoff validation
  -> production Desktop result validation
  -> PR20 CapabilityNormalizationBoundary
  -> candidate-only StateDeltaProposal
```

Research State is unchanged through the complete capability execution and normalization path. Only a later explicit Human Decision plus `StateTransitionService` can create the next authoritative snapshot.

The retrieval ledger is operational provenance, not Research State. Inaccessible material, blocked fetches, provider errors and no-result searches remain visible rather than disappearing from coverage. Operational inability to continue is not equivalent to a scientific/research stopping recommendation.

Browser/search vendors and LLM providers are intentionally non-goals. Managed retrieval providers can be added later behind the same PR11 semantics without forking the research contract.
