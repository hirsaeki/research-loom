# Production local workspace, application facade, and JSON CLI

PR27 turns the existing production-local composition into a reopenable application boundary without changing Research semantics. PR35 extends that same boundary with the missing external Desktop Research material-intake operations; it does not introduce a second execution path.

## Responsibility boundary

```text
ChatGPT Work / human / future frontend
              |
              v
        JSON CLI adapter
              |
              v
 transport-neutral Application Facade
              |
              v
      LocalResearchApplication
              |
    existing PR20-26 runtime/state path
```

A local workspace is a filesystem/composition concern under `plugins/local_application`. It is **not** a new Core domain object and it is not a second Research State.

`LocalResearchApplication` remains the production composition root. `LocalApplicationFacade` is the small operator-facing API. The CLI calls only that facade; it does not mutate SQLite repositories or operational stores directly. Workspace initialization and read-only diagnosis are also exposed through facade operations rather than CLI-owned storage logic.

## Three different bindings

A workspace persists three different things with different authority:

- **Project Config** is canonical project-local declarative configuration. It is not authoritative Research State.
- **Effective Profile Set** is an already-resolved declarative policy binding. PR27 does not resolve or hot-reload Profiles.
- **Research State** is the authoritative append-only state managed through the existing runtime and SQLite repository.

`workspace-binding.json` contains only reopen metadata: format/version, project identity, exact Config/Profile locators and digests, fixed runtime storage locations, and initialization metadata. Evidence, Findings, RQs, current Snapshot membership, Human Decisions, and execution results are not duplicated into the binding file.

## Bootstrap

`research-loom init` requires explicit canonical Project Config and an already-resolved Effective Profile Set. Both are schema-validated and their existing semantic bindings are checked before state creation.

Only Project Config fields that map losslessly to an existing Core Project are materialized. Bootstrap creates:

1. Core Project revision 0,
2. primary Research Lineage,
3. initial immutable Research Snapshot.

The existing SQLite Research State bootstrap primitive persists that validated `StateView`; PR27 does not introduce a second reducer.

### RQ seeds are not Research Questions

`research_questions.seeds` remain pre-adoption question-forming material. Bootstrap does not fabricate adoption state, revision, an answer, Method selection, Finding, Decision, Source, or Evidence from a seed.

An existing Core RQ reference is different from a seed. PR27's minimum bootstrap inputs do not contain an authoritative Core-object source, so a Config containing an existing RQ reference fails closed rather than fabricating the object. Legacy import/reconstruction is out of scope.

RQ-forming source material may be pasted or attached to ChatGPT Work in the MVP. Work may reason over that material and produce typed candidates, but PR27 adds no QuestionFormationEngine, RQ extractor/distiller, or RQ-specific LLM service.

### Resource references are hints

Project Config `resource_references` are references/hints only. Their presence does not create Core Source/Evidence and does not grant Runtime Authorization. Runtime access remains a separate explicit execution concern.

## Initialization safety

Initialization accepts an absent or empty workspace only. Explicit Config/Profile inputs are validated before workspace-owned paths are created. It then creates a `.research-loom/.initializing` marker before storage creation and writes the final `workspace-binding.json` only after all production stores have initialized successfully. A failure therefore cannot be mistaken for a ready workspace.

If initialization fails after filesystem creation begins, each input target is registered for cleanup before its write begins, so a partially created/truncated Config or Profile copy cannot strand the workspace. Only paths created by that init attempt are removed. A pre-existing empty workspace root is preserved, while a root created by the failed attempt is removed when empty. Re-running `init` against an initialized or unrelated non-empty directory is rejected. Workspace locators are fixed by the workspace format, must remain relative to the root, and symlink/path traversal escapes are rejected. No remote listener or general sandbox framework is introduced.

## Exact reopen

Reopen performs the following checks before returning an application:

```text
binding parse/version
 -> Project Config schema + semantic digest
 -> Effective Profile Set schema + exact digest
 -> Project/Profile request binding
 -> fixed storage layout/path confinement
 -> SQLite readability
 -> authoritative project identity
 -> active lineage + exact HEAD
 -> Config/Profile pins in project state and lineage
 -> conversation/decision/execution stores
 -> LocalResearchApplication
```

Project mismatch, Config/Profile digest mismatch, malformed/incompatible binding, partial initialization, missing DBs, stale pins, or an unrelated Research State fail closed. Reopen does not rebase, repair, migrate, or silently adopt changed files.

`doctor` runs the corresponding filesystem and SQLite integrity checks read-only. SQLite failures are projected as structured workspace issues rather than escaping as transport-specific exceptions. There is intentionally no `doctor --fix`.

## Application facade and typed ingress

`LocalApplicationFacade` accepts an untrusted action draft containing only:

- `action_type`,
- action-specific `payload`,
- optional `rationale`,
- optional local actor/conversation identity metadata.

The caller does not select route, effect, service, Capability implementation, execution style, confirmation policy, Runtime Authorization, Human Decision refs, StateTransitionRequest, CommitBundle/Commit ID, Snapshot-to-commit, authoritative timestamp, or storage location.

The existing `ActionRegistry` remains the authority for route/effect/confirmation/Capability binding. Typed ingress deliberately enters the same proposal construction, validation, Confirmation, PR9 execution, Runtime Authorization, PR26 Human Decision Gate, and StateTransitionService path used after natural-language resolution. No second execution pipeline exists.

The distinctions remain explicit:

```text
typed action submitted
    != Confirmation
    != Runtime Authorization
    != Human Decision
```

In particular, JSON generated by Work is not human Confirmation. Dynamic PR20 DecisionRequirements for `state.apply_candidate` continue to be derived from the exact candidate and cannot be supplied by the caller.

PR35 adds transport-neutral methods for the external Desktop Research execution interval only: attempt start, source capture, and attempt completion. These methods do not bypass the Capability execution service or create Research State. They resolve an already-prepared persisted Run, enforce the exact project/Capability/implementation/function/mode/Context binding and `RUNNING` status, then call the existing Desktop Research capture/attempt services.

## Status and action discovery

`research-loom actions` projects static registry metadata for consumers: action type, payload contract ID/version, effect, whether static Confirmation is required, and a consumer-facing route category. It does not serialize callables/internal objects or claim that a dynamic Human Decision is or is not required.

`research-loom status` is a bounded operational projection, not a history dump. Pending Confirmations and PREPARED/RUNNING execution Runs are queried by project and capped at 100 items per category. The response includes `truncated.pending_confirmations` and `truncated.pending_runs`; `true` means additional matching items exist beyond the returned bounded set. This keeps status cost independent of total historical documents while avoiding a false claim of completeness.

## Desktop Research external flow

The production external-first Desktop Research flow is:

```text
typed desktop_research.investigate
 -> prepare external Run = RUNNING
 -> external attempt start
 -> external operator performs actual search/fetch
 -> external capture when retrieval succeeds
 -> external attempt complete
 -> repeat
 -> external collect
 -> canonical result validation
 -> Handoff
 -> normalization
 -> candidate StateDeltaProposal
```

The CLI/facade does not add a search engine, browser provider, downloader, PDF parser, text extractor, or LLM provider. Retrieval outcomes such as blocked, unavailable, failed, duplicate, out-of-scope, and no-relevant-source are persisted by the existing append-only Retrieval Attempt Ledger. Acquisition failure remains unknown/gap/coverage-limitation provenance and is not converted into information nonexistence. Operational termination is not research stopping.

### External attempt start

The caller supplies only attempt intent/provenance:

```json
{
  "attempt_id": "ATT-G1-001",
  "strategy": "direct_fetch",
  "coverage_dimension_ids": ["COV-SUPPORT"],
  "query_or_target": "Levels of AGI",
  "provider_or_tool": "external_operator",
  "target_locator": "https://example.org/source",
  "provenance": {"reason": "known source"}
}
```

`started_at` is not accepted. The Harness clock records it. Coverage dimensions must already exist in the immutable Desktop Research Context; the facade does not infer missing dimensions.

### External source capture

A successful external retrieval is explicitly staged as two ordinary workspace files and then captured:

```json
{
  "capture_id": "CAP-G1-001",
  "source_category": "other",
  "exact_locator": "https://example.org/report.pdf",
  "acquired_at": "2026-08-31T00:00:00Z",
  "original_file": "g1-formal-sources/raw/report.pdf",
  "original_media_type": "application/pdf",
  "text_rendition_file": "g1-formal-sources/renditions/report.txt",
  "provenance": {"retrieval_method": "external_operator"}
}
```

The file locators are workspace-relative. Absolute paths and `..` traversal are rejected at ingress. The actual read goes through the existing `LocalExecutionStore` controlled intake implementation, which owns root containment, symlink/junction/reparse-point rejection, regular-file validation, bounded reads, and Windows final-path checks. The same security logic is not duplicated in the facade.

Caller input cannot declare artifact IDs, digests, sizes, storage locators, original/text artifact references, or other trusted store metadata. Original/text digest and byte length are computed from the bytes actually stored. The text rendition must decode as UTF-8. The source category and byte/capture-artifact limits must already be allowed by the bound Desktop Research Context.

Capture is execution provenance plus candidate source material only. It does not verify a Core Source or Evidence, adopt a Finding, complete an RQ, or strengthen confidence.

### External attempt complete

Completion records the observed outcome through the existing recorder:

```json
{
  "attempt_id": "ATT-G1-001",
  "outcome": "source_captured",
  "target_locator": "https://example.org/report.pdf",
  "resulting_capture_id": "CAP-G1-001",
  "provenance": {}
}
```

or, for example:

```json
{
  "attempt_id": "ATT-G1-002",
  "outcome": "blocked",
  "target_locator": "https://example.org/protected",
  "failure_or_blocking_reason": "JavaScript/cookie challenge",
  "provenance": {}
}
```

`completed_at` is not accepted. Existing recorder invariants remain authoritative: `source_captured` requires a capture ID; unsuccessful outcomes cannot claim one; blocked/unavailable/failed require a reason; duplicate starts and double completion fail closed.

### Persistence and finalization

Attempt events and capture artifacts are persisted before final collection. Therefore:

```text
attempt start
 -> process close
 -> workspace reopen
 -> attempt complete
```

remains valid for the same `RUNNING` Run. If final `external collect` fails Handoff/result validation or later normalization, already-recorded retrieval attempts and captured original/text artifacts remain execution provenance. Research State still does not change.

`external collect` retains its existing JSON contract:

```json
{
  "handoff": {},
  "extension": {}
}
```

PR35 does not relax pin, Handoff, source-category, coverage, citation, budget, or normalization validation and does not repair caller ID/digest mismatches.

## JSON CLI

The first concrete facade adapter is a structured CLI, not a REPL/TUI. Root `pyproject.toml` and `uv.lock` remain the single repository/application dependency contract. Normal operator use goes through the repository launchers, which always enter `uv run --frozen` and do not define a second dependency environment.

Windows / PowerShell:

```powershell
.\research-loom.cmd init --workspace PATH --project-config FILE --effective-profile-set FILE --json
.\research-loom.cmd status --workspace PATH --json
.\research-loom.cmd resume --workspace PATH --json
.\research-loom.cmd doctor --workspace PATH --json
.\research-loom.cmd actions --workspace PATH --json
.\research-loom.cmd action submit --workspace PATH --json INPUT.json
.\research-loom.cmd confirmation submit --workspace PATH --json INPUT.json
.\research-loom.cmd decision resolve --workspace PATH --json INPUT.json
.\research-loom.cmd external attempt start --workspace PATH --run-id RUN-ID --json ATTEMPT.json
.\research-loom.cmd external capture --workspace PATH --run-id RUN-ID --json CAPTURE.json
.\research-loom.cmd external attempt complete --workspace PATH --run-id RUN-ID --json ATTEMPT.json
.\research-loom.cmd external collect --workspace PATH --run-id RUN-ID --json RESULT.json
```

POSIX:

```bash
./research-loom init --workspace PATH --project-config FILE --effective-profile-set FILE --json
./research-loom status --workspace PATH --json
./research-loom resume --workspace PATH --json
./research-loom doctor --workspace PATH --json
./research-loom actions --workspace PATH --json
./research-loom action submit --workspace PATH --json INPUT.json
./research-loom confirmation submit --workspace PATH --json INPUT.json
./research-loom decision resolve --workspace PATH --json INPUT.json
./research-loom external attempt start --workspace PATH --run-id RUN-ID --json ATTEMPT.json
./research-loom external capture --workspace PATH --run-id RUN-ID --json CAPTURE.json
./research-loom external attempt complete --workspace PATH --run-id RUN-ID --json ATTEMPT.json
./research-loom external collect --workspace PATH --run-id RUN-ID --json RESULT.json
```

Research Loom requires Python 3.12+ and `uv` on `PATH`. The launchers do not install, download, bootstrap, or upgrade `uv`; they do not run an explicit `uv sync`; and they do not fall back to system Python, an active virtual environment, Conda, a repository `.venv`, or another interpreter when `uv` is unavailable. Structured production input should be supplied through a UTF-8 JSON file rather than relying on stdin in Work command environments.

The explicit developer/debug invocation remains supported:

```bash
uv run --frozen python research-loom status --workspace PATH --json
```

That direct form and the repository launchers reach the same CLI and Application Facade. No `[project.scripts]`, package installation, PEP 723 metadata, script-specific dependency list, or script-specific lockfile is introduced.

stdout is always one JSON document. Workflow states such as `CONFIRMATION_REQUIRED`, `HUMAN_DECISION_REQUIRED`, and `CAPABILITY_EXECUTION_PREPARED` are successful command processing and therefore exit 0. External attempt/capture success states are also normal exit 0. Malformed input, binding/integrity failures, validation failures, unsafe capture paths, and unexpected application errors return structured issues and a non-zero process exit. Repository launchers preserve the underlying CLI exit code and do not add wrapper text to stdout or stderr.

## ChatGPT Work and future transports

ChatGPT Desktop App Work is the MVP human-facing consumer. It owns natural-language reasoning and may translate intent into typed action JSON. Work is not an LLM embedded inside the Harness and has no special Research authority.

A future MCP, WebMCP, GUI, or other frontend should bind to the same Application Facade. PR35's attempt/capture/complete operations are transport-neutral facade methods rather than CLI-only storage operations. No `GenericTransport`, `FrontendProtocol`, HTTP listener, MCP server, PluginHost, AgentRuntime, managed Desktop Research provider, or generic arbitrary artifact-upload API is introduced merely in anticipation of a second transport.

OneDrive / M365 Copilot projection remains a later interchange/publication concern. The local authoritative SQLite database is not a shared synchronization object.
