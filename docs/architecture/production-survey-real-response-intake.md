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

## Incremental and cumulative exports (Issue #251)

The existing Dataset is also the immutable **acquisition batch**; there is no
second response store or parallel aggregation pipeline. The batch retains its
file locator, exact file digest, Instrument pins, first capture time and response
references. Its Aggregate refers to that exact Dataset ID/digest, not to an
implicit union of every export ever received.

A different filename, or different bytes at the same filename, creates a new
batch. Unchanged answers reuse their existing canonical records. Consequently,
`R1/R2` followed by a cumulative `R1/R2/R3` export produces populations of **2
and 3**, not 2 and 5. Do not sum overlapping batch populations. An export that
contains only R3 describes only that batch; automatic delta-export union is not
part of this interface.

New REAL file-intake responses bind the interchange format and record-level
producer provenance, not the enclosing file locator/digest. Reuse still requires
matching project, namespace/response ID, exact Instrument, origin/epistemic
status, canonical answers, validation result, raw input and producer facts.
Changing an answer or its Instrument under an existing response identity remains
`SURVEY_RESPONSE_DUPLICATE_RECORD`; use an explicitly new identity for revised
source records rather than overwriting historical responses.

Legacy responses carrying file-level provenance are also reusable after these
checks. Their original documents, ingestion time, raw inputs, provenance and
content/registry digests are retained unchanged; new batches refer to those
original digests. Repeated IDs within a single batch remain visible rejected
inputs, and malformed or origin-invalid records are not silently dropped to make
an analysis succeed.

### Recovery and concurrency

Response inserts and the Dataset/entry records commit in one existing SQLite
transaction. An interrupted batch write rolls back new answers without altering
older responses. A structurally malformed record with an already-persisted exact
project/namespace/response ID is also an immutable conflict, not a way to remove
that answer from a new batch's analysis population. The check runs under the
existing write transaction, so a valid response committed after normalization is
not missed. New/unidentifiable malformed records remain visible rejections, as do
later duplicates when the batch still retains its canonical first response.
Previously committed rejection batches remain immutable and can still be replayed;
a later valid answer does not retroactively rewrite their population.

After Dataset commit but before analysis completion, repeat the
same `survey_real_intake.capture` request: it verifies/reuses the batch and resumes
the existing shared analysis path. Close/reopen does not generate new historical
capture metadata.

Concurrent first captures use stable response content digests and the existing
SQLite write boundary. A new registry is published only after its complete schema
has committed, using a no-overwrite hard link from a same-directory staging file.
Another initializer's registry is never replaced. Existing/missing registered
stores retain the optional-child health rules; schema writes do not silently
recreate or repair a damaged registered database.

Acceptance tests cover renamed and cumulative exports, changed-answer/producer
conflicts, Instrument/origin separation, legacy records, rejected duplicates,
post-Dataset analysis interruption, transaction rollback/reopen, concurrent alias
and exact batches, and initial schema publication failure. The Windows CI job
runs the same acceptance suite; mocked interruptions are not a claim of physical
power-loss coverage.
