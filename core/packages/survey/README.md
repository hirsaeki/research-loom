# Canonical Survey Capability contracts

PR13 specializes PR12 `research_method` semantics for Survey. PR9 Context Pack / Invocation / Handoff and PR12 Research Method Context / result extensions remain authoritative and are not redefined.

Extension chain: `PR9 -> PR12 Research Method -> PR13 Survey`.

Survey owns population/sampling/recruitment design, versioned Questionnaire semantics, response/sample disposition, duplicate/missing-data preservation, and descriptive candidate-analysis metadata. Questionnaire generation is not approval; wording/scale changes are material revisions; responses are not verified Evidence; aggregates are not Findings; target-sample achievement is not research sufficiency.

The canonical Survey Design and Questionnaire remain distinct. Survey Design owns the research design: population, sampling, eligibility, recruitment, stopping, and representativeness. Questionnaire owns respondent-facing instrument semantics: stable question identity, optional stable response keys, stable option values distinct from display labels, sections, requiredness, scale/validation fields, branching, and explicit missing-value categories where needed. A missing response remains absence of a response and is not collapsed into `unknown`, `not_applicable`, or `prefer_not_to_answer`.

PR40 adds a production local registry and deterministic provider-neutral Instrument Exchange outside the canonical Survey meaning model. A persisted Instrument is the exact binding of one canonical Survey Design revision and one canonical Questionnaire revision plus RQ/Snapshot/project/profile provenance. Microsoft Forms, Google Forms, Graph/API payloads, Apps Script details, Copilot/Gemini prompt syntax, and provider item IDs are not canonical Survey fields. JSON and Markdown exchange are deterministic projections of the same persisted Instrument. The future Virtual Runner is expected to consume the same canonical Questionnaire rather than a runner-specific questionnaire.

`virtual` and `synthetic_test` are accepted PR12 execution modes, but synthetic respondent/persona generation is deliberately left to the later Virtual Runner contract. Synthetic responses cannot become empirical responses or empirical Evidence.

Out of scope: Forms provider integration, OAuth, contact distribution, response intake/cleaning/statistical execution, MISCO-specific questionnaire formats, Delphi, Case Study, Virtual Runner implementation, Writer/Publication, and UI/dashboard work.
