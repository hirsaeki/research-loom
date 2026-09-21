# Interrupted Workspace initialization

Never delete a Workspace or its `.research-loom` tree just because `init`
failed. Initialization now preserves failed attempts, including ordinary
exceptions, instead of recursively removing paths that may already contain a
committed State. The input Config/Profile files outside the Workspace are never
owned by the initializer.

Run `research-loom doctor --workspace <PATH> --json`. When `.initializing`
remains, the overall status is still `ERROR / WORKSPACE-PARTIAL-001`; the
`initialization` object supplies a classification and the next operation.
Normal `open` also refers the operator to this diagnosis. No research records,
markers, Config/Profile inputs or directories are changed by diagnosis. SQLite
may create/refresh SHM coordination or empty WAL sidecars during read-only
checks; this is not a checkpoint, repair, or consistent hot-backup protocol.

## Classifications

- `PRECOMMIT_STAGING`: a current initialization intent matches this root and the
  exact staged Config/Profile bytes, remains before the State-writing phase,
  and the directory contains only the small known initialization file set.
  This does **not** establish that the initializer has stopped. After stopping
  all processes, an operator may retain/quarantine the entire directory by an
  explicit filesystem move to a new, non-existing path. Do not delete it.
  Run normal `init` at a NEW absent/empty location with the original explicit
  Config/Profile inputs. The retained directory is not merged back into it.
- `COMMITTED_WORKSPACE`: the binding and all required canonical stores/pins
  pass the existing full doctor checks, independent of the marker. Optional
  child degradation remains visible and does not invalidate canonical State.
  Do not quarantine or reinitialize this as disposable staging. The exact,
  exclusive `init-finish` operation below can remove only the stale marker.
- `RESEARCH_RECORDS_PRESENT`: a State record is present, but the Workspace does
  not fully verify (for example, a crash before the binding write). Keep the
  complete directory, including SQLite WAL. Restore an exact complete backup
  or initialize elsewhere. Never combine guessed files or recreate the same
  historical identity. This command does not attempt to reconstruct binding.
- `INDETERMINATE`: legacy/malformed intent, interrupted State setup, foreign
  target, unexpected/user files, corruption, access/I/O problems, or other
  insufficient evidence. Preserve the whole directory and resolve the specific
  integrity failures. A fresh Workspace elsewhere remains available; no cleanup
  or in-place reinitialization is authorized by this classification.

`cleanup_allowed` is always false. Marker age, PID guesses, missing files or an
unrecognized directory are not proof of disposable staging. An inspection is
not a live-process/orphan detector. Stop all producers before a manual move or
whole-Parent backup. Only `PRECOMMIT_STAGING` offers the quarantine runbook.

## Finalize an already committed Workspace

Copy `initialization.binding_digest` from a fresh doctor result and review
`integrity_without_marker` before running:

```sh
research-loom init-finish --workspace <PATH> --expected-binding-digest <DIGEST> --json
research-loom doctor --workspace <PATH> --json
research-loom resume --workspace <PATH> --json
```

`init-finish` obtains the same exclusive OS lock held by initialization and
Profile updates, repeats full integrity/pin checks, and requires the exact
binding digest. A live initializer or normal handle gives bounded BUSY, not a
stolen lock. The only removal is `.initializing`, after verification. No database
or user input is removed, rewritten, or reconstructed. Missing/corrupt stores
remain errors even when the marker is absent. A wrong binding digest is rejected.

An I/O failure removing the marker leaves it retryable. If the process exits
after marker removal, the Workspace is already valid; repeating the same exact
command returns `VERIFIED_REUSE`. Existing valid directories still cannot be
reinitialized using ordinary `init`. Finish does not clear unrelated optional
child diagnoses and does not imply that missing research material was restored.

## Verification scope

Tests terminate child processes at intent, Config, Profile, State-start,
State-store, binding and marker-removal boundaries. They cover read-only
classification, exact finalization, live-process exclusion, wrong-target and
unexpected-file rejection, failed finalization, ordinary reopen failure after
commit, and stopped whole-Parent backup/restore. Removing the marker from an
incomplete/corrupt fixture still fails the canonical checks (ablation).

These are process-exit fault injections, not a claim that every filesystem,
power-loss, disk-cache or network-share failure has been simulated. The existing
stopped complete-Parent backup requirements still apply.
