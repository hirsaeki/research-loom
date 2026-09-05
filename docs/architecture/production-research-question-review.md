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
- `project_input_ids`

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

## Same-workspace project input additions

Bootstrap Theme/Expectations remain part of workspace initialization. When a project-input
document is supplied after initialization, operators register the explicit local file through
the public `research-input register` surface. Registration is bounded to regular files under
the workspace-controlled intake root and records immutable content bytes, SHA-256 digest,
media type, typed logical role, source-path/provenance, project/lineage binding, and the exact
current Research Snapshot. Re-registering the same project/role/content digest against the same
Snapshot returns the same project-input identity. Explicit registration after a Snapshot change
creates a distinct immutable registration identity, but Question Review does not require that
re-registration merely to reuse the original input within the same Research Lineage.

Project inputs are Question Review provenance, not Evidence, Attention, or Human authority.
A review may name registered IDs in `review_inputs.project_input_ids`. Unknown IDs, inputs from
a different project or Research Lineage, and missing or tampered stored content fail closed. An
immutable input registered against an older Snapshot remains reusable within the same lineage;
its original registration Snapshot is preserved while the Review binds the current Snapshot.
Registration itself requires the caller to pin `expected_snapshot_id` and
`expected_snapshot_digest`. The final project-input persistence is performed while holding the
same local Research State HEAD writer guard used by Survey/Research Exhibit capture, so a HEAD
change that occurs while the source file is being read is rejected rather than persisted against
a stale Snapshot.

Registered content is retrieved from the immutable content-addressed store, never by reopening
the original `source_path`. `research-input show --format text` exposes verified UTF-8 content for
textual media types, while `--format base64` provides a bounded binary-safe representation. Every
content read rechecks stored byte length and SHA-256 digest and fails closed on a missing or
corrupt blob. Metadata-only `show` remains the default and advertises the supported content
formats for the registered media type.

`research-input list` uses stable `(registered_at, input_id)` ordering and bounded keyset
pagination. `--limit` accepts 1..100 and `--cursor` consumes the opaque `next_cursor` from the
previous response; `truncated` explicitly reports whether another page exists. This preserves
historical registrations across Snapshot changes while making every item reachable.

`KEEP` remains a no-op, while material Question Deltas continue through the existing
Confirmation and Human Decision path.

This is distinct from raw Attention intake and from external Desktop Research materials:
project inputs describe the project's supplied framing/context, while external materials are
retrieved research sources and may later support Evidence through their existing adoption path.
