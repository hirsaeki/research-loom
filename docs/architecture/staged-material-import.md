# Staged verified material import

Issue #165 adds one bounded cross-workspace material path. It does not import old Research authority.

The public flow is:

```text
previous workspace / portable execution-material root
        ↓ external materials stage
<destination workspace>/intake/material-sources/<stage-id>/execution
        ↓ read-only metadata resolution + exact digest/size verification
external materials import
        ↓
<destination workspace>/.research-loom/execution
        ↓
current Desktop Research Run
```

The stage directory is deliberately outside `.research-loom/`. Staging copies only the self-contained execution/material child established by #160, omitting transient staging/lock state. A full previous workspace, its `.research-loom` parent, or the child execution root itself may be named as the source; the implementation resolves only these fixed layouts and never scans arbitrary host files.

Import selects one persisted source Run/capture pair, validates its original/text binding, stream-verifies the original digest and size, verifies the UTF-8 rendition, and copies both into the destination Run through the existing atomic managed-capture store. The copy seam receives the expected source digest and size, so changing staged bytes between verification and copy fails closed rather than registering different bytes.

Imported provenance retains historical source Run/capture/artifact identifiers, digests, locator, acquired-at value, source category, and persisted filename hints when available. It records the stage identity and import time, but no staged absolute path becomes destination content identity. Old Snapshot/Lineage, Findings, Evidence, decisions, Handoffs, and Run lifecycle are not imported as current authority.

After a successful import the intake stage is disposable. Deleting it does not affect destination material show/export or current Desktop Research use, because destination artifacts resolve only from the destination Parent Durable Store Root. Missing, corrupt, unreadable, or incorrectly bound staged material is rejected; import performs no network reacquisition.
