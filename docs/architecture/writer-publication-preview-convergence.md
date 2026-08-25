# Writer / Publication preview convergence (PR18)

PR18 establishes the first canonical downstream transformation flow on top of PR3-17 without introducing a production Writer or Publication runtime.

## Separate downstream boundary

PR9 describes Research Capability invocation/handoff. Writer and Publication do not perform Research Method execution, so they do not receive a second Capability ABI. Harness emits a content-bound Research Package; Writer projects it into reader-facing structure/prose and emits a Manuscript Package; Publication deterministically projects the manuscript into formal artifacts.

Authority remains separated:

- Harness owns adopted/qualified research meaning and remains the only authoritative Research State write boundary.
- Writer owns exposition projection: ordering, sections, headings, paragraphs, citations/exhibits, transitions, and draft prose.
- Publication owns medium projection: template/style, citation rendering, numbering, cross-references, layout, DOCX/PDF rendering, filenames, and render validation.

Writer does not read runtime storage directly and does not independently resolve Profile files. Publication does not add Evidence or alter Finding meaning, confidence, causal/generalization scope, limitations, or counterevidence.

## First preview flow

PR17 permits validated virtual research to move downstream only as `SYNTHETIC_TEST_ONLY`. PR18 uses that projection to diagnose Narrative/Profile, Writer, Publication, citation, exhibit, cross-reference, and template defects before REAL research/publication.

```text
Virtual Research Snapshot (SYNTHETIC_TEST_ONLY)
  -> Research Package
  -> Writer Preview / Outline Package
  -> Writing Feedback Package
  -> Manuscript Package (preview)
  -> Publication Preview
  -> Preview Artifact Manifest
  -> Profile Defect Candidate
```

Preview is diagnostic. It is not Research Freeze, Manuscript Freeze, Published Artifact, or Release Manifest.

## Research Package

The Research Package is the only Harness -> Writer research-content boundary. Preview and REAL use the same envelope. It binds Project Config, resolved Effective Profile Set, immutable Research Snapshot, Communication Brief, selected Research Questions/Findings/Arguments/Contributions/Evidence/Sources and locators/CounterReviews, qualifiers/limitations, unresolved Evidence Gaps, Research Attention, Narrative semantic constraints, project must-not-claim constraints, publication-facing requirements, and provenance/digests.

A virtual package preserves `SYNTHETIC_TEST_ONLY`, `preview_only=true`, `authoritative_research_freeze=false`, and `release_eligible=false`. Writer may not supplement the package with unsupplied research facts.

## Section Contract

A Section Contract is a projection contract, not a research ownership boundary. It records semantic purpose/stage, reader need, Argument/Finding/Evidence refs, CounterReview/qualifier/limitation refs that must survive exposition, Contribution/Recommendation refs, exhibit/citation requirements, opening/closing intent, bridge/length/emphasis hints, prohibited claims, and a generated heading marked non-authoritative.

Narrative partial order remains semantic. Writer may choose a concrete outline while preserving dependencies, but that concrete total order is not promoted back into canonical Narrative meaning. Removing a section never deletes the underlying Finding, limitation, or CounterReview from Research State.

## Writing Feedback

Writer returns structured feedback for missing evidence, ambiguous scope, unsupported or missing argument links, qualifier/limitation conflicts, unintegrated counterevidence, Narrative conflicts, Communication Brief gaps, and package traceability gaps. Writing Feedback is not Evidence, cannot revise a Finding directly, and cannot mutate authoritative Research State. Harness may translate it into a candidate NextAction/proposal subject to existing Human Decision boundaries.

## Publication Preview and defects

A preview Manuscript Package carries its Research Package/Snapshot, Writer/version, Effective Profile Set, Narrative/Publication pins, Outline pin, ordered section/content refs, citations, exhibits, bibliography inputs, Writer audit, unresolved writing issues, and provenance. A Preview Artifact Manifest binds the manuscript to Publication Profile, template, style-map, renderer/tool version, output digests, and validation checks.

Writer/Publication preview may emit Profile Defect Candidates targeting Narrative Profile, Publication Profile, Project Config, Writer contract, Publication contract, or Research Package. A defect candidate cannot directly mutate a Profile or weaken Core invariants. Ambiguous Profile conflicts are never resolved by last-write-wins; they require Human review under the existing composition semantics. Human-reviewed revisions create new versions/digests and a new immutable preview iteration. Previous preview artifacts are not overwritten.

## VIRTUAL -> REAL firewall

Human-reviewed Narrative/Publication Profile revisions, Writer rules/rubrics/prompts/templates, Publication templates/style maps, Section Contract schema, validation rules, defect history, and preview-test history may cross the cutover boundary.

The following may not cross as REAL manuscript content: Virtual manuscript prose, synthetic fact statements, virtual research citations, virtual analytical conclusions, synthetic respondent quotations, virtual Finding prose, and bibliography entries derived only from synthetic content.

REAL Writer execution always restarts from:

`REAL Research Snapshot -> new Research Package -> new Outline -> new Draft`

`Virtual Draft -> REAL Draft` promotion is forbidden.

## Citation semantics

Writer may cite only supplied Source/Evidence references and supplied locators. Synthetic placeholders use the explicit `preview:` namespace and are not citation-capable empirical sources. Publication never invents DOI, URL, or bibliography metadata; unresolved citations are returned as defects.

## Traceability

The preview chain remains digest-bound and traceable:

`Virtual Research Snapshot -> Research Package -> Outline -> Manuscript Package -> Preview Artifact Manifest -> Defect / Iteration`

Each stage pins its input digests and tool/profile/template versions where applicable.

## PR10 routing

A request such as “このVirtual Runの結果で報告書を仮組みして、Narrative / Publication Profileの問題を洗って” routes to Harness service `writer-publication.preview`, not PR9 Capability Invocation. It remains proposal-only/read-only with respect to authoritative Research State. Preview execution does not imply Research Freeze, Manuscript Freeze, Publication Release, or final release approval.

## Out of scope

Production Writer/Publication runtimes, final Research/Manuscript freeze, final Publication Release, concrete DOCX/PDF renderer implementation, concrete MISCO templates, SQLite, OneDrive publishing, Fork/Branch/Recovery, and legacy deletion remain outside PR18.
