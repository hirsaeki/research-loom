# Publication Skill

Use this Skill only after a Writer manuscript revision and its Research Package/Profile pins are fixed. Publication formats and checks the supplied manuscript; it does not change Research State or invent missing formal policy.

## Public workflow

1. Build a Publication preview from the selected Writer composition/revision through the public application operation.
2. Read the selected Publication Profile resources delivered in the Research Package. For MISCO these are `PUBLICATION_RULES`, `PUBLICATION_SOURCE_DOCUMENTS`, `PUBLICATION_FORMAL_SPEC`, and `PUBLICATION_URL_DISPLAY`; do not read the legacy `research-profile/` tree or external originals at runtime.
3. Use the selected Profile resources as authority for pinned formal layout and URL display. Supply runtime inputs only for genuinely project/material/review-specific values with authoritative provenance. Never infer research-group type, permission state, or editorial approval from examples or historical papers.
4. Inspect the preview/build receipt. A generated DOCX is only a preview until machine checks, required editorial QA, rendered-page review, and the bound human release decision are complete.
5. If a release request is allowed, inspect the exact rendered bytes named by that request before approving. Release approval applies only to that exact preview/output binding.

## MISCO formal-input boundary

`misco.publication@1.3.0` already pins:

- `formal_spec_profile` — current MISCO formal specification values and source/approval pin;
- `url_display_profile` — the Human-approved rule to display long URLs in full in references.

Application-specific inputs may still require:

- `research_group_type` — only when the outer formal structure branches on it;
- `permissions` — only for affected non-public/interview/internal material;
- `editorial_review` — explicit Human/Host review of the approved Publication editorial rules.

When a required conditional application input is missing, keep the affected check visibly unresolved and block only the operation that needs it. Do not substitute built-in renderer defaults or inferred permissions/approval for MISCO conformance.

## Authority and preservation

- Preserve manuscript meaning, numbers, citations, qualifiers, limitations, and Research Package bindings.
- A Publication preview, editorial review, or release decision is not Evidence and does not modify Research State.
- Do not turn working exhibits into approved research findings.
- Keep original source locators/provenance even when a reader-facing URL display profile changes visible formatting.
- Synthetic examples, Layer B provenance, and Layer C review-support material are not runtime Publication rules.

## Figures requested during preview

When a missing figure, replacement or removal is requested, preserve this preview and return through the existing Research Exhibit/Package/Writer path in `../../docs/operations/late-visual-needs.md`. Resolve the exact build internally; ask the human about research meaning, not Package/Exhibit IDs. Do not fill research gaps during layout. Build a new preview only from the resulting bound Writer revision, and inspect its actual visual pages. Missing assets, source metadata or explanation review stay unresolved and cannot become a release-ready text fallback.

## QA

Machine checks cover exact pins, native DOCX structure, cross-references, retained image bytes, citation/exhibit resolution, supported formal inputs, and selected deterministic formatting. Human/Host review covers editorial/semantic presentation and actual rendered-page quality.

For MISCO, `editorial_review` must contain a `misco-editorial-qa` result. `unevaluated` or `warning` is not release approval. The release request separately requires inspection of every rendered page, including tables, images, captions, reference targets, and layout.

See `references/application-input.md` for the explicit input shape and blocked-preview behavior.
