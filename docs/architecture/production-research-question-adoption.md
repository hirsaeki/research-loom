# Production Research Question adoption

Production Research Question adoption has two bounded semantic ingress actions:

```text
research_question.propose       -> one RQ in one candidate-only StateDeltaProposal
research_question.propose_many  -> multiple RQs in one candidate-only StateDeltaProposal
```

Everything after proposal creation reuses the existing State Transition, Confirmation, and Human Decision path. PR33 adds no generic batch mutation API and does not weaken stale-candidate protection.

## Responsibility split

```text
Human + conversational operator
  form and refine one question or one intentional group of questions
        |
        v
research_question.propose / research_question.propose_many
  validate bounded caller input
  allocate Harness-owned RQ identities
  bind the exact current state
  persist one candidate-only StateDeltaProposal
        |
        | authoritative Research State is unchanged
        v
state.apply_candidate
        |
        v
one Confirmation for the exact candidate packet
        |
        v
existing Human Decision Gate
        |
        v
approve_exact
        |
        v
one atomic StateTransitionRequest
  RECORD_DECISION + CREATE_OBJECT(research_question) ...
        |
        v
one CommitBundle + one new immutable Research Snapshot
```

The conversational layer owns wording and Human intent. The Harness owns candidate structure, identity allocation, state binding, validation, Confirmation, Human Decision, and authoritative transition semantics.

## Action Registry semantics

Both proposal actions are non-authoritative operational writes:

```text
effect: read_only
route: harness_service
confirmation_required: false
human_decision_required: false
```

Here `read_only` means the action cannot mutate authoritative Research State. It may persist Conversation, Action Proposal, Action Receipt, and StateDeltaProposal records.

`research_question.propose` remains the single-RQ happy path and retains its existing contract unchanged.

## Single-RQ proposal

Minimal input remains:

```json
{
  "action_type": "research_question.propose",
  "payload": {
    "text": "企業はどの条件でAIへ意思決定を委ねるべきか"
  },
  "actor_id": "local-human"
}
```

The optional caller-owned fields remain:

```text
text
rationale
acceptance_criteria
scope_limits
parent_question_id
derived_from_seed_ids
```

Unknown fields and Harness-owned authority or identity fields are rejected.

## Multi-RQ proposal

PR33 adds only this RQ-specific bounded ingress:

```json
{
  "action_type": "research_question.propose_many",
  "payload": {
    "questions": [
      {"text": "中心RQ..."},
      {"text": "副RQ1..."},
      {"text": "副RQ2..."}
    ]
  },
  "actor_id": "local-human"
}
```

`questions` must contain at least two items. Use `research_question.propose` for one item. No arbitrary upper bound is added by PR33.

Every `questions[]` item accepts exactly the same caller-owned fields as the existing single proposal. Caller-supplied RQ IDs, project IDs, revisions, adoption state, Decision references, Snapshot or profile pins, commit IDs, authoritative timestamps, transition vocabulary, and all other unknown fields are rejected.

This is intentionally not a generic StateDelta or generic batch ingress.

## All-or-nothing proposal validation

`research_question.propose_many` validates the complete group before persisting a StateDeltaProposal:

```text
1. resolve the current authoritative state once
2. determine the current Project Config / profile / lineage binding
3. validate every questions[] item
4. validate every seed and parent reference against that current state
5. only after all members are valid, allocate Harness-owned RQ IDs
6. materialize all Core RQ candidate values
7. persist one StateDeltaProposal
```

If any member is invalid, no partial StateDeltaProposal is stored and authoritative Research State remains unchanged. ID-provider sequence consumption is not an external contract.

Each generated RQ receives an independent `RQ-...` identity from the same Harness-owned ID provider used by the single path. Response ordering follows input ordering.

## Project Config seeds are pre-adoption material

`Project Config.research_questions.seeds[]` remains question-formation material rather than authoritative Research State or Evidence.

For both single and multi-RQ proposal paths, `derived_from_seed_ids` must resolve in the current Project Config. Batch provenance preserves both the aggregate configured seed references and their generated-RQ bindings. Seeds are not promoted to Core Source or Evidence objects and are not Runtime Authorization resources.

## Parent Research Questions

`parent_question_id`, when supplied, must already resolve to a current authoritative approved Research Question in the same project at proposal time.

PR33 deliberately does not add batch-local symbolic references. A new RQ in `questions[1]` cannot refer to the newly generated RQ in `questions[0]` as its parent in the same proposal. That capability, if needed, is separate future work.

## One existing StateDeltaProposal

A single proposal uses one existing `CREATE_OBJECT(research_question)` action.

A multi-RQ proposal uses one existing `StateDeltaProposal` containing multiple existing actions:

```text
StateDeltaProposal SDP-X
  CREATE_OBJECT RQ-A
  CREATE_OBJECT RQ-B
  CREATE_OBJECT RQ-C
  CREATE_OBJECT RQ-D
  CREATE_OBJECT RQ-E
```

No new TransitionKind or RQ-specific commit vocabulary is introduced.

The batch has one shared binding to:

- project and active lineage,
- exact current Snapshot ID and digest,
- current Project Config ref and digest,
- the source Action Proposal and Conversation Input, and
- one canonical StateDeltaProposal digest covering all target actions.

The proposal is `candidate_only=true`, so proposal creation does not change authoritative Research State.

## Adoption reuses `state.apply_candidate`

There is no batch-specific adoption action. Both proposal forms use:

```json
{
  "action_type": "state.apply_candidate",
  "payload": {
    "state_delta_proposal_id": "SDP-X"
  }
}
```

`state.apply_candidate` remains Confirmation-gated. A multi-RQ candidate produces one Confirmation Request because Confirmation binds the exact candidate packet, not each target action separately.

## Existing Human Decision grouping

After Confirmation, the existing authority validator derives one requirement per protected RQ action:

```text
decision_kind = research_adoption
choice = approve
subject = exact generated RQ ID
```

The existing PR26 Human Decision Gate groups requirements with the same `(decision_kind, choice)` into one Human Decision Request. Therefore a five-RQ candidate is represented conceptually as:

```text
research_adoption / approve
subjects:
  RQ-A
  RQ-B
  RQ-C
  RQ-D
  RQ-E
```

PR33 does not add a new Decision kind, Confirmation model, Human Decision model, or per-RQ Decision Request API.

## `approve_exact` is batch-exact

For a multi-RQ request, `approve_exact` approves the complete exact candidate. Partial approval is not supported.

The existing Decision Service materializes one authoritative research-adoption Decision and binds its Decision ID to each approved RQ action. The existing State Transition service then receives one request containing:

```text
RECORD_DECISION
CREATE_OBJECT RQ-A
CREATE_OBJECT RQ-B
CREATE_OBJECT RQ-C
CREATE_OBJECT RQ-D
CREATE_OBJECT RQ-E
```

Successful resolution produces one CommitBundle and advances to one new immutable Snapshot containing all target RQs. Transition failure leaves zero target RQs authoritative; PR33 adds no new transaction mechanism because the existing State Transition boundary is already atomic.

`decline` and `request_revision` remain terminal operational outcomes that do not change authoritative Research State. `request_revision` does not mutate the old candidate. The conversational layer must create a new proposal for revised content.

## Exact stale semantics are unchanged

A single or batch StateDeltaProposal is bound to the exact current authoritative state. Existing stale validation remains authoritative:

```text
S0
  -> propose_many -> SDP-X bound to S0
S0
  -> unrelated authoritative transition -> S1
SDP-X apply/resolve against S1 -> fail closed
```

PR33 performs no automatic rebase, carry-forward, semantic conflict analysis, Snapshot-mismatch relaxation, stale Decision reuse, candidate action rewriting, or generated-ID copying into a replacement candidate.

**This PR does not relax stale-candidate protection.**

The purpose of batching is to represent one Human intent atomically before it becomes stale, not to make stale candidates reusable.

## Resume representation

The PR31 resume surface remains a read model. Single-RQ candidate rows keep their existing shape with a singular `question` field.

A PR33 candidate is returned once, not once per contained RQ. Its additive batch shape includes:

```text
state_delta_proposal_id
proposal_digest
batch_size
questions[]
bound_snapshot
bound_to_current_snapshot
authoritative_same_ids
source_action_proposal
pending_confirmation_request_ids
human_decision_requests
```

`questions[]` preserves the generated RQ IDs and texts in proposal order. `bound_to_current_snapshot` applies to the whole packet. This prevents an operator from mistaking one multi-RQ proposal for independently adoptable candidates.

## Production CLI usage

PR33 adds no top-level CLI command and does not change the JSON envelope. Use the repository launcher and the existing generic action ingress.

Windows / PowerShell:

```powershell
.\research-loom.cmd action submit `
  --workspace <WORKSPACE> `
  --json rq-batch-proposal.json
```

POSIX:

```bash
./research-loom action submit \
  --workspace <WORKSPACE> \
  --json rq-batch-proposal.json
```

Runtime bootstrap details such as direct `uv run --frozen python ...` invocation are developer implementation details rather than operator-facing production syntax.

## Preserved single-RQ semantics

PR33 does not change the existing single-RQ behavior for:

- Harness-owned generated identity,
- candidate-only persistence,
- seed provenance,
- authoritative-parent validation,
- no Research State mutation at proposal time,
- Confirmation,
- Human Decision,
- `approve_exact`, `decline`, and `request_revision`, and
- stale fail-closed behavior.

## Explicit non-goals

PR33 does not add:

```text
generic batch mutation API
arbitrary StateDelta caller ingress
automatic candidate rebase
semantic conflict detection
stale Decision carry-forward
partial batch approval
batch-local symbolic parent references
adopted RQ revision
RQ closure / rejection workflow
Source / Evidence batch adoption redesign
Desktop Research redesign
new State Transition vocabulary
new Decision kind
new Confirmation model
new Human Decision model
```

The production use case is deliberately narrow: when a Human decides that several Research Questions form one adoption intent, the Harness can now represent and commit that intent as one exact authoritative candidate.
