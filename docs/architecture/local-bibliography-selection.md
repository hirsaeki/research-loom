# Optional local bibliography selection (#619)

Publication may omit a source from a formal section's reference list when all
registered uses in that scope have sufficient local source displays. Citation
registrations, locators, source objects, Writer revisions and research authority
remain unchanged. This is output selection, not citation deletion or evidence QA.

## Compatibility and responsibility

Without `bibliography`, all existing policies, build keys and output paths remain
unchanged. `bibliography.mode: repeat` retains existing reader output. An explicit
`omit_complete_local` request opts into selection. Historical pinned Profile assets
are not rewritten or upgraded. The Publication dialect provides sufficiency rules;
generic code never branches on an organization id. The initial implementation
supports MISCO formal reports only; unsupported modes/dialects reject this new
input rather than silently ignoring it.

## Input and local displays

Pass the optional top-level `bibliography` object to the public Publication
preview operation, alongside the existing formal-report input:

```json
{
  "mode": "omit_complete_local",
  "keep_sources": ["SRC-ALWAYS-LIST"],
  "displays": [
    {
      "display_id": "note-use-1",
      "section_id": "SEC-EXAMPLE",
      "source_ref": "SRC-EXAMPLE",
      "locator_ref": "p.25",
      "placement": "footnote",
      "marker": "{{source-note-1}}",
      "method": "generated"
    }
  ]
}
```

The example is the value of `bibliography`, not a complete preview request.
Each display binds an existing section/source/locator citation. For a footnote,
the marker must match exactly one existing `formal_report.footnotes` entry in
that section. Its text must already contain the source display. No note is
injected, no Writer text is repaired, and no placeholder is replaced by this
selection feature. Word retains native notes and per-page numbering.

For `placement: inline`, `marker` is the exact displayed source text in the
manuscript. It must occur once in the named section; repeated or overlapping
markers there are ineligible. Native footnote markers must be unique across the
body. `method: generated` requires exact equality with the normal
formal source label (author, title, publisher, year, locator and full web URL).
Existing inline citation tokens need no display declaration: the renderer itself
expands each to full source information and the registered locators.

## Sufficiency and conservative fallback

Automatic sufficiency requires nonblank author, original title, publisher and
publication/update date, plus a nonblank locator. Existing inline tokens show
the complete local locator set; missing locators prevent automatic omission.
For explicit displays, web URLs must occur in full in the displayed text.

`method: reviewed` uses exact-text human/host review instead of approximate
natural-language matching. The reviewer checks source identity, necessary
bibliographic fields, locator, proximity and independence from the reference list.
Source-level bibliography exceptions may satisfy legitimately absent fields
other than title only through this review. A missing locator additionally needs
a meaningful `locator_exception` on the display, such as a whole unpaginated
document being cited. Missing research information is never invented.

An initial preview retains unconfirmed displays and exposes their current
`review_digest` under `build.publication_policy.bibliography_decisions[].displays`.
After checking the exact display, supply its `review`:

```json
{
  "content_digest": "sha256:REPLACE_WITH_THE_CURRENT_PREVIEW_DIGEST",
  "status": "sufficient",
  "reviewer_id": "actual-reviewer",
  "reviewed_at": "2026-11-19T00:00:00Z",
  "rationale": "Record why this exact local display independently identifies the source and cited passage."
}
```

The placeholder is not a valid digest. Copy the actual preview digest only after
performing the review. `insufficient` and `unevaluated` never qualify.

Review binds the complete section (including citation registrations), source
object, display definition, corresponding note, formal structure and formal-spec
settings. Changes invalidate it conservatively; the source returns to the list.
An unrelated section edit does not invalidate this review unless structure or
formal settings also change. A new immutable build records the new result;
earlier builds and review records remain unchanged.

Every declared local display must qualify and every registered locator must be
covered. If any subsection's use is incomplete, the source remains in the parent
formal section's list. Other formal sections are evaluated independently.
`keep_sources` always retains the source. Empty lists omit their heading; retained
items keep their existing citation numbers, without renumbering or pruning input.
Sufficient declared displays replace the redundant section-level fallback source
line only in omission mode, even when the user elects to retain the list entry.
Figure/table sources and notes remain unchanged.

This mechanism verifies declared structured uses, not arbitrary prose. It cannot
discover an undeclared quotation, prove that a nearby sentence is supported, or
interpret an unregistered author-year abbreviation. Register each use and declare
each manual local display. Short references and `ibid.` chains are not resolved
automatically. Final editorial review must catch undeclared or ambiguous uses and
any remaining numbered references that depend on a list entry.

Uncertain sufficiency retains the source and does not create a new approval gate.
Invalid bindings/duplicate display identities are input errors. Existing unresolved
citation, missing bibliography, permission and release checks remain authoritative;
keeping a list entry does not cure them.

## Output and verification

Opted-in build policy retains the supplied configuration and per-subsection/source
decisions, including actual scope omission, reasons, display results and current
review digests. These are included in normal build identity and receipt integrity.
Selection is recomputed from pinned inputs when rendering, never trusted from a
caller-supplied decision. No research-state mutation is performed.

The final PDF review still checks every page, source-display proximity, note
placement and per-page numbering, full URL wrapping/clipping and absence of dangling
list references. Structural sufficiency is not a rendered-layout or rights approval.

Tests cover legacy/repeat output, inline and native footnotes, partial scope
coverage, explicit retention, missing/duplicate anchors, full URLs, missing locator
and source exceptions, review invalidation and the public immutable build/reuse path.
