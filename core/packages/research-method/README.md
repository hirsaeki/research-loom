# Canonical Research Method Capability contracts

This directory defines the method-independent execution semantics shared by later Survey, Case, Delphi, and Virtual Runner capability contracts.

It is an extension layer over the PR9 Research Capability ABI. It does **not** define a second Capability Context Pack, Invocation, or Handoff. Concrete method capabilities continue to declare `capability-context-pack@0.1.0` and `capability-handoff@0.1.0`, while these schemas bind method-specific common metadata to the exact PR9 objects.

## Boundary

A Research Method Capability may propose a method design, protocol, instrument, run result, analysis, Finding, or next action. It may not adopt a Core Method, approve a material protocol revision, qualify raw data as verified Evidence, adopt an Analysis/Finding, or mutate authoritative Research State.

`real` execution requires an already adopted Core Method and an approved, version/content-pinned Protocol. Method adoption and material Protocol revision require Human Decision authority. Work Conversation confirmation can commit an already-authorized action proposal but is never that Human Decision.

`virtual` and `synthetic_test` may exercise candidate designs and protocols. Their raw/output material remains synthetic and cannot be promoted to empirical Evidence.

Research Profile continues to own method-family and quality requirements. Project Config availability/permission hints remain descriptive and do not grant runtime authorization; PR9 Invocation remains the runtime-authorization boundary.

## Common functions

- `method_design` — propose bounded method design material.
- `instrument_design` — propose a versioned instrument.
- `execute` — run a pinned RunSpec under a pinned Protocol and preserve raw data, missingness, validity threats, coverage, and completion status.
- `analyze` — analyze pinned Run results and return candidate Analysis/Finding material through PR9 Handoff.

Method-specific vocabulary such as respondents, sample frames, Delphi rounds, panels, consensus, case selection, cross-case comparison, or virtual personas is deliberately deferred to later capability-specific contracts.
