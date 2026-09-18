# Production two-round Delphi vertical slice

Issue #223 adds the smallest production path over the existing canonical Delphi contracts. It does not introduce an N-round workflow engine or a generic primary-research framework.

## Public flow

```text
Delphi Design + panel identity
  -> Round 1 Instrument
  -> Round 1 response capture
  -> round analysis / disagreement / missing response inspection
  -> immutable controlled-feedback artifact
  -> explicit Round 2 Instrument revision
  -> Round 2 response capture
  -> change / stability / disagreement / attrition inspection
  -> stop/continue candidate
```

The public CLI namespace is `research-loom delphi` with `design`, `instrument`, `round`, `feedback`, `inspect`, and `stopping` operations.

## Exact lineage

Each stored response is contained in an immutable Round result and also carries an explicit binding to:

- `panel_id`;
- `round_sequence`;
- exact Instrument ID/version/digest.

Round 2 is accepted only when the caller supplies exact references to the Round 1 Instrument, Round 1 result, and controlled-feedback artifact. Retained item identities additionally carry explicit prior-item and feedback lineage. Ordering is never used to infer derivation.

Instrument approval and material Round 2 revision IDs must resolve to existing Human Decision records. The resulting Delphi analysis remains candidate-only and never mutates Research State.

## Disagreement, missingness, and attrition

The production slice keeps these states distinct:

- a participant can be expected for a round but submit no response (`missing_response`);
- a participant who responded in Round 1 can be absent from Round 2 (`attrition`);
- submitted numeric or ranking positions can differ (`explicit_disagreement`);
- the same pseudonymous participant can change a comparable numeric opinion between rounds (`changed_opinion`).

Round analysis retains all submitted positions. Controlled feedback summarizes the distribution and minority values without copying participant IDs into the feedback body. The feedback artifact is immutable and binds to both the Round 1 result digest and a digest of the Round 1 analysis it summarizes.

## Stopping boundary

The stopping candidate records configured stability/disagreement goals when present, observed stability/disagreement, attrition, missingness, and the maximum approved round count. No universal Delphi consensus threshold is introduced.

`stop`/`continue` is only a recommendation candidate. It explicitly records that a Human Decision is required before any authoritative Research State transition based on the result.

## Why this is not implemented as Survey-only reuse

The existing Survey production path already provides useful implementation patterns for immutable registries, canonical digests, bounded public surfaces, and missing-value preservation. Those patterns are reused.

The two-round probe also demonstrates the Delphi-specific state that a Survey-only record cannot represent without adding Delphi concepts back into Survey:

- stable item identity across explicit rounds;
- prior-round Instrument/result lineage;
- controlled feedback provenance;
- cross-round pseudonymous opinion change;
- panel attrition distinct from within-round missingness;
- candidate stopping semantics.

Therefore this slice does not extract a new shared Survey/Delphi abstraction. It keeps the common infrastructure patterns and adds only the Delphi-specific lineage/feedback/stopping state proven necessary by the two-round implementation.
