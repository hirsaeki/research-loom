# Detached Writer input

The exported `writer-input.json` is the complete runtime handoff for the selected sections. Each entry embeds its verified `section_input` including source pins, resolved research bodies, Profile constraints, and (when selected) `writer_profile` resources.

For a document-scoped review, use the public `writer-round-trip prepare-review`
operation (or `prepare_writer_document_review`) to materialize the exact response
plus its unchanged base sections. Read the returned target and necessary fixed
input materials before declaring results. Return the optional `document_review`
record with that exact `target_digest`, coverage, reviewed section IDs, reviewer
identity/method/time and document-scoped Profile groups. Keep semantic and
editorial judgments separate in their rule results and existing Writing Feedback.
Do not compute a target hash by hand or put the record into provenance.

Partial review cannot establish document conformance or document N/A. Omitted
or unevaluated document review does not block draft storage. A partial edit does
not inherit the old document review; review the newly assembled target only when
claiming it has been reviewed. Full coverage means the exported scope, not an
unread remainder of the paper. A target match proves identity, not text quality,
independent review or Human approval.

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
