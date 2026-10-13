# Detached Writer input

The exported `writer-input.json` is the complete runtime handoff for the selected sections. Each entry embeds its verified `section_input` including source pins, resolved research bodies, Profile constraints, and (when selected) `writer_profile` resources.

A host must not depend on the current repository checkout or legacy Profile tree for rule bodies. If required Profile content is missing from the detached input, report the gap; do not silently recover it from another source.

`writer_profile.review_plan` is deterministic routing metadata. It maps every delivered runtime rule ID to exactly one review group. The Writer's natural-language/editorial judgment remains a Host/Human check; backend validation only proves that the declared review covers the exact delivered IDs and that declared violations are connected to Writing Feedback.

For `WRITER_RULES.review_contract_version: 1.0.0`, use each item's `review`
metadata and `additional_sources` alongside its original source. These adopted
design clarifications are not original Clean Source Pack clauses. Report
`rule_results` for every group ID: `rule_id`, `outcome`, `applicability`, `method`
and a content-based `rationale`. Structural reference presence cannot establish
semantic conformance. Missing material or inspection stays `unevaluated`.
N/A needs an actual applicability review; group N/A requires all rules N/A.
Document-scoped rules stay unevaluated in a section review unless genuinely
non-applicable. This protocol cannot certify full-document completion.

Honor explicitly selected `section_contract.citation_requirements`; the
allowed Source inventory is not a usage checklist. Editorial recommendations
produce improvement observations and do not alone prevent draft storage or
unrelated research. Unknown KPI, budget, deadline or research judgments stay
unknown and return through existing Feedback.

`WRITER_SOURCE_DOCUMENTS` may carry a complete approved source document because several migrated rules share that document. Apply only the document's declared `writer_rule_ids`, which must match IDs in `WRITER_RULES` / `review_plan`. Text outside that Writer-ID mapping is source context and does not become an additional Writer requirement.
