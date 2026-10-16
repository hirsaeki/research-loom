# research-loom

`research-loom` is a monorepo for a reusable research harness, composable research profiles, writing/publication skills, organization-specific plugins, and project configuration.

## What it does

Research Loom keeps an LLM-assisted research project auditable: the conversation proposes, but only exact, Decision-bound commits change research state, and every material and claim stays traceable to pinned sources.

Through the production CLI (below) and its application facade a host can:

- **Bind a workspace** to an exact Project Config and Effective Profile Set (`init`, `status`, `resume`, `doctor`, `profile`).
- **Run research**: register inputs, propose and review research questions, run capabilities such as Desktop Research, Survey (real and virtual respondents) and Delphi, and inspect runs and captured external materials (`research-input`, `run`, `external`, `survey`, `delphi`, `candidate`, `synthesis-candidate`, `exhibit`).
- **Gate changes through people**: proposals become Confirmations and Human Decisions before any atomic commit (`actions`, `action`, `confirmation`, `decision`).
- **Package and write**: evaluate research quality, build pinned Research Packages, and round-trip detached Writer input and manuscript revisions, with writing feedback routed back to research (`research-quality`, `research-package`, `writer-composition`, `writer-round-trip`).
- **Publish**: build DOCX/PDF previews, run machine and editorial checks, and release only on a bound human decision (`publication`).

Late needs found while writing or publishing (a missing figure, a missing warrant) return to research instead of being patched in prose.

The canonical code lives in `core/`, `profiles/`, `plugins/`, `skills/` and `projects/` (see [Target areas](#target-areas)). The legacy `research-harness/` and `research-profile/` trees are migration and reference material only, are not runtime authority, and are scheduled for removal (#500); do not add new concepts to them.

For a human-facing research session driven by Codex or ChatGPT Work, explicitly load [`skills/research-conversation/SKILL.md`](skills/research-conversation/SKILL.md). The repository does not assume either host automatically discovers this skill, and repository development/review tasks should not be routed through it.

For Work deployment, see [runtime readiness, durable continuation and file delivery](docs/operations/work-host-runtime.md). Work reuses the existing Application Facade/CLI; a scratch workspace still requires a provisioned runtime and a durable whole-workspace backup before cross-session continuity can be promised.

## Production CLI

Research Loom requires Python 3.12+ and `uv`. Root `pyproject.toml` and `uv.lock` are the single repository/application dependency contract. (The legacy `research-harness/` keeps its own manifest for reference only; nothing installs it.)

For normal harness/host runtime use, provision the root project environment first with `uv sync --frozen` outside the host sandbox, then invoke the repository launcher from the repository root. Runtime launchers execute the pre-synced root `.venv` directly; they do not invoke `uv`, mutate dependencies, or depend on the persistent uv cache.

Windows / PowerShell:

```powershell
.\research-loom.cmd status --workspace PATH --json
.\research-loom.cmd resume --workspace PATH --json
.\research-loom.cmd actions --workspace PATH --json
.\research-loom.cmd synthesis-candidate list --workspace PATH --limit 20 --json
.\research-loom.cmd synthesis-candidate show --workspace PATH --candidate-id SDP-ID --json
.\research-loom.cmd run show --workspace PATH --run-id RUN-ID --json
.\research-loom.cmd external materials list --workspace PATH
.\research-loom.cmd external materials list --workspace PATH --json
.\research-loom.cmd research-quality evaluate --workspace PATH --json QUALITY-INPUT.json
.\research-loom.cmd action submit --workspace PATH --json TEMP-INPUT.json
```

POSIX:

```bash
./research-loom status --workspace PATH --json
./research-loom resume --workspace PATH --json
./research-loom actions --workspace PATH --json
./research-loom synthesis-candidate list --workspace PATH --limit 20 --json
./research-loom synthesis-candidate show --workspace PATH --candidate-id SDP-ID --json
./research-loom run show --workspace PATH --run-id RUN-ID --json
./research-loom external materials list --workspace PATH
./research-loom external materials list --workspace PATH --json
./research-loom research-quality evaluate --workspace PATH --json QUALITY-INPUT.json
./research-loom action submit --workspace PATH --json TEMP-INPUT.json
```

Use `external materials list` to answer which external research materials were actually captured in the workspace. It is material-centric: capture pairs are grouped across Runs only when their persisted original-byte content digests are identical. Retrieval attempts which produced no capture are not materials. Use `run show` when the question is about one Run's retrieval attempts, failures, diagnostics, or artifact provenance.

Ordinary operator workflow should not inspect `execution.db`, other SQLite stores, or artifact/blob directory layout to decide what has been captured. Research Exhibits are separate working analytical artifacts and are not included in the external material inventory.

Structured production input should be supplied through a UTF-8 JSON file rather than relying on stdin. Runtime launchers do not install, download, bootstrap, synchronize, or upgrade dependencies; they execute the pre-synced root `.venv` directly and fail closed if it has not been provisioned. They do not fall back to system Python, another environment, or runtime `uv` resolution.

For developer/debug use, the explicit form remains supported:

```bash
uv run --frozen python research-loom status --workspace PATH --json
```

No separate script dependency manifest or lockfile exists.

## Developer checks

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full development guide; coding agents should also read [AGENTS.md](AGENTS.md). Developer tools live in the opt-in `dev` dependency group, so runtime provisioning above stays runtime-only. CI runs the same checks:

```bash
uv sync --frozen --group dev
uv run --frozen --group dev ruff check .
uv run --frozen --group dev ruff format --check .
uv run --frozen --group dev mypy          # strict, currently scoped to core/
uv run --frozen python -m unittest discover -t . -s tests -p 'test_*.py'   # all tests
```

`tests/` is a package: shared fixtures are imported as `tests.runtime.*` / `tests.contracts.*`, so no `PYTHONPATH` setup is needed. Narrow a run with `-s tests/runtime` or `-s tests/contracts`, or pass test file paths / dotted module names directly to `python -m unittest`.

Formatting-only commits are listed in `.git-blame-ignore-revs`; run `git config blame.ignoreRevsFile .git-blame-ignore-revs` to skip them in local `git blame`.

## Target areas

- `core/` — generic research semantics: state transitions and validation, capability execution, Work Conversation and Human Decision services, and the versioned package/schema contracts
- `profiles/` — declarative research, organization, narrative, and publication profiles plus their contracts
- `plugins/` — imperative adapters: the local application facade and CLI, SQLite stores, capability implementations, and organization-specific extensions
- `skills/` — host-loaded workflows: `research-conversation`, `writer`, and `publication`
- `projects/` — project-specific configuration (Project Config and pinned Effective Profile Set)
- `docs/` — architecture records, operations guides, acceptance records, and migration ledgers
- `tests/` — `tests/contracts` (schema and semantic contracts) and `tests/runtime` (behavior); see [Developer checks](#developer-checks)
- `scripts/` — operational and CI helpers (offline runtime wheelhouse, CI test sharding, MISCO probes)

See [`docs/architecture/monorepo-structure.md`](docs/architecture/monorepo-structure.md) for ownership boundaries and [`docs/architecture/production-local-workspace-application-cli.md`](docs/architecture/production-local-workspace-application-cli.md) for the production local application boundary.
