# Production local workspace, application facade, and JSON CLI

PR27 turns the existing production-local composition into a reopenable application boundary without changing Research semantics. PR35 extends that same boundary with the missing external Desktop Research material-intake operations. PR36 adds a bounded read-only inspection surface for one explicitly named Capability Run. PR37 adds an independent lazy Research Exhibit registry for exact analytical-artifact capture and retrieval; none of these increments introduces a second Research State or execution path.

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
    existing runtime/state/store ports
```

A local workspace is a filesystem/composition concern under `plugins/local_application`. It is **not** a new Core domain object and it is not a second Research State.

`LocalResearchApplication` remains the production composition root. `LocalApplicationFacade` is the small operator-facing API. The CLI calls only that facade; it does not mutate or query SQLite repositories or operational stores directly. Workspace initialization, bounded Run inspection, Research Exhibit capture/retrieval, and read-only diagnosis are exposed through public application/store seams rather than CLI-owned storage logic.

Ordinary operator conversation must treat the public Application Facade / CLI as the source of truth. Direct reads of `execution.db`, `operational-trace.sqlite3`, table names, row IDs, or blob-store layout are implementation/debug concerns, not normal operator workflow.

## Three different bindings

A workspace persists three different things with different authority:

- **Project Config** is canonical project-local declarative configuration. It is not authoritative Research State.
- **Effective Profile Set** is an already-resolved declarative policy binding. PR27 does not resolve or hot-reload Profiles.
- **Research State** is the authoritative append-only state managed through the existing runtime and SQLite repository.

`workspace-binding.json` contains only reopen metadata: format/version, project identity, exact Config/Profile locators and digests, fixed runtime storage locations, and initialization metadata. Evidence, Findings, RQs, current Snapshot membership, Human Decisions, execution results, and Research Exhibits are not duplicated into the binding file.

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

Optional additive stores are not required workspace bindings. In particular, the Research Exhibit registry is not opened or created merely because a workspace is reopened.

`doctor` runs the corresponding filesystem and SQLite integrity checks read-only. SQLite failures are projected as structured workspace issues rather than escaping as transport-specific exceptions. There is intentionally no `doctor --fix`.

## Application facade and typed ingress

`LocalApplicationFacade` accepts an untrusted action draft containing only:

- `action_type`,
- action-specific `payload`,
- optional `rationale`,
- optional local actor/conversation identity metadata.

The caller does not select route, effect, service, Capability implementation, execution style, confirmation policy, Runtime Authorization, Human Decision refs, StateTransitionRequest, CommitBundle/Commit ID, Snapshot-to-commit, authoritative timestamp, or storage location.

The existing `ActionRegistry` remains the authority for route/effect/confirmation/Capability binding. Typed ingress deliberately enters the same proposal construction, validation, Confirmation, execution, Runtime Authorization, Human Decision Gate, and StateTransitionService path used after natural-language resolution. No second execution pipeline exists.

The distinctions remain explicit:

```text
typed action submitted
    != Confirmation
    != Runtime Authorization
    != Human Decision
```

In particular, JSON generated by Work is not human Confirmation. Dynamic DecisionRequirements for `state.apply_candidate` continue to be derived from the exact candidate and cannot be supplied by the caller.

PR35 adds transport-neutral methods for the external Desktop Research execution interval only: attempt start, source capture, and attempt completion. These methods do not bypass the Capability execution service or create Research State. They resolve an already-prepared persisted Run, enforce the exact project/Capability/implementation/function/mode/Context binding and `RUNNING` status, then call the existing Desktop Research capture/attempt services.

PR37 adds transport-neutral Exhibit methods outside the action/authority pipeline because Exhibit capture is working-artifact persistence, not a Research State mutation. `capture_exhibit`, `list_exhibits`, and `show_exhibit` still bind to the opened project and authoritative current RQs, but they do not create a StateDeltaProposal, Confirmation, Human Decision, or StateTransition.

## Status, resume, and Run inspection

`research-loom actions` projects static registry metadata for consumers: action type, payload contract ID/version, effect, whether static Confirmation is required, and a consumer-facing route category. It does not serialize callables/internal objects or claim that a dynamic Human Decision is or is not required.

`research-loom status` is a bounded current operational overview, not a history dump. Pending Confirmations and PREPARED/RUNNING execution Runs are queried by project and capped at 100 items per category. The response includes `truncated.pending_confirmations` and `truncated.pending_runs`.

`research-loom resume` is the saved bounded research continuation checkpoint. It remains focused on continuing the research conversation and does not absorb historical Run artifact/diagnostic/attempt detail or Research Exhibit content.

PR36 adds:

```text
research-loom run show --workspace PATH --run-id RUN-ID --json
research-loom run replay --workspace PATH --run-id RUN-ID --json
```

for one explicitly named Run. The Application Facade validates that the Run exists and belongs to the opened project, then projects only persisted Run-bound information:

- Run capability/implementation/function/execution identity and immutable bindings;
- current status, timestamps, failure code/message/retryability;
- Handoff reference/digest, when bound;
- append-only lifecycle events;
- persisted runtime diagnostics;
- artifact metadata (`artifact_id`, role, media type, byte length, digest, execution mode, provenance);
- for Desktop Research, reconstructed retrieval attempts, unsuccessful outcomes, outcome summary, and operational termination records.

Artifact bytes, raw Handoff/Invocation/Context payloads, storage locators, filesystem paths, SQLite paths/row IDs, and arbitrary operational event browsing are not exposed.

Diagnostics, artifacts, retrieval attempts, and operational terminations are capped at 100 returned items and carry explicit `truncated` flags. Lifecycle is already intrinsically bounded by the Run state machine. The command is entirely read-only and does not retry, abort, recover, normalize, adopt, or mutate Research State.

`run show` deliberately does **not** call `diagnose_integrity()`. Ordinary inspection asks what happened and what was persisted. Store integrity diagnosis asks whether persisted storage is internally corrupt and may re-hash artifact bytes. Those responsibilities stay separate; `run diagnose` / `doctor --run-id` are not introduced by PR36.

`run replay` is a bounded recovery path for a historical `COMPLETED` external Desktop Research Run that still has unresolved retrieval attempts. It never mutates the parent Run, its artifacts, attempts, Handoff, or Research State. Instead it re-materializes the original public `desktop_research.investigate` action against current authoritative Research State, prepares a new child Run through the existing `parent_run_id` retry contract, and carries only unresolved retrieval attempts into that child as new in-progress attempt records. Already captured sources are not copied or silently re-acquired. The child Run exposes `parent_run_id` and incremented `attempt` through the normal `run show` surface. If the original action can no longer be re-materialized against current Research State, replay fails closed rather than rebasing historical provenance silently.

Unknown Runs, cross-project Runs, corrupt persisted inspection data, and unexpected store read failures fail closed with application-level errors rather than leaking SQLite schema/table details.

## Research Exhibit capture and retrieval

PR37 stores reusable analytical tables, matrices, text-based graph specifications, and notes in the optional `.research-loom/research-exhibits.sqlite3` registry. It stores the content itself, not a generation recipe.

The supported representations are `markdown`, `json`, and `text`. Markdown/text digests are SHA-256 over the exact UTF-8 bytes; JSON uses RFC 8785 canonical bytes. The first local operational limit is 1 MiB per Exhibit. Images, PDFs, binary figures, and generic artifact storage remain out of scope.

Capture requires at least one RQ which resolves to a current authoritative approved Research Question. Optional source Runs must belong to the current project; optional source artifact references must belong to one of those declared Runs. Completed Runs can be cited as provenance without changing the Run or adding an Execution Artifact. The caller cannot set Exhibit ID, project ID, capture time, Snapshot binding, or content digest.

The registry is lazy and additive:

```text
store absent + status/resume/run show -> unchanged existing behavior
store absent + exhibit list           -> empty result, no store creation
store absent + exhibit show           -> unknown Exhibit
first exhibit capture                 -> store initialization
```

Capture records the current active lineage, Snapshot ref, and Snapshot digest but does not mutate Research State. Exhibits are immutable; revised analyses are new Exhibits linked by `derived_from_exhibit_ids`.

`exhibit list` returns metadata only, is capped at 100 items, and exposes `truncated`. `--rq-id` is the only PR37 list filter. `exhibit show` returns the exact stored content. Neither read surface changes Research State, Run state, artifacts, Attention, Confirmations, or Human Decisions.

See `docs/architecture/research-exhibit-registry.md` for the semantic boundary and future Writer/Publication relationship.

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

The caller supplies only attempt intent/provenance. `started_at` is not accepted; the Harness clock records it. Coverage dimensions must already exist in the immutable Desktop Research Context; the facade does not infer missing dimensions.

### External source capture

A successful external retrieval is explicitly staged as two ordinary workspace files and captured through the existing controlled `LocalExecutionStore` intake path. Absolute paths, `..` traversal, root escape, symlinks/junctions/reparse points, directories, non-regular files, and configured byte-limit violations fail closed.

Caller input cannot declare artifact IDs, digests, sizes, storage locators, original/text artifact references, or other trusted store metadata. Original/text digest and byte length are computed from the bytes actually stored. The text rendition must decode as UTF-8. Capture is execution provenance plus candidate source material only; it does not verify a Core Source or Evidence, adopt a Finding, complete an RQ, or strengthen confidence.

### External attempt complete and persistence

Existing recorder invariants remain authoritative: `source_captured` requires a capture ID; unsuccessful outcomes cannot claim one; blocked/unavailable/failed require a reason; duplicate starts and double completion fail closed.

Attempt events and capture artifacts are persisted before final collection. Therefore process restart between attempt start and completion remains valid for the same `RUNNING` Run. If final collection fails Handoff/result validation or later normalization, already-recorded retrieval attempts and captured original/text artifacts remain execution provenance. PR36 makes that persisted state visible without changing it.

## JSON CLI

The first concrete facade adapter is a structured CLI, not a REPL/TUI. Root `pyproject.toml` and `uv.lock` remain the single repository/application dependency contract. Normal operator use goes through the repository launchers, which always enter `uv run --frozen` and do not define a second dependency environment.

Windows / PowerShell:

```powershell
.\research-loom.cmd init --workspace PATH --project-config FILE --effective-profile-set FILE --json
.\research-loom.cmd status --workspace PATH --json
.\research-loom.cmd resume --workspace PATH --json
.\research-loom.cmd doctor --workspace PATH --json
.\research-loom.cmd actions --workspace PATH --json
.\research-loom.cmd run show --workspace PATH --run-id RUN-ID --json
.\research-loom.cmd exhibit capture --workspace PATH --json EXHIBIT.json
.\research-loom.cmd exhibit list --workspace PATH --json
.\research-loom.cmd exhibit list --workspace PATH --rq-id RQ-ID --json
.\research-loom.cmd exhibit show --workspace PATH --exhibit-id EXH-ID --json
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
./research-loom run show --workspace PATH --run-id RUN-ID --json
./research-loom exhibit capture --workspace PATH --json EXHIBIT.json
./research-loom exhibit list --workspace PATH --json
./research-loom exhibit list --workspace PATH --rq-id RQ-ID --json
./research-loom exhibit show --workspace PATH --exhibit-id EXH-ID --json
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

stdout is always one JSON document. Workflow states such as `CONFIRMATION_REQUIRED`, `HUMAN_DECISION_REQUIRED`, and `CAPABILITY_EXECUTION_PREPARED` are successful command processing and therefore exit 0. External attempt/capture success states, Research Exhibit capture/list/show, and successful `run show` are also normal exit 0. Malformed input, binding/integrity failures, validation failures, unsafe capture paths, unknown/cross-project Runs or Exhibits, corrupt persisted inspection data, and unexpected application errors return structured issues and a non-zero process exit. Repository launchers preserve the underlying CLI exit code and do not add wrapper text to stdout or stderr.

## ChatGPT Work and future transports

ChatGPT Desktop App Work is the MVP human-facing consumer. It owns natural-language reasoning and may translate intent into typed action or Exhibit JSON. Work is not an LLM embedded inside the Harness and has no special Research authority.

A future MCP, WebMCP, GUI, or other frontend should bind to the same Application Facade. PR35's external intake operations, PR36's Run inspection, and PR37's Exhibit methods are transport-neutral facade methods rather than CLI-only storage operations. No `GenericTransport`, `FrontendProtocol`, HTTP listener, MCP server, PluginHost, AgentRuntime, managed Desktop Research provider, generic arbitrary artifact-upload API, Run history browser, or operational event query language is introduced merely in anticipation of a second transport.

OneDrive / M365 Copilot projection remains a later interchange/publication concern. The local authoritative SQLite database is not a shared synchronization object.
