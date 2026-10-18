# Contributing to research-loom

This guide covers repository development: setting up, running the checks CI runs, and the conventions changes are expected to follow. For *using* Research Loom in a research session, see the [README](README.md) and [`skills/research-conversation`](skills/research-conversation/SKILL.md) instead.

## Setup

Python 3.12+ and [`uv`](https://docs.astral.sh/uv/) are required.

```bash
uv sync --frozen --group dev
```

Runtime provisioning (`uv sync --frozen`, the offline wheelhouse) stays runtime-only; the `dev` group adds ruff and mypy. Note that a plain `uv run --frozen ...` re-syncs to the runtime-only set, so keep passing `--group dev` when you use the tools through `uv run`.

## Checks

CI runs exactly these; run them before pushing.

```bash
uv run --frozen --group dev ruff check .
uv run --frozen --group dev ruff format --check .
uv run --frozen --group dev mypy                                   # strict, scoped to core/ and plugins/_infra/
uv run --frozen python -m unittest discover -t . -s tests -p 'test_*.py'
```

- `tests/contracts/` holds schema and semantic contract tests (fast); `tests/runtime/` holds behavior tests (slower, about 20 minutes serially).
- `tests/` is a package. Import shared fixtures as `tests.runtime.<module>` / `tests.contracts.<module>`; no `PYTHONPATH` setup is needed.
- Narrow a run with `-s tests/runtime`, or pass dotted module names or file paths to `python -m unittest`.

## Windows-sensitive tests

CI runs a Windows lane in addition to Linux. A test module joins it by declaring a module-level constant:

```python
CI_WINDOWS = True
```

- Any test module that branches on the platform (`os.name == "nt"`, `sys.platform`, `msvcrt`, ...) **must** declare `CI_WINDOWS` explicitly, `True` or `False` with a reason comment. `tests/contracts/test_ci_test_selection.py` enforces this.
- Shards are balanced from `tests/ci_durations.json`. After adding or substantially changing slow tests, refresh it with `uv run --frozen python scripts/ci_test_shards.py measure` and inspect the result with `... plan --platform linux --shards 4`.

## Architecture rules

See [`docs/architecture/monorepo-structure.md`](docs/architecture/monorepo-structure.md). In short:

- `core/` must not import `plugins/`, profiles, projects, or the legacy trees, and must not encode organization-specific (e.g. MISCO) behavior.
- Organization-specific policy belongs in declarative profiles; imperative extensions belong in `plugins/`.
- The legacy `research-harness/` and `research-profile/` trees were removed in #500 (tag `legacy-archive-2026`). Do not edit `docs/migration/misco-legacy-sources/`, which keeps the ledger-pinned legacy files byte for byte (#499).

## Binary and generated files

- Keep every tracked file under 256 KB. A larger file must be listed in `ALLOWED_LARGE` in `tests/contracts/test_committed_assets.py` with the reason it lives in the repository; the test fails otherwise.
- Do not use Git LFS. An offline checkout or wheelhouse must not depend on an LFS server.
- A generated file kept in the repository needs a regeneration command with a `--check` mode, and a test that compares the committed bytes with a fresh build. For example, `projects/misco-ai-2026/effective-profile-set.json` is rebuilt with `uv run --frozen python scripts/regenerate_project_eps.py` and verified by `tests/contracts/test_misco_production_project.py`.
- A binary kept as a record (such as `docs/acceptance/writer-reader-quality/detached-inputs.zip`) needs its digest recorded next to it and checked by a test.

## Pull requests

- Work is tracked on the [repository health roadmap (#475)](https://github.com/hirsaeki/research-loom/issues/475) and its epics. Keep one issue per PR and reference it with `Closes #N`.
- Keep refactors behavior-preserving unless the issue says otherwise, and say how you verified that in the PR body.
- Merge with **Rebase and merge**. GitHub rewrites commit SHAs when rebasing. If a PR adds a formatting-only commit, update `.git-blame-ignore-revs` with the SHA it receives on `main`.

## Codex Stop hook

`.codex/hooks.json` registers a Stop hook (`.codex/hooks/research_conversation_stop_guard.py`) that keeps internal implementation terms out of user-facing research-conversation answers. It applies only to sessions whose transcript shows `skills/research-conversation/SKILL.md` was loaded, so repository development sessions are not affected. Set `RESEARCH_LOOM_STOP_GUARD=off` (or `on`) to override the detection.
