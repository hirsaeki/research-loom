# Production REAL Survey response intake

Issue #221 adds one minimal REAL Survey response intake path over the existing canonical Survey response and shared aggregation services. It does not add provider-specific connectors or a second analysis model.

```text
provider-neutral UTF-8 JSON file
+ exact Instrument id/version/digest
        |
        v
survey_real_intake.capture
        |
        +--> canonical Survey response normalization / validation
        +--> immutable SurveyResponseDataset (origin=real, epistemic=EMPIRICAL)
        +--> existing SurveyAnalysisSpec
        +--> existing shared SurveyAggregateResult
        |
        v
survey_real_intake.show
        |
        +--> intake source + file digest
        +--> raw input + canonical response / rejection diagnostics
        +--> Dataset + Instrument pin
        +--> Aggregate result/items
        +--> candidate research-material marker
```

## Interchange format

The first production slice intentionally supports only provider-neutral JSON. The file is a UTF-8 object with one field:

```json
{
  "responses": [
    {
      "response_id": "REAL-001",
      "participant_id": "P-001",
      "identity_namespace": "real:project-import",
      "answers": {
        "Q1_RESPONSE_KEY": "stable-option-value"
      }
    }
  ]
}
```

Each response crosses the existing provider-neutral raw-response contract. Provider item IDs or Forms/Qualtrics-specific structures are not canonicalized here. A later adapter may emit this same interchange without changing the canonical path.

The file must be a controlled regular file inside the opened workspace. Its SHA-256 digest, workspace-relative locator, format identifier, and exact Instrument pin form the intake identity. Repeating the same bytes from the same locator against the same Instrument uses the existing immutable Dataset and preserves its first-capture metadata.

## Authority and origin boundaries

- REAL intake always requests `response_origin=real` and `epistemic_status=EMPIRICAL` at the existing normalization boundary.
- `synthetic:*` identities are rejected by that same boundary and remain inspectable as rejected inputs; they cannot enter the valid REAL analysis population.
- Instrument id/version/digest are resolved against the exact persisted Instrument revision before normalization.
- Branch-derived `not_asked`, declared missing reasons, multi-select values, scales, and free text are preserved by the existing canonical response path.
- Rejected inputs do not block valid responses from reaching the shared aggregation path.
- Aggregates remain research material. The intake action creates no Finding and performs no authoritative Research State mutation.

## Public actions

`survey_real_intake.capture` accepts `file`, exact Instrument pin fields, and optional existing `analysis_items`. It returns accepted/rejected counts, validation summary, Dataset and Aggregate references, intake lineage, origin/epistemic status, and an explicit candidate-research-material marker.

`survey_real_intake.show` joins the persisted intake lineage, raw/canonical response records or rejection diagnostics, Dataset, and one exact Aggregate result. If more than one Aggregate result exists for the Dataset, the caller must provide `aggregate_result_id`; inspection never guesses a latest result.

Provider connector ecosystems, invitation delivery, statistical inference, automated free-text coding, and automatic Finding adoption remain out of scope.
