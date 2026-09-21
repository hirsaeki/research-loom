# Workspace and Profile locks

Normal `LocalWorkspace.open` / Facade handles retain a **shared** OS lock until
closed. Independent normal opens can coexist. Profile advancement and interrupted
Profile recovery require an **exclusive** lock for the complete validation,
rebind or rollback operation. Individual writes still use their existing SQLite
transactions, expected-head checks and target-specific locks; a shared Workspace
lease is not permission to bypass those checks.

Acquisition retries only OS lock contention, for at most five seconds. A
`WORKSPACE-LOCK-BUSY-001` result means another live operation needs to finish or
its Workspace handles need to close. Retry the original operation afterward.
Close all handles in the calling thread before advancing: a shared-to-exclusive
upgrade is rejected immediately, rather than allowing a stale open application
to survive a Profile change. Internal exclusive nesting remains supported.

`WORKSPACE-LOCK-IO-001` means access, unsupported locking or filesystem I/O failed;
resolve that cause before retrying. POSIX nonblocking acquisition also treats
`EACCES` as possible contention for platforms emulating `flock` with `fcntl`;
file-open access denial is still immediate I/O failure. A persistent BUSY on
such a platform can require a permission/filesystem check as well as closing
active handles. Windows uses shared/exclusive `LockFileEx`
locks and distinguishes lock violation from access denied. Lock files are not
ownership records. Never delete them, infer ownership from timestamps, or break
a live lock. Normal close and process termination release the OS resource.

A pending Profile recovery is performed exclusively **before** acquiring the
normal shared lifetime. The marker is checked again after acquisition. A racing
interrupted operation can therefore return BUSY instead of repairing under a
shared lock; retry a fresh open after active handles close. Missing optional
children still use the existing DEGRADED diagnosis, without recreating empty
stores or converting an unrelated child fault into a canonical failure.

These are local host/filesystem locks, not distributed leases or a live-backup
protocol. The supported Parent Durable Store backup remains a quiesced copy:
finish operations and close **all** application processes/handles before copying
the whole Parent, including SQLite. Check the restored copy before use. A shared
inspection handle or a surviving lock file does not prove the store is quiescent.
