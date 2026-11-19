# Appendix PDF numbering regression and Word revalidation (#621)

## Result

On 2026-11-19 JST, Microsoft Word 16.0 re-exported the two retained synthetic
reports from the local-bibliography trial: repeat and omit-complete-local. Each
PDF has 18 A4 pages, body physical pages 10-13 and appendix physical page 16.
The appendix footer and appendix TOC visibly show `付1`.

Both PDFs pass the production PDF inspector with the appendix prefix derived
through the MISCO dialect from the pinned 1.6.0 formal layout. Checking the same
bytes with the historical numeric-only default reports exactly
`page-number:appendix:16` in both cases. No diagnostic was filtered or waived.

| Variant | Source DOCX SHA-256 | Re-exported Word PDF SHA-256 |
|---|---|---|
| Repeat | `7e5af5e95c25e31b8028e77f18d5d9fd2b86c726ac0dd0b07e2a6e691b6aace1` | `90717138cf90c3b539caf2b806d62da430a726fc15374d2c109e6a357d23ee70` |
| Omit | `8e0fe45b369dac89239054db9ae9b3350264ce56c03a8f4919c9173344ba2ecb` | `581e05eeebee51442191e23cf25a6bb9b4d40ffe9562046d206dc116cd1bbf25` |

Word rendering receipts match the exact source/PDF bytes. Source DOCX hashes
remain unchanged. All 36 re-exported pages were rasterized at 130 dpi and compared
pixel-for-pixel with the previously visually reviewed trial: every page is
identical. The new appendix page, TOC and long-URL footnote page were also reopened
for visual inspection. There is no clipping, overlap or glyph loss in these
checked images. Rendered fonts are Century, MS Gothic, MS Mincho and MS PGothic.

The repeat variant retains four section-reference headings; the omission variant
retains only the final one. Complete inline and footnote sources remain visible;
stale-review, incomplete-scope and explicit-keep sources remain listed. Native
footnotes restart at `*1` on each of physical pages 11, 12 and 13. Thus fixing the
PDF check does not change the generated citation or bibliography layout.

These are synthetic, four-body-page rendering fixtures, not approved research or
submission-ready reports. This exercise creates no research workspace, release,
research adoption or submission. It does not establish all-page-count or content
conformance for an actual long report.

## Regression boundaries

- Omitted `appendix_page_prefix` preserves the numeric-only inspector default.
- The pinned 1.4.0/1.5.0 layouts retain numeric appendix pages. The 1.6.0 layout
  supplies `付` through the dialect; generic code does not branch on MISCO ids.
- Missing, wrong or doubled prefixes, duplicated/skipped ordinals, a zero start,
  leading zeroes and missing appendix footers are rejected.
- Prefix support does not permit prefixes on body pages or page numbers in front
  matter. Alternative generic prefixes use the same exact-match rule.
- Public finalization forwards the selected expectation for both historical and
  1.6.0 builds and still rejects an actually blank synthetic PDF.
- Historical source bytes, Profile resources and finalization receipts are not
  rewritten. Exact retries preserve prior results; a fresh exact-PDF review creates
  a new finalization record.

## Reproduction

Use the isolated fixture workflow in
[formal validation](../operations/misco-formal-validation.md#reproduction).
Add `--publication-version 1.6.0` to both generation and `--inspect`, and pass
`-TocHelperPath scripts/appendix_toc_word_helper.ps1` when rendering with Word.
The default fixture version remains 1.4.0. The selected layout, not observed PDF
text or an inferred project type, determines the expected prefix.

The exact reports above and their local receipts, checker output and image
comparison are retained under the task's isolated scratch directory. Binary PDFs
are not committed; regenerated PDF metadata can change their hashes and requires
inspection against the newly produced bytes.
