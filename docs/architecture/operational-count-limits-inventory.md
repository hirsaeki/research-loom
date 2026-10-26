# Runtime count and capacity limits inventory

**Reviewed:** 2026-10-20

This inventory covers runtime code and package schemas under `core/` and
`plugins/`. It separates research/domain rules and integrity checks from
operational work budgets and bounded views. Test-only fixture sizes are not
runtime limits.

## Design rule

An operational count or capacity threshold is not a research stopping rule.
Keep all accepted research material and records. A bounded view must expose
whether more items exist and provide a way to reach them. When an operation
cannot safely complete within an actual resource budget, fail that operation
with the concrete budget and a recoverable continuation path; do not report
the research as invalid, saturated, complete, or discarded. See
[Research continuity and operational limits](research-continuity-and-operational-limits.md).

## Count-based hard rejections removed in this change

| Area | Previous runtime ceiling | Current behavior and remaining safeguards |
|---|---:|---|
| Research Package selection and Exhibit provenance | Objects 512, Runs 16, Exhibits 32, Project Inputs 32, Materials 128, Gaps 512, plus 128 unique selected/ancestor Exhibits and 16 source Runs | The item-count checks are removed. Duplicate identifiers, project binding, lineage, provenance, content integrity, and per-item validation remain. Attachments are checked incrementally against a 64 MiB per-operation budget; each item is at most 1 MiB and the serialized Package output at most 128 MiB. An over-budget build fails before publishing a partial Package and identifies splitting the selection across Packages as the recovery path. |
| Research action inputs | Fixed maxima on object/reference lists in question review, argument, recommendation, quality assessment, Project Input, visual need, generated explanation, and paired material continuation payloads | Unsupported list-length rejections are removed. Required/non-empty fields, unique IDs, binding and authority checks, and semantic shapes remain. |
| Writer Composition history writes | 64 composition series, 64 revisions per series, and 256 selection events | Removed from the production history-aware write path under [#177](https://github.com/hirsaeki/research-loom/issues/177). New series/revisions remain allowed; exact selection retries are idempotent, while real changes remain immutable history. The older base service still contains these checks, but the production facade uses `WriterCompositionHistoryService`. |
| Writer input export | 4 MiB per detached section and 16 MiB per round-trip receipt | The receipt shares duplicate material text across sections. The 4/16 MiB checks are replaced by a 64 MiB budget for the files emitted by one export. On overflow, export publishes no destination and reports how to split batches or narrow an oversized section. Later batches accumulate in one manuscript revision series under exact source pins. |
| Resume candidate lookup | First 100 candidate IDs queried in one database `IN` operation; larger lists were rejected | Lookups are split into internal batches of 100 and all unique candidates are checked. |
| Historical material reacquisition | Only the first 100 child Runs were considered for prior-success reuse and next-attempt numbering | Success lookup now keyset-pages newest-first through all child Runs; the next attempt is derived from the persisted maximum attempt number without loading Run history. |
| Profile discovery and resolution | 128 manifest files, 32 resources per Profile, and 128 effective resources | Count checks are removed. Resource sizes remain bounded at 1 MiB each and 8 MiB total for an Effective Profile Set. |
| Chart and Publication tables | 128 chart rows, eight chart columns, 512 table rows, and eight table columns | Row and maximum-column rejections are removed. Charts still require a label and at least one data series, and existing label/cell length and evidence excerpt checks remain. Tables still require non-empty rectangular rows and valid cell values. |
| Publication structures and PDF review | 128 sections; schema ceilings for appendices, structure, footnotes, permissions, and editorial checks; 256 PDF pages, review checks/pages/slides/citations | Count ceilings are removed. Publication application input and rendered output/PDF remain bounded at 16 MiB per operation. Oversized operations report the applicable byte budget and a split-volume recovery path. |
| Virtual Runner inputs | Eight LLM respondent Profiles and 16 prior Virtual Run IDs per request | Both fixed count rejections are removed. The caller's profiles and prior Run IDs are retained. External generation cost can grow with the supplied profile set; `population_size` remains bounded from 1 through 128. The former Profile threshold was not replaced by a calibrated soft warning. |
| Exhibit resume | 31 Exhibit IDs | The fixed ceiling is removed; existing project, question, lineage, and Exhibit integrity checks remain. |
| Profile generation history | First 10,000 matching events, after which history lookup silently returned false | The fixed event-count cutoff is removed. Complete source-to-successor history is read so existing workspaces remain resumable. |

These count checks had no demonstrated calibration to user research needs. The
remaining byte limits are capacity safeguards, not evidence that the chosen
values match measured peak memory or workload. Their values need separate
measurement before being described as calibrated capacity targets.

## Remaining hard operational work budgets

| Limit | Why it remains | Failure and continuation behavior |
|---|---|---|
| Profile dependency search: 10,000 visited states (`plugins/local_application/workspace/profile_resolution_support.py`, `profile_selection.py`) | This bounds combinatorial dependency search rather than the number of retained Profile declarations. | `PROFILE-RESOLUTION-LIMIT-001` reports the observed count and suggests pinning dependency versions, narrowing ranges, or reducing the candidate set. It writes no Effective Profile Set. This is an operation-level search failure, not a conclusion about research validity. The threshold has not been benchmark-calibrated. |
| Paired new-material continuation: 2–16 unique reacquisition Runs per group (`plugins/local_application/material/new_material_group_continuation_service.py`) | One operation holds target locks and builds one traceable continuation group from the selected reacquisition Runs. | `APPLICATION-NEW-MATERIAL-CONTINUATION-BINDING-001` reports the group range and tells the caller to split remaining Runs into additional groups. Each group remains separately traceable and subject to the same provenance and review requirements. The exact upper value has not been load-calibrated. |
| Desktop Research per-Run capture/search budgets (`plugins/desktop_research/conversation.py`, `result_validation.py`, `plugins/local_application/material/`) | The default Context extension permits 20 source captures, 50 search-trace entries, and 40 capture artifacts (two per capture). A project policy may pin different values to a Run. These budgets bound work and artifacts accepted for that Run. | Capture/storage and result-submission checks reject work beyond the Run's pinned budget. The caller must continue through another authorized Run with an appropriate budget; a rejected submission does not establish that research is complete. The defaults are contract values, not measurements shown to be calibrated by this inventory. |

These limits are local work budgets. They do not imply that a research
question is complete. Correlation/idempotency lookup for continuation now
reads all matching attempts rather than stopping after a fixed number.
Historical material reacquisition likewise pages through all child Runs when
checking for a verified prior result; its operation page size of 100 does not
cap total history or attempt numbering.

Writer composition lifetime write ceilings were removed under
[#177](https://github.com/hirsaeki/research-loom/issues/177). The production
history-aware service lets history continue growing while retaining bounded
list/history reads. Per-request section/reference limits and byte bounds remain
by design; they are not lifetime history ceilings.

## Bounded views and pagination

These limits size one response or page; they do not reject captured material or
bound lifetime storage.

| View | Page or response bound | Remainder access |
|---|---:|---|
| Research Exhibits | 100, caller may request 1–100 | `truncated` and an opaque `next_cursor`; `exhibit list --cursor ...` continues the same project/question-filtered ordering. |
| Research Packages | 100 | `next_cursor` pagination. |
| Project Inputs and External Materials | 100 | `next_cursor` pagination. |
| Survey free-text aggregate listing | 1–100 rows per result page | `truncated`, `offset`, and `next_offset`; run another analysis page against the same retained Dataset. |
| Survey response Dataset inspection | 1–100 entries per response | `pagination.offset`, `pagination.has_more`, and the caller-supplied `offset` retrieve later entries from the same Dataset. |
| Survey per-analysis provenance question IDs | One for a single-question analysis, two for a cross-tab | This records the question or pair used by an analysis item. It does not limit the number of analysis items in the overall result. |
| Survey free-text rows | At most 100 rows in a serialized result page | The aggregate result retains the total non-empty count; use `next_offset` to retrieve later rows. |
| Research resume and question-review snapshots | Defaults: 100 candidates, decisions, confirmations, and pending Runs; 50 attention maps; 20 recent Runs | Responses mark truncated categories. Resume limits cannot exceed these defaults, and not every category has a cursor; dedicated list/show surfaces are needed to inspect omitted records. This is a read-context boundary, not a write or research-state rejection. |
| Saved synthesis candidates embedded in resume | 20 items | The projection includes `truncated` and `next_cursor`; continue from the cursor with the synthesis-candidate listing surface. |
| Status and Run inspection projections | Up to 100 entries per projected category | Responses mark categories as truncated and stored records remain intact. The facades do not expose cursors for every category, so discovering records beyond the first page remains a read-access usability gap, not a write/processing rejection. |
| Writer Composition history views | 64 listed series per page; 256 recent selection events per history response | Composition listing returns a cursor and `truncated`; selection history reports `history_total` and `truncated`. Exact historical versions remain addressable by identity. Legacy recovery without a series index inspects at most 64 version files and reports an integrity error above that; this applies only to an ambiguous legacy layout, not current writes. |

## Other numeric boundaries that are not research stopping rules

- Minimum cardinalities, unique identifiers, rectangular tables, chart label
  plus series shape, and required provenance fields define valid domain or
  integrity structures. They are not interchangeable with capacity budgets.
- Writer's per-request document contracts retain schema count bounds: up to 64
  sections, 64 citation/exhibit bindings per section, 32 Profile-review rows,
  128 feedback/follow-up rows, and 256 rule results. These bound one composition
  or round-trip payload, not lifetime history. Their values are not shown here
  to be measured workload limits; #177 deliberately left these per-object
  contracts outside its lifetime-history change.
- `maxItems: 0` in schemas explicitly disallows an unsupported optional field;
  it is not a maximum on a supported research collection.
- Workspace initialization inspects at most 16 directory entries before
  deciding whether a staging directory is known and small enough for the
  narrowly defined initialization recovery. If the directory is larger or
  contains unknown entries, it preserves it and asks for a safe recovery path.
  This is a data-preservation guard, not a cap on research records.
- Raster images are bounded by a 4 Mi-pixel decoder limit; Research Exhibit
  content is limited to 1 MiB per Exhibit. These protect image decoding and
  single-item storage, not the number of research items.
- Research Package attachments are limited to 64 MiB per build and exported
  package content to 128 MiB. Publication application input, PDF input/review,
  and rendered output are limited to 16 MiB. Profile resource files are limited
  to 1 MiB each and an Effective Profile Set to 8 MiB. These capacity numbers
  are not empirically calibrated by this inventory.
- Existing text-length, identifier-length, and nested-object-depth checks
  protect parser and schema behavior. A length bound must not be described as
  an evidence count or a research-validity rule.

## Review guidance

When adding a limit, state whether it is a domain/integrity invariant, a
per-operation work budget, a per-response page size, or a byte/pixel capacity.
For operational limits, record the protected resource, measured or unmeasured
rationale, exact user-facing error/warning, and continuation mechanism. Prefer
warnings when work can safely continue. When a hard operation failure is
unavoidable, retain every input and existing record, expose what did not
complete, and make the next action recoverable.
