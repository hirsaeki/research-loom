# Production research resume context

## Purpose

`status` is intentionally a small health/status surface for the local workspace, current authoritative Research State, and pending operational boundaries. `resume` is the richer read-only projection used to continue an ordinary research conversation without reconstructing progress from Git history, prior chat memory, or raw SQLite.

```text
existing production stores
        ↓
bounded project-scoped reads
        ↓
LocalApplicationFacade.resume_context()
        ↓
research-loom resume --workspace <WORKSPACE> --json
```

The projection remains a read model only. It does not create a Research Stage, next-step model, persisted resume state, Core Research Object, Transition kind, Decision kind, database, or cache.

## Public surface

Use:

```python
facade.resume_context()
```

or the production repository launcher.

Windows / PowerShell:

```powershell
.\research-loom.cmd resume `
  --workspace <WORKSPACE> `
  --json
```

POSIX:

```bash
./research-loom resume \
  --workspace <WORKSPACE> \
  --json
```

`resume` takes no structured input. It does not create a Conversation Input, Action Proposal, Action Receipt, Confirmation, Human Decision, or Capability Run.

## Projection contents

The response keeps authoritative and non-authoritative material separate:

- `project`: Project Config identity, objective, and scope.
- `research_state`: current lineage, Snapshot, Project Config, and Effective Profile Set bindings.
- `research_questions.seeds`: Project Config pre-adoption seeds.
- `research_questions.authoritative`: current authoritative Research Questions only.
- `research_questions.candidates`: persisted bounded RQ proposal candidates from both the single and multi-RQ ingress paths.
- `research_attention`: baseline, active/effective guidance, and stored maps.
- `workflow`: pending Confirmations, pending Human Decisions, pending Runs, and recent terminal Runs.
- `truncated`: explicit flags for bounded collections.

Candidate rows are not semantically deduplicated or promoted merely because they exist. Human Decision history is reported as persisted rather than reinterpreted.

## Bounded reads

The PR31 production bounds remain unchanged:

| Collection | Default bound |
| --- | ---: |
| authoritative Research Questions | 100 |
| Research Question candidates | 100 |
| Attention Maps | 50 |
| activation references per stored Attention Map | 100 |
| pending Human Decisions | 100 |
| Human Decision history used for candidate correlation | 100 |
| pending Confirmations | 100 |
| pending Runs | 100 |
| recent terminal Runs | 20 |

PR33 does not add pagination or a generic query framework. Single and batch RQ candidates share the existing `research_question_candidates` bound and are combined into one newest-first bounded collection.

The Conversation Store retains the existing `state_delta_proposals(proposal_id, payload_json)` schema. PR33 requires no workspace migration or new candidate table.

Unreadable or invalid persisted candidate/binding data fails closed. Resume must not silently omit malformed progress and return a misleading healthy summary.

## Single-RQ candidate representation

The existing PR29/PR31 single candidate is still identified by:

- `candidate_only = true`,
- `provenance.producer = research_question.propose@0.1.0`,
- exactly one `CREATE_OBJECT(research_question)`, and
- a matching `affected_refs` identity.

Its existing output shape is preserved, including the singular:

```text
question
```

and the existing fields for candidate identity, bound Snapshot, `bound_to_current_snapshot`, `authoritative_same_id`, source Action Proposal, pending Confirmation IDs, and Human Decision history.

## Multi-RQ candidate representation

PR33 adds recognition of the bounded producer:

```text
provenance.producer = research_question.propose_many@0.1.0
```

A valid batch candidate must:

- be `candidate_only=true`,
- contain at least two actions,
- contain only `CREATE_OBJECT(research_question)` target actions,
- contain unique generated RQ IDs,
- have `affected_refs` that exactly match those RQs in proposal order,
- retain one exact Snapshot binding for the complete packet, and
- resolve to a source Action Proposal whose action type is `research_question.propose_many` and whose digest matches the stored binding.

A multi-RQ proposal is projected as **one candidate row**, never one row per RQ:

```json
{
  "state_delta_proposal_id": "SDP-X",
  "proposal_digest": "sha256:...",
  "batch_size": 5,
  "questions": [
    {"id": "RQ-A", "text": "Main RQ", "revision": 0},
    {"id": "RQ-B", "text": "G1", "revision": 0},
    {"id": "RQ-C", "text": "G2", "revision": 0},
    {"id": "RQ-D", "text": "M1", "revision": 0},
    {"id": "RQ-E", "text": "M2", "revision": 0}
  ],
  "bound_snapshot": {
    "snapshot_id": "SNAP-...",
    "content_digest": "sha256:..."
  },
  "bound_to_current_snapshot": true,
  "authoritative_same_ids": [],
  "source_action_proposal": {
    "proposal_id": "PROP-...",
    "created_at": "..."
  },
  "pending_confirmation_request_ids": [],
  "human_decision_requests": []
}
```

The actual question projections also preserve the same optional RQ fields as the single path, such as rationale, parent, acceptance criteria, scope limits, adoption state, and Decision IDs when present.

`batch_size` and `questions[]` make the Human intent explicit: the StateDeltaProposal is one atomic candidate containing several RQs. The UI/operator must not infer that each RQ can be independently applied from this row.

## Current and stale binding

`bound_to_current_snapshot` is evaluated once for the entire candidate packet:

```text
candidate Snapshot ID == current Snapshot ID
AND
candidate Snapshot digest == current Snapshot digest
```

After any authoritative HEAD advance, an old batch therefore becomes visibly stale as a whole. Resume does not rebase it, copy generated RQ IDs into a replacement proposal, or infer that only some actions remain usable.

If an approved batch is still present in operational history after its successful commit, `authoritative_same_ids` reports which exact generated RQ IDs now exist in authoritative state. Its original Snapshot binding is historical and therefore no longer current after the successful Snapshot advance.

## Confirmation and Human Decision correlation

Pending Confirmation Requests are correlated through their exact `state.apply_candidate` Action Proposal binding.

Human Decision Requests are correlated through their exact `source_state_delta_proposal` ID and digest. The same mechanism works for single and batch candidates. A batch still has one Confirmation and one grouped Human Decision Request; resume does not synthesize one request per RQ.

## Research Attention and execution

PR33 does not change Research Attention or Capability Run projection semantics. Baseline/effective Attention still uses the existing provider, stored Attention Maps remain factual history, and recent Runs report execution facts only.

A completed capability Run does not imply that a Research Question, Evidence item, Finding, or other research object is authoritative.

## No workflow inference

Resume returns facts, not workflow conclusions. It does not add fields such as:

```text
stage
phase
next_step
recommended_action
inferred_blocker
```

The conversational operator interprets the returned facts in ordinary research language.

## Operator guidance

Use the public resume surface as the primary source of saved research progress. Do not reconstruct normal progress from repository internals, raw SQLite, Git history, or prior chat threads unless resume reports an inconsistency or the Human explicitly asks for diagnosis.

Research Loom remains a backend control plane rather than normal conversational vocabulary. For example, a multi-RQ candidate can be summarized to the Human as:

> 中心RQと4つの副RQは、5件まとめて採択する1つの候補として保存済みです。まだ正式採択前です。

If that batch is stale, say that the saved group is bound to an earlier authoritative state and must be proposed again before adoption; do not imply that individual members can be carried forward automatically.
