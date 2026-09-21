# Native Publication exhibits (renderer 0.2)

Publication converts selected, pinned Writer exhibits into native DOCX objects.
It does not infer a chart, recalculate cells, retrieve a URL, or manufacture a
missing image. Existing source, capture, original/derived artifact, locator,
page/region and digest bindings remain part of the immutable build.

## Supported representations

- `table` / `matrix`: a standalone Markdown pipe table with an outer pipe on
  every line and an unaligned `---` separator, or JSON with exactly `columns`
  (string array) and `rows` (array of string arrays). Rows must be rectangular.
  Cells are literal strings; `001.20` remains `001.20`. Markdown cell padding
  and the separator are syntax, not content. Escaped pipes are supported;
  backticks, other backslash escapes, HTML, inline images and explicit column
  alignment require a separately supplied supported representation. This is
  not a general Markdown typesetting engine.
- Images: a retained PNG selected by `visual_target`, either the original
  image or an already retained derived image. The initial renderer supports
  non-interlaced 8-bit RGB/RGBA PNG, at most 1 MiB and four million pixels.
  CRC, dimensions, compression and scanline bounds are checked. Embedded bytes
  are identical to the retained bytes, not re-encoded. Other image types, PDF
  pages, SVG and graph source need an explicit retained PNG conversion with
  provenance; the renderer does not create that conversion.
- A page other than page 1 or a selected region needs a retained derived image.
  The whole original is never silently substituted for a selected crop. The
  original attachment must still verify when the derived image is used.

Tables are limited to 512 rows including the header, eight columns, and 2048
characters per cell. Existing Package/Publication aggregate byte limits also
apply. Tables use repeatable headers and a fixed page-width grid. Image scaling
preserves the aspect ratio and fits within the page; it does not alter pixels.
Caption numbers and `[[exhibit:ID]]`, `[[section:ID]]`, `[[citation:ID]]` references
are materialized, including references in captions and table cells. Exact
visual source notes accompany images. Full trace metadata is retained in
`customXml/item1.xml` inside the DOCX, not only in an external build receipt.

## Preview is not approval

Unsupported exhibits and unavailable visual assets produce visible diagnostic
placeholders. Their `exhibit_resolution` / `render_verification` checks fail and
no new release approval is accepted. An unresolved cross-reference likewise
cannot pass. A structurally openable diagnostic DOCX is not release eligible.

The special preview reader tolerates only unavailable *declared visual
attachments*, after Package schema, digest and reference bindings verify.
Nonvisual text, Package metadata and Writer pin failures are not downgraded.
Normal Package show/export and Writer operations retain their strict validation.
No repair, empty-store creation, adoption or Research State change occurs.

`render_verification=passed` means native tables, cell content, image parts and
relationships, captions, references and embedded provenance were inspected in
the generated archive. **It does not mean layout or visual quality passed.**
`layout_verification=warning` remains visible in the build, and the exact human
release request requires review of every rendered page: clipping, wrapping,
image placement, captions, citation locations and table/page breaks. Approve
only the exact reviewed build. The software cannot prove that a person really
performed this review.

## Recovery and renderer generations

Restore missing assets only from their exact retained bytes. Different content
or a different representation needs a new material/exhibit/Package/Writer
identity, not a substitution under an old digest. Rebuild afterward. A broken
asset produces a diagnostic build identity distinct from its healthy build;
restoring the exact bytes can reuse the original verified healthy build.
Neither diagnostic previews nor prior releases are rewritten.

A renderer version change produces a new build. Fresh approval of an old
renderer build is refused: rebuild with the current renderer and review the new
outputs. Existing decided historical releases retain exact idempotent reuse
and artifact recovery, including after renderer upgrades.

## Acceptance evidence and limits

The acceptance tests exercise the public Package -> Composition -> Writer ->
Publication flow with literal numeric cells, a retained PNG crop, unsupported
exhibits, missing/corrupt images, immutable rebuilds and release gating.
Ablation removes the native table or changes its image relationship/caption:
basic XML checks still accept the archive, while native verification rejects it.

Representative generated pages were rendered and visually inspected separately:
a three-column table with a retained crop, an existing six-column table with
citations, a Japanese literal matrix, and an unavailable-exhibit preview. This
is fixture-level layout evidence, not a guarantee for every possible document
or Word/LibreOffice version. Inspect each actual publication before approval.
