# Research-backed visual semantics

Issue #404 extends the existing immutable Research Exhibit registry. There is no
new phase, database, Research Object kind, or authority transition.

An optional `visual_semantics` capture field distinguishes `source_visual`,
`data_visualization`, and `explanatory_visual`. Legacy table/matrix/graph/note
captures and existing source `visual_target` records remain readable. Absence of
the new field is legacy working material, not a claim of validated visual semantics.

## Minimal capture contract

The caller supplies exactly:

```json
{
  "visual_class": "explanatory_visual",
  "semantic_changes": [],
  "generator": {
    "identity": "host generator",
    "version": "not exposed",
    "instruction": "Explain the selected existing research without adding claims."
  }
}
```

Reuse `source_object_ids` and `derived_from_exhibit_ids` for represented research.
For visual captures these must resolve; lightweight unknown object references are
still allowed for legacy analytical Exhibits. Loom retains each Research Object's
existing canonical digest and each represented Exhibit's exact content digest.
All represented references must be selected with the visual in its Research
Package; omitted or changed references fail package build and consumer validation.
An Exhibit reference is working-material provenance, never proof of approval.

The harness owns `semantic_refs`, `spec_digest`, `semantic_status`, and the retained
generation instruction digest. `spec_digest` binds the exact Exhibit content,
including labels, relations, or a structured visual/chart specification. The
existing content bound is 1 MiB; generator instructions are bounded to 64 KiB and
semantic references to 64. No arbitrary metadata bag or graph DSL is introduced.

`source_visual` additionally requires the existing exact `visual_target`, including
source capture, locator, retained original/derived digest and artifact provenance.
Its generator must be null. Generated visuals cannot have a source visual target.
Source citation and rights metadata remain owned by captured source/material and
the existing Publication Profile. New rendering or image capture is out of scope
for this contract increment; B/C provide those paths.

`data_visualization` and `explanatory_visual` require explicit generator identity,
version (or `not exposed`), and exact instruction. This does not validate numbers,
approve a generator's relations, or grant authority. Data mapping validation is B;
exact generated binary capture and semantic review are C.

## Meaning and authority

`semantic_changes` lists any requested new `value`, `aggregation`,
`classification`, `causality`, `relation`, `interpretation`, or `generalization`.
Any such change yields `research_required`; ordinary Research candidate,
evaluation, and adoption operations must establish the new meaning.

An empty list yields **`review_required`**, never `approved` or `conformant`.
Even a model's assertion of “no new meaning” cannot clear this status. Host/human
review must examine represented labels/relations against the pinned research;
arbitrary image meaning is not mechanically decidable. Capture/list/show are not
semantic review, Evidence verification, Finding adoption, manuscript approval,
or release approval.

Each regeneration/revision is a new Exhibit; past records remain immutable. A
byte-identical content digest does not imply identical semantic provenance.
Research Package retains the complete contract and verifies reference closure.

## Validation and bounded ablation

`test_issue404_visual_semantics.py` covers exact capture, immutable recapture,
Research State invariance, package export/verify round trip, changed/missing
research refs, stale spec digests, source/generated confusion, and attempted
caller-supplied approval. The same content with refs removed fails visual capture;
bytes alone may still be legacy working material but acquire no semantic class or
review status. Later visual consumer integration must preserve that distinction.

Local runtime tests cannot start in the current sandbox because `jsonschema` is
not installed. No dependencies were installed to reproduce CI. Syntax compilation
and `git diff --check` are available; execution tests run in the existing CI shards.
