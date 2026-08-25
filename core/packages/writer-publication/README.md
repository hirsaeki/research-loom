# Writer / Publication preview contracts

This package defines the canonical downstream transformation boundary from the Research Harness to Writer and Publication. Writer and Publication are **not** Research Capabilities and do not reuse the PR9 Capability Handoff envelope.

The canonical chain is:

`Research Snapshot -> Research Package -> Outline Package -> Manuscript Package -> Preview Artifact Manifest`

Writer may return a `Writing Feedback Package`; Writer or Publication preview may return `Profile Defect Candidate` objects. These are proposals/diagnostics only. The Harness remains the sole authoritative Research State write boundary.

## Research Package

`research-package.schema.json` is the only Harness -> Writer research-content boundary. It is snapshot/content bound, carries resolved Effective Profile Set pins, Communication Brief, selected research-object references, preservation constraints, project must-not-claim constraints, and publication-facing requirements. Writer does not read runtime storage or resolve Profile files independently.

A package sourced from PR17 virtual research uses the same envelope as REAL research but preserves `SYNTHETIC_TEST_ONLY`, `preview_only=true`, `authoritative_research_freeze=false`, and `release_eligible=false`.

## Writer preview

`writer-preview.schema.json` defines Outline/Section contracts and structured Writing Feedback. Section headings remain non-authoritative projections from Narrative semantics. Section deletion or reordering does not delete or rewrite Research State, and required counterreview/qualifier/limitation references must remain traceable.

Writing Feedback is not Evidence. It may propose missing-evidence or ambiguity follow-up but cannot edit Findings or Research State directly.

## Manuscript Package

`manuscript-package.schema.json` is the canonical Writer -> Publication boundary. It carries source package/snapshot pins, Writer identity/version, profile pins, outline pins, ordered sections, content/citation/exhibit references, audit summary, unresolved writing issues, and provenance.

A virtual manuscript is preview-only and cannot be promoted as the seed of a REAL draft. REAL Writer execution starts from a REAL Research Snapshot and builds a new Research Package, new Outline, and new Draft.

## Publication preview

`publication-preview.schema.json` defines Preview Artifact Manifest, Profile Defect Candidate, and Preview Iteration records. Publication may apply templates, citations, numbering, cross-references, layout, and rendering; it may not change research meaning or fabricate sources/citation metadata.

Preview outputs are explicitly non-releaseable. Profile revisions are Human-reviewed proposals under the existing Profile composition boundary and must produce new versions/digests before preview rerun. Previous preview artifacts are immutable.

`writer-publication-semantics.yaml` is the semantic error catalog used by the canonical contract oracle.
