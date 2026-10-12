# Issue #456 implementation validation

The original eight ZIP members were read, including the Word manual/template,
PowerPoint diagrams and Excel cells. Archive SHA-256:
`c5cc608e7a90499a46ed929b120c4a4e09111de00ebdecc57d8e3d20dd7d1439`.
The versioned coverage ledger records original locators and precedence.

## Microsoft Word host evidence (2026-10-13 JST)

The production renderer generated synthetic Japanese G/M reports with two
chapters, several sections, all seven heading levels, paragraphs, two tables,
two figures, full bibliographies, native notes on two body pages, appendices,
activities and roster. Word 16.0 updated fields and exported read-only with
`scripts/render_publication_word.ps1`. Source DOCX hashes stayed unchanged.

| Group | Source DOCX SHA-256 | Final PDF SHA-256 |
|---|---|---|
| G | `924293f77cd35b903cd3e505487a85066e5cfb9c31ffba584d7c16e3d708b82f` | `f8fedbc04a30198ac3573f154ee63203a2f0c8c7ed37dc0172525341b044f020` |
| M | `f7bc2c80795351c99c229f7f3c9786fc26648fad755cfa0c0fa6e502003e6a7a` | `3f123181496c6bfb745a7e01db516d70af401b5c23b7df67022b7cb6ded449da` |

Both PDFs have 18 A4 pages. Actually drawn text fonts are Century, MS Gothic,
MS Mincho and MS PGothic. Machine inspection returned no problems. Exported
`RL_*` bookmarks agree with the Host's section starts.

Every page of both exact PDFs was rendered and visually inspected, including
blanks. These observations are separate from the machine result:

| Physical pages | Observation in both outputs |
|---|---|
| 1 | Member box, synthetic title/subtitle, actual month and MISCO organization; text fits the cover boxes. |
| 2 | Blank cover reverse, no number. |
| 3–6 | One-page abstract, blank reverse and two divider faces, no footer. |
| 7–9 | Materialized TOC with chapter/section/item indentation and logical pages 1/2/3. G has blank 8 and right-page introduction 9. M has blanks 8/9 and no introduction. |
| 10 | Left-page body opening, logical 1; first table/figure, full sources and native footnote *1 below. |
| 11 | Logical 2; levels 3–7, separate body indentation, section bibliography and next section. Circled/Roman numerals render correctly. |
| 12 | Logical 3; second chapter, restarted exhibit numbers, full sources and another native footnote *1, confirming per-page restart. |
| 13 | Logical 4; section bibliography and completely wrapped long URL. |
| 14–15 | Blank back divider faces with no inherited body footer. |
| 16 | Appendix/activity/roster, independently restarted logical 1 and 12pt appendix headings; names and line breaks fit. |
| 17–18 | Copyright/disclosure notices then blank back-cover reverse, no footer. |

No missing image, cell, caption, source, note, number, visible clipping or
replacement font was observed. Independent OOXML tests verify the original
40×40 grid, margins, fonts/sizes, indentation and cover positions. This short
fixture cannot visually demonstrate a full 40-character × 40-line page.

These fixtures are not approved research or submission-ready reports. Their
four-page body falls outside 50–60 page guidance; chapter 2 starts on a left
page instead of the recommended right page. Production final QA must retain
reasoned `should` deviations, not full-conformance PASS. Editorial meaning,
actual membership, permissions, PPT/printing/transmission remain specific
Human/operator checks. No real project was advanced, activated, approved,
released or submitted by this validation.

## Reproduction

From the repository, choose a new empty scratch directory:

```powershell
uv run --frozen python scripts/verify_misco_word_fixture.py <scratch>
pwsh.exe -NoProfile -File scripts/render_publication_word.ps1 -SourceDocx <scratch>/G.docx -OutputPdf <scratch>/G.pdf -ReceiptPath <scratch>/G-host.json
pwsh.exe -NoProfile -File scripts/render_publication_word.ps1 -SourceDocx <scratch>/M.docx -OutputPdf <scratch>/M.pdf -ReceiptPath <scratch>/M-host.json
uv run --frozen python scripts/verify_misco_word_fixture.py <scratch> --inspect
```

Word PDF metadata may change regenerated hashes. Rebind to actual bytes and
inspect every page again. The Host helper refuses existing outputs.

## Regression evidence

29 Issue #456 tests and 312 contract tests passed. Existing publication (92),
Profile advancement (22), Research Package (30) and source bibliography (4)
tests also passed during implementation. Current-head CI/Kody are the final
integration review boundary.

Single-clause ablations cover font, size, indentation, grid type, paragraph
role, TOC indent, page/note restart and PDF bookmark/range binding. Public
tests cover unknown/saved/restarted/stale/conflicting G/M metadata, required
N/A rejection, bibliography exceptions, numbering/source order, exact PDF
binding, failed PDF blocking and immutable approval retry. Mocked PDF PASS
tests cover persistence only; actual blank PDFs fail the real inspector.
