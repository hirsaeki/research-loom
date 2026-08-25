# Canonical SQLite Research State persistence

PR21 adds a concrete SQLite adapter beneath the storage-neutral persistence
port established by PR20. The core rule is unchanged:

> SQLite persists canonical Research State; SQLite does not define Research
> State semantics.

## Storage model

Canonical Core objects are stored as deterministic UTF-8 JSON payloads together
with their canonical payload digest. The adapter does not reconstruct canonical
objects from normalized SQL columns. Normalized columns and tables exist only
for integrity, lookup, optimistic concurrency, and diagnostics.

The schema keeps generic Research State structures:

- immutable `object_revisions`
- immutable `snapshots` plus normalized `snapshot_members`
- immutable Decision and AuditEvent indexes over their canonical object rows
- mutable Research Lineage HEAD pointers
- one active-lineage pointer per project
- used Decision, adoption, non-reusable, and source-mode indexes
- immutable commit/idempotency receipts
- project configuration / Effective Profile Set pins required to reconstruct
  PR20 `StateView`

There are intentionally no `survey_result`, `delphi_result`, `case_result`,
`poc_result`, or other Capability-specific persistence tables. A future
Capability can use existing Core object semantics without forcing a Research
State database schema change.

## Immutable entities and mutable pointers

Object `(kind, id, revision)` rows are immutable. Re-inserting exact canonical
content is harmless; a different payload at the same immutable identity fails
closed.

Snapshot identity is single-use even if content would be identical. Snapshot
payload JSON is the source representation; `snapshot_members` is only an
integrity/lookup index and never defines Snapshot ordering or content.

Decisions and AuditEvents are immutable. Used Decision refs are separately
unique so the database provides defense in depth against replay already
forbidden by Core validation.

Research Lineage HEAD and project active-lineage are the mutable pointers. They
may change only as part of a PR20 `CommitBundle`; there is no SQLite utility
method that silently moves them. Fork creation writes the child lineage without
moving the parent HEAD or implicitly switching the active lineage.

## Atomic commit and optimistic concurrency

`ResearchStateRepository.commit()` executes one `BEGIN IMMEDIATE` transaction.
Inside that transaction the adapter:

1. checks the idempotency key,
2. resolves the source lineage,
3. compares its current HEAD digest with
   `expected_head_snapshot_digest`,
4. compares the current HEAD ref/digest with the bundle's previous Snapshot,
5. inserts/checks immutable object revisions and Decisions,
6. inserts the new Snapshot and member index,
7. creates/updates Lineages,
8. updates the active-lineage pointer when requested,
9. records used Decisions and adoption refs,
10. records immutable AuditEvents,
11. writes the immutable CommitReceipt/idempotency record, and
12. commits.

Any failure rolls the entire transaction back. Two writers that both observed
the same old HEAD cannot both commit: after writer A advances the HEAD, writer B
fails with `StaleHeadError`. The adapter never auto-rebases or silently retries
Research semantics.

An idempotency key with the same request digest returns the previous immutable
receipt and creates no new Snapshot. The same key with a different request
digest fails with `IdempotencyConflictError`.

## SQLite configuration

The adapter explicitly enables foreign keys. Its default durability policy is
`journal_mode=DELETE`, `synchronous=FULL`, and a 5-second busy timeout.
`journal_mode=WAL` can be selected as an operational option, but correctness is
not coupled to WAL behavior. A SQLite lock/busy error remains a physical
persistence error and is not conflated with a stale HEAD.

The SQLite database is a local authoritative store. It must not be treated as a
file-sharing/synchronization contract for OneDrive, SharePoint, or equivalent
systems.

## Exact JSON and digests

Payloads are serialized with the canonical JSON routine owned by PR20 and
stored as UTF-8 text. Non-finite JSON numbers (`NaN`, `Infinity`) are rejected.
Read-back checks the stored canonical payload digest; Snapshot read-back also
checks its embedded canonical `content_digest`.

The adapter never derives canonical Research content from SQL indexes and does
not overwrite a payload's declared digest during serialization.

## Schema migrations

`schema_migrations` records deterministic numbered physical schema migrations.
Fresh databases migrate to the latest schema; older known versions apply all
pending migrations transactionally. A migration failure rolls back the
migration transaction. A database claiming a newer/unknown version fails
closed.

Migration rules:

- no silent rewrite of immutable object revisions,
- no Snapshot content rewrite,
- no historical Decision or AuditEvent deletion,
- no digest recalculation without an explicit canonical migration contract,
- no lineage ancestry loss.

Physical schema evolution and a hypothetical semantic Research State migration
are separate operations.

## Integrity diagnostics

`integrity_issues()` is read-only. It reports foreign-key failures, canonical
payload/digest mismatches, Snapshot member-index mismatches, missing/mismatched
Lineage HEADs, dangling active-lineage pointers, and CommitReceipt integrity
problems. It never "repairs" corruption into a new Research State.

## Boundaries

The adapter depends on `core.runtime`; `core.runtime` does not depend on the
adapter. Composition-root wiring is intentionally deferred.

Artifact bytes, protected raw participant data, exports, publishing,
OneDrive/SharePoint, review import, backup/restore CLI, encryption-at-rest,
production Capability executors, Writer/Publication production runtimes, and
legacy schema deletion are outside PR21.
