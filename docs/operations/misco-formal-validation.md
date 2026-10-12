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
| G | `a587c8eeac34b192ca5a879ac0f65a0133f3122173c9d72ab016210d95652b05` | `40f52fb5847b90283342255b3ad2b3d2672156748532f0d3169fbacfe031b5f1` |
| M | `ec8a647847d5806816ec99d5886b8f3861c6f83eef86195f4c80fd4ed4dda9c6` | `f2e749964a26267227406a602c098b7c3574c6634f4b44464d01ffb8ba767b63` |

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
replacement font was observed. Independent OOXML tests verify the manual's
40×40 grid, margins, fonts/sizes, indentation and cover positions.

A separate dense Japanese probe (`--grid-probe`) repeats 4000 full-width
MS Mincho glyphs. The historical template pitch of 335 twips reported
40 lines in Word but exported 41 lines on a full page. At 343 twips Word
reported 39 lines. The new profile uses 342 twips, the integer floor of the
13719-twip text height divided by 40: every Word section reports 40 characters
and 40 lines, and physical page 12 of the dense PDF has exactly 40 lines
of 40 characters. That page was visually inspected without clipping.
Dense PDF SHA-256:
`6190479f22821a42a692b8209b6bb3d34a95a4150a6b9aa1eb0cdba6ed1e8e68`.
This documented precedence correction applies only to the new profile;
historical 1.3.0 pins are unchanged.

Actual Word pagination also verified both limit boundaries:

| Probe | Abstract range | Appendix range | Machine result | PDF SHA-256 |
|---|---|---|---|---|
| `--boundary-case limits` | 3–4 (2 pages) | 16–65 (50 pages) | No problems | `8ea595c780294330e50dc3c58df58352a9a8244db77f45213c6d9094b050e184` |
| `--boundary-case over-limit` | 3–5 (3 pages) | 18–68 (51 pages) | `abstract-over-2-pages`, `appendix-over-50-pages` | `740f20353e13ade89101adb068874b595d0d946b37dfabf9b48df94eaaa87cdb` |

These are real exported pages and Host ranges, not mocked page counts.

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

Use `--grid-probe` when generating a separate dense grid fixture. Count the
actual rendered rows/characters as well as checking Word's PageSetup values.
Use `--boundary-case limits` and `--boundary-case over-limit` in separate new
directories to reproduce the actual-pagination limit probes with the same
Word helper and inspector.

Word PDF metadata may change regenerated hashes. Rebind to actual bytes and
inspect every page again. The Host helper refuses existing outputs.

## Regression evidence

30 Issue #456 tests and 312 contract tests passed. Existing publication (92),
Profile advancement (22), Research Package (30) and source bibliography (4)
tests also passed during implementation. Current-head CI/Kody are the final
integration review boundary.

Single-clause ablations cover font, size, indentation, grid type, paragraph
role, TOC indent, page/note restart and PDF bookmark/range binding. Public
tests cover unknown/saved/restarted/stale/conflicting G/M metadata, required
N/A rejection, bibliography exceptions, numbering/source order, exact PDF
binding, failed PDF blocking, per-slide presentation citations, required
body-length deviation rationale and immutable approval retry. Mocked PDF PASS
tests cover persistence only; actual blank PDFs fail the real inspector.
The 2-chapter × 2-section regression includes two figures and two tables per
section, a reused exhibit identity and distinct locators from one source;
rendering leaves all inputs unchanged and preserves the eight image payloads.
