# Publication Skill

Use this Skill only after a Writer manuscript revision and its Research Package/Profile pins are fixed. Publication formats and checks the supplied manuscript; it does not change Research State or invent missing formal policy.

## Public workflow

1. Build a Publication preview from the selected Writer composition/revision through the public application operation.
2. Read the selected Publication Profile resources delivered in the Research Package. For MISCO these are `PUBLICATION_RULES` and `PUBLICATION_SOURCE_DOCUMENTS`; do not read the legacy `research-profile/` tree at runtime.
3. Supply only explicit formal inputs that have an authoritative source/approval pin. Never infer page settings, fonts, indentation, bibliography placement, URL display, research-group type, or permission state from examples or historical papers.
4. Inspect the preview/build receipt. A generated DOCX is only a preview until machine checks, required editorial QA, rendered-page review, and the bound human release decision are complete.
5. If a release request is allowed, inspect the exact rendered bytes named by that request before approving. Release approval applies only to that exact preview/output binding.

## MISCO formal-input boundary

`misco.publication` may require:

- `formal_spec_profile` — current MISCO formal specification values and source/approval pin;
- `url_display_profile` — the separately human-approved reader-facing URL display rule;
- `research_group_type` — only when the formal specification branches on it;
- `permissions` — only for affected non-public/interview/internal material;
- `editorial_review` — explicit Human/Host review of the approved Publication editorial rules.

When a required input is missing, keep the preview visibly diagnostic and treat formal conformance as failed. Do not substitute built-in renderer defaults for MISCO conformance. Those defaults exist only so a preview can still be inspected.

## Authority and preservation

- Preserve manuscript meaning, numbers, citations, qualifiers, limitations, and Research Package bindings.
- A Publication preview, editorial review, or release decision is not Evidence and does not modify Research State.
- Do not turn working exhibits into approved research findings.
- Keep original source locators/provenance even when a reader-facing URL display profile changes visible formatting.
- Synthetic examples, Layer B provenance, and Layer C review-support material are not runtime Publication rules.

## QA

Machine checks cover exact pins, native DOCX structure, cross-references, retained image bytes, citation/exhibit resolution, supported formal inputs, and selected deterministic formatting. Human/Host review covers editorial/semantic presentation and actual rendered-page quality.

For MISCO, `editorial_review` must contain a `misco-editorial-qa` result. `unevaluated` or `warning` is not release approval. The release request separately requires inspection of every rendered page, including tables, images, captions, reference targets, and layout.

See `references/application-input.md` for the explicit input shape and blocked-preview behavior.
