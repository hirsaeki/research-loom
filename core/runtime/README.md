# Canonical Research State runtime

This directory is the first production runtime boundary built on the PR3-19
canonical contracts. It does **not** redefine those contracts and it is not a
persistence adapter.

## Write boundary

Authoritative Research State can change only through `StateTransitionService`:

```text
Conversation / Capability / Writer feedback
        |
        v
candidate StateDeltaProposal
        |
        v
Human Decision + typed StateTransitionRequest
        |
        v
StateTransitionService
  A-N validation
        |
        v
pure reduce_state(current_state, request)
        |
        v
storage-neutral CommitBundle
        |
        v
ResearchStateRepository.commit(... expected HEAD ...)
```

Capabilities, LLMs, Writer, Publication and normalizers never receive a
repository write primitive. `CREATE_SNAPSHOT` is intentionally an internal
reducer operation, not a public transition kind.

## Closed state-semantic transition vocabulary

The public runtime accepts only `TransitionKind` values. The vocabulary names
Research State semantics (`CREATE_OBJECT`, `REVISE_OBJECT`, `ADOPT_OBJECT`,
`VERIFY_EVIDENCE`, `APPLY_LINEAGE_PLAN`, ...), never capability identities.
There is therefore no `APPLY_SURVEY_RESULT`, `APPLY_DELPHI_RESULT` or future
`APPLY_POC_RESULT` branch.

A genuinely new authoritative Research State semantic requires a canonical
contract revision. A new capability that produces existing Core semantics is
handled by its validator/normalizer without changing the reducer.

## Runtime models

`transition_models.py` contains storage-neutral immutable dataclasses for:

- `StateTransitionRequest` with exact project/lineage/head/config/profile pins,
  caller-supplied IDs/timestamp, idempotency key and canonical request digest;
- candidate-only `StateDeltaProposal`;
- `StateView` / `LineageView` as reducer input rather than DB rows;
- `ReductionResult`, `CommitBundle`, `CommitReceipt` and
  `StateTransitionRejected`.

The reducer never gets time, random-ID or filesystem services. Snapshot IDs,
commit IDs, audit IDs and timestamps are request inputs so fixture replay is
reproducible.

## Validation order

Validation uses stable stages corresponding to the PR20 boundary:

A. runtime/Core schema
B. request digest and Project Config/Profile pins
C. expected lineage HEAD
D. actor/runtime authorization
E. Human Decision kind/choice/subject/replay checks
F. Core reference integrity
G. Core non-overridable invariants
H. resolved Profile strengthening
I. Project Config guards (`must_not_claim` where mechanically decidable)
J. candidate/adoption boundaries
K. lineage/fork/recovery invariants
L. VIRTUAL/REAL epistemic firewall
M. proposed next-state/Snapshot integrity
N. CommitBundle integrity

Errors are collected and returned as stable `ValidationIssue` records. A
rejected transition performs no repository write. Rejected-attempt audit
storage is deliberately not coupled to the Research State transaction in this
PR; a later audit-attempt sink can record attempts without making partial
semantic writes possible.

`CanonicalResearchObjectSchemaValidator` validates proposed Core objects,
Snapshots and AuditEvents against the PR3 research-object JSON Schema supplied
by the composition root.

## Human authority

Existing Core Decision semantics are reused:

- `research_adoption / approve|reject`
- `research_revision / revise`
- `evidence_qualification / verify`
- `evidence_reclassification / reclassify`

Lineage operations add only runtime state semantics:

- `lineage_plan / apply`
- `lineage_reconfirmation / reconfirm`
- `active_lineage_selection / switch`

A Decision reference must resolve to a human Decision with matching project,
subject, kind and choice. Once used to authorize a committed transition it may
not be replayed. A combined transition must satisfy every independent authority
requirement.

PR10 Confirmation remains outside this authority mechanism: a confirmed
conversation action still needs the Human Decision required by the Research
State semantic.

## Revisions, Snapshots and atomicity

Core objects are never changed in place. Existing identities advance by exactly
one revision; new identities start at revision 0. Old revisions remain
addressable.

A successful semantic transition deterministically constructs a new immutable
Research Snapshot with exact `(kind, id, revision, digest)` membership and moves
the lineage HEAD in the same `CommitBundle`. The repository port is required to
persist the whole bundle or none of it and to compare the expected HEAD again at
commit time. The service never auto-rebases a stale request.

The same idempotency key and request digest returns the prior receipt. Reusing a
key with different content fails closed.

## Fork / recovery

`APPLY_LINEAGE_PLAN` consumes an already approved lineage plan projection. Each
baseline member must receive an explicit `PRESERVE`, `RECONFIRM` or `INVALIDATE`
treatment. `RECONFIRM` requires a derived immutable Core revision and an
explicit Human Decision bound to both the action and the derived object.

Creating a child fork/recovery Snapshot and lineage is one atomic bundle. The
parent lineage HEAD and active-lineage pointer do not move implicitly. Corrective
recovery also registers its replay-plan reference; actual capability replay is
a separate run lifecycle.

## Capability normalization

`CapabilityNormalizationBoundary` accepts the PR9 candidate-only Handoff outer
envelope plus an optional capability-specific extension. A concrete
`CapabilityResultNormalizer` validates that extension and returns only a generic
`StateDeltaProposal`.

Unknown extensions fail closed. The registry/loader/plugin-discovery mechanism
is intentionally not implemented here. Dependency direction is one way:

```text
Capability/plugin -> Normalizer -> State runtime -> Persistence port
```

The runtime has no imports from `plugins/`, Survey, Delphi, Case Study, Desktop
Research, Writer, Publication, SQLite or external service SDKs.

## Persistence

`ResearchStateRepository` is the production persistence port. PR20 intentionally
contains no SQL, ORM model or SQLite schema. `testing.py` contains an explicitly
test-only in-memory implementation used to prove atomic and storage-neutral
semantics. A later SQLite adapter must implement the same port and transaction
contract rather than changing the reducer.
