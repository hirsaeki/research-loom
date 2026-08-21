# Harness Recovery Runbook

Recovery is append-only compensation. Prior Runs, snapshots, Decisions,
submissions, and artifacts remain in place.

## Interrupted transition lock

If a process stops while a Discovery or Publication transition is running,
inspect the lock before retrying:

```powershell
uv run rh --root . locks status
```

The lock timestamp is diagnostic only. Do not reclaim by age. Confirm the
owner process is no longer active, then use an explicit Human release with a
reason and, when available, the observed owner token:

```powershell
uv run rh --root . locks release discovery-transition --by <human> --reason "confirmed orphaned process" --owner-token <token>
```

The Harness records the release immutably and removes the lock only if its
owner token is unchanged. Invalid metadata must be preserved for manual
investigation; a lock held by the current process cannot be released here.

## Defect found before a pending Run executes

1. Inspect `conversation status` and the pending Run manifest.
2. Confirm `ABORT_PENDING_RUN` or use the explicit CLI:

   ```powershell
   uv run rh --root . run abort <run-id> --reason "<operational reason>" --by <human>
   ```

3. Verify the original Run has `abort.json`, the Context Pack is unchanged, and
   a replacement (if requested) has a new Run ID.

## Defect found during or after Work

Late results for an aborted or superseded Run are rejected. Preserve the
exchange directory and result for audit. If the defect changes research
meaning, scope, method, Evidence treatment, or protocol, stop and open a
Recovery Request; do not use operational abort as a semantic repair.

## Reduced Research or downstream Publication defect

Prepare an exact request JSON containing the current head binding, affected Run
and state IDs, and a hash-proven known-good baseline:

```powershell
uv run rh --root . recovery request --request .rh/recovery/request.json
uv run rh --root . recovery show <recovery-id>
```

Review the bounded impact assessment. For every affected Decision, the Human
must choose `PRESERVE`, `RECONFIRM`, or `INVALIDATE`:

```powershell
uv run rh --root . recovery approve <recovery-id> --by <human> --treatment <decision-id>=RECONFIRM
```

Approval writes invalidated lineage, a new recovery Research snapshot, and an
immutable Replay Plan. It does not refresh prose, restore Publication
Eligibility, or authorize unlisted replay work.

## Replay and interruption

```powershell
uv run rh --root . recovery replay <recovery-id>
```

Replay accepts only the approved immutable plan and creates new Run/Context
Pack IDs. If the process stops, inspect `replay_interrupted-*.json`, retain the
old and new lineage, and resume only after checking the current recovery head
and plan hashes.

Invalidated artifacts are denied by normal Context Pack construction. Affected
Publication becomes `STALE`/review-required and cannot be exported as valid.
No operator command may copy an old snapshot over `head.json`; direct head
repair is prohibited. A technical artifact repair is an explicit exception and
must preserve immutable evidence and trace.
