# MISCO Publication Profile application

Issue #335 connects the production Publication Profile to the existing preview/release path without creating a second renderer or authority model.

## Current production boundary

`misco.publication@1.2.0` delivers four verified Publication resources through the normal resolver/Research Package path:

- `PUBLICATION_RULES` — the #331 Publication migration inventory;
- `PUBLICATION_SOURCE_DOCUMENTS` — the six Human-approved Layer A source documents needed to interpret those rules without the legacy tree;
- `PUBLICATION_FORMAL_SPEC` — the current formal-spec application values extracted from the MISCO/業際研 originals supplied on 2026-09-29, with the archive and every source member pinned by SHA-256;
- `PUBLICATION_URL_DISPLAY` — the Human Decision for reader-facing URLs: 長いURLも参考文献には原則全文表示する。

The binary formal-spec originals are not copied into the repository. The Profile resource records the exact source archive/member digests, source locators, approved application values, and the boundary between machine-applied values and Human/Host QA. This preserves provenance without turning external originals into a second runtime dependency.

The pinned formal values include the supplied A4 page geometry, margins/header/footer, Word grid values, body/heading/title/table/caption fonts and sizes, first-line/reference indentation, figure/table caption placement, and section-local reference-list convention. Project-specific outer structure, rights/permission decisions, page-count editorial targets, terminology/style judgement, and rendered-page approval remain explicit Human/Host work.

## Preview versus conformance

The generic renderer still has deterministic defaults for non-MISCO/diagnostic use. `misco.publication@1.2.0`, however, resolves its formal specification and URL display policy from the pinned Profile resources; built-in defaults are not treated as MISCO conformance.

An explicit application-level `formal_spec_profile` or `url_display_profile` may be supplied only when it exactly matches the pinned production resource. A differing explicit value is a conflict and fails closed instead of creating last-write-wins authority. Changing a production formal value therefore requires a new authoritative Profile/resource version, not a one-off runtime override.

The renderer applies the supported formal values to the actual DOCX and independently verifies the page/grid settings it can inspect. References are rendered at the end of each section, using `＜参考文献＞`; canonical source locators remain preserved, while reader-facing web references display the full URL.

## Applied rules and QA

Already machine-representable Publication behavior continues in the existing renderer: citation/source resolution, native tables/images, exact retained image bytes, cross-references, figure/table numbering, bibliography generation, and immutable pins. Issue #335 additionally applies the supplied formal page/font/grid/indent values and aligns native DOCX ordering with the approved rules that table titles are above tables and figure titles are below figures.

Editorial conformance remains Host/Human work. A MISCO application input must contain a `misco-editorial-qa` review result. `unevaluated`/`warning` remains visible and cannot pass the MISCO release check. Permissions and disclosure/original-review status are required only for affected non-public/interview/internal material. Research-group metadata is supplied only when a later outer-structure rule actually needs it.

Separately, the bound release decision still requires inspection of every rendered page; binary generation is not visual approval.

The build receipt stores the Publication Profile pin, all delivered resource pins, resolved formal/URL policy, remaining application inputs, QA result, and a digest of that Publication policy bundle. Release requests and release manifests bind the same policy digest to the exact output bytes.

## Authority and liveness

Publication never mutates Research State. Preview/render success does not approve the manuscript, editorial conformance, or release. Publication-only missing inputs block only the operation that requires them; they do not stop Research or Writer work.

Existing atomic release/recovery semantics remain unchanged. Same exact build/request may be verified/reused; different manuscript/profile/policy bytes produce a different build identity rather than rewriting an old result.

## Ablation

Acceptance holds the same manuscript content fixed and renders it with and without the pinned formal layout. The DOCX layout/output digest changes, while extracted manuscript text remains unchanged. A separate conflict case changes one pinned formal value in an explicit application input and verifies that Publication rejects it instead of silently overriding the Profile. Resource-pin corruption remains covered by production Profile integrity tests.

## Visual smoke check

The pinned production profile was exercised with representative build `PUB-75506a067fb7c8cce12e4634`. Its DOCX was converted with headless LibreOffice, rendered to PNG, and inspected manually. The page showed no clipping, overlap, black boxes, or mojibake; the table caption remained above the table; `＜参考文献＞` and its cited source appeared before the next section; and the reader-facing URL remained present.

A second renderer-only check used a deliberately long URL with the same pinned layout. LibreOffice wrapped the full URL across lines without clipping or elision. This confirms the renderer can display the approved full-URL policy rather than requiring a shortening convention. The Linux smoke renderer may substitute unavailable Windows fonts, so exact `ＭＳ 明朝` / `ＭＳ ゴシック` / `Century` font names are verified separately in the generated OOXML; the visual check covers layout/readability rather than Windows font-fidelity certification.

These render checks are distinct from editorial review and release approval. They do not authorize external publication.
