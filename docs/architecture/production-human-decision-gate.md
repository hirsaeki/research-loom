# Production Human Decision Gate

PR26 adds the production authority path between a candidate `StateDeltaProposal` and an authoritative PR20 state commit.

## Three separate authorities

- **Conversation Confirmation** confirms that a Human intends to execute a typed conversational action. It is single-use operational consent and is never a Core Decision.
- **Runtime Authorization** controls whether a service/adapter/capability may execute and access bounded resources. It is not research authority.
- **Human Decision** resolves a PR20 `DecisionRequirement` for an exact state-bound transition. Only this path may materialize a Core `decision` object.

Natural-language text such as `OK`, `進めて`, a Conversation `CONFIRMATION`, LLM output, recommendation, vote, or majority result is not accepted by `HumanDecisionService.resolve()`. Resolution requires a structured response with an explicit disposition and a human actor identity.

## Source of truth

`core.runtime.authority_validation.required_decisions_for_action(current_state, action)` is the only source used to derive authority requirements. The Decision Gate does not duplicate the PR20 mapping.

Typical requirements include:

- `research_adoption / approve|reject`
- `research_revision / revise`
- `evidence_qualification / verify`
- `evidence_reclassification / reclassify`
- `lineage_plan / apply`
- `lineage_reconfirmation / reconfirm`
- `active_lineage_selection / switch`

## Request lifecycle

Human Decision Requests are operational documents, not Core Research Objects. They are bound to:

- project and lineage
- exact `StateDeltaProposal` ID/digest
- source Action Proposal ID/digest when present
- exact Snapshot ID/digest
- Project Config ref/digest
- Effective Profile Set ref/digest
- every target `TransitionAction` digest
- the complete derived DecisionRequirement-set digest

The local operational lifecycle is `PENDING -> RESOLVING -> RESOLVED|DECLINED|REVISION_REQUESTED|STALE|CANCELLED`. `RESOLVING` is an internal recovery state; externally meaningful terminal states are the PR26 states above.

Issuing a request creates no Core Decision, Snapshot, adoption, or lineage-head change.

## Structured response semantics

`approve_exact` approves exactly the request packet. It does not allow arbitrary partial editing. A partial change must use `request_revision` and produce a revised `StateDeltaProposal`.

`decline` means only that this proposed transition is not executed. It is not translated into `research_adoption/reject` and creates no Core Decision.

`request_revision` leaves Research State and the old candidate unchanged. It signals the upper conversational/application layer to construct a new proposal.

## Staleness

Before resolution, the service rechecks Snapshot HEAD, Project Config, Effective Profile Set, exact target-action digests, and the PR20-derived requirement set. Any mismatch fails closed as `STALE`.

There is no automatic rebase and no stale Decision carry-forward. A new request must be derived from the new state.

## Atomic Decision + target transition

On `approve_exact`, Core Decision IDs are deterministic from the request and grouped only when `(decision_kind, choice)` is identical. Subjects may be grouped; unlike kinds or choices are never mixed.

The service injects only the exact resolving Decision IDs into target `TransitionAction.decision_refs` and, where canonical object provenance supports it, `object.decision_ids`.

The resulting PR20 request is one atomic request:

```text
RECORD_DECISION DEC-X
RECORD_DECISION DEC-Y
TARGET ACTION A
TARGET ACTION B
```

`StateTransitionService` still owns validation and creates one `CommitBundle`. A Decision is never committed by itself before its target transition.

PR20's decision pool already recognizes `RECORD_DECISION` objects from the same request. PR26 uses that existing validator rather than bypassing it.

For PR19 `RECONFIRM`, the exact reconfirmation Decision is bound to all three existing locations: the lineage action's `decision_refs`, `treatment.human_decision_ref`, and the derived object's `decision_ids`.

The pure reducer remains restrictive for lineage actions: `APPLY_LINEAGE_PLAN` and `SWITCH_ACTIVE_LINEAGE` may be accompanied only by `RECORD_DECISION` actions, never by unrelated state mutations.

## Operational persistence and recovery

`plugins/local_decision_store/decision.db` is separate from authoritative Research State SQLite. It records requests, structured responses (including rejected attempts), lifecycle state, and the final PR20 `CommitReceipt` binding.

No cross-database distributed transaction is claimed. The sequence is:

1. validate exact request/response binding;
2. claim one response with `BEGIN IMMEDIATE`;
3. deterministically build the PR20 request;
4. commit through `StateTransitionService`;
5. finalize the operational request with the `CommitReceipt`.

If step 5 fails after Research State commit, the deterministic PR20 idempotency key/request digest allows the same response to recover the existing `CommitReceipt` and finalize the operational store. A different response for the same claimed/terminal request fails closed.

Concurrent approve/decline responses cannot both own the same request.

## `state.apply_candidate`

The production local application no longer accepts caller-supplied `decision_reference_ids` for the happy path. It accepts only `state_delta_proposal_id`.

The handler loads the exact immutable candidate and delegates to the Human Decision Gate:

```text
state.apply_candidate
  -> derive PR20 DecisionRequirements
     -> none: build ordinary exact StateTransitionRequest
     -> present: persist Human Decision Request and STOP with Research State unchanged
```

A later explicit structured Human response is resolved through `LocalResearchApplication.resolve_human_decision()`.

`research.status` includes pending Human Decision request IDs, source candidate binding, subjects, Decision kinds, Snapshot binding, and operational status. The Coordinator does not execute a next Research Capability merely because a Decision Request exists; upper routing can use this status to surface the authority blockage.

## Desktop Research nuance

PR24 Desktop Research deliberately normalizes observations into candidate-only Source/Evidence/Finding objects. PR20 decides whether those exact proposed actions require Human Decisions. PR26 does not invent an extra Desktop-specific approval rule merely to force a gate. If a Desktop-derived proposal later includes an adoption, material revision, Evidence verification/reclassification, or lineage authority action, the same generic gate derives and enforces the corresponding DecisionRequirements.

This preserves the core rule: authority requirements come from PR20 state semantics, not from capability identity or Coordinator preference.
