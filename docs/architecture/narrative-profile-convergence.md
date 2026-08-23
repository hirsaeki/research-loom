# Narrative Profile convergence

PR 7 converges reusable Narrative Profile semantics above the Core research contract, PR 4 Profile composition contract, and PR 6 Research quality policy. It promotes only argument-structure and reader-facing semantic dependencies that can be reused without adopting a concrete project chapter map or implementing Writer runtime behavior.

## Compared legacy responsibilities

The legacy Research Harness / publication-writer material consistently treats writing as a read-only projection of approved research state: the Writer may expose supplied Findings, Arguments, model/recommendation links, qualifiers, and limitations, but must not create research conclusions, causal judgments, support decisions, or missing links. Its Primary Exposition Location is explicitly a reader-explanation hint rather than ownership of a Finding by a chapter.

The legacy Research Profile publication authority pack adds the complementary negative constraints: do not fix recommendation counts, model stages, method order, chapter order, or a generic paper template; do not create new interpretation/generalization/support judgments; and do not hide material counterevidence by moving it only to a generic limitations location.

Project feedback contains useful concrete narrative flows and chapter homes, but marks itself non-canonical project knowledge. Those project-specific Research Attention and literal chapter choices are therefore not promoted.

## Canonical ownership

Narrative Profile owns:

- semantic narrative stages and reusable semantic roles;
- the minimum partial-order/dependency edges between those stages;
- section-purpose semantics independent of headings and chapter numbers;
- read-only connections to authoritative Argument, Finding, Contribution, Recommendation, and related Core objects;
- preservation requirements for adverse findings/counterevidence effects, qualifiers, limitations, and supplied research-state links.

Narrative Profile does not own:

- Research Method selection or research design;
- the answer to a Research Question or any authoritative adoption/revision decision;
- project-specific Research Attention, topic emphasis, communication brief, or chapter map;
- literal chapter/section headings or publication locations;
- citation, formatting, template, rendering, or release policy.

## Stage semantics

`narrative.stages.definitions` is a set of semantic stage definitions. A stage has:

- `semantic_role`: what argumentative role it plays;
- `consumes`: authoritative research input kinds it may draw on when available;
- `requires`: authoritative research inputs that must exist before the stage can be instantiated;
- `produces`: Narrative products such as argument exposition or qualified finding exposition.

`produces` can never name a Core research object. Narrative can produce an exposition of a Recommendation, but it cannot create the Recommendation.

The catalog does not make a formation/model stage mandatory. Profiles may define different stage sets.

## Dependency semantics

`narrative.dependencies.required` defines a directed acyclic graph of minimum semantic dependencies. Edges are partial-order constraints only. Unrelated stages remain unordered, and a later Writer/Project projection may:

- choose any topological order consistent with the edges;
- realize multiple semantic stages in one literal section; or
- realize one semantic stage across multiple literal sections.

No chapter number or heading participates in canonical dependency identity.

## Section-purpose semantics

`narrative.section_purposes.definitions` gives reusable purpose IDs such as establishing context, exposing an argument, validating/qualifying a finding, synthesizing contributions, or presenting an approved recommendation. A future outline may map literal sections to these purposes. The purpose definition itself contains no literal heading, chapter number, or publication location.

## Preservation and authority

If selected research material carries counter-findings/counterevidence effects, qualifiers, or limitations, the Narrative projection must retain their constraining effect where the affected reasoning remains understandable. Merely moving adverse material to a detached limitations section is not preservation when doing so makes the Argument or Recommendation read stronger than the authoritative Research State.

Likewise, authoritative links such as Argument→support, Finding→counterevidence/qualifiers, Contribution→Finding, and Recommendation→Finding are preserved when both endpoints are projected. Missing links are reported as gaps; Narrative does not invent them.

Narrative is read-only with respect to authoritative Research State. Method choice, RQ answering, object creation/adoption, epistemic strengthening, and research-state mutation remain outside this layer.

## Projection hints

A provisional outline, primary/publication exposition location, literal heading, or chapter number can be useful input to a Writer/Project projection. They are explicitly non-normative hints:

- they do not create Narrative dependencies;
- they do not make a chapter the owner of a Finding;
- they do not alter Research State; and
- they are not canonicalized as reusable Narrative semantics.

Project Config will later determine the canonical home for project-specific Research Attention.

## Composition and conflicts

All `narrative.*` paths reuse PR 4 deterministic composition. The canonical paths in PR 7 use monotone `union`: composing Profiles can add stages, minimum dependencies, semantic purposes, preservation obligations, connection obligations, authority prohibitions, and recognized non-normative hint classes.

Structured set identities fail closed:

- same stage ID with divergent definitions;
- same section-purpose ID with divergent definitions; or
- same dependency endpoints with divergent relation semantics

are `PROFILE-NARRATIVE-IDENTITY-001`, never last-write-wins. Dangling stage references and dependency cycles also fail.

## Executable specification

The synthetic generic Narrative Profile demonstrates a reusable framing → formation → validation branch with separate synthesis and implication successors. The branch intentionally leaves synthesis and implication unordered to exercise partial-order semantics rather than a total chapter order.

Fixture-only projection cases verify that:

- counter-findings, qualifiers, and limitations are not lost;
- authoritative research-state links are preserved rather than invented;
- Narrative does not mutate Research State or answer an RQ; and
- Primary Exposition / provisional-outline hints remain non-normative.

These fixtures are executable specifications only. They do not define a Writer, Outline Package, Manuscript Package, or runtime projection wire format.
