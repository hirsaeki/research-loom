# Core

Canonical home for organization-agnostic research semantics, validation, and versioned interface contracts.

Python packages:

- `runtime/` — Research State model, state transitions and their validation (`*_validation.py`), digests and repository ports.
- `execution/` — Capability execution, authorization and context packs.
- `conversation/` — Work Conversation service and action routing.
- `decision/` — Human Decision Gate.

Each of `runtime/`, `execution/` and `conversation/` has a `testing.py` with deterministic in-memory doubles for tests. Production code never imports them; `tests/contracts/test_core_testing_doubles.py` checks that.

Data and contracts:

- [`models/research-object.schema.json`](models/research-object.schema.json) — canonical research-object semantic floor.
- [`validators/non-overridable-invariants.yaml`](validators/non-overridable-invariants.yaml) — hard invariants Profiles, Projects, plugins, skills, and implementations may not weaken. This directory holds the declarative catalog only; the code that enforces it lives in `runtime/`.
- [`packages/`](packages/) — common Research Capability Descriptor, bounded Context Pack, Invocation, Handoff, provenance, and adoption-boundary contracts established by PR 9.
- `fixtures/` — valid and invalid example documents for the contracts above.

Core owns shared meaning and cross-component boundaries. It does not own concrete Capability adapters, storage, SQLite/export/publish, or Writer/Publication implementations.
