# MISCO formal Publication (Issue #456)

## Profile 1.6.0: appendix TOC Word tools

`misco.publication@1.6.0` retains the 1.5.0 cover and adds a scoped `AUTO_BODY`
TOC, an `AUTO_APPENDIX` TOC over appendix titles, and a separate `付{ PAGE }`
footer restarted at 1. Both TOCs remain native Word fields derived from styles.
Historical profile output remains unchanged. Appendix content is still supplied
through the existing formal-report input; this does not reinterpret plain text
as new heading styles.

The `PUBLICATION_WORD_TOOLS` resource pins VBA, a PowerShell equivalent and
operator instructions. These bodies travel with the effective resources and
the verified preview policy; no installed checkout is needed to recover their
exact contents. Export them without installation or execution:

```bash
uv run --frozen python scripts/export_publication_word_tools.py --workspace WORKSPACE --build-id PUB-ID --output NEW-DIRECTORY
```

Paste the exported BAS into a standard module to run it manually on the active
document, or pass the exported PowerShell helper to
`scripts/render_publication_word.ps1 -TocHelperPath FILE` for PDF rendering.
The renderer checks its SHA256 against the DOCX metadata before loading it.
No VBA project injection, Normal.dotm installation, docm conversion, or Word
security setting change is performed. BAS uses ASCII and `ChrW` for the prefix.

The helper locates exactly one TOC with `\b AUTO_APPENDIX`, unlocks it, updates
native TOCs, repaginates and refreshes all numeric PAGEREF results before adding
any prefixes. This two-pass order avoids stale page values and later reference
updates erasing earlier prefixes. It adds `付` only to appendix results, removes footer gaps and
relocks the appendix fields before PDF export. Repeated execution must not add
duplicate prefixes. Missing/ambiguous scope or missing PAGEREF results is an
error, not a successful update. Use this workflow after content/page changes;
ordinary Word field updates alone do not maintain the cached prefix. Check the
final PDF after updates, including appendix first/last entries and both footer
and TOC numbering. A cached preview is not a final rendered-layout approval.

## Profile 1.5.0: cover interpretation supplement

`profiles/publication/misco/1.5.0/profile.json` adds a profile-driven cover for
MISCO research-theme reports. Select it through the existing profile
resolve/advance workflow; adding the version does not automatically upgrade
an existing workspace, package, or released document. Historical versions and
commissioned-report covers retain their existing behavior.

The pinned formal resource contains `docx_layout.misco_cover`: separate
`三井情報システム協議会(MISCO)` / `報告書` identification at 24pt, the actual
`formal_report.title` and optional `subtitle` in the 18pt theme block, real
issue month and optional assigned number, annotation-first organization font,
membership-box insets and paragraph spacing. No report number or subtitle is
invented. `created_month` is formatted with full-width digits (Reiwa dates also
show the era year). Long themes still require explicit line/layout review.

The supplement identifies the separately inspected attachment-5 PPT by digest
`aca50a88ea5f616016b5622717fd2af7f33eba43008d1f906f35ab3464302536` and pages
1, 6–9. It does not claim byte identity with the historical archive member or
replace its provenance. The user confirmed the report/theme hierarchy and
annotation-first fonts on 2026-11-04. The original example object's MS PGothic
organization setting does not override the explicit MS Gothic annotation.

Box coordinates are calibrated Word rendering inputs, **not** the page-1 text
position targets. The 70/200/230mm dimension lines refer to the upper text area;
inspect the final native PDF at the correct A4 aspect ratio, including glyph
metrics, centering, margins, spacing, clipping and actual metadata. The
supplement retains the screenshot reference positions separately. The XML
checker detects lost profile settings, but does not establish final PDF
conformance. The existing output-bound cover/typography review remains
required; photo-position exceptions are not applied automatically.

`misco.publication@1.4.0` adds the original ZIP's eight-member clause coverage
without changing historical `1.3.0` pins, research packages or releases. Select
the new manifest through the existing profile resolve/advance workflow. Its
archive digest is
`c5cc608e7a90499a46ed929b120c4a4e09111de00ebdecc57d8e3d20dd7d1439`.
`profiles/publication/misco/1.4.0/resources/publication-coverage.json` records
source, original clause, applicability, force, consumer and verification.
The reproducible Host test and page observations are in
[misco-formal-validation.md](misco-formal-validation.md).

## Project metadata and missing inputs

The project owner supplies `G` or `M`; neither meaning is inferred from a
project name or theme. Missing, null and whitespace are unknown. Formal preview
returns `INPUT-RESEARCH-GROUP-TYPE` and the Host question:
`今回の報告書はG研究会とM研究会のどちらですか？`.

Save the answer through `profile resolve` with
`publication_metadata: {"research_group_type":"G"}` (or M) and
`expected_project_config_digest` equal to the current configuration digest.
Pass the current profile manifests as `profile_manifest_files`; use the emitted
target documents with normal `profile advance`. This versions/digests the
configuration and retains the existing archive, stale guards and recovery.
It does not change the research question or activate attention. Repeating the
same answer is a configuration no-op. Publication rejects conflicting explicit
answers and stale configuration bindings.

## Draft and Word rendering

Use `publication preview --publication-input <JSON>` with
`document_mode: "formal_report"`. `formal_report` supplies the actual title,
month, abstract including proposals, activities, roster and optional appendices.
Its `structure` maps every pinned Writer section once, in order, to levels 1–7.
Each level must have its parent. Footnotes contain a unique literal marker in
the manuscript, `section_id` and actual note text. No sample theme, person or
year is supplied as a production default.

G research-theme reports require an introduction; M research-theme reports
omit it. Commissioned reports use the general manual's organization and require
actual department, committee, chair, assigned report number and introduction.
MISCO's G introduction is the explicit special rule over its general omission.
The abstract limit remains two pages; the original three-page blank example
does not relax it. Body length 50–60 is guidance, appendix length 50 is a limit.

The native DOCX contains the cover, blank reverse, abstract, divider, native TOC,
applicable introduction, numbered body, divider, separately numbered appendix,
copyright/back cover and blank reverse. Headings, Japanese/Latin fonts, body
indentation, native notes, references and captions remain structural inputs.
The draft's formal check stays warning and cannot be released as a final report.
`body_preview` remains available for partial Writer work.

On Windows with Microsoft Word, render a retained draft read-only:

```powershell
pwsh.exe -NoProfile -File scripts/render_publication_word.ps1 -SourceDocx <formal.docx> -OutputPdf <new-final.pdf> -ReceiptPath <new-host-receipt.json>
```

The helper updates TOC and footer fields, pads a preceding section when necessary
for the body's left physical page, exports a PDF and emits source/PDF digests,
Word version and physical section ranges. It never saves over the source DOCX
or overwrites existing outputs. Word's `evenPage` break cannot express both a
physical left page and a restarted logical page 1; final physical parity is
therefore checked in the PDF. This helper does not perform editorial approval.

## Exact PDF QA and release

Place the PDF inside the workspace and call
`publication finalize-pdf --build-id <draft> --json <JSON>`. Input contains
`pdf_path`, `pdf_digest`, `source_docx_digest`, `project_config_digest`,
`host_receipt` from the helper and `review`. Review binds this exact PDF with
`pdf_digest`, `reviewer_id`, ISO review time, clause `checks` and all `pages`.
Each row carries status and a concrete rationale. Use the coverage IDs plus
`misco-editorial-qa`, `final-pdf-all-pages`, `final-pdf-toc`,
`final-pdf-footnotes`, `final-pdf-parity` and `final-pdf-cover`. Pages enumerate
every physical page in order; inspect full-size page images including blanks.

Machine checks include A4, rendered fonts, required text, abstract/appendix
limits, range order, body parity and separate body/appendix numbering without
front/back footers. Human checks cover the actual TOC, note numbering, cover
positions, meaning, terminology, permissions and conditional original clauses.
Required N/A, unknown or duplicate IDs, unevaluated/failed rows and missing pages
cannot pass. A reasoned `should` deviation remains an explicit warning.
The measured body length outside 50–60 pages requires a warning rationale;
a blanket PASS for that measured deviation blocks final QA. Formal-report
mode also requires the coverage Profile, preventing a legacy DOCX-only release.

Finalization stores a new immutable build, leaving the draft intact. A failed
build is inspectable but cannot be released. A passing final PDF is the exact
release output; source manuscript, profile, configuration, policy, PDF bytes,
QA and release decision remain bound. Modified bytes require another review
and approval. Existing request/decision/release recovery remains applicable.

Presentation, printing, color and submission flags select their applicable
checks. Printing requires current operator confirmation; the 2017 184+A+B and
2020 52+A+B examples are not defaults. PowerPoint requires per-slide citations.
Interview/non-public source permissions remain source-specific. Saving or
releasing a PDF records `not_submitted`; sending to a coordinator needs the
separately authorized destination and actual transmission record.

When `presentation_required` is true, `review.presentation_review` records the
exact PPTX `artifact_digest` and `artifact_reference`, actual `software_version`,
`slide_count` and every `slides` row in order. Each row has `slide`, `status`,
`citations_required`, visible `citations` and concrete `rationale`. The named
reviewer verifies the referenced bytes and source placement. A cited slide
without its own citations fails even if the last slide has a reference list;
a source-free slide records why `citations_required` is false. This is an
explicit Host/Human review boundary, not an automated PPT renderer or claim
that the backend parsed the PPTX. The record is retained in the final policy
and approval digest. Report-only runs need no presentation input.

For printing, the applicable clause rationales identify the current operator,
record location, destinations, confirmed copies, assigned number, cover paper,
spine dimensions and schedule. For submission, record the coordinator,
authorized destination, exact PDF digest, transmission authority and external
operation record location; release itself remains `not_submitted`. For color,
identify each affected PDF page, why color is necessary and the grayscale
inspection outcome. These concrete operator records belong in the applicable
coverage check rationales, bound to the exact final PDF, not historical defaults.
