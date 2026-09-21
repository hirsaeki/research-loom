# Package and Writer inventory

`research-package list --workspace WORKSPACE --limit 100 --json` and
`writer-composition list --workspace WORKSPACE --limit 64 --json` accept an
optional `--cursor` copied verbatim from the preceding response's `next_cursor`.
The Facade methods accept the same `limit` and `cursor` keyword arguments.
Continue until `next_cursor` is null. `truncated: true` is not a complete list.
The allowed limits are 1–100 and 1–64 respectively.

Items are ordered by directory name. This is a live keyset traversal, not a
snapshot: later additions after the cursor can appear on a subsequent page;
additions before the cursor require a fresh traversal. Cursors are bound to the
workspace inventory path, project and kind. They are navigation tokens, not
credentials or signed snapshots. After moving a workspace, start a fresh list.

Each request scans directory names (O(n) time), retaining at most `limit + 1`
names. It reads only the selected items' metadata. Package metadata reads are
limited to 16 MiB; Writer metadata and its referenced package metadata are
limited to 4 MiB per file. Writer reuses its bounded latest/selection algorithms
without performing repair writes or reading full historical selection chains.
The package cache holds pin fields, not full package bodies. There is no new
limit on the number of saved packages, compositions, revisions or selections.

`AVAILABLE` with `verification_scope: METADATA_ONLY` means the metadata schema,
identity, digest and relevant metadata pins resolved. It does **not** verify
body or attachment bytes, current Research State eligibility, or release
eligibility. `show`, `export` and other content operations retain full
verification. They can reject a metadata-visible item whose payload is damaged.

An unreadable item is returned as `UNAVAILABLE`, with a directory identity when
safe to display (otherwise a fingerprint), a bounded diagnostic and a next
action. Missing metadata, malformed JSON, digest mismatch, permission/I/O
failures and read-bound excess are distinguished. Exceeding a read bound is not
proof of corruption. Unverified item bodies, source fields and exception text
are not exposed. Valid foreign-project items are omitted; unverified directory
identities have `project_scope: UNVERIFIED`. Thus a page may contain fewer rows
than its limit; `scanned_items` and `next_cursor` still advance past those slots.
Package staging directories (`.rp-*`) are not saved packages.

Listing does not restore files, regenerate an empty store, repair pointers or
change Research State. Preserve unavailable items; fix access or restore exact
retained bytes, then list again. Rebuilt material needs a new identity. For a
whole optional-store failure, use the optional-store diagnosis/backup procedures
rather than treating an empty result as successful recovery. Static symlink and
junction paths are not followed; this is not an OS-adversary race-free sandbox.
