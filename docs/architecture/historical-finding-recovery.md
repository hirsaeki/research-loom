# Historical Desktop Research Finding recovery diagnosis

Issue #145 keeps the exact-run recovery introduced by #142 and adds one bounded compatibility case for historical replay lineage.

For an eligible completed REAL `desktop-research/investigate` Run, `run show` may expose a `finding_recovery` diagnosis. The diagnosis is read-only and contains only the bounded stage/class plus requested/producer Run identity, producer relation, and (when safe) the historical proposal ID/digest. It does not expose arbitrary proposal contents or mutate Research State or historical records.

The exact producer relation remains the primary path. If no exact persisted candidate exists for the requested Run, compatibility recovery may follow one uniquely resolved **direct persisted replay child** only when all of these persisted facts agree:

- child `parent_run_id`, attempt, project, lineage, Snapshot, capability/function, and execution mode;
- child Invocation `trace.parent_run_id`;
- immutable parent and child Action Proposals, both `desktop_research.investigate`;
- child action payload equals the parent action payload plus the explicit `parent_run_id` replay binding.

No relation is inferred from filenames, object order, guessed IDs, statement/RQ similarity, or the operator's desired RQ. Zero or multiple plausible producer candidates, corrupt data, stale state binding, incompatible Handoff/provenance, an unverifiable replay relationship, or an unrecognized pre-#139 candidate shape all fail closed.

Once a producer is uniquely resolved, the implementation delegates to the existing #142 recovery for that exact producer candidate. The historical proposal stays immutable; recovery remains candidate-only and the existing `state.apply_candidate -> Confirmation -> Human Decision` flow remains the only authoritative Finding transition.
