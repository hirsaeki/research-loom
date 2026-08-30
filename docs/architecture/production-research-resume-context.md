# Production research resume context

## Purpose

`status` is intentionally a small health/status surface for the local workspace, the current authoritative Research State, and pending operational boundaries. That is not enough to resume an ordinary research conversation: saved Research Question candidates and saved Research Attention Maps are deliberately not authoritative Research State, so a snapshot at revision `0` can still have meaningful pre-adoption progress.

PR31 adds a separate, read-only application projection:

```text
existing production stores
        ↓
bounded project-scoped reads
        ↓
LocalApplicationFacade.resume_context()
        ↓
research-loom resume --workspace <WORKSPACE> --json
```

The projection is a read model only. It does not add a Research Stage, workflow phase, next-step model, Core Research Object, Transition kind, Snapshot member, Human Decision kind, database, cache, or persisted resume state.

## Public surface

Use the transport-neutral application method:

```python
facade.resume_context()
```

or the production JSON CLI:

```text
uv run --frozen python research-loom resume \
  --workspace <WORKSPACE> \
  --json
```

`resume` takes no structured input. It is a top-level read command like `status`, `doctor`, and `actions`; it is not a typed Conversation Action. Reading resume context therefore does not create a Conversation Input, Action Proposal, Action Receipt, Confirmation, Human Decision, or Capability Run.

## Projection contents

The response keeps authoritative and non-authoritative material separate:

- `project`: faithful Project Config identity, objective, and scope.
- `research_state`: the current lineage, Snapshot, and Project Config / Effective Profile Set bindings used by the status surface.
- `research_questions.seeds`: Project Config pre-adoption seeds.
- `research_questions.authoritative`: current authoritative Research Question objects only.
- `research_questions.candidates`: persisted PR29 `research_question.propose` StateDeltaProposal candidates, including exact Snapshot and source Action Proposal bindings.
- `research_attention.baseline`: Project Config baseline Attention.
- `research_attention.active_map`: the current persisted active-map binding, or `null`.
- `research_attention.effective`: the existing `EffectiveResearchAttentionProvider` result.
- `research_attention.stored_maps`: persisted maps whether active, previously activated, or never activated, represented by objective activation references rather than a new lifecycle enum.
- `workflow`: pending Confirmations, pending Human Decisions, pending Runs, and recent terminal Runs.
- `truncated`: explicit flags for every bounded collection that can be cut off.

Candidate rows are not semantically deduplicated. A saved candidate is not promoted merely because it exists, and terminal Human Decision status is returned as persisted rather than reinterpreted.

## Bounded project-scoped reads

Resume context uses fixed production bounds. The defaults are intentionally small and non-pageable in PR31:

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

Tests may inject smaller internal limits. There is no generic pagination or query framework. `pending_confirmations` and `pending_runs` use the same bounded override mechanism as the other public resume collections; the per-map activation-reference bound remains an internal production bound rather than a new query framework.

The Conversation Store keeps its existing `state_delta_proposals(proposal_id, payload_json)` schema. Project-scoped candidate listing uses SQLite JSON reads against the existing payload; there is no column addition, workspace-version bump, or migration. The same rule applies to the other stores: PR31 adds read helpers only.

Unreadable or invalid stored candidate/binding data fails closed. Resume does not skip malformed persisted progress and return a misleading healthy summary.

## Research Question candidate correlation

A resume candidate is identified by the bounded PR29 ingress shape, not by arbitrary StateDelta content:

- `candidate_only = true`
- `provenance.producer = research_question.propose@0.1.0`
- exactly one `CREATE_OBJECT` whose object kind is `research_question`
- a matching `affected_refs` Research Question identity

The projection reports facts such as candidate proposal ID and digest, Research Question fields, bound Snapshot, whether that binding is still current, whether an authoritative Research Question with the same ID exists, exact source Action Proposal binding, pending Confirmation Request IDs whose bound `state.apply_candidate` proposal references that candidate, and persisted Human Decision Request statuses bound to that candidate.

It does not invent `DRAFT`, `READY`, `SELECTED`, `SUPERSEDED`, or any other candidate lifecycle state.

## Research Attention projection

Baseline and effective Attention reuse PR30 semantics. `EffectiveResearchAttentionProvider` remains the only overlay calculation:

```text
no active map  → effective = Project Config baseline
active map     → effective = active map items
```

Stored maps are listed separately. Their activation facts are derived from existing activation events and the active pointer. An inactive stored map with activation references is historical; one with no activation references has never been activated. Activation references are bounded per map and expose `activation_ids_truncated`; the aggregate `truncated.attention_activation_events` flag reports whether any returned stored-map history was cut off. The active pointer is also checked against its persisted activation event before it is projected. No new workflow state is persisted.

Opening an older workspace with no Attention Store remains read-only. `resume` must not create `attention.sqlite3`; it returns baseline-only Attention and an empty stored-map list.

## Recent execution

`recent_runs` is a bounded newest-first projection of terminal project-scoped Runs. It reports execution facts only: Run identity, capability/function, execution mode, status, timestamps, handoff reference when present, and Snapshot binding.

A completed Run does **not** imply that research is complete, a Finding is adopted, or Evidence is verified. Research authority remains the current Research State.

## No workflow inference

The Harness does not generate natural-language conclusions such as “the research is in the RQ phase”, “the next step is adoption”, or “Desktop Research is blocked”. There is no `stage`, `phase`, `next_step`, `recommended_action`, or inferred `blocker` field. Resume context returns facts; the operator reasons over them.

## Operator guidance

When resuming a Research Loom conversation, use the public resume context as the primary source of research progress.

Do not reconstruct ordinary research progress from Git state or history, Codex or ChatGPT memory, prior conversation threads, raw SQLite, or repository implementation unless `resume` fails, reports an inconsistency, or the human explicitly asks for diagnosis. Raw SQLite inspection remains appropriate for corruption investigation and explicit developer debugging, not normal resume behavior.

Research Loom is a backend control plane, not the vocabulary for normal research conversation. Translate the machine facts into ordinary research language. For example:

- saved RQ candidate → “問い候補は保存済み”
- `active_map = null` with stored maps → “横断論点は候補として残っているが、まだ調査方針には反映していない”
- pending Human Decision → “ここだけ人の判断待ち”

Be exploratory and permissive in research discussion. Be conservative only when an authoritative or explicitly confirmed mutation boundary is actually reached. The operator should not duplicate Harness mutation guards as conversational prohibitions.

Do not add ceremonial startup reporting for project root, loaded instruction files, workspace path, mutation classification, or Git status unless it is actually needed for the task.

## Probe regression example

The motivating probe had facts equivalent to:

```text
Snapshot revision = 0
authoritative Research Questions = 0
saved Research Question candidates > 0
active Attention Map = null
stored Attention Maps > 0
pending Confirmations = 0
pending Human Decisions = 0
pending Runs = 0
```

That state does **not** mean “initialization only.” A Work operator can accurately summarize it in ordinary language as:

> 問いと横断論点の候補整理までは済んでいます。まだ正式採択やDesktop Researchの実行には進んでいません。

The resume projection makes those saved candidates visible without consulting Git, memory, previous threads, raw SQLite, or implementation details.