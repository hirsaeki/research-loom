# MISCO Publication Profile application

Issue #335 connects the production Publication Profile to the existing preview/release path without creating a second renderer or authority model.

## Current production boundary

`misco.publication@1.1.0` delivers two verified resources through the normal resolver/Research Package path:

- `PUBLICATION_RULES` — the #331 Publication migration inventory;
- `PUBLICATION_SOURCE_DOCUMENTS` — the six Human-approved Layer A source documents needed to interpret those rules without the legacy tree.

The Profile deliberately does not contain page/font/margin/indent values, bibliography placement, a URL display convention, research-group type, or permission decisions. #331 proved those concrete inputs are not present in the approved source pack and must not be invented.

`core/packages/writer-publication/publication-application.schema.json` is the explicit carrier for those externally supplied values. The input records source/approval pins; it does not make an arbitrary value authoritative.

## Preview versus conformance

The existing deterministic renderer remains available when formal inputs are missing so a human can inspect a diagnostic preview. In that case:

- built-in renderer defaults are used only to make the preview viewable;
- `PUBLICATION_FORMAL_INPUT_MISSING` is recorded;
- `formal_specification` is `failed`;
- the build is not release-eligible and `release-request` fails closed.

When an explicit formal-spec profile is supplied, supported page size, margins, fonts, sizes, and first-line indentation are applied to the actual DOCX and independently verified. The current renderer supports a reference list at the end of the document; a different formal-spec value is reported as `PUBLICATION_FORMAL_VALUE_UNSUPPORTED` rather than silently overridden.

Reader-facing URLs keep their underlying canonical locator. A supplied approved URL display profile may change only the visible bibliography rendering. When a MISCO source has a reader-facing URL and no such profile is supplied, the preview is diagnostic and release remains blocked.

## Applied rules and QA

Already machine-representable Publication behavior continues in the existing renderer: citation/source resolution, native tables/images, exact retained image bytes, cross-references, figure/table numbering, bibliography generation, and immutable pins. Issue #335 additionally aligns native DOCX ordering with the approved rule that table titles are above tables and figure titles are below figures.

Editorial conformance remains Host/Human work. A MISCO application input must contain a `misco-editorial-qa` review result. `unevaluated`/`warning` remains visible and cannot pass the MISCO release check. Separately, the bound release decision still requires inspection of every rendered page; binary generation is not visual approval.

The build receipt stores the Publication Profile pin, delivered rule/source-resource pins, explicit formal inputs, missing-input diagnostics, editorial-review result, and a digest of that Publication policy bundle. Release requests and release manifests bind the same policy digest to the exact output bytes.

## Authority and liveness

Publication never mutates Research State. Preview/render success does not approve the manuscript, formal conformance, or release. Missing Publication-only inputs do not stop Research or Writer work; they block only the formal/release operation that needs them.

Existing atomic release/recovery semantics remain unchanged. Same exact build/request may be verified/reused; different manuscript/profile/formal-input bytes produce a different build identity rather than rewriting an old result.

## Ablation and current blocker

Acceptance holds the same manuscript revision fixed and compares a preview with no formal inputs against one with explicitly supplied synthetic formal inputs. Only Publication diagnostics/build identity/formal output change; the source manuscript digest remains unchanged.

The synthetic formal values used by tests prove wiring and renderer behavior only. The repository still does **not** contain the current MISCO formal specification original or the human-approved long-URL display profile identified by #331. Therefore #335 cannot be treated as production-conformance complete until those external inputs are supplied and the resulting output is reviewed. The implementation intentionally preserves that blocker instead of creating defaults.

## Visual smoke check

A representative diagnostic Publication build was rendered with explicitly synthetic formal inputs and then converted from DOCX to PDF and page PNG for manual inspection. Build `PUB-d4acb0f5908165ad8d0988bb` produced one readable page with no observed clipping, overlap, or mojibake; the table caption appeared above the table, the figure-caption rule remained below figures, the References section and citation marker were present, and the synthetic URL display template was visible. This check validates the renderer/preview path only. Because the formal inputs were `SYNTHETIC_TEST_ONLY`, it is not evidence of MISCO formal conformance.
