# MISCO Research Harness

This repository contains the completed MVP Research Execution Control Plane
recorded in `docs/completion_audit.md`. The Work-chat control-plane and
safe-recovery scope is defined in
[`docs/work_chat_recovery_scope.md`](docs/work_chat_recovery_scope.md). Active
documents are implementation contracts, not a declaration that the proposed
research design is canonical.

Development uses Python 3.12+, `uv`, Pydantic v2, PyYAML, and pytest. Runtime
state is stored as immutable JSON snapshots and run artifacts on the local
filesystem.

Implementation is milestone-gated. See `docs/p0_contract_freeze.md` and
`docs/architecture.md` before changing runtime behavior.

The Work-based Desktop Research boundary is defined by
`contracts/capabilities/desktop-research/desktop_research_contract.md`. It uses
bounded Context Packs and a validated Research Handoff; it does not assume a
programmable Work API or implement search/browser automation.

The Work-chat control plane is defined by
`contracts/capabilities/work-conversation/conversation_contract.md`; safe
append-only recovery is defined by
`contracts/capabilities/harness-recovery/recovery_contract.md`. Operators can
inspect status, propose typed actions, confirm state-bound actions, abort a
pending Run, and request/approve/replay Recovery through the CLI documented in
[`docs/work_chat_operator_guide.md`](docs/work_chat_operator_guide.md) and
[`docs/harness_recovery_runbook.md`](docs/harness_recovery_runbook.md).
Detachable Attention intake and workspace lifecycle are documented in
[`docs/attention_intake_lifecycle.md`](docs/attention_intake_lifecycle.md).

## Development and deterministic mock quickstart

Install and verify the local CLI:

```powershell
uv sync --dev
uv run rh --help
uv run python -m pytest
```

Initialize a workspace from explicit inputs. The Seed may exist under
`quarantine/`; registration does not grant it access to Question Formation.

```powershell
uv run rh --root . init --theme intake/theme.md --expectations intake/expectations.md --seed quarantine/provisional_rq_seed.md --worker-backend mock
uv run rh --root . status
uv run rh --root . plan
uv run rh --root . continue --run-limit 10
```

`continue` assembles Context Packs, dispatches bounded workers, audits results,
and writes immutable run/state artifacts. It stops at a Human Decision Packet:

```powershell
uv run rh --root . decisions
uv run rh --root . decision show <decision-id>
uv run rh --root . decision record <decision-id> --choice ADOPT_PROPOSED_BASELINES --by <human-name>
uv run rh --root . continue --run-limit 10
uv run rh --root . validate
```

Attention intake is detachable from the normal Research cycle. Put raw material
in a workspace folder, explicitly register one batch, let the bounded Work
exchange distill it, and record the Human adoption decision:

```powershell
uv run rh --root . attention ingest --path .\intake\drop\batch-01 --by <human>
uv run rh --root . coordinator next
uv run rh --root . coordinator submit --result .rh\work_exchange\<run-id>\result.json
uv run rh --root . decision record <decision-id> --choice ADOPT_CANDIDATE_MAP --by <human>
```

The candidate is routing guidance only. `KEEP_CURRENT_MAP` and `REQUEST_REVISION`
are also explicit Human choices; a workspace may remain Map-less.

Archive and new-study creation are separate Harness operations. Archive first if
you need a frozen bundle, then initialize a clean target without copying the old
runtime:

```powershell
uv run rh --root . archive --destination ..\archives\misco-2026-08-19 --by <human> --reason "research boundary closed"
uv run rh --root ..\misco-next new --template-root . --theme .\intake\new-theme.md --expectations .\intake\new-expectations.md --worker-backend interactive-work
```

For a separate research repository, pass a versioned declarative Profile pack
and opt into Git initialization explicitly. `--init-git` only runs `git init`;
it does not create a commit, remote, or push.

```powershell
uv run rh --root ..\misco-study new `
  --template-root ..\misco-research-harness `
  --profile-source ..\misco-research-profile `
  --profile-ref v0.1.0 `
  --theme .\intake\theme.md `
  --expectations .\intake\expectations.md `
  --worker-backend interactive-work `
  --init-git
```

The generated `harness.lock.json` records Harness/Profile refs and hashes. To
upgrade a research workspace from a tagged Git/Forgejo archive:

```powershell
uv run rh --root . upgrade `
  --harness-source https://forgejo.example/hsaeki/misco-research-harness/archive/v0.2.0.zip `
  --harness-ref v0.2.0 `
  --profile-source https://forgejo.example/hsaeki/misco-research-profile/archive/v0.1.1.zip `
  --profile-ref v0.1.1
```

Upgrade is blocked while Work, Human Decisions, Attention drops, or transition
locks are pending, and when a Harness/Profile-managed file was edited in the
research workspace. It preserves `.rh` history and never uses
`git reset --hard`.

Harness and Profile are published as separate repositories. In the Windows
Codex environment, publish committed changes through the approved
`codex-safe-push.ps1` wrapper outside the Sandbox; the reviewer/approval layer
may allow that wrapper to run with the real user's Git Credential Manager
context. If Git reports dubious ownership for a trusted checkout, add only
that exact path to `safe.directory`; do not use the global `*` exception.

Inspect trace pointers without opening the whole project to a worker:

```powershell
uv run rh --root . runs show <run-id>
uv run rh --root . context show <run-id>
```

The CLI uses stable process exit codes: `0` for success, `10` when a Human
Decision is required, `11` when Work execution is required, and `1` for an
operational error. The JSON status on stdout/stderr remains the detailed
diagnostic surface.

Runtime output is written under `.rh/`. Run directories, Context Packs,
Decision Requests/Records, and state snapshots are immutable. Small `head.json`
documents and the Artifact Registry are atomically replaced pointers.

## Interactive Work Research

For a real research workspace, first read
[WORK_RESEARCH_COORDINATOR.md](WORK_RESEARCH_COORDINATOR.md). It is the stable,
research-neutral bootstrap contract for a Desktop Work session. Open the
repository in Work and tell Work only:

```text
Execute WORK_RESEARCH_COORDINATOR.md.
```

The Coordinator uses the Harness as the control plane and stops at the next
Human Decision. It does not assume a Work API, automate the Desktop UI, or
replace the Desktop Research contract. Real workspaces must explicitly select
the human-interactive backend; the CLI has no default backend, so an omitted
option cannot silently execute mock fixtures.

```powershell
uv run rh --root . init --theme intake/theme.md --expectations intake/expectations.md --worker-backend interactive-work
uv run rh --root . coordinator next
```

`--seed` is optional. To begin without a provisional prior seed, omit it from
`init`; Question Formation will run with only the Theme and Expectations. If a
human later decides to compare against a prior seed, register it before the
independent candidate snapshot is frozen:

```powershell
uv run rh --root . seed register --path quarantine/provisional_rq_seed.md
```

When no seed is registered, the independent candidate snapshot proceeds
directly to Question Review and Seed Comparison is skipped. A seed registered
after that snapshot is frozen is rejected for this cycle rather than being
introduced into the independent Question Formation Context Pack.

The Coordinator reads Harness state and returns one typed action. When the
action is `WORK_EXECUTION_REQUIRED`, it names the generated task, Context Pack,
schema, and result destination. That task is self-contained for the current
bounded run. Work reads only the Context Pack and manifest named in it, then
writes the required structured result to the exact expected output path. The
human does not choose a Context Pack or restate the research task.

For a direct manual check, the generated files are under
`.rh/work_exchange/<run-id>/` and Work can be told:

```text
Execute TASK.md.
```

Work writes the structured result to the location named in `TASK.md`. The
Coordinator submits it through the Harness and lets it validate, audit, reduce,
and expose the next action:

```powershell
uv run rh --root . coordinator submit --result .rh/work_exchange/<run-id>/result.json
uv run rh --root . coordinator next
```

Repeat the Coordinator loop at the next Work boundary. If the returned action
is `DECISION_REQUIRED`, Work stops and the human reviews and records the
emitted packet:

```powershell
uv run rh --root . decisions
uv run rh --root . decision show <decision-id>
uv run rh --root . decision record <decision-id> --choice <declared-choice> --by <human-name>
uv run rh --root . coordinator next
```

The Harness owns control, bounded Context Packs, schema validation, audit,
state reduction, decisions, and trace. Interactive Work performs bounded
research/reasoning only. The human owns semantic research decisions. Context
Packs remain immutable; task contracts, schemas, and result exchange live under
the separate `work_exchange` run directory.

### Evidence 0.1 provenance repair

For an explicitly prepared legacy repair plan, start the implementation-only
`PROVENANCE_AUDIT` boundary. Work still uses only the generated task and the
bounded Context Pack; it never writes into the Context Pack or Research State:

```powershell
uv run rh --root . provenance audit start --plan .rh/work_exchange/provenance-repair-28-20260817/manifest.json
uv run rh --root . coordinator next
```

Execute the generated `TASK.md`, then submit the exact result path returned by
the Coordinator:

```powershell
uv run rh --root . coordinator submit --result .rh/work_exchange/<run-id>/result.json
```

The Harness accepts only a complete 0.2 record or an explicit
`UNRESOLVED_GAP` for each target ID. A failed submission is retained as an
immutable failed trace; request a fresh exchange with:

```powershell
uv run rh --root . coordinator submit --reacquire
```

### Live contract migration

An existing `.rh` runtime can refresh its live Artifact Registry after the
contract or runtime policy files have changed. This is an explicit
`CONTRACT_MIGRATION_REVIEW` control-plane event: it freezes the old Registry,
validates the current contract set in a new Context Pack, and advances only
the Registry head. It does not reinitialize the workspace or change Research
State, Publication State, Human Decisions, or a pending Work run:

```powershell
uv run rh --root . contracts refresh
```

`contracts migrate` (and the singular `contract` spelling) are accepted as
aliases. A pending Work exchange must be collected or reacquired first so the
single Work slot remains unambiguous.

### Parallel provisional Publication

Publication does not form a new Research phase. Once a current Research State
has an explicit Human `publication_eligibility.status: ELIGIBLE`, refresh a
provisional Publication State while Research remains runnable:

```powershell
uv run rh --root . publication request-eligibility
uv run rh --root . decisions
uv run rh --root . decision show <publication-decision-id>
uv run rh --root . decision record <publication-decision-id> --choice ALLOW_PUBLICATION --by <human-name>
uv run rh --root . publication refresh
```

The eligibility request is a Publication-only Human Decision. It is not added
to Research's pending decision queue, so Research can continue while the human
decides whether the current snapshot may be used provisionally. The Harness
stores the recorded Decision ID in the Research State; neither Work nor the
Writer invents one.

The refresh generates a reader-facing provisional chapter/section structure
from the current Research State and the Attention Map. Chapter and section
add/remove/merge/split/move/rename changes are Publication-only deltas. They
cannot select a Research method, change a Research Question, or reinterpret
Evidence. A Writer result can be stored separately, together with structured
non-Evidence Feedback:

```powershell
uv run rh --root . publication writer-submit --result .rh/publication/writer-output.json
```

Research can continue, but a later Research snapshot does not inherit
Publication Eligibility. It must receive a new Publication-only Human Decision
before refresh; prior Publication snapshots and Feedback remain immutable.

Publication export and Feedback routing remain independently testable
application boundaries. The CLI exposes the supported Publication Lane
request, refresh, and Writer submission operations; it does not add commands
solely to expose internal exporter/router modules.

## What remains human and why

The Harness automates file transport and operational state. It does not make
research judgments. A human still records Question Baseline, method/protocol,
Evidence qualification, Finding/Model/Recommendation, claim-scope, and
Publication `STABLE`/`FINAL` decisions. These transitions change research or
release meaning; automatic adoption would violate the Research Constitution.

Mock mode does not perform external web research and is only for deterministic
tests and demonstrations. In interactive mode, protocol approval starts a real
human-executed Desktop Research Work task; its structured Handoff is audited and
reduced before the next Human research decision. Publication Writer integration
remains a bundle/interface boundary; this repository does not re-implement the
writer.

Each Desktop Research Evidence Capture now includes a UTC acquisition time, an
exact UTF-8 text snapshot, its SHA-256 and exchange path, plus typed
excerpt-to-locator mappings. Work writes snapshots under
`.rh/work_exchange/<run-id>/evidence_snapshots/`; the Harness verifies and
copies them immutably to the corresponding `.rh/runs/<run-id>/evidence_snapshots/`
directory before committing the Handoff and Research State. Working papers,
preprints, industry reports, and corporate publications are `LOW_CONFIDENCE`
context or lead evidence and cannot establish an independent or causal effect
alone. Social-media and online-forum material is `LOW_TRUST` exploratory input
only. Company blogs and press releases are `COMPANY_PRIMARY` / `COMPANY_CLAIM`,
not independent-effect evidence.

## Validation and limitations

See [the test report](docs/test_report.md) and
[known limitations](docs/known_limitations.md). The requirement-by-requirement
result is in [the MVP completion audit](docs/completion_audit.md). The active contract inventory
and non-blocking design decisions remain in
[the P0 contract freeze](docs/p0_contract_freeze.md).
