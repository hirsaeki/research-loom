# Canonical Survey Capability contracts

This package specializes the PR12 Research Method Capability for Survey without redefining the PR9 Capability Context Pack / Handoff or the PR12 Research Method envelopes.

The extension chain is:

`PR9 Context Pack -> PR12 Research Method Context extension -> PR13 Survey Context extension`

and:

`PR9 Handoff -> PR12 Research Method result extension -> PR13 Survey result extension`

## Owned here

- Survey method design: target population, unit of analysis, sampling frame/strategy, eligibility, recruitment/contact constraints, target sample/stopping rule, representativeness assumptions.
- Questionnaire: stable question identity, supported item types, options/scales, requiredness, branching/skip logic, randomization, and construct/RQ/Evidence Gap traceability.
- Survey execution projection: response records, sample disposition, incomplete/partial/nonresponse/dropout/exclusion, duplicate handling, missingness preservation, and privacy-sensitive identity separation.
- Survey descriptive analysis projection: response/eligible/completion counts, item denominators, missingness/exclusions, aggregation/subgroup provenance, optional free-text coding references, and candidate response-bias/coverage limitations.

## Authority boundaries

- A generated SurveyDesign is candidate MethodDesign material, not a Core Method.
- A Questionnaire is an Instrument, not a Core Method. Generation does not approve it.
- Wording or scale changes are material Questionnaire revisions and require Human Decision authority before approved real execution.
- Responses are raw method data. They are not verified Evidence by collection alone.
- Aggregates/statistics/coding are candidate Analysis material. They are not Findings by calculation alone.
- Achieving a target sample does not establish research sufficiency.
- The Survey capability may propose candidate next methods through the PR9 Handoff, but cannot select/adopt them.

## Virtual boundary

`virtual` and `synthetic_test` remain PR12 execution modes. This package deliberately does not define synthetic respondent/persona generation. Synthetic responses cannot become empirical responses or empirical Evidence.

## Out of scope

Concrete hosting/runtime/API integration, contact/email distribution, MISCO-specific questionnaire items, Excel import/export, Delphi, Case Study, Virtual Runner implementation, SQLite, Writer/Publication, and legacy deletion.
