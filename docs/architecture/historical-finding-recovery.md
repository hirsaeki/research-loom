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

## Canonical-result recovery decision

Issue #148 adds a broader recovery decision without turning historical recovery into a generic proposal browser or prose-to-Finding path. `run show` keeps the #145 compatibility diagnosis above and additionally exposes a bounded `recovery_class`:

- `proposal_rematerializable`: either the existing #142/#145 persisted-candidate path is usable, or the requested Run itself retains one complete, verified canonical Handoff/result extension whose Source/Evidence/Finding closure can be normalized again;
- `replay_required`: the canonical result is incomplete and persisted retrieval history still contains unresolved work eligible for the existing completed-Run replay path;
- `material_recovery_required`: canonical structured output exists but a required persisted capture cannot pass the verified artifact read boundary;
- `not_recoverable`: trusted persisted structured provenance is insufficient or inconsistent.

Canonical-result rematerialization reuses `DesktopResearchNormalizer`; it does not synthesize semantics from Handoff prose, Package text, Exhibit text, Composition content, or current web content. The source Run, Handoff, result extension, execution pins, capture bytes, exact current project/lineage/Snapshot binding, and normalizer validation must all verify. A new candidate-only `StateDeltaProposal` receives a fresh deterministic recovery identity plus explicit recovery provenance. The historical Run/Handoff/result are not rewritten, and Research State remains unchanged until the ordinary `state.apply_candidate -> Confirmation -> Human Decision` authority flow.

The legacy `status`, `failure_class`, and producer fields remain the #145 diagnosis for compatibility. Operators choosing the broader #148 branch use `recovery_class` and `recovery_route`; an old proposal-shape failure can therefore coexist with `recovery_class=proposal_rematerializable` when the canonical historical result itself is sufficient.

## Divergent material continuation

Issue #171 keeps `NEW_MATERIAL_VERSION` outside historical recovery. A successful
`desktop_research.material.reacquire` result whose regenerated rendition differs
from the historical bytes may be continued through
`desktop_research.material.continue_new_version` by supplying only the persisted
reacquisition Run ID.

The continuation verifies the reacquisition result, the persisted divergent
artifact, its historical provenance, and the exact historical original used as
the paired material. It then creates a new normal REAL `desktop-research/investigate` Run, captures a new source pair, replays the persisted retrieval
attempt facts without network retrieval, and submits the candidate research
content through the ordinary external Desktop Research assembler and validator.
Citation containment is therefore checked against the new rendition bytes; a
changed version that no longer contains the cited material fails closed rather
than rematerializing the historical result.

This branch never restores or rewrites the missing historical artifact and never
satisfies historical Finding recovery. Its output remains candidate-only and the
ordinary Confirmation / Human Decision path remains the only Research State
authority. `run show` exposes the new Run's parent reacquisition, historical
Run/capture, material digest/size, exact locator, and historical/reacquired
timestamps without exposing managed storage locations. Repeating a completed
continuation reuses the one existing child result; conflicting prior children
fail closed.
