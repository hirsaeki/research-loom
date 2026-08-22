# Canonical contract checks

This directory is the executable specification for the canonical contracts established by PR 3 (Core) and PR 4 (Profiles).

It is intentionally test-only. `core_semantic_oracle.py` and `semantic_oracle.py` model only the semantics needed to distinguish the canonical fixtures; they are not runtime validators, resolvers, storage services, or public APIs.

## Covered contracts

- Core research-object JSON Schema valid/invalid fixtures for every canonical object kind.
- Core non-overridable invariant graph/history fixtures, including exhaustive schema-defined reference forms, immutable snapshots, snapshot-member identity/digest behavior, human-owned authoritative transitions, and epistemic reclassification.
- Profile manifest / Effective Profile Set schema and semantic fixtures.
- Core invariant catalog ↔ Profile strengthening-registry consistency.
- Deterministic version selection, composition, provenance, invariant evaluation, and canonical serialization under shuffled input order.

### Fixture-only sentinels

Some Core invariants are intentionally implementation-neutral and therefore do not prescribe a runtime wire representation for the proof they require. The contract tests use deterministic **fixture-only sentinels** to make those requirements executable without expanding the canonical runtime contract:

- `Decision.decision_kind` / `Decision.choice` sentinel pairs such as `research_adoption` + `approve`, `research_revision` + `revise`, and `evidence_qualification` + `verify` represent a Decision that resolves the fixture transition being tested. PR 3 leaves both fields as non-empty strings; these sentinel values are **not** a production enum or required runtime vocabulary.
- When a snapshot-member digest must be checked, the fixture oracle uses SHA-256 over RFC 8785 canonical JSON bytes of the exact fixture object revision. This is a deterministic test convention for proving that the member digest identifies its target revision; it does **not** establish a runtime object-serialization or package-wire digest format.

A conforming implementation may use different Decision vocabulary, serialization, storage, or validation machinery as long as its behavior is equivalent to the canonical invariant.

### Reference completeness

`reference-cases.json` contains one schema-valid complete research graph and one schema-valid mutation for every reference-bearing field in the Core JSON Schema. The test suite derives the reference-field inventory independently from the schema and requires exact equality with both the oracle mapping and fixture mutation inventory. This prevents a newly added Core reference from silently escaping `CORE-REF-001` regression coverage.

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
