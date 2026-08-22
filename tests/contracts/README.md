# Canonical contract checks

This directory is the executable specification for the canonical contracts established by PR 3 (Core) and PR 4 (Profiles).

It is intentionally test-only. `core_semantic_oracle.py` and `semantic_oracle.py` model only the semantics needed to distinguish the canonical fixtures; they are not runtime validators, resolvers, storage services, or public APIs.

## Covered contracts

- Core research-object JSON Schema valid/invalid fixtures for every canonical object kind.
- Core non-overridable invariant graph/history fixtures.
- Profile manifest / Effective Profile Set schema and semantic fixtures.
- Core invariant catalog ↔ Profile strengthening-registry consistency.
- Deterministic version selection, composition, provenance, invariant evaluation, and canonical serialization under shuffled input order.

## Stable CI check

The workflow file is `.github/workflows/contracts.yml`. Both the workflow and job are named `contract-checks` deliberately so the resulting check can later be configured as a required status check without renaming it.

The workflow runs on every pull request rather than using path filters. A required check that is skipped because of path filtering can otherwise remain pending and block merging. The suite is kept small enough to run unconditionally.

Direct test dependencies are pinned and the CI environment fixes Python 3.12, `PYTHONHASHSEED`, timezone, and locale to reduce accidental variability.

## Scope

These tests must not grow into:

- a production research-object validator;
- a Profile runtime resolver;
- legacy implementation compatibility tests;
- SQLite/export/publish behavior;
- Writer/Publication implementation tests;
- concrete MISCO or source-quality policy.
