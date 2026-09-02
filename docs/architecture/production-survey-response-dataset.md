# Production Survey Response and Response Dataset boundary

PR42 establishes one provider-neutral production boundary for Survey response data. The boundary is shared by the PR41 structural Virtual Runner and future REAL adapters. It does not add aggregation, LLM respondents, Forms/CSV importers, participant management, or Evidence adoption.

## Authority boundary

The stored canonical Survey Instrument remains the authority for response semantics. A response intake pins exactly:

- `instrument_id`
- `instrument_version`
- `instrument_digest`

Question IDs, response variables, question families, stable choice values, scale/numeric constraints, required state, branch/skip logic, and declared missing-value semantics are read from that exact Instrument revision. Response intake does not infer a schema from incoming columns or values and never edits the Instrument.

The existing PR41 `survey_response_record@0.1.0` remains the structural producer record used by the Virtual Runner. PR42 adds a raw intake envelope and an immutable persisted `survey_response` / `survey_response_dataset` representation around that producer boundary rather than replacing the PR41 contract.

## Shared data flow

```text
PR41 Structural Virtual Generator
future LLM Virtual Respondent
future REAL Forms / CSV adapter
            │
            ▼
   Raw Survey Response Input
            │
            ▼
      Normalization
            │
            ▼
    Canonical SurveyResponse
            │
            ▼
       Validation
            │
            ▼
 Canonical SurveyResponseDataset
            │
            ├──> future shared aggregation
            └──> bounded human inspection
```

Normalization and validation are separate responsibilities. Normalization performs representation conversion that the pinned Instrument can prove, such as a unique display label to its stable choice value. Validation checks the resulting answer against the Instrument. Invalid choices, ranges, required answers, branch states, or missing semantics are not repaired into valid data.

## Answer and missing semantics

Each canonical answer separates `state` from `value`. `answered` carries a value. Missing-like states carry no value:

- `missing`: the question was reachable but no answer was supplied
- `unknown`
- `not_applicable`
- `prefer_not_to_answer`
- `not_asked`: branch/termination logic made the question unreachable

This prevents a stable choice value such as `"unknown"` from being confused with the missing state `unknown`. Multi-select answers remain explicit arrays and are validated against stable Instrument values.

A display label may be normalized to a stable value only when the exact pinned Instrument has one unambiguous label-to-value mapping. Unknown or ambiguous input is rejected rather than guessed.

## Origin, epistemic status, and research adoption

Response acquisition has an explicit `response_origin` (`synthetic` or `real`) and an explicit `epistemic_status`. Current supported pairs are:

```text
synthetic -> SYNTHETIC_TEST_ONLY
real      -> EMPIRICAL
```

Identity namespaces remain separate (`synthetic:*` and `real:*`). IDs are otherwise provider-neutral; adapters do not need to rewrite a legitimate external identifier merely to add a prefix.

These fields describe response acquisition only. They do **not** mean:

- Evidence was verified or adopted
- a Finding was adopted
- a Recommendation was adopted
- an RQ was answered

Canonical response records therefore persist `verified_evidence_claimed=false` and `research_state_mutation_performed=false`. Dataset capture uses the same Research State head guard as PR40 Survey persistence and verifies the Snapshot is unchanged after capture.

## Rejected response preservation

Malformed or invalid input is not silently discarded. A Dataset separates:

- `accepted_response_refs`: valid canonical responses eligible for later analysis
- `rejected_response_refs`: canonicalizable responses that failed validation
- `rejected_inputs`: exact raw input, digest, issues, and a canonical response reference when one could safely be formed

A duplicate `response_id` is always rejected for the duplicate occurrence. Duplicate respondent identity is not a universal Core rule; the shared intake boundary allows it unless an authoritative producer policy requires one response per respondent. PR41 Virtual Runner integration enables that stricter rule to preserve its existing duplicate-identity semantics.

Rejected raw input can therefore be inspected by STRESS tests without contaminating the accepted population.

## Dataset invariants

A `survey_response_dataset` is immutable and homogeneous:

- one exact Instrument ID/version/digest
- one response origin
- one epistemic status supported for that origin
- no rejected response in the accepted population

Mixed-origin or mixed-Instrument content cannot enter the accepted population because Dataset intake has a single pinned envelope. A record that conflicts with that envelope is rejected. Cross-version analysis is deliberately outside PR42.

Dataset content digests use canonical serialization and normalize response-reference, rejected-input, and source-Run ordering, so reordering the same response collection does not change the content digest. Dataset identity is immutable but distinct from the content digest, allowing a later intake event to create a new immutable Dataset when provenance requires it.

The local canonical registry is `.research-loom/survey-response-registry.sqlite3`. It is separate from the PR40 Instrument registry so PR42 does not require a migration of the established Survey Design/Instrument store.

## PR41 integration

After a PR41 Survey Virtual Run completes, PR42 reads the existing `survey_virtual.synthetic_responses` artifact, adapts each PR41 record to `Raw Survey Response Input`, and captures a Dataset in the Survey response registry.

The completed Run is not modified. No Dataset artifact is appended to the Run. Instead, the Dataset records `source_run_ids` and source provenance containing the existing response artifact identity/digest and scenario class.

STANDARD should normally produce an all-accepted synthetic Dataset. STRESS intentionally produces rejected inputs and validation issues such as invalid choice, required missing, branch violation, duplicate response, or malformed input. PR42 preserves those defects; it does not normalize them away.

## Public Application Facade and JSON action path

Transport-neutral facade methods:

```text
normalize_survey_response
capture_survey_response
capture_survey_response_dataset
show_survey_response
show_survey_response_dataset
```

PR42 reuses the existing public `action submit` JSON CLI boundary instead of adding a second command namespace. The production actions are:

```text
survey_response.normalize
survey_response.capture
survey_response.show
survey_response_dataset.capture
survey_response_dataset.show
```

The `show` actions are read-only. Dataset show accepts bounded `limit` / `offset` pagination. Individual response show returns the exact stored canonical response and exact raw input. `response_id` may legitimately repeat across producer namespaces (for example PR41 runs), so the show payload accepts `identity_namespace` when the ID is ambiguous. This supports later human inspection of LLM-backed virtual respondents without direct SQLite access.

## Explicit non-goals

PR42 does not implement:

- frequency, percentage, cross-tab, mean/median, missing-rate summaries, or charts
- `SurveyAnalysisSpec` or an analytics DSL
- LLM provider/model/persona/prompt generation
- Microsoft Forms, Google Forms, CSV, Excel, or manual REAL import adapters
- participant registry / CRM / PII workflow
- Evidence, Finding, Recommendation, or RQ adoption
- UI

Those can consume this boundary later without changing producer-specific response semantics.

### Producer lineage extension

Provider-specific response production metadata belongs in raw response `provenance`, which canonical normalization projects into `SurveyResponse.source_provenance.producer`. LLM Virtual Respondent Runs use this existing extension point for the exact synthetic profile ID/digest, source Run, generation-attempt ref, and parsed-answer digest. These fields are response-level provenance; they are not question-answer semantics. Future REAL producers can use the same producer-provenance boundary without adding LLM-specific answer fields.
