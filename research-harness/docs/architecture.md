# Architecture

The package keeps independently testable boundaries for orchestration, context
building, worker execution, audit, reduction, publication export, feedback
routing, decisions, and trace storage.

The durable scope and invariants for the Work-chat control plane and safe
Recovery are defined in `docs/work_chat_recovery_scope.md`. The active contract
inventory and conflict record are maintained in `docs/p0_contract_freeze.md`,
and observed acceptance evidence is maintained in
`docs/completion_audit.md`.

The filesystem Trace Store is the source of run history. Run directories and
state snapshots are immutable. Mutable heads are small pointer documents written
atomically. Every material input is registered with an explicit role and is
hash-checked before worker execution and semantic commit.

Discovery and Publication transitions use owner-token lock files with
process-local re-entrancy. An orphaned lock is never reclaimed by age alone;
operators inspect and explicitly release it, with an immutable release record.

Context Packs contain copied INCLUDE artifacts, retrieval pointers for RETRIEVE
artifacts, and an explicit forbidden list. They never scan the repository for
useful files. Publication and research lanes are separated structurally.

The lanes may progress independently. `DiscoveryOrchestrator.refresh_publication`
consumes a current Research State snapshot only when it carries explicit,
snapshot-bound Human Publication Eligibility whose recorded carrier is that
current head, then writes a new immutable Publication State snapshot without
advancing the Research phase. A later Research snapshot does not inherit
eligibility and requires a new decision. Publication Structure is a provisional
reader-facing projection of that snapshot plus the Attention Map; its add,
remove, merge, split, move, and rename deltas never constrain Research
Questions, method selection, or Evidence interpretation. Writer drafts and
structured Feedback stay in the Publication Lane and are never reduced into
Research State.

Worker adapters receive a Context Pack path and produce a structured result.
The subprocess adapter uses an argument array with `shell=False`; worker output
cannot supply commands for the reducer to execute.

Desktop Research adds a backend-neutral `DESKTOP_RESEARCH` event. Its Context
Pack carries a bounded `DesktopResearchContextSpec`; a human/interactive Work
execution can use `InteractiveWorkResearchBoundary` to receive that pack and
return the same validated `DesktopResearchHandoff` required from any future
verified adapter. The Harness does not prescribe Work's search sequence or
pretend that an unverified Work API exists.

The Desktop Research Handoff keeps source-and-locator Evidence Captures,
including UTC acquisition time, exact text snapshots, snapshot paths and
SHA-256, and typed excerpt-to-locator mappings. Work snapshots are exchanged
under `.rh/work_exchange/<run-id>/evidence_snapshots/` and copied immutably to
the corresponding run directory before Handoff and State reduction. Question
Impact, Findings, Counterevidence, Unknowns, Evidence Gaps, coverage, remaining
information value, and non-binding next-method options remain loss-sensitive;
the State Reducer preserves them, and the Decision Broker turns method options
into a Human Decision Request.

An explicit `PROVENANCE_AUDIT` implementation event handles closed-world
legacy Evidence repair. It binds the plan to a baseline Research State hash,
uses a separate interactive Work exchange, validates 0.2 capture metadata and
semantic preservation, and stores only immutable run artifacts. It does not
reduce into Research State. A failed submission is quarantined under the run's
`submissions/` directory; the Coordinator can discard that run and create a
fresh exchange without overwriting the failed trace.

`CONTRACT_MIGRATION_REVIEW` is the corresponding live-runtime maintenance
event for contract and runtime-policy changes. It freezes the previous
Artifact Registry, builds an implementation-only Context Pack from the
current canonical contract files, validates the refreshed Registry, and then
atomically advances only the Registry head. Research/Publication State,
Human Decisions, and pending Work are left untouched; an existing pending Work
exchange must be completed or reacquired before migration.

The First Discovery Cycle uses the same boundary pattern with
`--worker-backend interactive-work`. `rh continue` persists a planned run and
stops in `WORK_EXECUTION_REQUIRED`, identifying the immutable Context Pack, a
generated JSON Schema for `IndependentQuestionFormationHandoff` or
`SeedComparisonHandoff`, and the expected result file. `TASK.md`, schemas, and
results live in `.rh/work_exchange/<run-id>/`; Work preparation and collection
do not modify the Context Pack. After interactive Work
execution, `rh work collect <run-id> --result <file>` validates and independently
audits the handoff, uses the shared reducer/state-transition path, and resumes
orchestration. Mock mode remains the deterministic default.

The reducer proposes semantic deltas but cannot approve them. Operations such as
run status and manifests may commit automatically. Question baselines, method,
Evidence qualification, Findings, Models, Recommendations, and publication
stability/release require a recorded Human Decision.

## First Discovery Cycle state machine

```text
QUESTION_FORMATION
  -> independent Context Pack (Seed DENY)
  -> SEED_COMPARISON (Seed INCLUDE; independent snapshot immutable)
  -> QUESTION_REVIEW / Human Decision
  -> RESEARCH_PLANNING
  -> Desktop Research preparation (no external research in MVP)
  -> METHOD_REVIEW / Human Decision
  -> DESKTOP_RESEARCH / interactive Work
  -> DESKTOP_RESEARCH_REVIEW / Human Decision
```

Each automatic step creates a new Run, Context Pack, Audit Result, State Delta
Proposal, Research Handoff, Research State snapshot, and Orchestrator State
snapshot. Run manifests point to their Context Pack and hashed inputs. Research
candidate entries point back to their Run. Decision Packets reference the runs
that caused the semantic stop.

The compact Orchestrator head retains at most 20 recent run pointers plus a
monotonic total count. Full history remains in the Trace Store and therefore
does not enlarge the planning context.

## Detachable Attention intake and workspace lifecycle

Attention is an optional, detachable control-plane capability. A Human-selected
raw drop is explicitly registered and hash-frozen under `.rh/intake/drops/`; the
Harness never watches or broadly scans a loose folder. Registration schedules a
bounded `ATTENTION_DISTILLATION` Work event through the same Context Pack,
`TASK.md`, generated schema, and result submission boundary used by Desktop
Research. Work returns only an `AttentionDistillationHandoff` candidate. It
cannot adopt a Map or determine a Question, method, Evidence, Finding, or
answer.

The Harness stops for the typed `ATTENTION_MAP_ADOPTION` Human Decision. Adoption
creates a new immutable `ATTENTION_PUBLICATION_MAP` version and changes only the
active Map pointer; Keep preserves the current pointer, and Request Revision
requeues the same drop. A workspace may intentionally have no active Map, and
Publication Structure falls back to a state-only scaffold in that case.

`rh archive` creates and verifies an append-only self-contained bundle before
freezing the source lifecycle as `ARCHIVED`. It does not delete or rewind the
source. `rh new` copies only the explicit template implementation inputs and
initializes an independent target; it never copies the old runtime, decisions,
runs, Research State, or Map.

## Publication application surface

The Publication exporter and Feedback Router are independent application
boundaries so their contamination and routing rules can be tested directly.
The CLI intentionally exposes the supported lane operations
(`publication request-eligibility`, `publication refresh`, and `publication
writer-submit`) but does not add thin commands merely to make internal
exporter/router modules reachable. A future direct export or feedback-routing
workflow requires an operator contract before CLI exposure is added.

## Runtime boundaries

- Registry absence and unknown roles fail closed.
- Artifact-level policy may narrow a role policy but cannot broaden it.
- `INCLUDE` copies a hash-verified file into an immutable pack; `RETRIEVE`
  records a hash-verified pointer only.
- Publication Draft/Feedback cannot enter Research Evidence.
- REAL and VIRTUAL inputs require an explicitly included mode bridge contract.
- Archive provenance is never discovered. Explicit migration/provenance events
  are the only policies that can authorize it.
- Desktop Research denies Publication Drafts, Publication Feedback, publication
  style sources, and archive/provenance roles.
- Company primary sources remain company claims unless an independent source is
  explicitly linked; material evidence requires a source locator.
- Desktop Research may inspect social-media and online-forum material as
  `LOW_TRUST` exploratory input only. It is limited to `DESCRIPTIVE_CONTEXT` or
  `LEAD_ONLY`, cannot be the sole support for a material Finding, and cannot
  resolve an Evidence Gap.
- Working papers, preprints, industry reports, and corporate publications are
  `LOW_CONFIDENCE` contextual/lead evidence and cannot establish independent or
  causal effects alone. Company blogs and press releases remain
  `COMPANY_PRIMARY` / `COMPANY_CLAIM`.
- Desktop Research stopping is coverage/information-value based, never fixed-N.
- Subprocess workers receive argument arrays with `shell=False`; their output is
  data only and cannot cause reducer command execution.
- `WorkConversationCoordinator` is a thin typed interface over the existing
  Orchestrator, Decision, Run, Publication, and Recovery services. It classifies
  chat, renders a bounded `ChatStatusView`, and emits state-bound confirmations;
  it is not a planner and does not assume a Work API.
- `RecoveryService` writes immutable request, impact, decision, lineage, replay,
  and interruption records. Approval creates a new Research snapshot and
  invalidates affected Registry records; replay uses a new Run/Context Pack ID.
  It never copies an old snapshot over a mutable head. Affected Publication
  States become stale and the exporter rejects them until Human review.
