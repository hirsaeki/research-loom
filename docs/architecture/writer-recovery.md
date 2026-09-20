# Writer continuity and interrupted persistence

Composition capture and Writer import keep a single directly addressed continuity
record per composition series. The record retains the exact next canonical document
before installing its version/revision and updating its derived latest pointer.
All three writes run under the same per-series OS lock. Another response cannot
bypass a pending predecessor and create a second revision at the same position.
Research State, Package/Snapshot pins and human selection are not changed by recovery.

Healthy retries do not enumerate history. If an older workspace has no continuity
record, recovery walks its canonical history once and requires one contiguous chain
of exact parent ID/version/digest bindings. Missing or competing predecessors are
not guessed. This exceptional recovery walk has no lifetime history-count limit;
it is not used for ordinary capture or import. A lagging pointer is repaired only
when it is an exact ancestor of the retained latest document.

## Operator recovery

| State | Next action |
| --- | --- |
| Continuity record intact; canonical latest document or head/index absent | Repeat the exact `writer-round-trip import-response` / composition capture. Restore the original document, including its timestamp and digest; then repair the derived pointer. |
| Canonical document written, pointer update failed | Repeat the exact write. A different stale response is rejected after pending persistence is reconciled; it must be based on the recovered latest revision. |
| Legacy record absent, canonical history uniquely verifies | Repeat capture/import. Retain the original latest facts and repair only missing/lagging pointers. |
| Pointer unreadable or conflicting | Preserve it for diagnosis. Restore its exact backup, or explicitly remove only the derived `head.json` / `series-index.json` and retry with verified retained history. No read command silently repairs it. |
| Canonical document, parent, Package pin or continuity record corrupt/unreadable | Preserve existing bytes; fix access or restore a consistent exact backup. Do not replace them with a newly timestamped copy under an old identity. |
| Original facts unavailable or successors ambiguous | Restore a consistent backup or explicitly start a new composition series with a new ID. Old dependent approvals and publications are not transferred to it. |

Composition records are under `writer-compositions/.<composition-id>.capture.json`.
Manuscript records are under `writer-round-trips/.<composition-id>.latest.json`.
Keep these records with the whole quiesced Parent backup, not only the canonical
series subdirectories. They retain the latest original facts, not every historical
version. Restoration of an older missing version still needs that version's exact
backup. Mixed-generation backups and an attacker rewriting every trust source are
not supported recovery guarantees.

Results distinguish new writes, verified reuse and restored components. Recovery
returns a separate `recovered_at` without changing `created_at`, original IDs or
digests. Writer revision IDs also include a nonce, preventing identity reuse if all
local records are lost; this is not proof that lost history was restored. The
response digest addresses its immutable replay slot independently of that nonce.
Latest manuscript inspection reports pending recovery rather than presenting a
stale head as current. Explicit inspection of an existing historical revision is
read-only. Composition selection remains an independent human action.

Writes stage and fsync in the same directory. Immutable versions use no-clobber
installation; mutable continuity/head/index documents use atomic replacement.
Staging initialization, installation and cleanup failures return public write
errors. Resolve the I/O problem and retry; retained canonical facts are not deleted
when a later pointer write fails.
