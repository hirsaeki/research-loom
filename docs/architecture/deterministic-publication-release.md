# Deterministic Publication preview and release

Issue #220 completes the production boundary after the Writer round trip. Publication consumes an immutable Writer manuscript revision plus the exact Research Package and Publication Profile pins already reachable from that revision. It does not read or mutate authoritative Research State to rewrite content.

The public surface is intentionally small:

```text
research-loom publication preview         --workspace ... --composition-id ... [--revision-id ...]
research-loom publication show            --workspace ... --build-id ...
research-loom publication release-request --workspace ... --build-id ... --actor-id ...
research-loom publication release         --workspace ... --build-id ... --json approval.json
```

`preview` deterministically produces a Markdown sidecar and one formal DOCX artifact under managed Publication state. The persisted `preview-manifest.json` is the canonical `preview_artifact_manifest` defined by `core/packages/writer-publication/publication-preview.schema.json`; an internal build receipt carries the Markdown sidecar metadata and the additional Research Package / snapshot provenance needed by the local application.

Citation keys resolve only against Source objects already supplied by the pinned Research Package. Exhibit references resolve only against Research Exhibits already bundled in that package. Explicit `[[section:...]]`, `[[exhibit:...]]`, and `[[citation:...]]` references are resolved without changing manuscript meaning. Section cross-references are limited to sections actually present in the immutable manuscript revision. Unknown references remain visible in preview and are recorded as defects.

The DOCX renderer has no external dependency. It rejects XML-incompatible text, writes the same package members in the same order with fixed ZIP metadata, and parses the generated XML as part of render verification. For identical pinned inputs equivalent rebuilds are byte-identical. Build-ID scoped locking makes concurrent identical requests serialize to the same immutable build and verified reuse.

Preview and release are deliberately separate. Preview may contain warnings or failed reference checks and remains inspectable. A release request can only be issued after all configured blocking checks (citation, exhibit, cross-reference, render) pass. The request binds the project, human actor, canonical preview digest, manuscript, Research Snapshot, Publication Profile, and formal output digest. The human response must echo that immutable request ID and digest with the permitted `approve_release` disposition. Publication decisions remain in the Publication lane rather than becoming Research-State pending decisions.

Immediately before formal release, the stored DOCX is reverified against the preview build's size and digest and its XML is parsed again. The Release Manifest binds the released bytes to the manuscript revision/digest, Research Package/digest and Research Snapshot provenance, Publication Profile version/digest, output digest/size/media type/reference, verification results, and exact Publication release request/response. The released DOCX is copied byte-for-byte from the verified preview build. No Finding, Evidence, Argument, Research Snapshot, or other Research authority object is changed.
