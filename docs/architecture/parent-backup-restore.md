# Quiesced Parent backup and restore

The workspace Parent Durable Store Root is `<workspace>/.research-loom/`.
A whole-workspace backup must preserve this **complete tree as one stopped
backup set**, not combine individually valid databases from different times.
A portable child copied for read-only intake is not a whole-workspace restore.

## Before copying

1. Stop every process using the workspace, including CLI invocations, open
   Facade/application handles, workers, and other hosts writing a synced copy.
   Close all SQLite connections cleanly. The workspace/Profile lock is not a
   multi-host backup lock; a lock file's mere existence proves nothing.
2. Keep the workspace stopped through verification and copying. Do not let a
   file-sync client merge versions during the operation. A provider's history
   of independent files is not automatically one consistent backup set.
3. Run `research-loom doctor --workspace <workspace> --json`. Record the exact
   output and repository version. Resolve canonical State/Decision integrity
   failures before calling a backup healthy. A snapshot can still be retained
   for forensic recovery, but label its known failures rather than calling it
   verified. This is not a deep hash of every material blob or optional store.
4. After that command exits, copy the entire Parent into a new, uniquely named
   backup-set directory outside the source workspace. Include all initialized
   children, bindings, Profile history, payloads, and any SQLite `-wal`, `-shm`,
   or `-journal` files that remain. Never delete sidecars as a cleanup shortcut:
   a committed transaction may not yet be present in the main DB file. A clean
   close normally settles them, but their absence alone does not prove quiescence.

For example, **only after stopping all users**, in PowerShell:

```powershell
$workspace = 'D:\research\current'
$backupSet = 'E:\backups\research-20260920-unique'
if (Test-Path -LiteralPath $backupSet) { throw 'Choose a new backup-set directory' }
New-Item -ItemType Directory -Path $backupSet -ErrorAction Stop | Out-Null
Copy-Item -LiteralPath (Join-Path $workspace '.research-loom') `
    -Destination $backupSet -Recurse -ErrorAction Stop
```

A copy failure leaves an **incomplete, unusable backup**, not a set to fill in
from a later database generation. Remove or quarantine only the failed copy;
leave the source untouched, then repeat the full stopped copy into a new set.
Record backup-set identity, source workspace/project, repository version, time,
copy completion, and verification results alongside the copied Parent. A file
manifest of paths/sizes/SHA-256 hashes is useful for transfer verification but
does not make a live copy transactionally consistent.

## Verify the copy, then resume the source

Run doctor against the backup-set directory (the directory containing the
copied `.research-loom`, not the Parent itself). Verify selected required
material through its public verified-read/health operations. Retain the output.
Keep a verified backup immutable/offline as appropriate; do not use it as a new
active writable research workspace. Resume the source only after the copy is
complete. This procedure adds no automatic backup daemon or new backup API.

## Restore into an isolated destination

1. Stop all users of the affected workspace. Retain the original broken Parent
   untouched as a separate quarantine; never copy backup files over live DBs.
2. Choose one complete backup set. Copy its whole Parent into a **new empty
   workspace directory**. Copy databases and their sidecars from that same set;
   do not pair an older main DB with a newer WAL, drop a WAL, or mix a newer
   Decision database with an older State database.
3. If restore is interrupted, do not open the partially copied workspace as
   healthy. Keep the backup intact; discard/quarantine the incomplete destination
   and repeat the complete copy into another empty destination.
4. Run doctor on the destination. In particular, `decision_state_receipts`
   checks terminal Human Decision receipts against historical canonical commits,
   Snapshots, and consumed Decisions. It does not require the historical receipt's
   Snapshot to remain today's HEAD. `WORKSPACE-DECISION-STATE-MISMATCH-001` means
   a receipt cannot be proven against this State history; do not auto-replay an
   authority effect to make the databases agree.
5. Use public `status` and relevant domain inspection/verified-read operations.
   Only then designate this destination as the active workspace and resume work.
   Do not run the old and restored copies concurrently as the same active
   workspace. Changes made after the selected backup are not silently recovered.

## Interruption classes

| Observation | Meaning and supported next step |
|---|---|
| State commit exists; Decision is still `RESOLVING` after finalize failure | Ordinary same-response recovery remains supported. This is not proof of mixed restoration. |
| Decision says `RESOLVED`; its canonical commit/receipt or Decision is missing/different | Mixed-generation or damaged canonical history. Restore a consistent complete set; resolution reports `DECISION-STATE-MISMATCH-001` instead of success or an implicit new effect. |
| State has progressed beyond a historical successful receipt, or active Lineage changed | Not itself corruption. Verify the actual historical commit, not equality with current HEAD. |
| Copy/restore is incomplete or a required database is absent | Incomplete destination, not an empty new store. Repeat the whole stopped copy; doctor is not a reconstruction tool. |
| DB-only copy omitted a committed WAL, or sidecars came from another generation | Unsupported copy. SQLite may reject it, or individual quick checks may pass while cross-store history disagrees. Neither a passing quick check nor this targeted receipt check proves every possible WAL mismatch absent. |
| All trusted canonical State/Decision/Exhibit facts are gone | Restore an exact trusted backup or start explicitly new research. Do not infer old approval, Finding meaning, Exhibit analysis, timestamps, or identity from surviving material alone. |

The tests inject one omitted-State-WAL sequence, a State-only rollback, an
operational receipt mismatch, missing canonical Decision payload, an interrupted
restore, and positive whole-set/later-commit/Lineage/ordinary-finalize controls.
They do not claim live-copy safety, all WAL interleavings, power-loss durability,
or a distributed transaction across the separate stores.
