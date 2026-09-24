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
