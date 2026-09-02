# Production shared Survey aggregation

PR43 adds the production descriptive-analysis boundary for canonical Survey response Datasets. It deliberately does not add a Virtual-only analytics path and it does not create a second response normalization path.

```text
                   structural Virtual
                          │
                  future LLM Virtual
                          │
                   future REAL intake
                          │
                          ▼
                SurveyResponseDataset
                          │
                          ▼
                 SurveyAnalysisSpec
                          │
                          ▼
              Shared Aggregation Service
                          │
          ┌───────────────┼────────────────┐
          ▼               ▼                ▼
      Frequency        Cross-tabs      Missingness
          │               │                │
          └───────────────┼────────────────┘
                          ▼
               SurveyAggregateResult
                          │
                          ▼
                   Human inspection
```

The canonical `SurveyResponseDataset` introduced by PR42 is the only analysis input. Raw structural Virtual output, future LLM output, Forms exports, CSV rows, or any other producer-specific representation must cross the PR42 normalization/validation boundary before PR43 can inspect it.

## Authority and pins

A `SurveyAnalysisSpec` is immutable and pins:

- one `dataset_id` and exact Dataset content digest;
- one Instrument ID, revision, and exact Instrument digest inherited from that Dataset;
- an explicit ordered set of descriptive analysis items.

A `SurveyAggregateResult` pins the Dataset, Instrument, and AnalysisSpec again. A stale or mismatched pin fails closed. Dataset or Instrument revisions therefore produce a different specification/result identity rather than rewriting an existing result.

Instrument semantics remain authoritative. Aggregation never guesses that a string is categorical or a number is a scale. Question type, stable choice values, branching, response variables, and missing-value semantics come from the exact canonical Instrument revision.

## Minimal analysis surface

The first production slice supports only:

- `frequency` for single-choice and multiple-choice questions;
- `missingness` for every question type;
- `scale_summary` as a value distribution and count;
- `cross_tab` for explicitly requested single-choice × single-choice pairs;
- `free_text_listing` with an explicit maximum row count.

The default specification is a projection from Instrument semantics. It adds missingness for every question, frequency for categorical questions, scale distribution for scales, and a bounded free-text listing for free text. Numeric questions receive missingness only. Default generation does not mutate the Instrument and does not generate all possible cross-tabs.

Regression, factor analysis, clustering, significance tests, confidence intervals for population estimates, weighting, imputation, causal analysis, psychometrics, NLP/topic modeling, chart grammar, dashboards, and a general-purpose statistics DSL remain out of scope.

## Denominator semantics

Percentages never have an implicit denominator. Frequency and scale items declare one of:

- `all_responses`: all accepted canonical responses in the Dataset;
- `asked_responses`: accepted responses except those whose canonical state is `not_asked`;
- `valid_responses`: accepted responses whose canonical state is `answered`.

Every result exposes all three denominator counts plus the selected rule/count. Branch-skipped respondents therefore do not become missing answers and do not enter `asked_responses` or `valid_responses`.

Missingness is first-class and preserves separate counts for:

```text
answered
missing
unknown
not_applicable
prefer_not_to_answer
not_asked
```

Rejected Dataset entries are not part of any valid denominator. Result-level exclusion metadata preserves rejected counts and validation issue-code counts.

For multiple-choice questions, option counts are selection counts while the denominator remains respondents under the declared denominator rule. Percentages may therefore sum above 100%; the result states that semantic explicitly.

For two-way cross-tabs, the initial implementation uses only valid paired single-choice answers. It exposes the `valid_pairs` denominator, cell counts, row denominators/percentages, and column denominators/percentages. Sparse cells remain visible, including zero counts. Privacy/disclosure suppression is not introduced in this PR.

## Epistemic firewall

The shared aggregation formula does not branch on response origin. Synthetic and future REAL Datasets with the same canonical answer semantics are calculated the same way.

The epistemic meaning is not the same:

```text
same aggregation engine
!= same epistemic meaning
```

A synthetic Dataset produces a `SYNTHETIC_TEST_ONLY` aggregate result and an explicit warning that percentages are configuration-dependent synthetic test output, not population estimates. Aggregation cannot promote synthetic output to empirical status.

Creating an AnalysisSpec or AggregateResult does not:

- verify Evidence;
- adopt a Finding;
- adopt a Recommendation;
- answer an RQ authoritatively;
- mutate the Research Snapshot;
- auto-register a Research Exhibit.

A useful aggregate table may later be captured as a Research Exhibit by an explicit separate operation.

## Persistence and deterministic identity

Analysis specifications live in the optional local `.research-loom/survey-analysis-registry.sqlite3` registry. The registry is not part of authoritative Research State.

`SurveyAnalysisSpec` and `SurveyAggregateResult` use RFC 8785 canonical content digests. Volatile timestamps and generated object IDs are excluded from semantic content digests. IDs are deterministically derived from those content digests, so the same exact pinned analysis produces the same semantic identity. Persisted rows are immutable; an identity cannot be overwritten with different content.

`SurveyAggregateResult` also records `survey_shared_aggregation@0.1.0` as implementation provenance so a future calculation change can coexist with historical results.

## Public application surface

The existing audited `action submit` path exposes:

```text
survey_analysis_spec.capture
survey_analysis_spec.show
survey_aggregate.run
survey_aggregate.show
```

`survey_analysis_spec.capture` accepts only a persisted canonical Dataset ID/digest plus optional explicit analysis items. It has no raw-response field. `survey_aggregate.run` requires exact AnalysisSpec and Dataset IDs/digests again before calculation.

The show surfaces return structured JSON. Free-text rows are bounded by the captured AnalysisSpec (`1..100`, default `25`), and aggregate result items are bounded by the show surface (`1..100` per page), so persisted inspection does not require direct SQLite access.

## Virtual / REAL composition

The production aggregation input remains the canonical PR42 Dataset regardless of producer. Structural Virtual and LLM Virtual therefore share the same PR43 semantics, and future REAL intake must do the same. Synthetic aggregation remains `SYNTHETIC_TEST_ONLY` and is never a population estimate.

The structural production smoke path is:

```text
PR41 STANDARD / STRESS
        ↓
PR42 normalization and validation
        ↓
SurveyResponseDataset
        ↓
default or explicit SurveyAnalysisSpec
        ↓
PR43 shared aggregation
        ↓
SurveyAggregateResult
```

For STRESS output, invalid/rejected responses remain visible in exclusion summaries but cannot enter valid frequencies or cross-tabs. Valid extreme responses remain in the accepted population. Branch-derived `not_asked` remains distinct from missing.

The LLM Virtual Respondent path composes identically after generation:

```text
LLM Virtual Respondent
        ↓
PR42 normalization and validation
        ↓
SurveyResponseDataset
        ↓
existing SurveyAnalysisSpec
        ↓
PR43 shared aggregation
        ↓
SurveyAggregateResult
        ↓
Human inspection
```
