# Deterministic Publication preview and release

Issue #220 completes the production boundary after the Writer round trip. Publication consumes an immutable Writer manuscript revision plus the exact Research Package and Publication Profile pins already reachable from that revision. It does not read or mutate authoritative Research State to rewrite content.

The public surface is intentionally small:

```text
research-loom publication preview --workspace ... --composition-id ... [--revision-id ...]
research-loom publication show    --workspace ... --build-id ...
research-loom publication release --workspace ... --build-id ... --json approval.json
```

`preview` deterministically produces two immutable outputs under managed Publication state: a Markdown preview and one formal DOCX artifact. Citation keys resolve only against Source objects already supplied by the pinned Research Package. Exhibit references resolve only against Research Exhibits already bundled in that package. Explicit `[[section:...]]`, `[[exhibit:...]]`, and `[[citation:...]]` references are resolved without changing manuscript meaning. Unknown references remain visible in preview and are recorded as defects.

The DOCX renderer has no external dependency. For identical pinned inputs it writes the same package members in the same order with fixed ZIP metadata, so equivalent rebuilds are byte-identical. A repeated build verifies and reuses the existing immutable build rather than creating another semantic version.

Preview and release are deliberately separate. Preview may contain warnings or failed reference checks and remains inspectable. Release requires all configured blocking checks (citation, exhibit, cross-reference, render) to pass and requires an exact human approval bound to the preview build ID and digest. Open Writer feedback is reported as a non-release-blocking warning.

The Release Manifest binds the released bytes to the manuscript revision/digest, Research Package/digest and Research Snapshot provenance, Publication Profile version/digest, output digest/size/media type/reference, verification results, and exact human release decision. The released DOCX is copied byte-for-byte from the verified preview build. No Finding, Evidence, Argument, Research Snapshot, or other Research authority object is changed.
