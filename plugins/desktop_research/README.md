# Production Desktop Research adapter

This plugin is the first production concrete Research Capability implementation of the canonical PR11 `desktop-research@0.1.0 / investigate` contract.

It is **external-first**. `DesktopResearchExternalAdapter` declares `ExecutionStyle.EXTERNAL` and deliberately owns no Google/Bing/Brave/SerpAPI binding, browser automation, Playwright session, ChatGPT/Work connector, or LLM provider. An external operator or future managed provider drives retrieval between `prepare_external()` and `collect_external()` while the same canonical PR9 Context Pack/Handoff and PR11 Context/result extensions remain in force.

## Context preflight

PR24 adds a capability-neutral Context-extension validation seam to Core execution. The Desktop validator binds the exact Context Pack/project/target, requires an adopted Research Question or an explicitly non-authoritative question candidate, gives every PR9 resource exactly one Desktop role, fails closed over Writer/Publication/archive material, and enforces bounded resources without interpreting source category as quality.

The validator is deterministic and has no resource access or Research State writes. A capability that declares `requires_context_extension = True` cannot start when the extension, its validator, or immutable extension store is missing.

## Production external retrieval flow

PR35 exposes the existing Desktop Research capture and Retrieval Attempt Ledger services through the production local Application Facade and JSON CLI. The external operator flow is now:

```text
desktop_research.investigate
 -> external Run = RUNNING
 -> external attempt start
 -> actual external search/fetch
 -> external capture, when retrieval succeeds
 -> external attempt complete
 -> repeat as needed
 -> external collect
 -> canonical result validation
 -> normalization
 -> candidate-only StateDeltaProposal
```

The production CLI surfaces are:

```text
research-loom external attempt start
research-loom external capture
research-loom external attempt complete
research-loom external collect
```

Attempt timestamps remain Harness-owned. `started_at` and `completed_at` are not accepted from callers. Capture accepts the real external acquisition time as RFC3339 UTC because that is source-acquisition provenance rather than a Harness event timestamp.

A capture references two ordinary files that the operator has explicitly staged inside the opened production workspace: the original bytes and a UTF-8 text rendition. The files are read through the existing `LocalExecutionStore` controlled intake path. Workspace escape, `..`, symlink/junction/reparse-point traversal, directories, missing/non-regular files, and configured byte-limit violations fail closed. The CLI does not become a generic arbitrary artifact-upload API.

Every intake operation re-resolves the persisted Run and requires the opened project, `desktop-research@0.1.0 / investigate`, the production external implementation, real execution mode, the immutable Context-extension binding, and `RUNNING` status to match. A Run from another project/capability, or a completed/failed/aborted Run, cannot receive Desktop Research intake.

## Capture provenance

`DesktopResearchCaptureService` writes original bytes and a separate UTF-8 text rendition through the PR23 Artifact Store. Trusted digest, media type, byte length, storage locator, artifact identity, and original/text parent relation come from bytes actually stored by PR23 and are not caller authority. PR35's production ingress rejects unknown fields and reserved trusted metadata in caller provenance. `acquired_at` must be UTC and the exact locator is retained independently from publication/update dates.

The production intake also preserves the immutable Desktop Context bounds: the source category must already be allowed by the Run Context and original/text/capture-artifact budgets are checked before storing bytes. It does not infer missing coverage dimensions or source categories.

A capture is execution provenance/candidate source material only. It is not a verified Core Source, Evidence, or Finding.

## Retrieval Attempt Ledger

`DesktopResearchAttemptRecorder` exposes a narrow Run-bound API over the generic append-only Operational Trace port:

`start_attempt -> actual external search/fetch -> complete_attempt`.

The production attempt-start ingress requires explicit configured coverage-dimension IDs; it does not infer them. The ledger preserves successful and unsuccessful retrievals (`source_captured`, `no_relevant_source`, `unavailable`, `blocked`, `duplicate`, `out_of_scope`, `failed`) across process restart and Run abort. The result validator reconciles the persisted ledger exactly against PR11 `search_trace`; successful-only retrospective reporting is rejected.

Acquisition failure is never converted into evidence that information does not exist. Failed/blocked/unavailable retrieval remains explicit as unknown/gap/coverage limitation. An operational stop such as budget exhaustion is separate from the research stopping recommendation.

## Result validation and normalization

The production validator checks the canonical PR11 result schema/digest/bindings, trusted Artifact Store provenance, UTF-8 integrity, citation excerpt containment, capture and artifact budgets, search-trace/ledger equality, null projections, Evidence Gap identity/materiality, complete coverage dimensions, remaining information value, stopping constraints, and candidate next-method preservation.

`external collect` retains its existing `{ "handoff": {...}, "extension": {...} }` submission contract. PR35 does not weaken Handoff, pin, source-category, coverage, or budget validation. Capture/attempt records are append-only execution provenance: if final collect or later normalization fails closed, material already captured and retrieval attempts already recorded remain available for audit, while Research State is unchanged.

`DesktopResearchNormalizer` implements the PR20 `CapabilityResultNormalizer` port. It returns a `candidate_only=true` `StateDeltaProposal`; it never verifies a Source/Evidence item, adopts a Finding or Method, strengthens confidence, marks an RQ complete, or commits Research State. Metadata that cannot be mapped losslessly to existing Core objects remains in proposal execution provenance rather than being forced into a new Desktop-specific state model.

For `virtual` and `synthetic_test` Runs, captured material is retained as non-evidentiary artifacts/provenance and is not projected into empirical Source/Evidence/Finding candidates. PR35's local external-intake CLI is deliberately bound to the current real production external execution path rather than introducing a generic artifact API for arbitrary modes or capabilities.

## Future managed provider path

A future `DesktopResearchManagedAdapter` may compose `SearchProvider`, `FetchProvider`, and `TextRenditionProvider`, but it must reuse the same canonical descriptor, Context extension, PR9 Handoff, PR11 result extension, validator, attempt ledger, and normalizer. Provider choice is composition/runtime configuration; ambiguous last-write-wins implementation selection remains forbidden by PR22 `CapabilityRegistry` semantics.
