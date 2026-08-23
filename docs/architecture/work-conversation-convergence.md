# Work Conversation / Research Coordinator convergence

PR 10 establishes the implementation-neutral interaction boundary that lets a Human use natural language around the canonical Research Harness without turning chat into a second source of research authority. It builds on PR 3–9, especially PR 8 Project Config and PR 9 Research Capability Invocation/Handoff. Both legacy trees remain unchanged.

## Canonical boundary

The conversation layer has five closed input classes: `QUERY`, `PROPOSAL`, `COMMITTABLE_ACTION`, `CONFIRMATION`, and `CANCEL`. Natural-language text is input material only. It never directly becomes Evidence, a Research State patch, a Human Decision, a Capability result, or an authoritative Handoff.

The canonical machine boundary is:

```text
ConversationInput
  -> ActionProposal
    -> [ConfirmationRequest -> ConfirmationReceipt]
      -> Harness service
      or PR9 Capability Invocation
        -> [PR9 Capability Handoff]
      -> ActionReceipt
```

PR9 Handoff `candidate_next_actions` and `candidate_next_methods` may additionally be surfaced as a `CandidatePresentation` and a proposal-only `ActionProposal`. Presentation is not commitment or adoption.

## Typed Action Proposal, not a canonical action enum

Legacy Work Conversation used a concrete `ConversationActionType` containing status, decision recording, Work submission, recovery, Attention intake and archive operations. PR 10 deliberately does not promote that vocabulary.

A canonical `ActionProposal` instead carries a namespaced action identifier, `read_only` or `state_changing` effect, explicit payload contract and digest, `proposal_only` or `commit_requested` mode, confirmation policy, Human Decision boundary, current-state binding and applicable research pins, plus one route: Harness service, PR9 Capability Invocation, or deliberately unresolved proposal-only material.

This leaves recovery, archive, Attention intake, workspace lifecycle, Survey, Case, Delphi, Desktop Research and future adapters free to define their own action vocabulary while sharing one interaction safety contract.

## Read-only, proposals, and commitment

A resolved `QUERY` is read-only: no confirmation, no Research State mutation, and identical before/after state in its receipt. A `PROPOSAL` is never executable. `COMMITTABLE_ACTION` makes an explicit typed action eligible for commitment; state-changing actions must first issue a Confirmation Request.

The conversation layer does not decide whether an RQ answer is correct, Evidence is qualified, a Finding is adopted, or a Research Method is selected. Those remain Human/Core authority boundaries.

## Confirmation is not Human Decision

The reusable legacy property is preserved: confirmation is exact, state-bound, expiring, single-use, and fail-closed. A Confirmation Request binds the proposal digest, Human actor, action type and exact payload digest, current state identity/revision/digest, and applicable Project Config / Effective Profile Set / Research Snapshot pins.

Missing, stale, mismatched, ambiguous, duplicate/replayed, expired, or unknown confirmation attempts fail closed. Confirmation only authorizes an already typed action attempt; `confirmation_is_human_decision` is always false. It cannot substitute for RQ-answer adoption, Evidence qualification/reclassification, Finding adoption, Research Method selection, or other Human-owned transitions.

## PR 9 Capability routing

Conversation defines no second Capability path. A Capability-routed proposal identifies the intended Capability/function/mode and bounded Context Pack and binds the expected research context. It does not contain or mint runtime authorization evidence.

Actual execution must materialize `capability-invocation@0.1.0`; PR9 remains responsible for separate opaque runtime authorization evidence. Capability availability and Project Config permission hints remain descriptive only. The Action Receipt binds the actual PR9 Invocation ID/digest and, when produced, the structured PR9 Handoff ID/digest. Conversational prose cannot replace either contract.

## Handoff candidates

PR9 candidate next actions/methods are surfaced by binding the exact Handoff digest and candidate proposal ID. Display prose is non-authoritative; the resulting proposal remains `proposal_only`; no route is selected merely to make it runnable. A candidate next method retains `human_decision_boundary.required = true`. Method/capability selection requires a later Human-owned decision and, if execution is requested, a separate committable action.

## Cancellation versus abort

`CANCEL` targets only an identified still-pending proposal or Confirmation Request. It produces an immutable cancelled receipt, performs no execution, preserves bound state, and never rewinds prior Runs, Decisions, Research Snapshots, or receipts.

Aborting an already active Run is not implicit `CANCEL` behavior. If exposed conversationally it is a distinct typed state-changing Harness action that follows the same proposal/confirmation/receipt boundary. Concrete abort/recovery/workspace-lifecycle semantics are deferred.

## Audit

Every executed, rejected, failed, or cancelled state-changing attempt is represented by an immutable digest-bound `ActionReceipt` that records actor, exact action/proposal binding, before/after state, applicable research pins, confirmation where required, execution route, trace identity, and completion time.

## Legacy convergence decisions

Promoted from legacy `work-conversation`, `attention-intake`, `WORK_RESEARCH_COORDINATOR.md`, and their tests: Work/chat is an interface to Harness authority; the five input classes are closed; natural language proposes rather than mutates; state-changing commitment is Human-confirmed and state-bound; Work cannot infer next phase/method; structured Handoff/result contracts cannot be replaced by prose; Human Decision is a hard stop; and CLI, interactive Work, and future adapters share the same underlying Harness boundaries.

Not promoted: the legacy concrete action enum; `REGISTER_ATTENTION_DROP`; recovery/archive/workspace lifecycle semantics; concrete Work exchange paths or CLI syntax; Work UI behavior; a runtime coordinator, permission engine, state store, transport, or fixed expiry duration.

## Executable fixture boundary

`core/fixtures/conversation/valid/generic-conversation-flow.json` covers read-only status, proposal/cancel, committable Capability execution through exact confirmation and PR9 Invocation/Handoff, and proposal-only presentation of PR9 next-action/next-method candidates. `tests/contracts/conversation_oracle.py` is fixture-only executable specification, not a production classifier/coordinator/confirmation service/authorization engine/state reducer.

PR 10 does not implement Work UI automation, a concrete runtime coordinator, Desktop Research/Survey/Case/Delphi/Virtual Runner policy, SQLite, recovery/archive, Writer/Publication, or legacy deletion.
