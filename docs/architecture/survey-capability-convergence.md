# Survey Capability convergence (PR13)

## Purpose

PR13 specializes the PR12 Research Method Capability for Survey. It does not create a second capability ABI: PR9 still owns Context Pack / Invocation / Handoff, and PR12 still owns method-design / instrument-design / execute / analyze authority, execution-mode, RunSpec, Protocol, raw-data, and candidate-analysis boundaries.

The legacy harness described Survey as appropriate for respondent/company self-reported As-Is, perception differences, value/burden/control, and practical issues, while explicitly excluding causal effects, precise ROI, normative desirability, and future prediction. It also required method selection to follow Evidence Gaps and Human Decision rather than a precommitted workflow. PR13 preserves those boundaries in canonical contracts.

## Extension chain

- `capability-context-pack@0.1.0`
  - `research-method-context-extension@0.1.0`
    - `survey-context-extension@0.1.0`
- `capability-handoff@0.1.0`
  - `research-method-result-extension@0.1.0`
    - `survey-result-extension@0.1.0`

Survey references are content-pinned resources in the PR9 Context Pack. The Survey extension cannot widen Context Pack bounds or treat Project Config availability/permission hints as runtime authorization.

## Method design

`survey-design@0.1.0` keeps target population, unit of analysis, sampling frame, sampling strategy, eligibility, recruitment/contact constraints, target sample/stopping rule, and representativeness assumptions together. It remains candidate MethodDesign material. Target-sample achievement is not a research-sufficiency decision.

## Questionnaire

`questionnaire@0.1.0` treats question identity as stable across versions and makes question type, options/scale, requiredness, branching, randomized order, and construct/RQ/Evidence Gap traceability explicit. Wording and scale changes are material revisions. Generation never approves the instrument; approved real execution requires Human Decision references.

The Questionnaire is an Instrument and is never a Core Method.

## Execution

Survey execution projects PR12 raw `response` refs into Survey-specific response/disposition metadata. It keeps complete/partial responses, nonresponse, dropout, exclusions, duplicate handling, timestamps/provenance where permitted, and missingness. Privacy-sensitive respondent identity may be externally referenced by Survey execution policy/result metadata, but is explicitly not a Core research object.

Responses remain raw method data and do not become verified Evidence automatically.

## Analysis

Survey analysis is descriptive candidate material. It preserves eligible/response/completion counts, item-level denominators, missingness/exclusions, aggregation provenance, subgroup-definition provenance, optional free-text coding refs, limitations/coverage, and candidate response-bias assessment. Aggregates/statistics/coding outputs do not become Core Analysis or Findings automatically.

## Real / virtual / synthetic_test

PR13 accepts PR12 execution modes. It does not define synthetic respondent/persona generation. Any `virtual` or `synthetic_test` response is non-empirical and cannot be promoted to empirical Evidence.

## Deliberately not canonicalized

- runtime/hosting/API implementation
- contact or email distribution service
- MISCO-specific questionnaire content or Excel layout
- Delphi, Case Study, or Virtual Runner semantics
- SQLite / Writer / Publication
- Research Profile quality thresholds
- legacy deletion
