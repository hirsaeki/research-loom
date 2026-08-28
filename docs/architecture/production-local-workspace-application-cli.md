# Production local workspace, application facade, and JSON CLI

PR27 turns the existing production-local composition into a reopenable application boundary without changing Research semantics.

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

## Status and action discovery

`research-loom actions` projects static registry metadata for consumers: action type, payload contract ID/version, effect, whether static Confirmation is required, and a consumer-facing route category. It does not serialize callables/internal objects or claim that a dynamic Human Decision is or is not required.

`research-loom status` is a bounded operational projection, not a history dump. Pending Confirmations and PREPARED/RUNNING execution Runs are queried by project and capped at 100 items per category. The response includes `truncated.pending_confirmations` and `truncated.pending_runs`; `true` means additional matching items exist beyond the returned bounded set. This keeps status cost independent of total historical documents while avoiding a false claim of completeness.

## Desktop Research external flow

PR27 preserves the PR24-26 external-first Desktop Research model:

```text
typed desktop_research.investigate
 -> prepare external Run
 -> external operator performs retrieval
 -> Retrieval Attempt Ledger / captures
 -> collect_external
 -> canonical result validation
 -> Handoff
 -> candidate StateDeltaProposal
```

The CLI/facade does not add a search engine, browser provider, or LLM provider. Retrieval outcomes such as blocked, unavailable, failed, duplicate, out-of-scope, no-relevant-source, unknown, and evidence gaps remain part of the existing Desktop Research semantics. Operational termination is not research stopping.

## JSON CLI

The first concrete facade adapter is a structured CLI, not a REPL/TUI. The canonical developer/operator path is repository-level `uv` execution so the same root dependency declaration and lockfile are used locally and in CI:

```bash
uv sync --frozen
uv run --frozen python research-loom init --workspace PATH --project-config FILE --effective-profile-set FILE --json
uv run --frozen python research-loom status --workspace PATH --json
uv run --frozen python research-loom doctor --workspace PATH --json
uv run --frozen python research-loom actions --workspace PATH --json
uv run --frozen python research-loom action submit --workspace PATH --json -
uv run --frozen python research-loom confirmation submit --workspace PATH --json -
uv run --frozen python research-loom decision resolve --workspace PATH --json -
uv run --frozen python research-loom external collect --workspace PATH --run-id RUN-ID --json -
```

Research Loom requires Python 3.12+. Root `pyproject.toml` and `uv.lock` own the repository/application dependency contract. The CLI does not run `pip install`, `uv sync`, or any other dependency bootstrap internally.

Direct `python research-loom ...` or `python -m plugins.local_application.cli ...` execution is equivalent only when the dependency environment has already been prepared. In that alternate mode, dependency consistency is the operator's responsibility. The `uv run --frozen python research-loom ...` form is cross-platform and is the canonical form for fresh checkouts, including PowerShell.

stdout is always one JSON document. Workflow states such as `CONFIRMATION_REQUIRED`, `HUMAN_DECISION_REQUIRED`, and `CAPABILITY_EXECUTION_PREPARED` are successful command processing and therefore exit 0. Malformed input, binding/integrity failures, validation failures, and unexpected application errors return structured issues and a non-zero process exit.

## ChatGPT Work and future transports

ChatGPT Desktop App Work is the MVP human-facing consumer. It owns natural-language reasoning and may translate intent into typed action JSON. Work is not an LLM embedded inside the Harness and has no special Research authority.

A future MCP, WebMCP, GUI, or other frontend should bind to the same Application Facade. PR27 intentionally does not introduce `GenericTransport`, `FrontendProtocol`, an HTTP listener, MCP server, PluginHost, or AgentRuntime merely in anticipation of a second transport.

OneDrive / M365 Copilot projection remains a later interchange/publication concern. The local authoritative SQLite database is not a shared synchronization object.
