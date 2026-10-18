# Desktop Research retention edge cases

Desktop Research treats successful external acquisition and final result normalization as separate facts.

## Oversized originals

Normal Execution Artifacts keep the repository-wide `max_artifact_bytes` and `max_run_output_bytes` limits. When a Desktop Research Context explicitly permits a larger `max_original_capture_bytes`, the production local store may retain that original in the Loom-managed `external-original://sha256/...` payload class. The exact bytes, SHA-256 digest, byte size, media type, artifact identity, capture identity, Run binding, and provenance remain first-class artifact metadata. The paired UTF-8 rendition remains a normal bounded artifact.

The caller still supplies only the ordinary `external capture` input. Storage representation is selected internally. Controlled workspace containment, regular-file, symlink/reparse-point, Windows final-path, and Run-status guards remain in force. Large originals are streamed through staging and hashing rather than materialized as one Python `bytes` value. Metadata for the original and rendition is committed atomically; newly created unreferenced payloads are removed on failure, while pre-existing digest-deduplicated payloads are preserved.

PR38 material inventory identity remains the original-byte digest, independent of storage representation. Public Run and material projections do not expose managed filesystem paths.

## Missing coverage declarations

A configured coverage dimension omitted by a submitted result is not inferred as covered, partial, uncovered, or not applicable. Canonical Desktop Research normalization completes the projection with one explicit `unknown`/unassessed dimension and preserves the submitted result as submitted provenance. Unknown dimensions remain research limitations and do not imply saturation or completion. Unknown dimension IDs, duplicates, malformed objects, and inconsistent trace bindings continue to fail closed.

## Citation whitespace containment

Citation validation keeps exact substring containment as the first check. After the citation's text-rendition digest is bound to the trusted captured rendition, a failed exact check may use a validation-only projection that collapses CR/LF, tabs, and consecutive ASCII whitespace to one space. No case folding, punctuation removal, fuzzy distance, semantic similarity, hyphenation repair, OCR repair, or quote rewriting is performed. Stored original bytes, rendition bytes, digests, citation excerpt, locator, and capture identity are unchanged.

These retention rules do not verify a Source, adopt Evidence or Findings, answer an RQ, claim research completion, or mutate Research State. Desktop Research normalization remains candidate-only and continues through the existing Confirmation / Human Decision / State Transition authority boundary.
