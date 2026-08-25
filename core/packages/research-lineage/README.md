# Research Lineage / Fork / Recovery

This package defines the canonical logical lineage boundary for immutable Research State snapshots. A Research Lineage is not a Git branch and a Fork is not rollback.

## Core rules

- Research Snapshots remain immutable; a lineage head is only a pointer to the current immutable Snapshot.
- Fork and Recovery are append-only. Parent history, Runs, Decisions, Evidence, Findings, and downstream artifacts are never deleted or rewritten.
- `exploratory_fork` preserves the source path while allowing an alternative hypothesis, Method, scope, Project Config, or Profile path.
- `corrective_recovery` starts from a known-good historical Snapshot and requires explicit impact treatment and replay provenance.
- Inheritance is explicit: `PRESERVE`, `RECONFIRM`, or `INVALIDATE`. `INVALIDATE` preserves historical truth; `RECONFIRM` never means automatically approved.
- The Harness remains the only authoritative Research State write boundary. LLMs and Capabilities may propose Fork/Recovery actions, treatments, execution order, and next Methods but cannot commit or adopt them.
- Fork creation and active-lineage selection are distinct operations.
- Automatic lineage merge is forbidden. Comparison is read-only; selective adoption/convergence is a future contract.

## Replay and recovery

Replay uses an approved immutable plan, rebuilds Context Packs from the target lineage, allocates new Run IDs, and produces new Capability Invocations/Handoffs. Old Run IDs and Handoffs cannot be reused as new results. Interrupted and partial replay remain explicit historical states.

## Identity

Core Research Object schemas are not globally modified with `lineage_id`. A Fork Plan may carry parent→derived object mappings plus the origin Snapshot, preventing `(kind, id, revision)` collisions without making lineage identity a universal Core field.

## Writer / Publication

PR18 packages remain immutable historical artifacts. `research-package-lineage-binding.schema.json` binds an exact Research Package digest to an exact source Lineage digest and source Research Snapshot digest. After active-lineage selection, old packages may be `stale`, `non_current`, or `rebuild_required`; they are not deleted or promoted into the new lineage.

## VIRTUAL / REAL

Forks are only `virtual → virtual` or `real → real`. PR17 cutover remains the only VIRTUAL→REAL boundary; synthetic Evidence, Analysis, Finding content, participant identity, or virtual manuscript content cannot cross through Fork/Recovery.

Runtime persistence, SQLite, workspace cloning, Git integration, automatic merge, convergence implementation, concrete recovery execution, and Writer/Publication runtime are intentionally out of scope.
