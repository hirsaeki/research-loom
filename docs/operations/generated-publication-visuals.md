# Generated visuals in Publication

Publication reuses its existing native table / exact retained PNG consumer for all visual classes. It determines formal numbers from manuscript ordering and the pinned Profile. Exhibit identity remains independent of that number. Table captions remain above; figure captions remain below; manuscript `[[exhibit:...]]` references resolve to formal numbers.

A data chart must validate again against selected verified Evidence, its exact original generation Package and retained PNG. The native figure legend contains the exact category/value strings and ordinals; no Unicode labels are inferred from pixels. The adjacent source note preserves chart caption, explicit units, denominator and period. Legend cells and generated source-note literals are not interpreted as manuscript reference-token syntax. Native DOCX verification checks the exact cells as well as PNG bytes, caption placement and cross references.

Publication is independent of the upstream renderer. The unchanged reference
chart path verifies deterministic replay. A Host-rendered quantitative chart
instead retains renderer provenance and exact PNG and requires a separate exact
conforming review covering axes, series, ordering and major values (#430).
`VISUAL_REVIEW_REQUIRED` and `VISUAL_CONFORMANCE_FAILED` are unavailable figure
diagnostics, not healthy images. FAIL cannot be overwritten by later PASS; a new
candidate needs its own review. Both paths retain the same native legend/data
note, numbering, caption, source, rights and page QA requirements.

An explanatory candidate must have a separate exact selected conforming review note in its rebuilt Package. Pending reviews yield `VISUAL_REVIEW_REQUIRED`; research-changing or conflicting reviews yield `VISUAL_RESEARCH_REQUIRED`. Neither condition silently becomes a valid figure. Declared added meaning on any visual requires Research. Candidate generation and review are operational evidence; neither adopts a Finding nor approves a manuscript/release.

The DOCX's existing provenance record preserves the semantic contract, generation inputs, selected output digest, original Package attachment pin and explanation review notes. It distinguishes generated research-derived images from retained external source visuals. Source visuals retain exact capture/locator/crop provenance and adjacent external source notes.

MISCO uses the pinned formal typography/layout and existing permission/editorial inputs. For external source visuals it requires an exact retained Source with matching capture digest/locator and explicit title, publisher/author and publication/update date. External sources represented by generated charts, Findings or derived working Exhibits also require these fields; their existing reference/provenance closure is followed rather than erased by generation. Missing bibliographic fields yield `VISUAL_SOURCE_METADATA_REQUIRED`; the Host obtains actual metadata rather than inventing it. Permissions for internal/non-public/confidential/interview Sources (including a canonical `source_type` with that classification) must allow publication, preserve company disclosure/anonymization and attest original review. These are existing Publication inputs, not a new rights system. Actual source adequacy, disclosure and all rendered pages still require Human review.

Missing/corrupt declared PNG payloads can produce a diagnostic Publication preview under a different build identity. The normal Package verifier stays strict. Generation metadata, reference closure, original generation Package and all non-image attachments remain strict even in diagnostic mode. A repaired image restores the healthy build identity without overwriting the diagnostic or earlier preview. A changed candidate/Package/Writer input yields a new preview.

The renderer pin is 0.2.1 because generated-image/legend behavior changes exact output. Generic existing native tables and source PNGs retain their behavior. Machine structural/content checks are not page layout or visual readability QA. A build, even one passing these checks, still requires explicit existing release review/approval for its exact bytes.

## Completing retained Source bibliography

When a retained external Source has the exact captured material/locator but lacks
bibliographic fields required by the selected Publication Profile, use the public
`research.source.bibliography` action. The request pins the exact current Source
revision and canonical object digest, supplies only actual `title`,
`publisher_or_author`, `publication_or_update_date` and optional
`version_or_revision`, and creates one candidate-only Source revision. It cannot
change Source identity, type, canonical locator, acquired time, media type or
content digest. Apply the exact candidate through the existing
`state.apply_candidate` Confirmation path, then rebuild the affected Research
Package / Composition / Writer revision / preview. This is bibliographic
provenance transcription, not new research meaning or a Publication bypass.
