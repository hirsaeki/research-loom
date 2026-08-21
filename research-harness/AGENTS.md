# MISCO Research Harness repository rules

## GOAL.md work-ledger lifecycle

- `GOAL.md` is a temporary work ledger for the current multi-step task. It is
  not a durable contract, archive, project history, or source of research
  authority.
- Put durable scope, contracts, invariants, operator procedures, and acceptance
  evidence in the appropriate `docs/` or `contracts/` files while the work is
  in progress.
- Keep `GOAL.md` while any work item remains incomplete. An unresolved
  documentation gap or stale reference is also incomplete work.
- When all work items and documentation gaps are resolved, delete `GOAL.md`
  completely as part of the completion cleanup. Do not retain a pointer,
  archive copy, or historical duplicate solely to preserve the ledger; Git
  history is sufficient.
- Do not treat the absence of `GOAL.md` as a missing contract. Use the durable
  documents and the active contract inventory in `docs/p0_contract_freeze.md`.

- Treat the current increment scope and active implementation contracts listed in
  `docs/work_chat_recovery_scope.md` and `docs/p0_contract_freeze.md` as the
  repository's durable implementation authority.
- Treat `vendor/misco-publication-writer` as the RC1 integration contract, never as a runtime skill.
- Do not discover or read `archive/provenance/` during ordinary implementation
  or runtime work. Access requires an explicitly permitted provenance or
  migration event under the applicable active contract.
- Unknown and unregistered artifact roles fail closed. Never infer access from a path or filename.
- Publication drafts and publication feedback are never research evidence.
- VIRTUAL/SYNTHETIC and REAL/EMPIRICAL material must remain isolated unless an explicit bridge contract exists.
- Human research decisions must not be auto-committed. Preserve immutable run history and prior snapshots.
- Use `uv`, Python 3.12+, pytest, JSON state, SHA-256, and atomic filesystem writes.
- Implement and test one milestone at a time. Run the narrow milestone tests before proceeding.
