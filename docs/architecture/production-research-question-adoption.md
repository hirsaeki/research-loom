# Production Research Question adoption

PR29 adds one production semantic ingress to the local application:

```text
research_question.propose
    -> candidate-only StateDeltaProposal
```

Everything after that boundary reuses the existing State Transition, Confirmation, and Human Decision path.

## Responsibility split

```text
Human + ChatGPT Work
  form and refine the question
        |
        v
research_question.propose
  validate bounded candidate input
  allocate Harness-owned RQ identity
  bind provenance and current state
  persist candidate-only StateDeltaProposal
        |
        | Research State is unchanged
        v
state.apply_candidate
        |
        v
PR10 Confirmation
        |
        v
PR26 Human Decision Request
  dynamic PR20 research_adoption / approve requirement
        |
        v
approve_exact
        |
        v
RECORD_DECISION + CREATE_OBJECT(research_question)
  one atomic authoritative transition
        |
        v
new immutable Research Snapshot
```

Work or another conversational operator owns question formation and wording. The Harness does not contain an RQ extraction, distillation, planning, or generation model. The Harness owns candidate structure, identity allocation, current-state binding, validation, Confirmation, Human Decision, and authoritative commit semantics.

## Project Config seeds are pre-adoption material

`Project Config.research_questions.seeds[]` is question-formation material. A seed is not an authoritative Core Research Question and workspace bootstrap never promotes it automatically.

`research_question.propose` may receive `derived_from_seed_ids`. Every supplied ID must resolve to the current Project Config. The IDs are recorded as candidate provenance only.

They are deliberately not projected into:

- Core `source` objects,
- Core `evidence` objects,
- `StateDeltaProposal.source_refs`,
- Runtime Authorization evidence, or
- capability resource authorization.

A configured seed is provenance for forming a question, not research Evidence.

## Conversation material is not Evidence

Material pasted or attached to ChatGPT Work can inform question formation, but PR29 does not promote conversation material to a Core Source or Evidence object. If material later supports a research claim, it must enter through the appropriate Source/Evidence path, such as Desktop Research and its normalization/adoption boundary.

## `research_question.propose`

The production Action Registry exposes:

```text
action_type: research_question.propose
effect: read_only
route: harness_service
confirmation_required: false
human_decision_required: false
```

Here `read_only` means the action cannot mutate authoritative Research State. It may persist operational Conversation, Action Proposal, and StateDeltaProposal records.

Minimal payload:

```json
{
  "text": "企業はどの条件でAIへ意思決定を委ねるべきか"
}
```

Optional candidate material:

```json
{
  "text": "企業はどの条件でAIへ意思決定を委ねるべきか",
  "rationale": "研究テーマと幹事期待を意思決定条件へ蒸溜した。",
  "acceptance_criteria": [
    "委任レベルを比較可能に説明できる",
    "人間承認が必要な条件を示せる"
  ],
  "scope_limits": [
    "AGI実現時期そのものの予測は対象外"
  ],
  "parent_question_id": null,
  "derived_from_seed_ids": [
    "RQ-SEED-001"
  ]
}
```

Unknown fields are rejected. Harness-owned fields such as RQ ID, project ID, revision, adoption state, Decision references, transition vocabulary, state pins, commit IDs, and authoritative timestamps cannot be supplied by the caller.

The handler allocates `RQ-...` through the configured `id_provider` and materializes a complete Core candidate whose desired authoritative value has:

```text
kind = research_question
revision = 0
project_id = current project
adoption_state = approved
```

`approved` describes the value that would exist if Human Decision approves the exact candidate. The object is not authoritative at proposal time.

When `parent_question_id` is present it must resolve to a current authoritative Research Question in the same project. The handler never fabricates a parent from an ID.

## Candidate-only StateDeltaProposal

The proposal action builds the existing PR20 `StateDeltaProposal` model with an existing `CREATE_OBJECT` action. No RQ-specific transition vocabulary is introduced.

The candidate carries:

- Harness-generated StateDeltaProposal identity,
- current project and active lineage,
- current Snapshot ID and digest,
- exact proposed Core Research Question,
- affected RQ reference,
- rationale,
- producer/action/input provenance,
- current Project Config ref and digest,
- optional Project Config seed provenance,
- canonical proposal digest, and
- `candidate_only=true`.

It is persisted with the existing Conversation Store `store_state_delta_proposal()` operation. There is no QuestionRepository, candidate database, or RQ draft table.

Keeping pre-adoption candidates out of Research State avoids treating conversational drafts as authoritative research objects and keeps the immutable Snapshot history focused on adopted research state.

## Adoption uses `state.apply_candidate`

PR29 does not add `research_question.approve`, `research_question.commit`, or `research_question.adopt`.

Work takes the returned `state_delta_proposal_id` and submits:

```json
{
  "action_type": "state.apply_candidate",
  "payload": {
    "state_delta_proposal_id": "SDP-..."
  }
}
```

`state.apply_candidate` retains its existing PR10 Confirmation requirement. Submitting the typed action is not Confirmation.

After explicit Confirmation, the existing PR20 authority validator examines the exact `CREATE_OBJECT(research_question)` candidate. Because the new object has `adoption_state=approved`, `required_decisions_for_action()` derives:

```text
decision_kind = research_adoption
choice = approve
subject = exact generated research_question ID
```

PR29 does not hard-code that requirement or build an RQ-specific Human Decision request.

The existing Decision Request `candidate_value` carries the exact RQ content, including its rationale, acceptance criteria, scope limits, parent, and candidate provenance context. Confirmation and Human Decision remain separate authority events.

## Work-friendly Human Decision input

The existing `decision resolve` command still accepts a complete canonical Human Decision response. PR29 additionally lets the Application Facade accept this explicit minimal intent:

```json
{
  "request_id": "HDREQ-...",
  "request_digest": "sha256:...",
  "disposition": "approve_exact",
  "actor_id": "local-human"
}
```

Allowed dispositions remain exactly:

```text
approve_exact
decline
request_revision
```

For minimal intent, the Facade:

1. loads the exact stored request,
2. checks the supplied request digest,
3. checks the request belongs to the Facade project,
4. checks the explicit disposition and bound human actor,
5. obtains `responded_at` from the Harness clock,
6. calls existing `make_response()` to generate canonical response identity and digest, and
7. passes that response to existing `HumanDecisionService.resolve()`.

No natural-language approval inference is added. Work only converts a Human's explicit response into the typed intent.

## Approval, decline, and revision request

`approve_exact` uses the existing Human Decision service to materialize an authoritative Core Decision, bind its ID to the RQ, and submit `RECORD_DECISION + CREATE_OBJECT` in the same state transition. Successful resolution creates a new immutable Research Snapshot containing the approved RQ.

`decline` and `request_revision` are terminal operational outcomes for that Decision Request. They do not create the RQ and do not move the Research Snapshot HEAD. The historical candidate may remain in the operational store. After a revision request, Work and the Human can refine the wording and create a new `research_question.propose`; PR29 does not try to reuse pre-adoption candidate identity.

Revision, closure, and out-of-scope workflows for an already authoritative RQ remain future work.

## Stale candidates

A StateDeltaProposal is bound to the exact current Snapshot. Existing Human Decision candidate validation and Decision Request snapshot binding fail closed if the lineage HEAD or configuration pins change. PR29 performs no automatic rebase and does not copy an old candidate onto a new HEAD. Work must create a new proposal against the new authoritative state.

## Persistence across Work command invocations

Every command may be a separate OS process. Durable Conversation and Decision stores therefore preserve the path:

```text
process A: research_question.propose
process B: state.apply_candidate
process C: confirmation submit
process D: decision resolve
process E: research.status
```

No part of candidate identity, Confirmation, or Human Decision resolution depends on in-memory-only state.

## Work + frozen uv + temporary JSON files

Production Work execution continues to use the repository-root frozen environment:

```powershell
uv run --frozen python research-loom ...
```

Because command-execution stdin can remain at EOF waiting boundaries, structured input can be written as a UTF-8 temporary JSON file.

Example proposal file `rq-proposal.json`:

```json
{
  "action_type": "research_question.propose",
  "payload": {
    "text": "企業はどの条件でAIへ意思決定を委ねるべきか",
    "derived_from_seed_ids": ["RQ-SEED-001"]
  },
  "actor_id": "local-human"
}
```

Submit it with:

```powershell
uv run --frozen python research-loom action submit `
  --workspace <WORKSPACE> `
  --json rq-proposal.json
```

Use the returned StateDeltaProposal ID in a second file for `state.apply_candidate`; submit the returned Confirmation Request ID with `confirmation submit`; then write the explicit minimal Human Decision intent to another UTF-8 JSON file and call `decision resolve`.

The stdin form remains supported; PR29 does not redesign CLI I/O.

## Intended conversational UX

The CLI and JSON boundary is infrastructure, not the normal Human-facing interface.

```text
Human:
  このテーマでまず問いを整理したい。資料と幹事期待はこれ。

Work:
  論点を整理すると主RQ候補はAです。ただし範囲を限定する案を勧めます。

Human:
  それで。

Work:
  [research_question.propose]
  候補を保存しました。Research Stateはまだ変更されていません。

Work:
  この候補をResearch Stateへ適用する確認が必要です。実行しますか？

Human:
  はい。

Work:
  [confirmation submit]
  この正確なRQを研究上の正式な問いとして採択しますか？

Human:
  採択する。

Work:
  [decision resolve / approve_exact]
  [Decision + RQ are committed atomically]
```

At that point `research.status` can return the approved authoritative RQ and downstream Desktop Research has a legitimate research question to target.

## Explicitly outside PR29

PR29 does not add an RQ LLM, generic CRUD API, arbitrary StateDelta ingress, adopted-RQ revision, automatic Source/Evidence ingestion, attachment ingestion, Desktop Research behavior changes, managed browsing/search, survey/Delphi/case/virtual-runner functionality, Writer/Publication runtimes, MCP/WebMCP, OneDrive integration, Profile resolution, new Core TransitionKind values, or new Confirmation/Human Decision models.
