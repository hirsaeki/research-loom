# Survey Capability convergence (PR13, production projection in PR40)

PR13 specializes PR12 Research Method Capability semantics for Survey. The legacy harness treats Survey as suitable for respondent/company self-reported As-Is, perception differences, value/burden/control, and practical issues, while explicitly not establishing causal effects, precise ROI, normative desirability, or future prediction. It also requires method choice to follow Evidence Gaps and Human Decision rather than a fixed Survey/Delphi/Case sequence.

Canonical ownership is therefore limited to Survey method design, Questionnaire semantics, response/sample disposition, and descriptive candidate analysis. PR9 continues to own Context Pack / Invocation / Handoff; PR12 continues to own MethodDesign/Core Method authority, Protocol/RunSpec pins, execution modes, raw-data separation, incomplete-run semantics, and candidate Analysis/Finding boundaries.

## Design and Instrument are different objects

`Survey Design != Questionnaire / Instrument`.

Survey Design owns population, unit of analysis, sampling frame/strategy, inclusion and exclusion, recruitment constraints, target/stopping conditions, and representativeness assumptions. It remains candidate material and does not self-adopt a Core Method or claim research sufficiency.

Questionnaire owns respondent-facing semantics. Question IDs are lineage identities across versions. PR40 adds optional stable response keys, explicit section binding, stable option values distinct from display labels, and explicit missing-value option bindings. Wording/scale changes are material Questionnaire revisions. Questionnaire generation never approves an Instrument. Real execution still requires the already-approved method/protocol boundary from PR12 plus Questionnaire Human Decision authority.

A missing response is preserved as no response. `unknown`, `not_applicable`, and `prefer_not_to_answer` may be represented as distinct stable response values; they must not be collapsed into one null/empty value.

## Production registry and provider-neutral exchange

PR40 adds a local production registry without changing the authority of the canonical Survey contracts:

```text
Research Question
      -> Survey Design revision
      -> Questionnaire revision
      -> persisted Design/Questionnaire binding
      -> deterministic Instrument Exchange
```

The registry adds stable revision addressing and provenance: authoritative RQ bindings, active lineage/Snapshot binding, Project Config digest, Effective Profile Set digest, capture time, and immutable content digests. Capturing or exporting a Survey Design/Instrument is not Evidence verification, Finding adoption, Recommendation adoption, research completion, or Research State mutation.

`Canonical Instrument != Microsoft Forms != Google Forms`.

The canonical Questionnaire remains provider-neutral. PR40 projects the same persisted Instrument to deterministic UTF-8 JSON and Markdown. Provider-specific form IDs/item IDs, Microsoft Graph payloads, Google Forms API payloads, Apps Script implementation details, and Copilot/Gemini prompt syntax belong in future adapters. The dependency direction is:

```text
Canonical Survey Design + Questionnaire
          -> provider-neutral JSON/Markdown Exchange
          -> external human/LLM/form-builder adapter
```

The future Virtual Runner should consume the same canonical Questionnaire revision and digest. It must not define a separate "Virtual Runner questionnaire".

Export is a read-only projection. Re-exporting the same persisted revision produces stable ordering and bytes; export-time timestamps are not injected into the semantic payload.

## Execution and analysis boundaries

Responses preserve partial/nonresponse/dropout/exclusion/duplicate/missing-data state and may carry timestamps/provenance where permitted. Privacy-sensitive respondent identity stays outside Core research semantics. Responses are not verified Evidence automatically.

Analysis preserves eligible/response/completion counts, item denominators, missingness/exclusions, aggregation and subgroup-definition provenance, free-text coding refs, limitations/coverage, and candidate response-bias assessment. Statistics are candidate Analysis material, not Findings.

`virtual`/`synthetic_test` are accepted PR12 modes, but PR13/PR40 do not define synthetic respondent/persona generation. Synthetic responses cannot become empirical responses or empirical Evidence. Virtual Runner execution remains a later PR.
