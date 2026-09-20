# Exact managed-payload recovery

Issue #250 covers damaged bytes whose persisted identity is still known. It does
not reconstruct missing SQLite rows, citations, approvals, acquisition times or
research meaning. Keep the exact historical digest, length, role, project,
acquisition metadata and Snapshot pins; do not weaken them to make repair pass.

## Public operations

External Material uses the existing `desktop_research.material.recover` action:

```json
{
  "action_type": "desktop_research.material.recover",
  "payload": {
    "run_id": "RUN-...",
    "capture_id": "CAP-...",
    "kind": "rendition",
    "source_file": "operator-recovery/source.txt"
  }
}
```

Submit it with `research-loom action submit --workspace WORKSPACE --json INPUT`.
`kind` can be `original` or `rendition`. The source must be a controlled regular
file inside the Workspace, outside `.research-loom`; traversal, links/reparse
points, outside sources and oversized input are rejected by controlled intake.
Canonical capture-to-artifact metadata is checked before byte repair.

Inspect the relevant Run with `run show`, and the restored material with
`external materials show`. A successful repair can unblock existing Finding
recovery and Package creation; it does not automatically adopt a Finding.

Project Input uses its registered ID, never caller-supplied replacement metadata:

```sh
research-loom research-input show --workspace WORKSPACE --input-id PIN-... --json
research-loom research-input recover --workspace WORKSPACE --input-id PIN-... --source-file operator-recovery/input.md --json
research-loom research-input show --workspace WORKSPACE --input-id PIN-... --format text --json
```

Metadata show reports `payload_health` and the next operation without changing
records. Repair does not re-register the input against the current Snapshot.
The original input can be consumed by Package and Question Review afterward.

## Classification

| Physical/metadata condition | Behavior |
|---|---|
| Missing bytes | Exact replacement returns `RESTORED`. |
| Readable digest/size mismatch | Preserve the bad bytes, install identical historical content, return `REPAIRED`. |
| Already verified | Validate the supplied source and return `ALREADY_VERIFIED`; do not invent a new recovery time. |
| Permission or I/O failure | Restore access or retry; unreadable bytes are not treated as proven corruption. |
| Missing/invalid metadata, wrong project/capture/role binding or unsafe locator | Refuse payload repair; use an exact metadata/Parent backup or a separately registered new material/input. |

When operator bytes are unavailable, the existing `material.reacquire` action
also accepts a corrupt readable payload. An exact retrieval/regeneration uses the
same byte-repair path. Different bytes remain `NEW_MATERIAL_VERSION`; the old
corrupt/missing object is not silently replaced. A rendition still requires its
verified historical original. No new acquisition provider is introduced here.

## Persistence and concurrency

Both content-addressed stores use small file-I/O primitives in
`plugins/local_payload_repair.py`. Callers retain metadata, authority and intake
validation. There is no new metadata registry or general Recovery Engine.

A bounded OS lock is keyed by the physical payload address within the store, not
Artifact ID, Run ID or Project Input ID. Separate references/roles to that same
blob therefore serialize repairs. Ordinary writers use no-clobber publication;
readers can observe either the old invalid bytes (and reject them) or the exact
new bytes, never a partially written replacement.

The actual staged bytes are verified. For a corrupt present payload, a hard link
under the store's `quarantine/` preserves the old inode **before** atomic
replacement. The old payload remains in place if installation fails. Repeated
failed repairs may retain more than one quarantine reference; none is deleted
automatically. A filesystem that cannot create a hard link cannot perform this
repair safely and receives an I/O failure without overwriting the bad payload.

After installation, verify again and save a separate `repairs/*.json` receipt
with expected content binding, prior health, quarantine reference and
`recovered_at`. External Material also retains the existing Run diagnostic. A
receipt/diagnostic write failure is reported as a warning when bytes are already
verified; it does not fabricate a successful diagnostic write or undo the repair.

A crash before installation keeps old bytes and the quarantine copy. A crash
after installation can leave an exact blob without its final receipt: re-open,
verify and reuse that effect. Temporary intake/staging leftovers are not canonical
objects. If staging cleanup fails, a warning identifies the generated temporary
filename and error class without exposing source content or an absolute path.
After restoring access, stop all Workspace users and inspect that exact file in
the execution store staging directory before removing it; do not sweep staging
while an intake/repair may still be active. No background cleanup is scheduled.
Do not delete valid shared blobs to roll back a diagnostic or cleanup
failure. Recovery does not change Research State or previously recorded facts.

The supported backup procedure remains a quiesced whole Parent copy, as described
in `parent-backup-restore.md`; optional child loss still has the locality contract
in `optional-durable-health.md`. This is not protection against an OS attacker
rewriting every trusted file or a guarantee for every physical power-loss/disk
failure sequence. Tests cover controlled faults and abrupt process exits; the
Windows acceptance job exercises the same public recovery cases on Windows.
