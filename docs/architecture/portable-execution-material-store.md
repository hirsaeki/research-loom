# Portable execution/material child Durable Store Root

Issue #160 defines the existing workspace execution subtree as one self-contained child durability unit. It does not add a new storage backend or cross-workspace import semantics.

The current child root is `<workspace>/.research-loom/execution/`. Its durable contents include `execution.db`, content-addressed payload directories such as `blobs/sha256/` and `large-originals/sha256/` when present, plus the existing execution-adjacent durable databases/files already located in that subtree. `staging/` and lock files are transient operational state, not required durable payloads.

Persisted artifact/resource locators are backend-relative (`artifact://sha256/...`, `resource://sha256/...`, or `external-original://sha256/...`). Resolution is always against the supplied child root. Original acquisition or intake paths may remain in provenance, but they are not backing-content identity and are not consulted to resolve committed payloads.

## Supported offline move / backup / restore

Only a quiesced procedure is supported:

1. close the workspace / execution store so no writes are in flight;
2. copy the complete `.research-loom/execution/` child root as one unit;
3. `staging/` may be omitted from the copy;
4. move or restore the copied child root at any absolute host path;
5. open the child root with `open_read_only_execution_store(root)` when it is being consumed as a source, or through the normal workspace composition when restored in a workspace;
6. verify selected material with existing verified-read / material-health operations before treating the material as healthy.

This contract intentionally does **not** claim hot-copy safety. The default SQLite configuration uses a close/quiesce boundary; callers must not infer that copying `execution.db` while writers are active is safe. Any SQLite journal/WAL side files that exist before a clean close are part of the live database state and are not replaced by a DB-only copy procedure.

## Integrity semantics

`execution.db` alone is not the durable unit. Metadata may reopen while required payload bytes are missing; such material is diagnosed by the existing material-health vocabulary (for example `content_missing`, digest/size mismatch, or unreadable content) and must not be called healthy.

Conversely, copying the complete child root preserves historical Run/capture identity, persisted storage locators, digests, sizes, and provenance without rewriting them merely because the root moved. Read-only opening does not create `staging/`, run migrations, capture material, or mutate Research State.

## Parent relation and authority boundary

This child root remains under the workspace Parent Durable Store Root addressed by #193. Independent portability exists only so the child can later be opened as a bounded read-only material source by #165; it is not a second workspace durability tree.

Opening, moving, restoring, or verifying the child does not import material into another workspace and does not adopt Evidence/Findings or mutate Snapshot/Lineage authority. #165 owns cross-workspace intake semantics.
