# Research Capability contract convergence

## Decision

PR 9 canonicalizes the common invocation/handoff boundary shared by Desktop Research, Survey, Case, Delphi, Virtual Runner, and future research Capabilities, without migrating any one implementation.

```text
Project Config + Effective Profile Set + immutable Research Snapshot
                              |
                       bounded Context Pack
                              |
                    runtime authorization
                       (separate proof)
                              |
                    Capability Invocation
                              |
                        plugin/runtime
                              |
                     Capability Handoff
                              |
                     validate / review
                              |
                 canonical Core adoption path
               (Human Decision where required)
```

Legacy Desktop Research already separated bounded context from execution, returned structured handoff data including counterevidence/unknowns/gaps, proposed rather than selected next methods, and routed adoption back through Harness validation/Human Decision. PR 9 promotes only those capability-independent semantics. Desktop-specific source policy, capture layout, stopping/coverage logic, Work assumptions, and concrete question-impact vocabulary remain deferred.

## Descriptor and authorization

A Descriptor declares capability identity/version/kind, functions, modes, compatibility, descriptive availability, and a content digest. `capability_kind` and function IDs remain open vocabularies.

Availability, Project Config `capability_hints`, and runtime authorization are three separate concepts. Only Invocation `runtime_authorization_evidence` represents the runtime decision; its credential/token/policy-engine format is deliberately opaque and out of scope.

## Bounded Context Pack

A Capability receives a read-only bounded projection rather than the whole repository/database. It pins:

- Project Config digest;
- whole Effective Profile Set digest plus selected Profile manifest pins and Core contract versions;
- Research Snapshot identity, revision, and content digest.

It carries relevant Research Questions/Core-object references, explicitly allowed Project resources, Research Attention, project requirements/prohibitions/must-not-claim, and the exact Effective Profile constraints. Bounds constrain ordinary context material; they never permit silent loss of governance semantics.

Project input/artifact references are context-only. Pre-registered Project Source references may be candidate source bases. A Handoff may also capture a newly acquired source from an authorized execution; this remains a candidate capture and is not silently registered as Core Source/Evidence.

## Execution modes

- `real`: authorized real resources/participants; empirical candidates are possible but not automatically authoritative.
- `virtual`: simulated execution; evidentiary output is synthetic.
- `synthetic_test`: deterministic fixture/test execution; evidentiary output is synthetic test material.

Virtual/synthetic output cannot be relabeled empirical by a Capability or Handoff validator.

## Invocation

One Invocation binds one Descriptor digest, one declared function, one supported mode, one exact Context Pack, the same Project/Profile/Snapshot pins, separate opaque runtime authorization evidence covering the mode/function/resources, run/trace identity, and a content digest.

## Handoff

The Handoff is the machine-readable source of truth. It may return structured candidate observations, source captures, evidence candidates, candidate Findings, counterevidence, conflicts, unknowns, evidence gaps, candidate next actions, and candidate next-method options. Next methods are proposals only.

It also records implementation/run/trace provenance, content digests, exact input pins, and which Research Attention, project guards, and Effective Profile constraints were preserved. Conversational prose may explain a run but cannot substitute for the Handoff.

`valid`, `partial`, and `rejected` are validation outcomes, not adoption states. Every Handoff explicitly states that no Research State mutation occurred, outputs are candidates, and authoritative transitions follow Core Human Decision semantics. Writer/Publication artifacts may be read as context when authorized but can never justify Research Evidence.

## Ownership and deferred work

Common contracts belong in Core. Concrete imperative Capability adapters/runtimes belong in `plugins/`. Project Config configures but does not own implementations; Profiles constrain but do not implement them.

PR 9 does not implement Desktop Research details, Survey/Case/Delphi/Virtual Runner behavior, Work Conversation UI/coordinator, a permission engine, SQLite/export/publish, Writer/Publication, or legacy deletion.
