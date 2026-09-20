# Publication request and release recovery

The public `publication release-request` and `publication release` commands retain
request/decision facts before exposing their output files. One small per-request
operation record under `publication/release-operations` moves atomically from
`PENDING` (exact request) to `DECIDED` (exact request and release manifest).
The emitted request JSON and release directory are copies of those facts and the
independently approved preview output. This does not change Research State.
Request copies use the stable operation ID as their filename; the full immutable
request ID (including its nonce) is retained and verified inside the document.
Missing-operation diagnosis therefore does not enumerate unrelated requests.

## Detection and continuation

| Failure | Public result / next action |
| --- | --- |
| Emitted request JSON missing, operation intact | Repeat release-request (or the exact release response). Restore the identical request; do not change issued_at. |
| Manifest, artifact, or whole release directory missing, decided operation intact | Repeat the exact release response. Verify the retained decision against the approved build and restore only missing parts. |
| Output or manifest exists but differs | Integrity error; preserve it. Restore a consistent exact backup, not an automatic overwrite. |
| Operation lost, original complete release manifest intact | Verify against the request and approved build, then retain those exact original facts. A missing output can be restored. |
| Decision facts lost from both operation and release manifest | Recovery-required error. Restore the exact operation or explicitly renew the approval request. Never invent the old decision time. |
| Operation corrupt or inaccessible | Local integrity/I/O diagnosis. Keep the bytes and correct access or restore the exact record. |
| Entire Publication child absent | Parent doctor/status/resume are DEGRADED; only Publication consumers fail. Restore the exact child from a consistent Parent backup. |

Restoration reports `RESTORED`, the restored component names (for a release), and
`recovered_at`. The immutable `issued_at`, `decided_at`, request/decision/release
IDs and digests do not change. Recovery is a write operation, not hidden in
preview inspection or doctor. A staged file is not a committed operation.

Request output failure resumes from `PENDING`. Failure after the decision record
but before either output file resumes from `DECIDED`; it does not normalize the
minimal approval again. Operation and output writes share a per-request OS lock.
Output installation is no-clobber; permission or replacement failures retain the
last committed record for an exact retry. Symlink/escape targets are rejected.

## When exact facts no longer exist

Use an explicit new approval request rather than recycling an old ID:

```sh
./research-loom publication release-request --workspace PATH \
  --build-id PUB-ID --actor-id HUMAN-ID --renewal-of PUBRELREQ-OLD --json
```

The result contains a new request ID/digest that the human must approve. Retrying
that same renewal reuses its request; old releases and their remaining files are
not overwritten. `renewal_of` records the operator's intended predecessor, not a
claim that missing predecessor facts were verified or recovered.

New request IDs also contain a nonce. Even complete request-record loss followed
by an explicit new request cannot generate the old ID with a new timestamp or
digest (including under a fixed clock). An old response cannot approve it.
Supported legacy requests/releases are readable. A legacy request without its
original decision facts must use exact backup or explicit renewal before release;
absence is not proof that no prior release occurred.

Back up/restore the quiesced whole Parent as described in
`parent-backup-restore.md`. Do not mix an old PENDING operation with files from a
newer generation. The copies are useful for partial-loss recovery, not a claim
of protection against an attacker rewriting every trust source or arbitrary
mixed-generation backups. A changed renderer needs a new build and approval;
these recovery paths never mutate an old released output.
