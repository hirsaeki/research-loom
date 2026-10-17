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
uv run --frozen python -m unittest discover -t . -s tests -p 'test_*.py'
```

When iterating, it is fine to run only the affected test modules, but run the full suite before you report the work as done.

## Conventions

- `core/` stays generic. It must not import `plugins/` and must not contain organization-specific (MISCO) logic. It must pass `mypy --strict`.
- `plugins/_infra/` holds low-level helpers (file locks, atomic writes, SQLite PRAGMAs). It must not import other plugins and must pass `mypy --strict`.
- Plugin packages must not import each other in a cycle (lazy imports count) or import another package's `_private` names; see the plugin layering in [`docs/architecture/monorepo-structure.md`](docs/architecture/monorepo-structure.md). `tests/contracts/test_plugin_layering.py` enforces this.
- Import test helpers as `tests.runtime.*` / `tests.contracts.*`.
- Test modules that branch on the platform must declare `CI_WINDOWS = True` or `CI_WINDOWS = False  # reason`.
- Never edit or extend `research-harness/` or `research-profile/`. They are frozen legacy reference trees.
- Never change digest-pinned assets (profiles, project configs, effective profile sets, fixtures) unless the task is explicitly about them. Their digests are checked by tests.
- Keep refactors behavior-preserving, and do not skip, disable, or weaken tests to get CI green.
- Reference the tracking issue in commits and PRs. The roadmap is [#475](https://github.com/hirsaeki/research-loom/issues/475).
