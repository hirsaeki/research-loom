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

## Operator read surfaces

External Desktop Research has two distinct persisted read projections:

```text
research-loom run show --workspace PATH --run-id RUN-ID --json
research-loom external materials list --workspace PATH [--json]
research-loom external materials show --workspace PATH --run-id RUN-ID --capture-id CAPTURE-ID [--max-text-bytes N] --json
research-loom external materials export --workspace PATH --run-id RUN-ID --capture-id CAPTURE-ID --kind original|rendition --output NEW-FILE --json
```

`run show` is Run-centric. Use it to inspect one Run's lifecycle, failure, diagnostics, retrieval attempts, termination provenance, and artifact metadata.

`external materials list` is material-centric. It projects only persisted `desktop_research.original_capture` + `desktop_research.text_rendition` capture pairs belonging to real Desktop Research `investigate` Runs in the opened project. Attempt-only records are not materials.

The original captured-byte digest is the material identity for this read model. Identical original digests are grouped across Runs; URL, filename, title, or text similarity never causes grouping. The projection retains each capture observation, its source locator, original artifact metadata, UTF-8 rendition metadata, and Run binding. Result ordering is deterministic by first capture time and material identity.

This inventory is read-only and introduces no Source/Evidence adoption, Run merge, artifact rewrite, deduplication mutation, or new material entity. Research Exhibits remain a separate analytical-artifact registry and are not included.

`external materials show` selects one exact `(run_id, capture_id)` and verifies the persisted UTF-8 rendition before returning bounded text. `external materials export` uses the same explicit capture identity to emit exact original or rendition bytes to a new non-managed path without overwrite or content conversion. The commands do not silently select a representative capture when identical original bytes were captured in multiple Runs. See `docs/architecture/external-material-content-read.md` for the integrity, size, and output boundaries.

Normal operator workflow should use these public Application Facade / CLI surfaces rather than reading SQLite tables or artifact/blob directories to determine what was retrieved or captured.
