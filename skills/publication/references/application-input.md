# Publication application input

The optional third argument to the public Publication preview operation follows `core/packages/writer-publication/publication-application.schema.json`.

For a production MISCO run, values must come from the actual current formal source/approval. The schema is an input carrier, not authority by itself.

If no MISCO formal specification is available, omit it. The renderer may still create a diagnostic preview using its built-in deterministic defaults, but the build receipt records `formal_specification: failed` and release remains blocked.

Tests may use values explicitly marked `SYNTHETIC_TEST_ONLY` to prove wiring/rendering behavior. Such values are not MISCO defaults and do not establish production conformance.
