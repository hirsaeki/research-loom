# Research State runtime / State Reducer convergence (PR20)

## Decision

PR3-19 established the canonical semantic floor, Profiles/Project Config,
Capability and Conversation boundaries, Research Methods, VIRTUAL/REAL
separation, Writer/Publication preview packages and Research Lineage. PR20 is
the transition from contract-only work into runtime/persistence work.

The Harness is the single authoritative Research State writer. Runtime code
consumes canonical objects and pinned configuration; it does not reinterpret or
replace the earlier contracts.

## Atomic transition sequence

1. Receive a typed `StateTransitionRequest` bound to an exact lineage HEAD,
   Project Config digest and Effective Profile Set digest.
2. Validate request/Core schemas and digests.
3. Reject a stale expected HEAD; never auto-rebase.
4. Validate actor authorization and all required Human Decisions.
5. Purely reduce `StateView + request` to a proposed next state.
6. Validate Core references/invariants, Profile strengthening, Project guards,
   adoption boundaries, lineage rules and the VIRTUAL/REAL firewall.
7. Construct an immutable Snapshot and storage-neutral `CommitBundle`.
8. Ask the persistence port to atomically persist immutable revisions, Decision
   records, Snapshot, lineage/active pointer changes, adoption references,
   AuditEvents and the receipt while rechecking expected HEAD.
9. Return the persisted receipt, or return a rejection with no semantic write.

This separates concurrency/transactions from semantic reduction. SQLite is a
later adapter choice.

## State representation

The reducer receives `StateView`, not SQL rows. Effective state is the set of
exact Core object revisions named by the current Research Snapshot. Historical
revisions remain available to validators and recovery/fork logic but do not
become effective merely because they exist in storage.

Snapshot membership is deterministic and sorted. Member digests bind exact
object content. Snapshot content digest excludes no semantic field and is
computed only from caller-supplied deterministic inputs.

## Authority boundary

A Capability Handoff, Writer Feedback package, Conversation proposal or
`StateDeltaProposal` is candidate material. None can call the reducer as an
implicit patch or write directly to persistence.

Authoritative transitions use closed state-semantic actions plus resolving Core
Decision objects. PR10 Confirmation and Research authority remain separate.

## Extensibility proof

The runtime tests include `fixture.future-research-capability/evaluate`, which is
not Survey/Delphi/Case/Desktop Research. Its PR9 Handoff and separate synthetic
extension are accepted only when a matching external normalizer validates the
extension and projects it to an ordinary `CREATE_OBJECT` claim candidate.

The same fixture is rejected when no normalizer supports it. No capability ID is
stored in the Core claim, Decision or Snapshot, demonstrating that adding a new
capability does not require reducer code when existing Research State semantics
are sufficient.

## Non-goals

PR20 does not add SQLite schema/migrations, ORM selection, artifact byte stores,
production run executors, plugin loading, Work UI, Writer/Publication runtime,
DOCX/PDF rendering, export/publish, OneDrive integration, archive/new-workspace
flows or legacy deletion.
