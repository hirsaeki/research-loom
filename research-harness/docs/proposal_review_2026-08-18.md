# Proposal review: P1-P12

## Purpose and status

This document preserves the disposition of the findings in
`Proposal_From_Claude.md`. It is a review and implementation ledger, not a
runtime contract and not a source of research authority.

The proposal identifies `8e47e1b` as its target HEAD. The current repository
HEAD at revalidation was `28e8420`, and the worktree contained additional
uncommitted implementation changes. Every finding was revalidated against the
current worktree before implementation. The proposal's test result is evidence
about its stated baseline, not acceptance evidence for the current HEAD.

Durable semantics belong in the relevant `contracts/` file. A temporary
`GOAL.md`, if created for the implementation increment, may contain only the
phase checklist, links to this record, and acceptance commands. It must be
removed when the increment and its documentation gaps are complete.

## Overall disposition

P1 and P2 are boundary-breaking findings and are implementation gates. P3
through P10 are accepted as work items, but several proposed patches require
design hardening before they are copied into the code. P11 is split into
duplicate-code cleanup and an explicit decision about CLI exposure. P12 is a
continuous documentation gate, not a final cleanup that can be deferred until
the end.

## Finding-by-finding decisions

| Finding | Disposition | Implementation phase | Durable destination / evidence |
|---|---|---|---|
| P1: unverified identifiers escape Trace Store | Adopt. Treat as a security boundary. Validate path-producing identifiers at the model boundary and confine every Trace Store write/read path at the storage boundary. | F1 | `contracts/runtime_artifact_policy.yaml` where policy wording is needed; implementation tests for model rejection and Trace Store confinement. |
| P2: Publication eligibility is not snapshot-bound | Adopt with the already-decided `SNAPSHOT_ONLY` meaning. No automatic inheritance to a later Research State; a stale decision request cannot authorize a changed head. The data model must preserve the reviewed basis snapshot and the snapshot carrying the recorded eligibility; field names are frozen before coding. | F1 | Primary contract: `contracts/publication_parallel_lane.md`. Integration tests for stale decision, later-state rejection, re-eligibility, and immutable prior Publication history. |
| P3: lock coverage and stale-lock recovery | Adopt the problem statement, not the patch verbatim. Define lock ownership, re-entrancy, coverage, crash recovery, and operator procedures first. Age alone must not silently reclaim a lock; use an owner token and a safe stale/release policy, especially on Windows. | F2 | `docs/known_limitations.md`, `docs/harness_recovery_runbook.md`, lock-focused tests, and CLI/operator documentation. |
| P4: Desktop Research contamination audit is ineffective | Adopt. Derive denied roles from the policy authority, and prevent Work-declared IDs from laundering a registered artifact that policy denies. Add a collision/registered-artifact check and a regression fixture. | F1 | `contracts/runtime_artifact_policy.yaml` and the Desktop Research contract remain authoritative; tests are acceptance evidence. |
| P5: `cli.main()` always returns success | Adopt. Define stable exit-code categories for success, human-decision wait, Work wait, and error. Do not let broad exception handling turn an operational failure into exit code zero. | F2 | CLI/operator documentation and integration tests. |
| P6: decision meaning depends on ID prefixes | Adopt, after the boundary fixes. Add an explicit `decision_kind`/equivalent typed discriminator and migrate legacy records once. IDs remain identifiers, never dispatch types. | F3 | Versioned model/migration tests; decision packet rendering must expose the typed kind. |
| P7: positional merge of proposed baselines | Adopt with fail-closed identity rules. Prefer a required stable candidate ID. Do not use question text as a silent fallback unless uniqueness is contractually guaranteed; missing or duplicate identity must reject or remain unmerged. | F3 | Question-formation schema/contract and permutation, missing-key, and duplicate-key tests. |
| P8: asymmetric snapshot-materialization defense | Adopt. Consolidate source/destination validation into a shared helper used by both Desktop Research and provenance paths, with the Trace Store confinement from P1 underneath it. | F1 | Snapshot-materialization regression tests, including symlink and traversal cases. |
| P9: production invariant uses `assert` | Adopt as a mechanical hardening item. Replace runtime `assert` with domain errors and add a lint rule for production code. Test behavior under optimized execution if relevant. | F2 | Unit tests and lint configuration. |
| P10: directory fsync and non-atomic immutable creation | Adopt the durability goal, but design the cross-platform write protocol before implementation. Exclusive creation, atomic replacement, and parent-directory durability must be tested separately; do not copy a reservation-plus-replace sequence without checking its Windows failure behavior. | F3 | Trace Store unit tests, crash/durability notes, and platform-specific validation. |
| P11a: duplicated materialization and related helpers | Adopt. Perform this with P8 so one shared implementation owns the security checks. | F1 | Refactor tests must preserve both lane behaviors. |
| P11b: exporter/feedback modules not directly reachable from CLI | Do not add CLI commands merely to make modules reachable. The current architecture describes these as independently testable Publication boundaries, while the current CLI already exposes the Publication Lane operations it supports. Make the supported boundary explicit in docs; add a CLI only if an operator workflow requires it. | F4 decision | `docs/architecture.md`, `docs/known_limitations.md`, and a CLI test only if exposure is chosen. |
| P12: documentation contradicts implementation | Adopt as a standing gate. Update the affected contract or operator document in the same phase as each behavior change, then run a final requirement-by-requirement audit. Do not treat P12 as a prose-only afterthought. | Every phase; closure in F4 | Relevant `contracts/`, `README.md`, `docs/architecture.md`, `docs/known_limitations.md`, and `docs/completion_audit.md`. |

## P2 semantic freeze

Publication Eligibility is `SNAPSHOT_ONLY`:

1. The decision request identifies the exact Research State snapshot reviewed by
   the Human.
2. Recording the decision is valid only while that reviewed snapshot remains
   the Research head.
3. A later Research snapshot is not eligible by inheritance. It requires a new
   Publication Eligibility decision.
4. A prior Publication State remains immutable and valid for the snapshot and
   decision from which it was created.
5. A stale request is closed or rejected as stale; it must not be silently
   retargeted to the newer head.

The implementation must keep enough lineage to distinguish the reviewed basis
snapshot from any new immutable Research snapshot created while recording the
decision. This is a contract decision, not an incidental Pydantic field.

## Current-head revalidation and implementation result

The following dispositions were rechecked against the current worktree and
closed in the P1-P12 increment. Evidence paths are intentionally concrete so
the result remains auditable after the temporary `GOAL.md` is removed.

| Finding | Result | Implementation and regression evidence |
|---|---|---|
| P1 | CLOSED | Safe identifier fields and Trace Store confinement in `src/misco_harness/models.py` and `trace_store.py`; traversal rejection in `tests/unit/test_trace_store.py`. |
| P2 | CLOSED | `SNAPSHOT_ONLY` reviewed/recorded lineage, stale-head rejection, no inheritance, and immutable Publication history in `orchestrator.py`, `publication_lane.py`, and `tests/integration/test_publication_parallel.py`. |
| P3 | CLOSED | Owner-token, process-local re-entrant Discovery/Publication locks, explicit-only orphan release, CLI status/release, and immutable release records in `orchestrator.py`, `cli.py`, and `tests/integration/test_optional_seed.py`. |
| P4 | CLOSED | Policy-derived denied roles and registered-artifact anti-laundering audit in `context_builder.py` and `orchestrator.py`; regression in `tests/unit/test_desktop_research.py`. |
| P5 | CLOSED | Stable exit codes `0`, `1`, `10`, and `11` in `cli.py`; CLI integration expectations in `tests/integration/test_cli.py`. |
| P6 | CLOSED | Typed `DecisionKind`, packet exposure, one-time sidecar migration, and typed routing in `models.py`, `decision_broker.py`, and `tests/unit/test_proposal_hardening.py`. |
| P7 | CLOSED | Candidate/proposal identity merge with missing/duplicate fail-closed behavior in `orchestrator.py`, Worker schemas, and `tests/unit/test_proposal_hardening.py`. |
| P8 | CLOSED | Shared snapshot and source-capture materialization validation/copy path for Desktop Research and provenance in `orchestrator.py`, with existing exchange regression tests. |
| P9 | CLOSED | Production runtime assertion replaced by `PublicationLaneError`; Ruff `S101` guard in `pyproject.toml`; publication regression tests. |
| P10 | CLOSED | Exclusive immutable creation, atomic head replacement, file/parent durability hooks, and confined immutable copy in `trace_store.py`; immutable-history and traversal tests. |
| P11a | CLOSED | Desktop and provenance materialization routes delegate to shared helpers in `orchestrator.py`; full suite preserves both lane behaviors. |
| P11b | CLOSED AS DOCUMENTED BOUNDARY | Publication exporter and Feedback Router remain independently testable application boundaries. Supported Publication CLI operations are documented; no thin reachability-only commands were added. |
| P12 | CLOSED | README, architecture, Publication contract, limitations, operator guides, active inventory, test report, this review, and `docs/completion_audit.md` are synchronized. |

## Implementation phases

### F0 — current-head revalidation

Reproduce or refute each proposal claim against `28e8420` plus the current
worktree, record changed line
locations, and add focused regression tests before changing behavior. Confirm
that existing migration behavior can handle any pre-P2 eligibility records.

### F1 — boundary and containment

Implement P1, P2, P4, P8, and P11a. Update the affected contracts and add the
security/semantic regression tests. This phase must pass before operational
hardening proceeds.

### F2 — operational correctness

Implement the reviewed lock protocol for P3, exit-code semantics for P5, and
runtime exception handling for P9. Update operator procedures and known
limitations in the same phase.

### F3 — data integrity and durability

Implement P6, P7, and P10, including explicit migration and failure-path tests.
Re-run the full relevant suite only after the narrow tests pass.

### F4 — surface and documentation closure

Make the P11b CLI-boundary decision, update all affected README/architecture/
limitation text, and complete the P12 requirement-by-requirement audit. Remove
the temporary `GOAL.md` only after the implementation and documentation gaps
are closed.

## Non-negotiable review rules

- `Proposal_From_Claude.md` remains the source proposal; this file records its
  disposition, not a claim that every proposed code fragment is correct.
- No implementation phase may weaken the existing artifact-role firewall,
  Human Decision boundary, immutable history, or REAL/VIRTUAL separation.
- A passing test count from the old proposal baseline is not completion
  evidence for the current HEAD.
- Each phase must leave its acceptance tests and documentation links
  discoverable from the repository's active contract inventory.
