# Core package and interface contracts

PR 9 establishes the common Research Capability execution boundary in Core:

- `capability-descriptor.schema.json` — identity, version, kind, declared functions, descriptive availability, and compatibility.
- `capability-context-pack.schema.json` — bounded read-only context pinned to Project Config, the complete Effective Profile Set, and a Research Snapshot.
- `capability-invocation.schema.json` — one function/mode invocation plus separate opaque runtime authorization evidence.
- `capability-handoff.schema.json` — structured candidate observations, source/evidence captures, candidate Findings, counterevidence/conflicts/unknowns, gaps, next-action/method proposals, validation, provenance, and adoption boundary.
- `capability-semantics.yaml` — shared cross-contract semantics and stable fixture error IDs.

These are interfaces, not a runtime permission engine, adapter SDK, state reducer, storage format, or Capability implementation.

Availability and Project Config permission hints never authorize execution. A Capability cannot mutate authoritative Research State, adopt Evidence/Finding, select the next Research Method, or bypass Human Decision-owned Core transitions. `virtual` and `synthetic_test` evidentiary output remains synthetic.

Common contracts live here; concrete imperative adapters/runtimes belong in `plugins/`. Project Config configures/hints at Capabilities without owning them, and Profiles constrain them without owning implementations.
