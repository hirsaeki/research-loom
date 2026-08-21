# Work Chat Control Plane and Safe Recovery Scope

Status: **COMPLETE**
Acceptance record: [`completion_audit.md`](completion_audit.md)
Active contract inventory: [`p0_contract_freeze.md`](p0_contract_freeze.md)

## Purpose

Work chat is the normal Human interface for Research Harness operation. The
Python Harness remains the authoritative typed state machine, operational
source of truth, and audit boundary. Humans retain authority over research
meaning. The control plane also provides append-only recovery that can abort,
invalidate, and replay affected work without deleting history or silently
reversing Human decisions.

## Durable scope

The increment provides:

1. a backend-neutral Work Conversation Contract;
2. bounded status and allowed-action views derived from Harness state;
3. typed proposals, confirmations, receipts, and stale-action rejection;
4. safe pending-Run abort and replacement;
5. Human-approved Recovery using invalidation and replay;
6. Decision, Artifact, Research, and Publication impact analysis;
7. CLI and interactive-Work integration over shared application services;
8. detachable Attention intake/distillation and Human Map adoption over the
   same Work exchange;
9. append-only workspace archive/freeze and independent `rh new` creation;
10. failure tests, operator documentation, and requirement-level acceptance
   evidence.

The detailed schemas and semantics are authoritative in:

- `contracts/capabilities/work-conversation/`;
- `contracts/capabilities/harness-recovery/`;
- `contracts/capabilities/attention-intake/`;
- `contracts/capabilities/workspace-lifecycle/`;
- `docs/architecture.md`;
- `docs/attention_intake_lifecycle.md`;
- `docs/work_chat_operator_guide.md`;
- `docs/harness_recovery_runbook.md`.

## Non-negotiable boundaries

- Chat prose is neither Research Evidence nor authoritative Harness state.
- Natural-language interpretation may propose an action but cannot commit it.
- State-changing actions are typed, allow-listed, Human-confirmed where
  required, state-bound, and receipted.
- CLI and chat use the same application services and cannot bypass validation
  or Human gates.
- Research-semantic decisions, Evidence qualification, Publication
  Eligibility, and Publication `STABLE` / `FINAL` remain Human-owned.
- Recovery is append-only compensation: prior Runs, snapshots, Decisions,
  submissions, and artifacts remain immutable; replay uses new Run and Context
  Pack IDs; an old snapshot is never copied over a current head.
- Unknown actions, roles, event policies, artifacts, and recovery targets fail
  closed.
- Invalidated or superseded lineage is excluded from normal Context Packs.
- Publication Draft/Feedback is not Research Evidence, and Research/Publication
  and REAL/VIRTUAL lanes remain isolated unless an explicit bridge contract
  authorizes a relationship.
- Counterevidence, conflicts, nulls, limitations, unknowns, Evidence Gaps,
  failed or aborted Runs, rejected submissions, and recovery uncertainty remain
  explicit.
- Raw Attention material requires explicit Human registration and is available
  only to `ATTENTION_DISTILLATION`; Work cannot adopt a candidate Map. A Map may
  be absent, and archive/new lifecycle operations do not change research meaning.

## Transport boundary and exceptions

This scope does not claim or require a programmable Work API, Work UI
automation, browser automation, search-order automation, or a research
algorithm. The supported exchange is backend-neutral: the Harness emits typed
tasks, Context Packs, schemas, or Decision Requests; Work returns a structured
result through the declared exchange path; the Harness validates, audits,
reduces, and returns a receipt or status view.

Large or restricted file transfer, authentication, technical artifact repair,
direct immutable-artifact audit, and comparisons too large or unsafe to present
accurately in chat remain explicit Human escape hatches.

## Completion evidence

Gate-by-gate results, observed commands, limitations, and unmet external
capabilities are recorded in `docs/completion_audit.md`. Completion of this
scope does not claim Work UI automation, external research execution, or
validation of any research result.
