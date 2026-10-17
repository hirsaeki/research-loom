# ADR 0001: Two persistence tiers with shared conventions

- Status: Accepted
- Date: 2026-10-17
- Tracking: #492 (roadmap #475, Epic #478)

## Context

The local stores under `plugins/` come in two shapes, and there was no rule for which shape a new store should take:

- **Package stores**: `sqlite_state_store/`, `local_execution_store/`, `local_conversation_store/` and `local_decision_store/`.
- **Module stores on the optional-durable registry**: `local_durable_store.py` together with `local_{attention,delphi,project_input,research_exhibit,survey,survey_analysis,survey_response}_store.py`.

#488 and #490 already moved the shared mechanics down a layer: file locks, atomic writes and SQLite PRAGMAs live in `plugins/_infra/`, and the DDL of the module stores lives in `plugins/local_store_schemas.py`. The comparison below is of what is left after that.

## Comparison

| Concern | Package stores | Module stores |
|---|---|---|
| Lifecycle | Required. Created by `LocalResearchApplication` at workspace init. Every workspace open checks them, and a failed check stops the open. | Optional. Created lazily on first write and registered in the binding's `durable_children` before any domain data is accepted. A lost child makes the workspace DEGRADED and stops only its own feature. |
| Connections | One long-lived connection per store. Execution, Conversation and Decision guard it with an `RLock` and open it with `check_same_thread=False`. | A new connection for every operation. |
| Atomicity | Every write runs in `BEGIN IMMEDIATE … COMMIT` and rolls back on error. In Execution, nested writes join the outer transaction. | Most writes use `BEGIN IMMEDIATE`. Two do not: `LocalSurveyStore._capture` uses Python's implicit transaction, and `LocalAttentionStore.store_map` uses a deferred `with connection`. |
| Cross-database writes | None are distributed. `guard_research_state_head` holds the State writer lock across a registry write. Decision uses a RESOLVING claim, then a finalize or recovery step. | Same as package stores; they take part through the guard. |
| Durability settings | Explicit. State and `execution.db` use `journal_mode=DELETE` with `synchronous=FULL`. Conversation, Decision and the two execution side databases use WAL with `FULL`. | Not set; SQLite's defaults apply. |
| Schema version | State and Execution keep a `schema_migrations` table and apply numbered `.sql` migrations in one transaction. Conversation and Decision record no version: they create tables if missing, check the columns and fail closed on a mismatch. | A one-row `*_store_meta(schema_version)` table that must match exactly; there are no migrations. Project Input differs: it uses `PRAGMA user_version` and has a real migration. |
| Diagnostics | Workspace open and `doctor` run `quick_check` and a required-column check. The deeper `integrity_issues()` on State (full `integrity_check`, foreign keys, digests) has no caller. | `inspect_optional_child(ren)` reports OK, UNINITIALIZED, UNAVAILABLE or LEGACY_AMBIGUOUS, and `doctor` adds `quick_check`. Every read and write first calls `require_optional_available`. Payload digests are checked on each load. |
| Locking | Within a process: the `RLock`. Across processes: the SQLite busy timeout and the workspace lifetime lock (`workspace_lock`). | The SQLite busy timeout, plus `_infra/file_lock` around registration in the inventory. |
| Backup and restore | Covered by the whole-Parent quiesced copy (`parent-backup-restore.md`). | Same procedure. In addition, a lost child is restored exactly and is never recreated automatically (`optional-durable-health.md`). |
| Testing | Built on real files in temporary directories. Large public surfaces. | Built on real files in temporary directories. Small `exists` / `capture*` / `load*` / `list*` surfaces, exercised mostly through the facade. |

The two shapes are different in kind, not just in file layout. The package stores are the workspace's required core, and the module stores are optional feature registries. The difference in shape follows from that split. Merging the two into one shape would either make every feature registry a required, eagerly created store, or make the core stores optional. Neither is wanted.

The differences that do *not* follow from the split are accidental:
- module stores leave journal and synchronous settings to SQLite's defaults;
- two module-store writes skip `BEGIN IMMEDIATE`;
- schema versions are recorded in three different ways;
- the deep State integrity check is never run.

## Decision

1. **Keep two tiers, and choose a new store's tier by its role.**
   - **Core tier** (package stores): data the workspace cannot open without. Created at init, checked on every open, may hold a long-lived connection. Lives in a package under `plugins/`.
   - **Optional tier** (module stores): feature registries a workspace can run without. Created lazily, listed in `OPTIONAL_DURABLE_CHILDREN` (`plugins/local_workspace_layout.py`), registered through `local_durable_store.register_optional_path` before the first domain write, guarded by `require_optional_available`, and inspected by `inspect_optional_child`. Its DDL goes in `plugins/local_store_schemas.py`. Lives in a single `plugins/local_<name>_store.py` until it outgrows one module.
2. **Share these conventions across both tiers:**
   - Every mutation runs in `BEGIN IMMEDIATE … COMMIT`, with rollback on error.
   - Every connection applies its PRAGMAs through `_infra.sqlite.apply_pragmas` and sets `journal_mode` and `synchronous` explicitly: `synchronous=FULL` in both tiers, and `DELETE` or `WAL` by store as today.
   - The schema version is recorded in exactly one place per store:
     - `schema_migrations` with numbered migrations in the core tier;
     - the `*_store_meta` row in the optional tier.
     - An unknown or newer version is rejected. An upgrade, when one exists, runs in a single transaction.
   - Stores never recreate lost data. Only an explicit, documented migration changes an existing schema.
   - `doctor` can reach every store's deepest integrity check, at least behind an explicit deep mode.
3. **Do not move existing stores between tiers.** The current assignment already matches the roles.

## Consequences

- New stores have a rule to follow, and reviewers have a checklist to apply.
- No store changes tier, so no data or file layout moves.
- Bringing the existing stores to the shared conventions is a set of small, independent changes, tracked below. Each one keeps on-disk data compatible.

## Migration plan

Each step is its own issue and PR, in this order. The easy, behavior-preserving fixes come first; the ones that change durability or doctor output follow.

1. **Atomic writes in the optional tier** (#530). `LocalSurveyStore._capture` and `LocalAttentionStore.store_map` move to `BEGIN IMMEDIATE`, with a regression test.
2. **Explicit durability settings in the optional tier** (#531). Every module store applies `journal_mode=DELETE` and `synchronous=FULL` through `apply_pragmas`. These match SQLite's default journal mode and make the synchronous level explicit.
3. **One version record per store** (#532).
   - Project Input moves from `PRAGMA user_version` to the `*_store_meta` convention through a one-way migration that keeps reading old files.
   - Conversation and Decision gain a `schema_migrations` record (migration `0001` = current schema) without changing their tables.
4. **Deep integrity in `doctor`** (#533). A `--deep` mode runs State's `integrity_issues()`, plus `integrity_check` on every core and optional store. The default `doctor` output stays as it is.
5. **Documentation.** `docs/architecture/optional-durable-health.md` and this ADR stay the reference. When E5 reorganizes `docs/`, this file moves to the decision-record location.
