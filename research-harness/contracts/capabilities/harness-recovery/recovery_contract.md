# Harness Recovery Contract v0.1

Recovery is append-only compensation. A request freezes exact affected Run and
state IDs, a known-good baseline hash, defect and version metadata, a proposed
replay phase, and known downstream consumers. The Harness calculates a bounded
impact assessment and issues a Human Recovery Decision Packet.

Approval records a Human treatment for every affected semantic Decision:
`PRESERVE`, `RECONFIRM`, or `INVALIDATE`. It then writes explicit invalidated
lineage records, a new recovery Research snapshot, and an immutable Replay Plan.
It never copies an old snapshot over `head.json`, deletes a prior Run, or
silently chooses semantic inheritance.

Replay accepts only the approved immutable plan, uses new Run IDs and Context
Packs, and records interruption or uncertainty. Invalidated artifacts are
excluded by the normal Context Builder. Publication dependencies become stale
and remain blocked from valid export until Human review.
