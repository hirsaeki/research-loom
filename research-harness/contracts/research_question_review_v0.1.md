# Research Question Review lifecycle contract v0.1

This contract extends `research_harness_v0.4.md` with the revision-aware lifecycle for an adopted Research Question.

## Initial baseline

An adopted Initial Question Baseline is immutable at `revision=0`. Later review never rewrites that revision.

Each active RQ exposes a stable `question_lineage_id`; for an Initial Baseline that has no explicit lineage field, its RQ identity is the lineage identity. A later revision or derived RQ records the exact source RQ revision(s) in `derived_from_question_revisions`.

## Question Review and Question Delta

A review result is exactly one of:

- `KEEP`
- `REFINE`
- `SPLIT`
- `MERGE`
- `CLOSE`

`KEEP` is a no-change result: it creates no Research Snapshot and requires no Human Decision.

`REFINE`, `SPLIT`, `MERGE`, and `CLOSE` are material semantic changes. They MUST be emitted as candidate-only State Delta Proposals bound to the exact current Research Snapshot and MUST NOT become authoritative without the existing Human Decision boundary.

Approved changes create a new immutable RQ revision or derived RQ identity. Historical RQ revisions, Runs, Snapshots, Evidence, Decisions, and Publication feedback remain addressable against the revision they originally referenced.

## Subsequent Run binding

Capability Context Packs for subsequent Runs MUST bind the selected current RQ identity and exact revision through `research_object_references`. A material Question Delta MUST NOT silently rebind historical Runs.

## Review inputs and downstream review

Question Review may record uncovered Attention, Evidence Gap, and Publication Feedback identifiers as provenance. These inputs are not Human authority and do not change Evidence adoption semantics.

When a material change affects current downstream Research or Publication objects, the Question Delta MUST identify those objects for review. It MUST NOT automatically rewrite or invalidate those downstream objects.

## Scope boundary

This contract does not change Evidence adoption, Publication Eligibility, Publication approval, or Capability execution authority. Work, chat, workers, Capability results, and Publication feedback may propose or motivate a Question Delta but may not auto-adopt it.
