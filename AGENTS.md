# Agent instructions for repository development

These instructions are for coding agents (Codex, Claude Code, and similar) that edit, review, test, or maintain this repository.

If the user has asked you to conduct a research session with the research-conversation Skill, follow that Skill instead; nothing in this file applies to such a session.

**Do not load `skills/research-conversation/SKILL.md` for development work.** That Skill, together with the Codex Stop hook that enforces it, is for human-facing research sessions only. See [`skills/research-conversation/references/host-bootstrap.md`](skills/research-conversation/references/host-bootstrap.md).

## Before you finish a change

Run the same checks CI runs (details in [CONTRIBUTING.md](CONTRIBUTING.md)):

```bash
uv sync --frozen --group dev
uv run --frozen --group dev ruff check .
uv run --frozen --group dev ruff format --check .
uv run --frozen --group dev mypy
uv run --frozen python scripts/run_tests.py --jobs 4
```

When iterating, it is fine to run only the affected test modules, but run the full suite before you report the work as done. The runner verifies its selection against full unittest discovery before executing contracts and all runtime/unit modules in parallel; this is the full suite on every platform, not the Windows CI subset.

## Conventions

- Preserve human research continuity when introducing or changing limits. Follow [Research continuity and operational limits](docs/architecture/research-continuity-and-operational-limits.md) and the [runtime count and capacity limits inventory](docs/architecture/operational-count-limits-inventory.md): operational count/capacity thresholds default to warnings, preserve all data, and never silently truncate. Keep required research/domain, integrity, provenance, security, and authority blockers distinct; unavoidable capacity failures belong to the affected operation and must provide a recoverable continuation path.
- `core/` stays generic. It must not import `plugins/` and must not contain organization-specific (MISCO) logic. It must pass `mypy --strict`.
- MISCO-specific behavior lives in `plugins/local_application/misco/`, behind an extension point such as `PublicationDialect`. Generic code must not branch on a MISCO id; `tests/contracts/test_misco_isolation.py` enforces this.
- `plugins/_infra/` holds low-level helpers (file locks, atomic writes, SQLite PRAGMAs). It must not import other plugins and must pass `mypy --strict`.
- Plugin packages must not import each other in a cycle (lazy imports count) or import another package's `_private` names; see the plugin layering in [`docs/architecture/monorepo-structure.md`](docs/architecture/monorepo-structure.md). `tests/contracts/test_plugin_layering.py` enforces this.
- Import test helpers as `tests.runtime.*` / `tests.contracts.*`.
- Test modules that branch on the platform must declare `CI_WINDOWS = True` or `CI_WINDOWS = False  # reason`.
- The legacy `research-harness/` and `research-profile/` trees were removed in #500; the `legacy-archive-2026` tag keeps them. Never edit `docs/migration/misco-legacy-sources/`: it holds byte-identical copies of the legacy files that the migration ledger pins.
- Never change digest-pinned assets (profiles, project configs, effective profile sets, fixtures) unless the task is explicitly about them. Their digests are checked by tests.
- Keep refactors behavior-preserving, and do not skip, disable, or weaken tests to get CI green.
- Reference the tracking issue in commits and PRs. The roadmap is [#475](https://github.com/hirsaeki/research-loom/issues/475).
