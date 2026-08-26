# Canonical Research Capability execution runtime

PR22 turns the PR9 Capability Invocation envelope into an auditable Capability
Run without turning execution into a planner, Research Coordinator, or State
mutation path.

## Ownership and flow

```text
validated PR9 Invocation + Descriptor + bounded Context Pack
        -> exact CapabilityRegistry resolution
        -> runtime authorization
        -> immutable Run / input capture
        -> managed execute OR external/interactive collection
        -> immutable raw Handoff / extension / artifact metadata capture
        -> PR9 Handoff validation
        -> PR20 CapabilityNormalizationBoundary
        -> candidate StateDeltaProposal (or no proposal)
```

The runtime stops there. It never calls `StateTransitionService` and never
commits a `StateDeltaProposal`. Human review, Decision, confirmation, and the
PR10/PR20 authoritative transition boundary remain separate.

`core/execution` depends only on canonical contracts/runtime ports. Concrete
Capability implementations belong outside Core and receive no Research State
repository, SQLite connection, transition service, workspace root, or arbitrary
file-system handle.

## Registry and future capabilities

Registration is explicit/static in PR22. A binding is the tuple
`(capability_id, capability_version, function_id, execution_mode)`. Unknown
bindings fail closed. Multiple implementations for the same exact binding remain
visible as an ambiguity and also fail closed; there is no implicit
last-write-wins selection.

The generic runtime has no Survey/Delphi/Case/Desktop/PoC dispatch. A future
Capability is added by a Descriptor, adapter and registered result
validator/normalizer. The generic executor is unchanged.

Dynamic import, package installation, entry-point discovery, marketplaces and
remote plugin installation are deliberately outside PR22.

## Authorization and resource confinement

Descriptor/project availability is descriptive and is not authorization.
Before execution the runtime validates PR9 Descriptor/Context/Invocation
schemas, RFC8785 content digests, current Snapshot/Project Config/Effective
Profile Set pins, declared function/mode compatibility, bounded Context limits,
and the structural authorization binding. It then asks a
`RuntimeAuthorizationProvider` to validate the opaque authorization evidence.

Capabilities receive only `BoundedResourceAccess`. A read is allowed only when
the resource is both present in the immutable Context Pack and granted by the
runtime authorization decision. Input/artifact resources remain `context_only`
under the PR9 contract; they cannot become research evidence merely because an
adapter can read them. Core does not expose a Research State database or an
arbitrary workspace scanner to plugins.

## Run lifecycle and trace

Runtime-only Run states are `PREPARED`, `RUNNING`, `COMPLETED`, `FAILED`,
`ABORTED`, and `SUPERSEDED`. Terminal Runs do not reopen. A retry is a new PR9
Invocation with a new Run ID and optional `trace.parent_run_id`; mode changes are
not implicit retries. There is no automatic semantic or network retry policy in
PR22.

Lifecycle events are append-only. Descriptor, Context Pack, Invocation,
Handoff, result extension and output artifact metadata are immutable trace
records. Reuse of an immutable identity with different content fails closed;
Run IDs are single-use even for identical content.

ExecutionTraceStore is deliberately separate from ResearchStateRepository.
PR22 provides only a test in-memory trace implementation. A production
filesystem/SQLite trace store and production artifact byte store are future
adapters.

## Managed and external execution

Managed execution resolves a managed adapter and calls `execute()` with a copy
of the pinned inputs plus bounded resource access. External/interactive
execution uses the same preflight and creates the same immutable Run/context,
but returns a prepared Run for work performed elsewhere. `collect_external()`
reloads the pinned documents, revalidates current State and runtime
authorization, verifies the originally pinned implementation binding, then
validates the submitted Handoff.

This keeps interactive Desktop Research or other human/tool workflows inside
the canonical execution path even when no programmable Work API exists.

## Handoff, normalization, stale State

The runtime stores the raw Handoff before canonical validation so a malformed or
rejected result remains auditable. PR9 validation checks digest/run/input pins,
provenance, preservation of Research Attention/project guards/effective
constraints, output identity/reference consistency, resource evidentiary role,
validation status consistency, and VIRTUAL/synthetic epistemic rules.

`valid` and `partial` Handoffs are offered to the existing PR20
`CapabilityNormalizationBoundary`; `rejected` Handoffs are retained but never
normalized. Capability-specific result extension meaning remains with the
registered PR20 validator/normalizer, not the execution service.

Normalization reads the current Research State again. If execution started from
SNAP-10 and HEAD is now SNAP-11, the Handoff remains in the trace but PR20 stale
binding rejection yields no StateDeltaProposal. The executor never rebases it.

## Abort, late results, and VIRTUAL/REAL

Abort records an append-only terminal event and may call an adapter cancel hook
best-effort. A later external result is retained only as a diagnostic and is not
accepted as the Run Handoff or normalized.

PR17 isolation is preserved: `virtual` and `synthetic_test` evidence-bearing
outputs must be synthetic. The executor cannot relabel synthetic data as real,
change execution mode during retry, continue a VIRTUAL Run as a REAL Run, or
perform any automatic VIRTUAL-to-REAL adoption.

Future filesystem trace/workspace adapters must additionally enforce run-root
confinement, no traversal/symlink escape, exclusive immutable writes, digest
verification and atomic staging/finalization. Those physical storage mechanics
are not implemented by PR22.
