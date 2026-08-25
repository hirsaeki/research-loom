# SQLite Research State Store

`SQLiteResearchStateRepository` is the first production persistence adapter for
the storage-neutral PR20 `ResearchStateRepository` port.

It is deliberately **not** a Research semantics layer. Core/runtime owns
validation, reduction, authority, Human Decision, VIRTUAL/REAL, and lineage
semantics. This adapter owns physical transactions, durability, indexes,
migrations, optimistic concurrency checks at commit time, and fail-closed
integrity diagnostics.

## Placement and dependency direction

```text
plugins/sqlite_state_store
        |
        | implements
        v
core.runtime.ResearchStateRepository
```

`core/runtime/*` never imports this package. Application composition/wiring is a
separate concern.

The implementation uses Python's stdlib `sqlite3`; no ORM is introduced.

## Connection policy

Defaults are explicit:

- `PRAGMA foreign_keys = ON`
- `PRAGMA journal_mode = DELETE`
- `PRAGMA synchronous = FULL`
- `PRAGMA busy_timeout = 5000`
- authoritative writes use `BEGIN IMMEDIATE`

`WAL` may be selected operationally, but correctness does not depend on WAL.
A lock/busy failure is a physical persistence failure; it is not reported as a
stale Research Lineage HEAD.

## Bootstrap

`initialize_from_validated_state_view(...)` exists only for migration, tests,
and initial bootstrap from an already validated PR20 `StateView`. It is not a
normal Research State mutation API. Normal writes must go through
`StateTransitionService` and one `CommitBundle`.

## Migrations

Migrations live in `migrations/` and are numbered deterministically from
`0001`. All pending physical migrations are applied in one explicit SQLite
transaction. A failed migration rolls the whole migration transaction back.
Unknown/newer schema versions fail closed.

Physical SQLite schema migration is distinct from Research State migration.
Future migrations must not silently rewrite immutable object revisions or
Snapshots, delete historical Decisions/AuditEvents, recalculate canonical
digests without an explicit canonical migration contract, or discard lineage
ancestry.

## Non-goals

This adapter does not store arbitrary PDF/binary/raw-dataset bytes and is not a
secret manager. It does not export JSON/YAML/Markdown, publish DOCX/PDF, sync
with OneDrive/SharePoint, import reviews, execute Capabilities, or define
Capability-specific result tables.

The database file is local authoritative runtime state. It is **not** a
OneDrive/SharePoint interchange or sharing format. Future sharing should use a
projection/publish layer:

```text
SQLite authoritative state
        -> snapshot/export projection
        -> JSON/YAML/Markdown
        -> publication/shared artifacts
```
