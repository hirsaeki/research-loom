# Optional durable child health and local degradation

`LocalWorkspace.open` validates the core binding, configuration, State,
Conversation, Decision and Execution stores as before. Losing an optional child
must not stop unrelated candidate work. The existing `durable_children` inventory
also includes Publication; its registration is not a new global opening gate.

## Public diagnosis

`research-loom doctor --workspace PATH --json` reports an `optional_child` check
for each supported child. `status` and `resume` include `optional_children`.

- `UNINITIALIZED`: the inventory exists, this child has not been registered, and
  no child exists. An empty list is legitimate; listing does not create a store.
- `OK`: the child is present and the declared check passed.
- `UNAVAILABLE`: a registered child is missing, an initialized directory has no
  metadata DB, its SQLite data/schema cannot be read, or its path is unsafe.
  The report includes a named diagnostic and recovery action. Workspace status
  is `DEGRADED`, not a false `OK`, while unrelated operations remain available.
- `LEGACY_AMBIGUOUS`: the old Parent has no inventory, so absence alone cannot
  prove that a child was never initialized. No missing historical data is
  reconstructed. This compatibility state does not claim recovery coverage.

Doctor performs read-only SQLite `quick_check`, required-table/column and schema
version checks for the seven optional SQLite stores (including the database
inside Project Input). It tolerates supported legacy schemas and absent derived
caches, not absent canonical tables. Status and dependent operations perform
presence/schema checks, not repeated full database or payload scans.

Directory children are checked for safe presence/access, not recursively scanned
for item integrity. `payload_integrity=UNCHECKED` is explicit. Missing or changed
blobs still fail their domain's existing exact content verification. `OK` on a
metadata DB does not mean all its referenced payloads have been checked. SQLite
read-only connections may maintain WAL shared-memory coordination files; no
canonical record, payload, schema or inventory is repaired by diagnosis.

## Initialization and recovery

Each store records initialization in the Parent inventory after its schema/root
is ready **before accepting domain data**, not merely when the Workspace closes.
A short bounded inventory lock serializes additions without imposing a lifetime
limit on stored data. A process exit after capture therefore does not forget
that the child existed. A failure to register accepts no user record; the next
explicit write can finish a schema-ready empty initialization. The existing
close-time inventory discovery remains a compatibility fallback.

Project Input list/show use read-only connections and do not initialize an empty
registry or migrate a legacy schema. An explicit registration operation can
perform the existing supported migration before writing. A known missing or
incompatible registry is never migrated into an empty replacement.

To recover, stop dependent operations, preserve the damaged material and restore
that exact child from a consistent backup, then run doctor and the relevant
public show/content read. See `parent-backup-restore.md` for quiesced Parent
backup rules. A healthy restored child is usable under its original identities;
no artificial metadata/timestamps, authority effects or automatic empty-store
recreation are introduced. Payload repair and item-level list isolation are
separate contracts; this check does not invent lost content.

When Attention is unavailable, resume marks it unavailable and does not pretend
that baseline attention is the selected map. Operations which need effective
Attention still reject it; independent RQ candidate creation remains possible.
