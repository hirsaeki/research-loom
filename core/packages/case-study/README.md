# Canonical Case Study Capability Contracts

This package specializes the PR12 Research Method Capability for Case Study work without redefining the PR9 Capability Context Pack, Invocation, or Handoff wire envelopes or the PR12 Method envelopes.

The capability kind is `research_method.case_study` and binds exactly `method_design`, `instrument_design`, `execute`, and `analyze`.

## Authority boundary

The Harness remains the only authoritative Research State write boundary. Case Study capability and LLM outputs are candidate material: generated designs do not adopt a Core Method; raw observations do not become verified Evidence; coding labels and recurring patterns do not become Findings; selection does not imply population representativeness; mechanism candidates do not establish causality; stopping and next-case/next-method outputs are proposal-only. Human Decision boundaries from PR12 remain authoritative.

## Method design

Case design owns the purpose and target Research Question / Evidence Gap, unit of analysis, explicit organizational/temporal/process/system/other boundary, selection strategy and rationale, eligibility criteria, known case universe/candidate set, selected cases, case-count rationale, within/cross-case intent, embedded units, transferability assumptions, validity threats, access constraints, and additional-case criteria.

A selected case is not a representative population sample. Case count alone is not research sufficiency. Convenience-only selection must not be relabeled as theoretical/purposive, maximum-variation, or critical selection.

## Instrument specialization

`instrument_design` means Case Protocol / extraction template / coding frame / observation guide design, not questionnaire generation. The Case Protocol is versioned and digest-bound, preserves stable variable/construct/observation-field identities, RQ/Evidence Gap/construct traceability, within- and cross-case coding frames, source-role distinctions, triangulation planning, chronology/process-tracing fields, negative evidence, rival explanations, and revision lineage. Approved or materially revised protocols remain subject to PR12 Human Decision boundaries.

## Execution and analysis

Execution pins the selected case identity, immutable case-boundary digest, Protocol, and RunSpec. It preserves observation/source/artifact provenance, chronology where applicable, unavailable sources, access failures, incomplete observations, missing variables/periods, case dropout/unusable cases, deviations, exclusions with rationale, contradictions, negative evidence, unresolved ambiguity, and human/LLM coding provenance.

Direct observation, source extraction, and researcher interpretation are distinct roles. Researcher interpretation must back-reference observations; extracted or observed data must back-reference original source/artifact locators. Multiple observations derived from one primary source remain one independence group.

Within-case analysis may reconstruct chronology, patterns, mechanism candidates, rival explanations, expected-vs-observed comparisons, boundary conditions, and validity threats. Cross-case analysis pins the comparison set and common constructs, retains per-case provenance, negative/deviant cases, subgroup/cluster-definition provenance, missing/incomparable dimensions, and synthesis limitations. All remain candidate analysis.

Recurring pattern is not a causal mechanism; sequence consistency is not causal proof; cross-case similarity is not generalizability. Mechanism/causal candidates remain subject to the PR6 Research Profile causal-support policy.

## Epistemic and stopping boundary

`real` uses real cases and observations/material under PR12 authority. `virtual` is for protocol/coding/analysis-flow/missingness validation only; synthetic case content cannot be carried into real observations or empirical Findings/Evidence. `synthetic_test` validates schema/flow and has no empirical semantics.

Stopping cannot rely on fixed case count alone. Important rival explanations, material Evidence Gaps, potential falsifiers, or new coverage dimensions preserve remaining information value. Saturation/diminishing-gain and stopping are candidate assessments, not Research completion or Human Decision.

Missing required input, authorization, Human Decision, valid case boundary, RQ/Evidence Gap binding, or compatible protocol pins fails closed. The capability reports an Evidence Gap, ambiguity, or blocked reason instead of filling the missing premise.
