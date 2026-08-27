# Production Work Conversation / Research Coordinator runtime (PR25)

PR10 remains the canonical wire contract. The production runtime does not define a second conversation format and does not turn conversational prose into Research State mutations.

## Ownership and authority

`core/conversation/` is an application orchestration boundary. It owns validation, exact state binding, typed action routing, confirmation binding, immutable receipts, and candidate presentation. It is **not** a research planner, Research Method selector, evidence verifier, Finding adopter, completion judge, or Human Decision engine.

The authority chain is:

`Conversation Input -> candidate resolver -> registered typed Action Proposal -> exact current-state binding -> registered route -> existing authoritative service`.

Natural-language text is visible only to `ConversationActionResolver`. Resolver output is candidate-only and can name only registered semantic actions. Unknown actions fail closed. The resolver cannot emit a State patch, canonical PR9 Invocation, Human Decision, filesystem path authority, or arbitrary Capability choice.

## QUERY / PROPOSAL / COMMITTABLE_ACTION

- `QUERY` may route only to a read-only registered operation. Successful receipts keep the same Research Snapshot and set `research_state_mutation_performed=false`.
- `PROPOSAL` stops after a typed Action Proposal. It creates no Run, no confirmation request, and no Research State mutation.
- `COMMITTABLE_ACTION` means explicit intent to execute the typed proposal. Read-only Capability execution may have operational side effects (network, trace, captures, artifacts) while Research State remains unchanged. Authoritative Research State writes still go only through `StateTransitionService`.
- `CONFIRMATION` binds human intent to one exact proposal/current state. It is not runtime authorization and is never a Human Decision.
- `CANCEL` cancels only pending proposals or confirmation requests. `run.abort` is a separate typed action.

## Confirmation, authorization, Human Decision

These boundaries are independent:

1. **Confirmation**: exact human intent binding to proposal, actor, payload digest, current state, Project Config, Effective Profile Set, Research Snapshot, expiry, and single-use request.
2. **Runtime Authorization**: PR9 execution authority supplied by an independent authorization-evidence provider during Invocation materialization. Confirmation bytes are not authorization evidence.
3. **Human Decision**: semantic Research authority already owned by Core/PR20. Confirmation is never promoted into RQ/Method/Finding/Evidence/lineage authority.

The local Conversation Store performs confirmation consume with `BEGIN IMMEDIATE`; request state validation, receipt persistence, and consume marking occur in one transaction. Restart and concurrent processes therefore cannot successfully consume one request twice.

## Action and service registries

`ActionRegistry` is explicit and rejects duplicate/unknown registrations. Action names describe research/application semantics (`research.status`, `desktop_research.investigate`, `run.abort`, `state.apply_candidate`) rather than UI commands.

`HarnessServiceRegistry` contains typed handlers. The Coordinator contains no business SQL and never calls SQLite directly. State-changing handlers return a `StateTransitionRequest` which is passed to the existing `StateTransitionService`; Capability work goes only through `CapabilityExecutionService`.

## Context Pack and Invocation materialization

PR10 Capability routes require an exact PR9 Context Pack reference/digest. Therefore Context materialization happens at proposal construction from the authoritative current `StateView`, not in the resolver. The immutable materialization is persisted and execution reuses the same bytes.

The generic Coordinator knows only `CapabilityActionMaterializer`. Capability-specific context construction lives with the adapter. `DesktopResearchConversationMaterializer` projects the selected adopted RQ, current Project/Profile/Snapshot pins, bounded Research Attention/guards/constraints, and only pre-registered resource IDs into the PR9 Context Pack plus PR11 extension.

It does not dump SQLite, the project filesystem, historical Runs, Writer/Publication drafts, or unrelated archive material. A path/URL merely appearing in conversational text or payload grants no resource access. Resource registration + Context Pack inclusion + runtime authorization are all required.

## Desktop Research external route

The initial production route is:

`desktop_research.investigate -> PR9 Context Pack + PR11 extension -> exact PR9 Invocation -> PR24 DesktopResearchExternalAdapter -> CapabilityExecutionService.prepare_external`.

External execution receives the Run identity, immutable Context/extension stored by PR22-24, expected canonical output contracts, and bounded resource/artifact interfaces. Result collection always returns through `CapabilityExecutionService.collect_external`; the Coordinator does not call a normalizer or `StateTransitionService` directly.

Retrieval Attempt Ledger outcomes (`blocked`, `unavailable`, `failed`, `no_relevant_source`), coverage gaps, unknowns, partial coverage, and remaining information value remain in the structured Handoff/result. Human-facing prose is auxiliary and cannot replace those structured objects.

## Candidate and stale-result boundaries

A PR20 `StateDeltaProposal` produced by execution is persisted as candidate material and is never auto-committed. Handoff next-action/next-method candidates are projected only into PR10 Candidate Presentations and proposal-only Action Proposals with unresolved routes. A next Method candidate is never automatic Method selection.

Every proposal binds the exact current Research State and research pins. A changed HEAD makes later execution stale; automatic rebase is forbidden. PR22/24 stale Capability results retain execution trace but do not become authoritative state simply because execution succeeded.

## Persistence and composition

`plugins/local_conversation_store/` owns non-authoritative conversation operational persistence. It is a separate SQLite database from both `SQLiteResearchStateRepository` and `LocalExecutionStore`. Canonical input/proposal/confirmation/receipt/presentation documents are immutable; only pending/consumed/cancelled operational indexes mutate.

`plugins/local_application/LocalResearchApplication` is the explicit local composition root. It wires the SQLite Research State repository, StateTransitionService, LocalExecutionStore, CapabilityExecutionService, Desktop Research adapter/context validator/normalizer, LocalConversationStore, registries, resolver, clock, authorization provider, and Coordinator. Concrete imports occur only in this composition layer/adapters, not in `core/conversation/`.

Future Survey, Delphi, Case, or PoC production capabilities add an adapter, context materializer/validator, result validator/normalizer, and explicit registry registrations. The Research Coordinator itself should not change.

## Structured source, not private reasoning

Conversation persistence stores canonical structured inputs, proposals, confirmations, receipts, candidate presentations, materialization provenance, and explicit contractual rationale. It does not store private LLM chain-of-thought. Display prose is never an authority input for later actions.
