# Survey Capability convergence (PR13)

PR13 specializes PR12 Research Method Capability semantics for Survey. The legacy harness treats Survey as suitable for respondent/company self-reported As-Is, perception differences, value/burden/control, and practical issues, while explicitly not establishing causal effects, precise ROI, normative desirability, or future prediction. It also requires method choice to follow Evidence Gaps and Human Decision rather than a fixed Survey/Delphi/Case sequence.

Canonical ownership is therefore limited to Survey method design, Questionnaire semantics, response/sample disposition, and descriptive candidate analysis. PR9 continues to own Context Pack / Invocation / Handoff; PR12 continues to own MethodDesign/Core Method authority, Protocol/RunSpec pins, execution modes, raw-data separation, incomplete-run semantics, and candidate Analysis/Finding boundaries.

Question IDs are lineage identities across versions. Wording/scale changes are material Questionnaire revisions. Questionnaire generation never approves an Instrument. Real execution requires the already-approved method/protocol boundary from PR12 plus Questionnaire Human Decision authority.

Responses preserve partial/nonresponse/dropout/exclusion/duplicate/missing-data state and may carry timestamps/provenance where permitted. Privacy-sensitive respondent identity stays outside Core research semantics. Responses are not verified Evidence automatically.

Analysis preserves eligible/response/completion counts, item denominators, missingness/exclusions, aggregation and subgroup-definition provenance, free-text coding refs, limitations/coverage, and candidate response-bias assessment. Statistics are candidate Analysis material, not Findings.

`virtual`/`synthetic_test` are accepted PR12 modes, but PR13 does not define synthetic respondent/persona generation. Synthetic responses cannot become empirical responses or empirical Evidence. Virtual Runner semantics remain a later PR.
