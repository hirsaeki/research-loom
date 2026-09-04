# Production iterative Research Question review

The Initial Research Question baseline remains immutable at revision `0`. Later research cycles use a bounded semantic ingress:

```text
research_question.review
  -> KEEP
  -> REFINE | SPLIT | MERGE | CLOSE
```

`KEEP` is a no-change review result. It records no authoritative state mutation and requires no Human Decision.

Material Question Deltas reuse the existing authoritative path:

```text
research_question.review
  -> candidate-only StateDeltaProposal bound to the exact current Snapshot
  -> state.apply_candidate
  -> Confirmation
  -> existing Human Decision Gate
  -> immutable object revision(s) + new Research Snapshot
```

No Question Delta may be auto-adopted from Work, chat, a worker, Publication feedback, or any Capability result.

## Revision and lineage semantics

An initial adopted RQ starts at revision `0`; its RQ identity is the lineage identity until a material review persists explicit lineage metadata. The read projection exposes that identity as `question_lineage_id`.

- `REFINE` keeps the RQ identity, advances `revision` by exactly one, and records the exact source revision in `derived_from_question_revisions`.
- `CLOSE` keeps the RQ identity, advances its revision, and sets `adoption_state=closed`.
- `SPLIT` closes the source RQ in a new immutable revision and creates two or more new RQ identities. Each child records the source revision and inherits the source `question_lineage_id`.
- `MERGE` closes all source RQs in new immutable revisions and creates one new RQ identity with every source revision recorded. The merged RQ starts a new lineage identity while preserving its derivation links.

Historical revisions are never rewritten or deleted. Historical Snapshots and Runs therefore remain addressable against the exact RQ revision they originally referenced.

## Review inputs

A review may bind the cycle inputs that motivated the review without treating them as Human authority:

- `uncovered_attention_ids`
- `evidence_gap_ids`
- `publication_feedback_ids`

These references are provenance for Question Review. They do not become Evidence and cannot authorize a material Question Delta.

## Downstream review impact

For material changes, the review boundary identifies current Research State objects that directly reference the affected RQ identity through question bindings. The new RQ revision(s) carry these as `downstream_review_required_refs`.

This is an explicit review marker, not an automatic rewrite of Findings, Methods, Arguments, Publication material, or Evidence. Existing downstream objects remain immutable and retain their historical question binding until an independent authoritative change is approved.

## Stale-head behavior

Question Delta candidates are pinned to the exact current Snapshot ID and digest. Existing stale-candidate protection is unchanged:

```text
S0 -> review -> Question Delta candidate bound to S0
S0 -> unrelated authoritative transition -> S1
candidate apply against S1 -> fail closed
```

No rebase, carry-forward, or semantic merge is performed automatically.

## Read surfaces

Current RQ projections expose, when present:

- active `revision`
- `question_lineage_id`
- `derived_from_question_revisions`
- `question_delta`
- `review_inputs`
- `downstream_review_required_refs`

The Initial baseline remains visible as revision `0` in historical state, while the active Snapshot selects the current revision.

## Scope boundaries

This lifecycle does not change Evidence adoption, Publication Eligibility, Publication approval, or Capability execution boundaries. It only closes the gap between the Initial Question Baseline and later Question Review cycles.
