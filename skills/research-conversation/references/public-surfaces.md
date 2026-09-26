# Public surfaces for research conversation

Use public Facade/CLI operations. Do not make private SQLite or blob-layout inspection part of ordinary research conversation.

## Normal research conversation

On the public surfaces that support a view, **explicitly select the conversation view** for ordinary progress/resume/discovery/result interpretation. Do not rely on the omitted/default view for the normal host workflow; the omitted view intentionally remains the legacy exact/detail contract for compatibility.

| Need | Normal public surface | What it proves |
|---|---|---|
| Resume saved work | `resume --view conversation --json` | Bounded persisted checkpoint, pending workflow, Research Questions, and compact saved candidate meaning |
| Read current research status | `status --view conversation --json` | Current public status and pending decisions without raw target envelopes |
| Discover saved Recommendation/Argument | `synthesis-candidate list --view conversation --json` | Bounded discovery and semantic content; candidate position is not adoption |
| Inspect one saved synthesis candidate normally | `synthesis-candidate show --candidate-id ... --view conversation --json` | Semantic content/current relation for conversation |
| Inspect one Run | `run show --run-id ... --view conversation --json` | Run lifecycle, result availability, gaps, and relevant recovery state |
| Replay the supported completed Desktop Research path | `run replay --run-id ... --view conversation --json` | Result of that replay operation without making raw target envelopes normal conversation input |
| Execute a typed operation | `action submit --view conversation --json INPUT.json` | Result of that exact operation, interpreted narrowly |
| Continue an issued operation confirmation | `confirmation submit --view conversation --json INPUT.json` | Result of that exact confirmation; it is not research adoption |
| Resolve an already reviewed Human Decision | `decision resolve --view conversation --json INPUT.json` | Resolution/commit result for that exact Decision; current state still needs a fresh public read |
| Collect a Desktop Research result | `external collect --view conversation ...` | Run/normalization/result/gap meaning without raw candidate duplication |

Prefer the smallest read that answers the current question. `resume` is not a full audit log, and a bounded/truncated list does not prove older items do not exist. A conversation projection is presentation input, not a replacement canonical document.

## Minimal mutation inputs for the adoption path

These JSON shapes are **host-to-Loom transport contracts**, not wording to show to the human. Use the exact references returned by public Loom operations; do not guess field names, add invented fields, or substitute synonymous disposition words.

To start adoption of an already saved candidate, submit only the exact saved StateDeltaProposal reference in the action payload:

```json
{
  "action_type": "state.apply_candidate",
  "payload": {
    "state_delta_proposal_id": "<exact saved candidate_id>"
  },
  "actor_id": "<human actor id>"
}
```

Use this through `action submit --view conversation --json INPUT.json`. The `state_delta_proposal_id` is the public candidate/proposal reference returned by the save operation. Do not replace it with the research-object ID, a display number, or a reconstructed target. Decision references are derived by Loom and are not caller input to this action.

When Loom returns `CONFIRMATION_REQUIRED`, continue only that issued operation confirmation. The confirmation input accepts `confirmation_request_id` and optional `actor_id`; do not add action/candidate/decision fields:

```json
{
  "confirmation_request_id": "<exact issued confirmation_request_id>",
  "actor_id": "<human actor id>"
}
```

Use this through `confirmation submit --view conversation --json INPUT.json`. When the human actor is already known for the flow, preserve that exact actor identity rather than inventing a new one.

When Loom returns `HUMAN_DECISION_REQUIRED`, first read the immutable request with `decision show --request-id ... --json` and review its exact target/current context. The minimal Decision resolve input is exactly:

```json
{
  "request_id": "<exact issued request_id>",
  "request_digest": "<exact issued request_digest>",
  "disposition": "approve_exact",
  "actor_id": "<exact request human_actor_id>"
}
```

The supported `disposition` values are `approve_exact`, `decline`, and `request_revision`. Do not substitute `approve`, `APPROVE`, `adopt`, or other synonyms. `approve_exact` approves exactly the issued request packet; changing only part of it requires the revision path instead.

After `decision resolve --view conversation --json INPUT.json`, perform a fresh conversation-view `status` or `resume` read before describing the change as current. The exact input fields above are authority mechanics; ordinary human-facing progress should still use research meaning rather than exposing these opaque fields unless diagnostics are requested.

## Exact approval and diagnostic detail

Use exact detail only when its precision is required.

| Need | Exact public surface | Rule |
|---|---|---|
| Review an issued Human Decision before asking the human | `decision show --request-id ... --json` | Read the immutable issued request and its separate operational status. Use its exact `request_id` and `request_digest`; do not recreate the request from prose. |
| Recover the full persisted StateDeltaProposal named by an exact reference | `candidate show --candidate-id ... --json` | Returns the exact saved candidate without rebinding it to current state. Candidate target values are not current authority by themselves. |
| Explicit diagnostics on a view-capable surface | the same operation with `--view detail` (or Facade `view="detail"`) | Show requested IDs/digests/codes/bindings and explain them. Do not make detail the default ordinary-progress input. |

Before a Human Decision, the host must inspect the exact issued request and enough exact target/current research context to know what the answer will authorize. Human-facing numbering or summaries are never authority inputs. Bind resolution to the issued `request_id + request_digest + actor_id + disposition` required by the public Decision contract.

After resolution, a commit receipt proves the committed transition it names; it is not a substitute for a current-state read when the human asks what is current now.

## Public surfaces without conversation/detail views

These remain their existing contracts; do not invent view arguments for them:

- `actions --json` — registered typed actions/contracts.
- `external materials list --json` and material detail operations — captured-material facts and content-health semantics.
- specialized Survey/Delphi/Writer/Publication commands unless their own public contract explicitly adds a view.

If an operation is not covered by the conversation view, do not silently use a raw/detail payload as though it had been normalized for ordinary conversation. State that interpretation is not covered, or use the specific public detail only for an explicit diagnostic/authority need.

## Lost response or projection failure

If a mutation succeeded but its response was lost, or conversation projection reports unavailable, **read the resulting public state/detail**. Do not repeat the mutation merely to recover a display payload. Existing exact idempotent Decision recovery remains the authority-preserving path when its contract applies.
