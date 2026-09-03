# PR19 Research Lineage / Fork / Recovery convergence

PR19 adds logical Research State ancestry without introducing Git branch semantics or runtime persistence. It extends the canonical contract surface after PR18 while preserving PR3–18 authority boundaries.

A lineage head is a pointer to an immutable Research Snapshot. Fork/Recovery creates a child lineage from an exact historical baseline and leaves the parent head unchanged. Semantic inheritance is explicit through `PRESERVE`, `RECONFIRM`, and `INVALIDATE`; historical records are never deleted.

Corrective recovery is modeled as a specialized fork. Its Replay Plan is immutable, uses new Run IDs, rebuilds Context Packs from the target lineage, and forbids copying old Capability Handoffs as new results. Impact Assessment intentionally allows `unknown` so the Harness never assumes LLM-computed downstream coverage is complete.

Core Research Object identity remains unchanged. Parent→derived object mapping is carried by the Fork Plan where needed, preventing revision collisions without adding `lineage_id` to every Core object.

Fork creation and active-lineage selection are separate state-changing operations. Work Conversation can produce proposal-only routing and confirmation, but PR10 confirmation does not replace a Core Human Decision. Lineage Comparison is read-only; automatic merge/adoption is out of scope.

PR18 downstream artifacts are immutable historical products. A companion Research Package lineage binding pins the exact package digest, source Lineage digest, and source Snapshot digest so packages can be classified as current, stale, non-current, or rebuild-required after an active-lineage switch.

PR17 remains the only VIRTUAL→REAL cutover boundary. Fork semantics permit only REAL→REAL or VIRTUAL→VIRTUAL lineage ancestry and cannot promote synthetic research content into empirical state.

Production-local Run replay is deliberately narrower than Research State recovery. A completed external Desktop Research Run with unresolved retrieval work may be replayed as a new child Run using the existing execution `parent_run_id` contract. The parent Run and its persisted provenance remain immutable; only unresolved attempts are carried forward, while the action is re-materialized against current authoritative Research State. If that current binding cannot be satisfied, the operation fails closed. Research lineage fork/recovery remains the mechanism for changing Research State ancestry; Run replay does not adopt candidate results or switch lineages.
