# Research Method Capability convergence

PR 12 establishes a common semantic layer between the generic PR9 Research Capability ABI and later concrete Survey, Case, Delphi, and Virtual Runner contracts.

The legacy design treats methods as capabilities selected from an Evidence Gap rather than mandatory pipeline stages, and requires Human Decision for method adoption and material protocol changes while permitting mechanical continuation inside an already approved protocol. The canonical convergence keeps those implementation-neutral boundaries without importing MISCO-specific method policy.

## Authority model

A generated `MethodDesignRef` is candidate design material, not a Core `Method`. The authoritative method identity remains the PR3 Core Method object, and `real` execution requires its `adoption_state` to be `approved` with a resolving Human Decision. A generated Protocol or Instrument is likewise candidate material until an approved/pinned version is supplied to execution.

A material Protocol revision is a research decision. A repeated Run under the same approved Protocol is not, by itself, a new research-level adoption decision; it still requires ordinary PR9 runtime authorization.

PR10 confirmation and Core Human Decision remain distinct. Confirmation can authorize commitment of a state-bound conversational proposal, but cannot satisfy method-adoption or material-protocol-revision authority.

## Data and epistemic boundaries

A Run preserves raw observations, responses, measurements or other data references separately from PR9 `evidence_candidates`. Raw data is not automatically verified Evidence. Candidate Analysis is not Core Analysis, and analysis output is not automatically a Finding.

`real` execution may produce empirical candidate material when the method/protocol and runtime are valid. `virtual` and `synthetic_test` outputs stay synthetic; they cannot be promoted to empirical Evidence by a later reducer or adapter.

Incomplete, partial, and failed Runs are first-class outcomes. Missingness, dropout, unavailable data, limitations, validity threats, and coverage are preserved rather than normalized away.

## Contracts

- `research-method-context-extension.schema.json` binds questions, Evidence Gaps, method/protocol/instrument/RunSpec references, prior Run results, and Human Decision references to one exact PR9 Context Pack.
- `research-method-result-extension.schema.json` binds generated candidate design refs, RunResultSummary data, raw data refs, validity/limitation reports, candidate Analysis, and PR9 candidate references to one exact Handoff.
- `research-method-semantics.yaml` is the normative common semantic catalog and stable error-code inventory.

No PR9 envelope is modified. No Survey/Case/Delphi/Virtual Runner-specific schema, runtime, SQLite, Writer/Publication behavior, or MISCO-specific requirement is introduced.
