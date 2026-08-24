# Case Study capability convergence

PR16 specializes the PR12 Research Method Capability for canonical Case Study semantics while preserving the contracts established in PR3–15.

## Convergence decision

`research_method.case_study` is a PR12 method specialization, not a second capability ABI. PR9 remains the only Context Pack / Invocation / Handoff wire format and PR12 remains the owner of MethodDesign/Core Method, Protocol/Instrument/RunSpec, Run identity, execution mode, raw-data, candidate Analysis, and Human Decision boundaries.

Case-specific contracts therefore describe only the bounded design, Case Protocol, case-run/result extension, blocked-result extension, and semantic checks needed to prevent Case Study-specific category errors.

## Case-specific invariants

- A case is selected with an explicit rationale inside an explicit boundary; selection does not imply representative population sampling.
- Convenience-only selection cannot be represented as purposive/theoretical, critical, or maximum-variation selection.
- Fixed case count is never sufficient by itself to claim research sufficiency.
- Case Protocol is the `instrument_design` specialization; it is not a questionnaire.
- Stable construct/field identity, RQ/Evidence Gap traceability, coding lineage, triangulation plan, negative/rival capture, and material-revision Human Decision remain explicit.
- Run execution pins case identity/boundary plus Protocol/RunSpec and preserves access failure, missingness, deviation, exclusion, dropout/unusable case, contradiction, ambiguity, and researcher/LLM coding provenance.
- Raw observation / extraction is not verified Evidence, coding is not Finding, and interpretation is not observed fact.
- Same-primary-source observations do not become independent Evidence through repeated extraction.
- Within-case and cross-case outputs are candidate analysis. Negative/deviant cases cannot be silently discarded.
- Recurring pattern is not mechanism, sequence is not causal proof, and cross-case similarity is not generalizability. PR6 owns causal-support quality rules.
- Stopping and additional-case recommendations are proposal-only and do not complete research.
- Real, virtual, and synthetic-test content are epistemically isolated; no virtual-to-real content promotion is permitted.

## Harness and Conversation boundaries

The Harness is the only authoritative Research State writer. Capability output may report candidates, ambiguities, Evidence Gaps, and blocked reasons, but cannot adopt Evidence/Findings/Methods or select the next case/method.

The PR10 routing fixture uses `proposal_only` and routes through PR9 `capability-invocation@0.1.0`. Conversational confirmation cannot substitute for Method adoption or material Case Protocol revision Human Decision.

## Fail-closed guardrail

Case execution is blocked when required input, runtime authorization, Human Decision, valid boundary, RQ/Evidence Gap binding, or compatible protocol/version pins are unavailable. Missing premises are never silently manufactured by the capability.

## Explicit non-goals

No concrete analyzer/runtime, transcription runtime, qualitative-coding LLM, MISCO-specific case, synthetic persona/case generator, Virtual Runner, Fork/Branch/Recovery implementation, SQLite, Writer/Publication, or legacy deletion is introduced here.
