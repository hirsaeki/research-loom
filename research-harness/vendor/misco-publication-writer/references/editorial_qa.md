# Editorial QA Checklist

Run after drafting/revision/editorial integration. This checks publication behavior, not academic truth.

## Research decision protection

- No new RQ, hypothesis, proposition, classification, model, claim, recommendation, causal conclusion, generalization, success factor, or expected effect was created.
- No support/refutation/revision/judgment-impossible decision was made by the Writer.
- Counts/pillars/categories/stages were not fixed by style.
- Missing evidence was not repaired through prose.

## Observation / interpretation / uncertainty

- Observation precedes approved interpretation.
- Inference/assumption/estimate is visibly qualified.
- Claim strength does not exceed the approved state.
- Approved uncertainty, counterevidence, limits, applicability, minority warnings, and unresolved issues remain visible.
- No new alternative explanation was added.

## Navigation / repetition

- Background reaches the approved problem/purpose instead of stopping at importance.
- Chapter opening/closing uses approved arrival points and next links only.
- Repetition is functionally justified rather than paraphrase churn.
- Primary Exposition Location control prevents repeated re-analysis/scattering of method results; `home_chapter_map` is only a legacy alias.

## Figures / quantitative

- Figure/table has required title/number/source/reading metadata.
- n/denominator/multiple response etc. are visible when applicable.
- Body does not read every cell.
- No new causal/general claim is discovered from numbers.
- Conditional color/grayscale QA is run only when color figures are used.

## Cases / models

- Selection role and permissions are respected.
- Case facts and approved meaning are separated.
- Cross-case comparison axis/result was supplied, not discovered.
- Small-case evidence is not overgeneralized.
- If a case set revised a model, the prose shows the approved change from old assumption to revised model and preserves unresolved conditions.

## Recommendations / final synthesis

- Recommendations existed upstream and are linked to already presented approved analysis.
- Recommendation section does not introduce new major evidence.
- Effects are conditioned and unverified effects remain expectations.
- Summary/body recommendation naming/order correspondence is preserved where the same set is repeated.

## Terminology firewall

- Internal IDs/labels are absent from normal body unless genuinely required in a methods explanation.
- Generic academic schema such as IMRaD, Literature Review, Findings, or Cross-case synthesis was not imposed as MISCO structure.
- Trace IDs, if needed, remain in QA metadata.

## Formal

- Current formal profile is used as source of concrete settings.
- Missing formal metadata was not guessed.
- Permission/anonymization requirements were honored.

## Academic QA handoff

Send evidence–claim entailment, causality, citation support, statistical validity, and generalization validity to `[NEEDS_ACADEMIC_QA]`; do not resolve them here.

## Research Harness interoperability checks (Publication operations, not new Style Rules)

- [ ] Publication Eligibility is `ELIGIBLE`, or backward-compatible approval is unambiguous; `NOT_ELIGIBLE` content is not used.
- [ ] Candidate/provisional research-object status is preserved rather than strengthened.
- [ ] `FINAL_EDITORIAL` defaults to `INTEGRATED`; `STABLE`/`FINAL` appear only with explicit Human authorization.
- [ ] Publication Feedback, when present, is separated from reader-facing prose and is not treated as Research Evidence.
- [ ] `primary_exposition_map` takes precedence over `home_chapter_map`; conflicts are recorded rather than silently merged.
- [ ] Writing-discovered gaps are routed back as Feedback/stop conditions without Writer-created research repair.
