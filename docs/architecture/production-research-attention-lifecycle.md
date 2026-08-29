# Production Research Attention lifecycle

## Status

PR30 adds a production lifecycle for project-local Research Attention discovered during Human / ChatGPT Work conversation. It preserves the PR8 semantic boundary and keeps Project Config immutable while allowing later research work to use versioned effective guidance.

The only new runtime concepts are:

```text
immutable Attention Map + active pointer + Effective Research Attention projection
```

There is no Core Attention object, new TransitionKind, Human Decision kind, Project Config revision system, or generic guidance workflow engine.

## Semantic boundary

Research Attention is project-local guidance for issues that should remain visible while question formation, coverage, and interpretation evolve. It is not:

- Research Evidence or a Core Source;
- a Finding or Research Question;
- answer authority;
- Research Method selection authority;
- Publication release authority; or
- Runtime Authorization.

It is also more durable than an untracked conversational note: active, dropped, and out-of-scope items remain explicit so that an issue cannot disappear silently.

## Project Config baseline and Effective Research Attention

`Project Config.research_attention` remains the immutable baseline established at workspace/project configuration time. Runtime Attention evolution never rewrites `project-config.json` and never changes the Project Config digest.

Effective Research Attention is deliberately simple:

```text
no active Attention Map
    -> Project Config.research_attention

active Attention Map exists
    -> active_map.items
```

An Attention Map is a complete effective snapshot, not a delta overlay. A new candidate is built by copying the current Effective Research Attention and applying bounded operations. Runtime reads therefore do not traverse or merge an override chain.

## Immutable Attention Map

`projects/contracts/research-attention-map.schema.json` owns the runtime map envelope without promoting it into the Core Research Object contract.

Each map binds:

- Harness-owned `map_id`;
- current `project_id`;
- exact Project Config ref/digest;
- exact guidance base;
- a complete `items` array;
- source Action Proposal ID/digest;
- source Conversation Input ID;
- creation time; and
- `map_digest`.

The digest is calculated by omitting `map_digest`, serializing the remaining document with RFC 8785 JCS, hashing with SHA-256, and encoding as `sha256:<hex>`.

Stored map bytes are immutable. Reusing an existing `map_id` as an overwrite is rejected.

### Item semantics are not redefined

The map contract repeats the existing Project Config `attention_item` definition exactly. The fields remain:

```text
attention_id
statement
rationale
source_reference_ids
related_question_ids
related_question_seed_ids
disposition
disposition_reason
projection_hints
```

Contract tests pin the map definition to the Project Config definition so that one side cannot silently gain different semantics.

## Candidate proposal

The production registry exposes:

```text
research_attention.propose
  effect: read_only
  route: harness_service
  confirmation_required: false
  human_decision_required: false
```

`read_only` means that proposing guidance cannot mutate authoritative Research State. It may persist an operational candidate Attention Map.

Work does not submit an arbitrary complete map. The bounded payload contains one or more of:

- `additions`;
- `dispositions`; and
- `links`.

For additions the Harness allocates `ATT-...`, sets `disposition=active`, supplies project/map identity, and computes the map digest. Caller-supplied Attention identity or disposition is rejected.

Existing Attention identity remains stable. An existing item may only change:

- `disposition` and `disposition_reason`;
- `related_question_ids`; and
- `related_question_seed_ids`.

`statement`, `rationale`, `source_reference_ids`, and `projection_hints` are not rewritten in place. A semantic replacement is represented as an explicit disposition of the old item plus a new addition.

The builder starts from the complete current Effective Research Attention. Existing active, dropped, and out-of-scope items therefore carry forward automatically. A caller cannot remove an existing Attention item by omission.

## Reference integrity

Map creation fails closed unless:

- every `source_reference_id` resolves in current Project Config `resource_references`;
- every `related_question_seed_id` resolves in current Project Config seeds; and
- every `related_question_id` resolves to a current authoritative Research Question in the project.

A registered resource reference remains only a reference. It is not promoted to Core Source/Evidence and does not grant runtime access.

Conversation provenance is similarly separate from Evidence. An issue discovered in ChatGPT Work is bound to its Action Proposal and Conversation Input, but that conversation is not automatically promoted into Source or Evidence.

## Persistence and workspace compatibility

The local composition uses a fixed optional store:

```text
.research-loom/attention.sqlite3
```

It is deliberately absent from the `workspace_version=0.1.0` binding layout. Existing PR27-29 workspaces therefore remain compatible.

Behavior is additive:

- opening an older workspace does not require the Attention store;
- absent store means baseline-only guidance;
- reads do not create the store;
- the first Attention write initializes it at the fixed local path;
- Research State, Conversation, and Human Decision databases remain separate; and
- callers cannot select an Attention database path.

`doctor` treats absence as a valid baseline-only state. If the store exists, doctor performs read-only SQLite/schema validation and does not create, migrate, or repair it.

## Activation and optimistic base binding

The production registry exposes:

```text
research_attention.activate_candidate
  effect: state_changing
  route: harness_service
  confirmation_required: true
  human_decision_required: false
```

A candidate created from the Project Config baseline can activate only while no active map exists. A candidate created from active map X/digest Y can activate only while the current pointer is still exactly X/Y.

A mismatch fails closed with stable `ATTENTION-STALE-001`. There is no automatic merge or rebase; Work must create a new candidate from the current effective guidance.

Activation is one SQLite transaction containing:

```text
immutable activation event insert
        +
active pointer switch
```

The event records activation ID, project, candidate map ID/digest, prior map ID/digest, source activation Action Proposal binding, actor, timestamp, and its own digest. The candidate map itself is never rewritten during activation.

## Why Core Human Decision is not used

Attention activation changes future research guidance, not authoritative Research knowledge. It therefore does not use PR26 Core Human Decision adoption semantics:

- no Core Decision object is created;
- no `HumanDecisionService.gate_candidate()` call is made;
- no DecisionRequirement or new decision kind is introduced; and
- the Research Snapshot does not move.

This does **not** weaken authoritative Research adoption. Research Questions, Findings, Methods, and other Core state continue to use their existing Human Decision requirements.

## Exact PR10 Confirmation remains the Human boundary

`Confirmation != Human Decision` remains true.

Submitting `research_attention.activate_candidate` only creates the existing PR10 Confirmation Request. The activation handler is not executed until a matching human Confirmation binds the exact Action Proposal, actor, current Research State/context, expiry, and single-use request.

If the Human does not want the candidate, Work can leave the request unconfirmed or use existing cancellation behavior. Revision means creating a new `research_attention.propose`; there is no KEEP_CURRENT_MAP / REQUEST_REVISION Decision workflow.

## Desktop Research projection

`DesktopResearchConversationMaterializer` receives a small Effective Research Attention callable from local composition instead of reading `state.project_config["research_attention"]` directly.

The generic Capability Context Pack ABI remains `0.1.0`. The existing structured field:

```text
research_attention
```

contains the Effective Research Attention actually used for that run. No map ID/digest is added to the generic ABI merely for provenance convenience. The existing `context_pack_digest` already pins the exact Attention content.

The materializer still enforces its existing bounds, and duplicate Attention IDs fail closed.

## Prepared Runs remain immutable

Activation affects future materialization only:

```text
Run A -> Context Pack digest X -> Attention X
activate another map
Run B -> Context Pack digest Y -> Attention Y
```

Run A's stored Context Pack bytes and digest remain X. PR30 does not retroactively mutate or invalidate prepared Runs.

Desktop Research Handoff preservation semantics also remain unchanged: every Attention item projected into a Context Pack is still a Research Attention item, whether it came from the Project Config baseline or an active runtime map.

## Work execution convention

Production Work execution continues to use the frozen repository environment and UTF-8 temporary JSON files rather than relying on stdin:

```powershell
uv run --frozen python research-loom action submit `
  --workspace <WORKSPACE> `
  --json attention-proposal.json
```

Example proposal file:

```json
{
  "action_type": "research_attention.propose",
  "payload": {
    "additions": [
      {
        "statement": "Keep a synthetic cross-cutting implication visible.",
        "rationale": "Treat it as guidance rather than a separate Research Question."
      }
    ]
  },
  "actor_id": "local-human"
}
```

Work can inspect `research_attention.status`, submit a bounded proposal, then submit an activation action using only the returned `attention_map_id`. The activation action returns a normal PR10 Confirmation Request. Only an explicit human `confirmation submit` executes the pointer switch.

## Non-goals

PR30 does not add Attention extraction/distillation LLMs, legacy Attention Drop ingestion, filesystem watchers, Core Attention objects, new transitions or Core decisions, Project Config runtime rewriting, generic hot reload, arbitrary full-map ingress, semantic duplicate detection, automatic RQ/Method/Source/Evidence promotion, Capability Context Pack ABI changes, Writer/Publication work, MCP/WebMCP, OneDrive/M365 integration, adopted-RQ revision, or a workspace migration framework.
