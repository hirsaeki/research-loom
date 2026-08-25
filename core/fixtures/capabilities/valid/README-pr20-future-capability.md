# PR20 future-capability regression fixture

`generic-future-capability-handoff.json` is a PR9-shaped candidate-only Handoff
for a deliberately unknown capability, `fixture.future-research-capability`.
`generic-future-capability-result-extension.json` is a separate synthetic
capability-specific extension.

They do not canonicalize a PoC/Experiment capability. Runtime tests use them
only to prove the extension boundary:

- no matching normalizer -> fail closed;
- valid extension + matching normalizer -> generic `StateDeltaProposal`;
- reducer uses existing Core transition semantics with no capability branch;
- the capability identity does not leak into authoritative Core/Snapshot state.
