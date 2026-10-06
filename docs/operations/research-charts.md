# Bounded research charts

Issue #405 uses the existing Evidence qualification authority and Exhibit registry.
There is no chart database, new Research Object, analysis engine, or extra runtime
dependency. The first input is a **verified Evidence** selected in an exact Research
Package. Unverified Evidence and an ordinary saved table are not approved data.

The Evidence's already-qualified `excerpt` must contain an explicit JSON object:

```json
{
  "columns": ["city", "cases"],
  "rows": [["東京", 30], ["大阪", 20], ["名古屋", 50]],
  "units": {"city": null, "cases": "件"},
  "denominator": null,
  "period": "2026"
}
```

Establishing or revising this excerpt belongs to ordinary Research and its existing
Evidence qualification authority. For current unverified Evidence, the public
`research.evidence.qualify` action creates one exact, candidate-only verification
revision. Its payload pins `evidence_id`, current `expected_revision` and
`expected_digest`, gives the qualification `rationale`, and may supply the exact
`excerpt` being reviewed. The operation copies source, locator, statement, capture
binding, Evidence kind/mode and limitations unchanged. It never commits the revision:
use the existing `state.apply_candidate` -> Confirmation -> Human Decision path, whose
Core authority validation derives `evidence_qualification / verify`. A verified exact
retry is a no-op; changing already-verified content is rejected.

The chart operation does not extract numbers from prose or approve an extraction.
A source's original/capture/locator and supporting Evidence remain in the Package's
existing reference closure. For charts, the Human review must cover the exact
structured quantitative excerpt; the later chart validator checks its bounded shape
and exact values but does not replace that research judgment.

The `exhibit chart` CLI or `capture_chart_exhibit` Facade accepts an existing
`package_id`, `chart_spec`, optional `generator_identity` and `generator_version`.
The spec has exactly these fields:

- `schema`: `research-chart/v1`;
- `chart_type`: `bar`, `line`, or `scatter`;
- `input_evidence_id` and the existing canonical `input_digest`;
- `x_column` and `y_column`: distinct input columns, one series in v1;
- `row_order`: a complete permutation of the input row indices;
- `title`, `caption`, `units`, `denominator`, `period`.

Every value comes directly from the bound verified excerpt. There is no literal
value override, row subset, aggregation, expression, computed ratio, invented
category, or added series. Metadata must match the input exactly. Bar categories
must be unique literal strings. Line/scatter x and all y values must be finite
numbers; line order must be explicitly increasing. v1 is bounded to 128 points,
eight columns, and absolute numeric values at most 1e12.

Operator- and model-proposed specs use the same validator. Generator identity is
provenance; it never grants authority. Current Research Evidence must still match
the selected Package Evidence. Final Exhibit persistence uses the existing State
HEAD guard, and raw `exhibit capture` cannot bypass chart/spec/output validation.

## Output and immutable provenance

The reference/fallback renderer `research-chart-png/1` emits a deterministic 800×480 RGB PNG using the Python
standard library. Its numerical axes use bounded tick formatting; exact values
remain in the required native legend. Bar x labels are row ordinals, explicitly
mapped to original Unicode category labels in that legend. Line/scatter legends
also retain exact x/y values. The Publication consumer must display the legend
and the original unit/period/denominator metadata; it must not present anonymous
ordinals as original research categories. No Unicode label is silently replaced.

The new immutable graph Exhibit retains the exact spec, generation Package
identity/digest, spec proposer/instruction, renderer identity, exact PNG bytes and
digest, and category/value legend. Existing JSON-content and Package aggregate
limits apply. Package rebuild emits the PNG as a separately pinned retained
attachment in `generated_visual`, retaining the structured Exhibit as well.

For the reference path, build and consumer validation independently check the input/spec and deterministic
output, including its legend. A corrupt image with a recomputed digest still cannot
be passed off as the chart of the original data. An implementation change needs
a new renderer generation and new captured output; it must not overwrite history.
Renderer failure is an error and leaves no successful replacement Exhibit.

Capture additionally loads the actual immutable generation Package and checks
its exact digest and selected Evidence. Package rebuild repeats that check and
retains the exact original Package **document** as a pinned JSON attachment (one
copy per generation Package, within existing attachment bounds). Exported consumer
verification rechecks its document digest and selected research against the visual
semantic refs. This is retained generation-context metadata, not a second store or
a promise to render the old Package without its assets. An invented Package binding
cannot be accepted through raw Exhibit capture or a later Package build.

Publication integration, formal captions/numbering/rights and visual QA are #408.
Chart generation is neither manuscript nor release approval. The generation
operation leaves Research State unchanged and does not rebuild existing Packages.
Use the existing Package build/revision path for downstream use (#407).

## Validation

`test_issue405_research_charts.py` checks real deterministic PNGs for all three
types, equivalent operator/model specs, modified data/digest/unit/category/period,
invented values, unsupported aggregation, nonfinite values, output tampering,
legend tampering, unverified Evidence, and renderer failure with provenance intact.
Its injected package read is explicitly unit-level evidence, not Host/live UAT.
The full Package/Writer/Publication round trip and fresh-host acceptance remain
separate #408/#409 gates. Local syntax/diff checks are available; dependency-complete
runtime execution runs in the existing CI shards.

## Host-rendered quantitative charts (#430)

Host/native/Data/Python and other available renderers may produce the PNG. The
reference renderer remains unchanged for CI, exact replay and fallback. Do not
ask the researcher to select tooling unless their request requires a specific
method or reproducibility guarantee.

The same `exhibit chart` JSON operation accepts `package_id`, the unchanged
`research-chart/v1` `chart_spec`, a `renderer` containing bounded non-empty
`identity`, `version` (`not exposed` where necessary), and `instruction`, plus
`output_base64` with the exact bounded PNG. Do not mix this with the reference
path's proposer fields. Capture reuses the exact current Evidence/spec validator
and retains a `research-generated-chart/v2` candidate with the spec digest,
renderer/instruction provenance, generation Package, exact PNG digest and the
machine-derived legend. It validates PNG encoding/digest, not pixel semantics.
Raw capture and package/consumer validation enforce the same constraints.

The existing `exhibit review-visual` operation records a separate immutable
`research-visual-review/v1` note for the exact candidate. Host charts additionally
require `chart_checks` with `axes`, `series`, `ordering`, and `major_values`, each
`pass` or `fail`. A Host/Human must inspect the exact PNG against the validated
data/spec; renderer self-report or a capture receipt is insufficient. Use
`existing_meaning_only` only when all checks pass and no meaning is added;
`nonconforming` for visual mismatch; or `research_required` for new research
meaning. Retain an explicit reviewer and inspection rationale.

Select candidate and review in the rebuilt Package. Missing review yields
`VISUAL_REVIEW_REQUIRED`, visual FAIL yields `VISUAL_CONFORMANCE_FAILED`, and new
meaning yields `VISUAL_RESEARCH_REQUIRED`; these are unavailable figures, never
healthy Publication images. A later PASS cannot erase conflicting FAIL: revise
the candidate and review its new exact bytes. Regeneration preserves history.
Normal numbering/caption/source/rights/QA and the exact native legend/data note
apply independently of renderer. Capture/review grants no Research/release approval.

`test_issue430_host_charts.py` provides synthetic backend controls for reference,
reviewed Host output, unreviewed output and FAIL output, including tampering,
immutable regeneration and exact DOCX embedding. These do not satisfy live UAT.
