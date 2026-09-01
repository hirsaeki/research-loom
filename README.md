# research-loom

`research-loom` is a monorepo for a reusable research harness, composable research profiles, writing/publication skills, organization-specific plugins, and project configuration.

## Repository status

The canonical production path has converged through PR26: Core research semantics and Profiles/Project Config, Capability ABI and Research Method contracts, Desktop Research external execution, lineage/recovery, production State transitions and SQLite persistence, execution/artifact/resource persistence, Work Conversation coordination, and the Human Decision Gate with atomic Decision-bound commits are connected end to end.

PR27 adds the production-local operator boundary: fresh local workspace bootstrap/reopen, exact Project Config + Effective Profile Set binding, a transport-neutral application facade, and a machine-oriented JSON CLI. ChatGPT Desktop App Work is the first intended human-facing consumer, but Work/ChatGPT semantics are not part of the Harness itself.

The legacy directories remain reference material only:

- `research-harness/` — legacy Research Harness implementation
- `research-profile/` — legacy Research Profile implementation

New work should converge toward the canonical areas below rather than adding new cross-cutting concepts to either legacy tree.

## Production CLI

Research Loom requires Python 3.12+ and `uv`. Root `pyproject.toml` and `uv.lock` are the single repository/application dependency contract.

For normal operator use, invoke the repository launcher from the repository root. The launcher owns frozen `uv` execution; callers do not need to select a Python environment.

Windows / PowerShell:

```powershell
.\research-loom.cmd status --workspace PATH --json
.\research-loom.cmd resume --workspace PATH --json
.\research-loom.cmd actions --workspace PATH --json
.\research-loom.cmd run show --workspace PATH --run-id RUN-ID --json
.\research-loom.cmd external materials list --workspace PATH
.\research-loom.cmd external materials list --workspace PATH --json
.\research-loom.cmd action submit --workspace PATH --json TEMP-INPUT.json
```

POSIX:

```bash
./research-loom status --workspace PATH --json
./research-loom resume --workspace PATH --json
./research-loom actions --workspace PATH --json
./research-loom run show --workspace PATH --run-id RUN-ID --json
./research-loom external materials list --workspace PATH
./research-loom external materials list --workspace PATH --json
./research-loom action submit --workspace PATH --json TEMP-INPUT.json
```

Use `external materials list` to answer which external research materials were actually captured in the workspace. It is material-centric: capture pairs are grouped across Runs only when their persisted original-byte content digests are identical. Retrieval attempts which produced no capture are not materials. Use `run show` when the question is about one Run's retrieval attempts, failures, diagnostics, or artifact provenance.

Ordinary operator workflow should not inspect `execution.db`, other SQLite stores, or artifact/blob directory layout to decide what has been captured. Research Exhibits are separate working analytical artifacts and are not included in the external material inventory.

Structured production input should be supplied through a UTF-8 JSON file rather than relying on stdin. The launchers do not install, download, bootstrap, or upgrade `uv`, and they do not fall back to system Python or another environment when `uv` is unavailable.

For developer/debug use, the explicit form remains supported:

```bash
uv run --frozen python research-loom status --workspace PATH --json
```

No separate script dependency manifest or lockfile exists.

## Target areas

- `core/` — generic research domain, provenance, workflow, validation, and package contracts
- `profiles/` — declarative research, organization, narrative, and publication profiles
- `plugins/` — imperative integration and organization-specific extension code
- `skills/` — writer and publication workflows that consume versioned packages/contracts
- `projects/` — project-specific configuration, inputs, and artifacts

See [`docs/architecture/monorepo-structure.md`](docs/architecture/monorepo-structure.md) for ownership boundaries and [`docs/architecture/production-local-workspace-application-cli.md`](docs/architecture/production-local-workspace-application-cli.md) for the production local application boundary.
