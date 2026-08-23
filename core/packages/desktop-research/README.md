# Canonical Desktop Research capability contracts

PR 11 specializes the PR 9 Research Capability ABI without changing the generic `capability-context-pack@0.1.0`, `capability-invocation@0.1.0`, or `capability-handoff@0.1.0` envelopes.

- `desktop-research-capability-descriptor.json` is the canonical implementation-neutral Descriptor instance.
- `desktop-research-context-extension.schema.json` binds Desktop Research targeting, retrieval scope, source-category allow-list, resource-role deny-list, coverage dimensions, and bounded budgets to one exact PR 9 Context Pack.
- `desktop-research-result-extension.schema.json` binds capture provenance, excerpt back-references, unsuccessful search trace, null/gap preservation, coverage, saturation, remaining-information-value, and stopping recommendation metadata to one exact PR 9 Handoff.
- `desktop-research-semantics.yaml` records cross-document semantics and stable contract-check error IDs.

The result extension is **not** `DesktopResearchHandoff` and is unusable without its exact PR 9 Handoff binding. Generic Handoff outputs remain the authoritative machine-readable candidate result. Source discovery/capture never adopts Evidence or a Finding, candidate next methods are never selected here, and a stopping recommendation is neither Research completion nor a Human Decision.

Source quality, independence/directness, support sufficiency, and causal-support policy remain Research Profile concerns. This contract intentionally contains no source-type → quality-tier matrix and no search-engine, browser, Work API, filesystem layout, or adapter-specific transport. Interactive execution and future adapters must preserve the same contracts.
