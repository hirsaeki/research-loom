# Canonical Survey Capability contracts

PR13 specializes PR12 `research_method` semantics for Survey. PR9 Context Pack / Invocation / Handoff and PR12 Research Method Context / result extensions remain authoritative and are not redefined.

Extension chain: `PR9 -> PR12 Research Method -> PR13 Survey`.

Survey owns population/sampling/recruitment design, versioned Questionnaire semantics, response/sample disposition, duplicate/missing-data preservation, and descriptive candidate-analysis metadata. Questionnaire generation is not approval; wording/scale changes are material revisions; responses are not verified Evidence; aggregates are not Findings; target-sample achievement is not research sufficiency.

`virtual` and `synthetic_test` are accepted PR12 execution modes, but synthetic respondent/persona generation is deliberately left to the later Virtual Runner contract. Synthetic responses cannot become empirical responses or empirical Evidence.

Out of scope: runtime/hosting/API/contact distribution, MISCO questionnaire/Excel formats, Delphi, Case Study, Virtual Runner implementation, SQLite, Writer/Publication, legacy deletion.