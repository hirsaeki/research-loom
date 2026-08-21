# MVP completion audit

Date: 2026-08-15

This audit records completion of the superseded MVP baseline as it existed on
2026-08-15 (recoverable from Git history at `aabd620` and `a9ddc82`) and treats
Appendix N of `contracts/research_harness_v0.4.md` as its acceptance authority.
The current Work-chat and Recovery scope is defined by
`docs/work_chat_recovery_scope.md` and the active contracts listed in
`docs/p0_contract_freeze.md`. This document does not claim that the research
design is canonical or that any research result has been validated.

## Current Work-chat and Recovery increment audit

This section is the completion audit for the Work-chat and Recovery increment.
It is kept separate from the superseded MVP audit above.

| Gate | Result | Observed evidence |
| --- | --- | --- |
| P0 contract freeze | PASS | New Conversation/Recovery contracts, active inventory, no blocker conflict, and baseline `uv run python -m pytest` before behavior changes: 95 passed. |
| P1 status view | PASS | `ChatStatusView`, bounded summaries, allowed typed actions, and `test_conversation_recovery.py`. |
| P2 confirmation routing | PASS | State ID/hash binding, actor/expiry/single-use checks, unknown action fail-closed, immutable receipts; 7 focused tests. |
| P3 pending Run abort | PASS | Immutable abort records, fresh replacement Run ID, preserved original directory, late-result rejection. |
| P4 Recovery assessment | PASS | Hash-bound request, bounded impact assessment, Human Decision Packet, precise affected IDs. |
| P5 invalidate/replay | PASS | New recovery snapshot and Replay Plan, invalidated lineage exclusion, new Run IDs, interruption records, no direct head rewind. |
| P6 Decision/Publication impact | PASS | Explicit `PRESERVE`/`RECONFIRM`/`INVALIDATE` records and back-references; stale Publication state and export rejection. |
| P7 Work/CLI integration | PASS | `WorkConversationCoordinator` and `rh conversation`, `rh run abort`, `rh recovery` commands share application services; no Work API assumed. |
| P8 failure/regression checks | PASS | `103 passed`, Ruff clean, compileall clean, `git diff --check` clean; existing lane/mode/Evidence regressions remain green. |
| P9 operator handoff | PASS | Work-chat guide, Recovery Runbook, exceptional boundaries, direct-head-repair prohibition, and this requirement audit. |

The increment is complete only to the active implementation contracts listed in
`docs/p0_contract_freeze.md`; it does not claim that Work UI automation,
external research, or any research result has been validated.

## Detachable Attention and workspace lifecycle increment

Date: 2026-08-19. This increment implements the detachable raw-drop intake,
bounded Attention Distillation Work exchange, Human Map adoption/versioning,
verified archive/freeze, and independent `rh new` lifecycle described by
`GOAL.md` while that temporary ledger was active. `GOAL.md` is removed after
this audit and the durable contracts/docs below remain authoritative.

| Gate | Result | Observed evidence |
| --- | --- | --- |
| Contract and policy freeze | PASS | Attention Distillation, Workspace Lifecycle, runtime event/lane, intake/candidate roles, optional Map semantics, and legacy Map compatibility are recorded in the active inventory. |
| Detachable intake | PASS | Explicit `attention ingest`, path/symlink confinement, SHA-256 manifest/file copies, duplicate-source rejection, and scoped unregistered-file denial. |
| Work boundary | PASS | `AttentionDistillationHandoff`, generated schema/TASK/result path, candidate hash check, exact drop classification audit, and immutable failed submission traces. |
| Human adoption | PASS | `ATTENTION_MAP_ADOPTION` supports adopt/keep/revision; adoption creates a new Map artifact and pointer while preserving prior artifacts and Research State. Map-less Research and Publication fallbacks are tested. |
| Archive/new lifecycle | PASS | Bundle tree/artifact verification precedes `ARCHIVED`; incomplete archives require explicit opt-in; `rh archive --verify` is read-only; `rh new` starts a clean mapless target and can queue an initial drop. |
| Conversation/docs | PASS | Typed, confirmed, state-bound drop/archive actions and synchronized README, architecture, operator, scope, limitations, lifecycle, inventory, and test-report documents. |

Focused lifecycle validation collected 8 tests with 7 passed and 1 skipped
(Windows symlink creation unavailable). Full validation collected 118 tests with
117 passed and 1 skipped.

```text
uv run python -m pytest
117 passed, 1 skipped

uv run ruff check src tests
All checks passed!

uv run python -m compileall -q src tests
exit 0

uv lock --check
Resolved 14 packages in 1ms

git diff --check
exit 0

vendor/misco-publication-writer static checks and contract regression
PASS
```

## P1-P12 proposal-hardening completion audit

Date: 2026-08-18. This audit covers the current worktree revalidation recorded
in [`proposal_review_2026-08-18.md`](proposal_review_2026-08-18.md), not the old
proposal baseline. `GOAL.md` was a temporary ledger for this increment and is
removed after this audit's documentation and validation gates pass.

| Phase / finding | Result | Acceptance evidence |
| --- | --- | --- |
| F0 current-head revalidation | PASS | Current HEAD `28e8420` reviewed; all P1-P12 dispositions and changed locations recorded in the proposal review. |
| F1 P1/P2/P4/P8/P11a | PASS | Identifier/path confinement, snapshot-bound eligibility, policy-derived Desktop Research denial, and shared materialization tests. |
| F2 P3/P5/P9 | PASS | Re-entrant owner-token locks with explicit release, CLI exit-code tests, runtime domain error, and Ruff assert guard. |
| F3 P6/P7/P10 | PASS | Typed decision migration, stable candidate identity, exclusive immutable creation, atomic replacement, and durability implementation/tests. |
| F4 P11b/P12 | PASS | Publication exporter/router CLI boundary documented; README, contracts, architecture, limitations, operator docs, active inventory, test report, review, and this audit synchronized. |

### Requirement-by-requirement result

| Finding | Result | Evidence |
| --- | --- | --- |
| P1 | PASS | `src/misco_harness/models.py`, `src/misco_harness/trace_store.py`, `tests/unit/test_trace_store.py`. |
| P2 | PASS | `contracts/publication_parallel_lane.md`, `src/misco_harness/orchestrator.py`, `tests/integration/test_publication_parallel.py`. |
| P3 | PASS | `src/misco_harness/orchestrator.py`, `src/misco_harness/cli.py`, lock sections in operator/recovery docs, lock regression test. |
| P4 | PASS | `src/misco_harness/context_builder.py`, `src/misco_harness/orchestrator.py`, `tests/unit/test_desktop_research.py`. |
| P5 | PASS | Stable exit-code constants and CLI integration tests. |
| P6 | PASS | `DecisionKind`, migration sidecar/marker, packet rendering, and migration regression test. |
| P7 | PASS | Identity-based proposal normalization with permutation/missing/duplicate coverage. |
| P8 | PASS | Shared `_materialize_snapshots_common` and `_materialize_source_captures_common` paths plus lane exchange tests. |
| P9 | PASS | `PublicationLaneError` runtime invariant and `pyproject.toml` Ruff `S101` guard. |
| P10 | PASS | `O_EXCL` immutable creation, atomic head writes, file/parent fsync hooks, and immutable-history tests. |
| P11a | PASS | Desktop Research and provenance routes delegate to the shared materialization implementation. |
| P11b | PASS AS DOCUMENTED BOUNDARY | Supported Publication Lane commands are exposed; internal exporter/router reachability-only commands are intentionally not added. |
| P12 | PASS | All affected durable documents are linked from the active inventory and synchronized with implementation. |

### Final observed validation

```text
uv run --with pytest python -m pytest
110 passed

uv run --with ruff ruff check src tests
All checks passed!

uv run python -m compileall -q src tests
exit 0

uv run python vendor/misco-publication-writer/tests/run_static_checks.py
STATIC_CHECKS=PASS

uv run python vendor/misco-publication-writer/tests/run_contract_regression.py
CONTRACT_REGRESSION=PASS

git diff --check
exit 0
```

## Appendix N acceptance criteria

| # | Result | Authoritative evidence |
| --- | --- | --- |
| 1 | PASS | `models.py` defines strict Research, Publication, and Orchestrator State; `TraceStore.snapshot`; `test_trace_store.py`; initial heads/snapshots in `DiscoveryOrchestrator.initialize`. |
| 2 | PASS | `DiscoveryOrchestrator.plan`; CLI `rh plan`; `test_cli.py`. |
| 3 | PASS | `ArtifactAccessPolicy` and `ContextBuilder`; isolation tests in `test_context_builder.py`. |
| 4 | PASS | `MockWorkerAdapter` and `SubprocessWorkerAdapter`; deterministic and subprocess tests in `test_workers_run_manager.py`. |
| 5 | PASS | strict `WorkerResult`, `audit_worker_result`, and integration run artifacts containing `worker_result.json` plus `audit.json`. |
| 6 | PASS | `reduce_worker_result`; exact preservation assertions in `test_audit_reducer.py`. |
| 7 | PASS | `PublicationExporter`; contamination, approval, and eligibility tests in `test_publication.py`. |
| 8 | PASS | exhaustive `ROUTES`, fail-closed unknown type, and routing tests. |
| 9 | PASS | `DecisionBroker`; immutable JSON/Markdown packet, pending stop, choice validation, state snapshot, and resume tests. |
| 10 | PASS | `test_first_discovery_cycle_needs_no_manual_context_transport` executes Theme/Expectations through independent candidates, Seed comparison, Question Decision, and Desktop Research preparation. |
| 11 | PASS | automated REAL/VIRTUAL, Research/Publication, provenance/active, and quarantine isolation tests. |
| 12 | PASS | explicit registry fields, policy expansion during bootstrap, unknown role fail-closed test, and `rh validate` rejection of missing/unknown policies. |
| 13 | PASS | historical, superseded canonical, and simulation provenance exclusion tests; Publication Export rejection tests. |
| 14 | PASS | Attention Map is included for planning, has false method/answer capabilities, and is rejected by the Research Evidence check. |
| 15 | PASS | Run Manifest points to Context Pack and hashed inputs; Research candidate entries point to Run; state snapshots preserve prior IDs; Decision Packet references causal Run; integration assertions cover every generated artifact. |

## Required stress and regression scenarios

| Scenario | Result | Evidence |
| --- | --- | --- |
| Forbidden context leak | PASS | Question Formation pack forbids and does not copy `rq-seed`. |
| Publication contamination | PASS | Context evidence and Publication Export tests reject Draft/Feedback. |
| Mode contamination | PASS | mixed REAL/VIRTUAL build raises `ModeContamination`; explicit bridge test passes. |
| Compaction loss | PASS | reducer preserves counterevidence, unknowns, scope limits, minority warnings, and question reasons exactly. |
| Decision block | PASS | E2E stops in `QUESTION_REVIEW` and `METHOD_REVIEW` with pending packets. |
| Decision resume | PASS | recorded choices resume automatically; revision choices return to proposal phases. |
| Backend failure | PASS | failed immutable Run, bounded retry, distinct retry IDs. |
| Schema failure | PASS | malformed subprocess output creates no `worker_result.json` or semantic commit. |
| Feedback orphan | PASS | unknown feedback type raises `FeedbackRouteError`. |
| Orchestrator context growth | PASS | 23-run stress test retains 20 compact pointers while all 23 Run directories remain. |
| Re-run | PASS | revision stress and bounded retry create new unique Run IDs and preserve prior Runs. |
| Hash mismatch | PASS | Run Manager re-verifies Context Pack inputs before dispatch; mutated retrieval input produces failed Run and no Worker Result. |

## Phase gates

- P0: active contracts inventoried, contradictions recorded, no BLOCKER found;
  current RC1 static and contract regression scripts pass.
- P1: strict schemas, hashes, atomic writes, immutable history pass.
- P2: Seed, G1/Clean Source, old canonical, simulation, Attention Map,
  publication, and mode boundaries pass.
- P3: deterministic Mock and local subprocess backends, bounded retry, and
  schema failure pass without network.
- P4: independent Audit, Human-only semantic checks, reduction block, and
  compaction-sensitive preservation pass.
- P5: Writer bundle firewall, fake Writer `INTEGRATED` ceiling, and feedback
  routing pass.
- P6: JSON/Markdown Decision Packet and block/resume pass.
- P7: `init`, `status`, `plan`, `continue`, `decisions`, `decision show/record`,
  `runs show`, `context show`, and `validate` are exposed; run limit is tested.
- P8: the full first Discovery Cycle fixture passes without manual file
  transport.
- P9: README quickstart, architecture, test report, known limitations, this
  audit, static review, compilation, unit/integration tests, and RC1 contract
  checks are complete.

## Final observed validation

```text
uv run python -m pytest
39 passed in 7.73s

uv run --with ruff ruff check src tests
All checks passed!

uv run python -m compileall -q src tests
exit 0

uv run python vendor/misco-publication-writer/tests/run_static_checks.py
STATIC_CHECKS=PASS

uv run python vendor/misco-publication-writer/tests/run_contract_regression.py
CONTRACT_REGRESSION=PASS
```

## Definition-of-done conclusion

No known BLOCKER contract violation remains. Context isolation and Human
semantic ownership are enforced by code and covered by tests. The Discovery
Cycle transports files and state automatically, but still stops for actual
Question and method decisions. The manual boundary and next increment are
documented in `README.md` and `docs/known_limitations.md`. No remote write,
repository creation, push, release, participant contact, or publication was
performed.
