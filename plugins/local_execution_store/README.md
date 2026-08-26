# Local Execution Store

`plugins.local_execution_store` is the first production local adapter for the
PR22 execution persistence ports. It is deliberately separate from the
authoritative Research State repository.

## Boundary

- **Research State** remains owned by `StateTransitionService` and
  `SQLiteResearchStateRepository`.
- **Execution Trace** stores Run lifecycle, immutable invocation inputs,
  Handoffs, result extensions, diagnostics, and artifact metadata for audit,
  reproduction, and recovery.
- **Artifact / Resource bytes** are immutable content-addressed files. They are
  not Research State merely because they exist in the store.

The adapter never calls `StateTransitionService`, never adopts candidate
Evidence/Findings, and never moves a Research Snapshot or Lineage HEAD.

## Layout

```text
execution-store/
├── execution.db
├── blobs/
│   └── sha256/
│       └── ab/
│           └── <sha256>
└── staging/
```

`execution.db` is intentionally a different logical store from the Research
State SQLite database. Large source originals, raw responses, measurements,
logs, generated code, and binaries stay out of Research State SQLite.

## Run lifecycle and immutable documents

Run transition CAS is one SQLite `BEGIN IMMEDIATE` transaction: persisted
status is checked, the current Run projection is updated, the next append-only
lifecycle event is inserted, and only then is the transaction committed.
Concurrent completion/abort attempts therefore cannot both succeed.

Descriptor, Invocation, Context Pack, Handoff, and result-extension documents
are canonical JSON immutable records. Reusing an identity with different
content fails closed. Raw Handoffs are stored before canonical Handoff
validation, preserving rejected/invalid execution output for audit.

## Artifacts and bounded output

`CapabilityExecutionRequest.artifacts` is a `BoundedArtifactSink`. The
capability can provide bytes, role, media type, and optional provenance, but it
does not receive a filesystem root and cannot choose the storage locator,
digest, size, Run ID, or execution mode.

The trusted store:

1. writes into `staging/`;
2. flushes and fsyncs;
3. calculates SHA-256 and actual byte size;
4. enforces configured per-artifact and per-Run limits;
5. hard-links the completed staging file into the content-addressed location
   without overwriting an existing blob;
6. records immutable Run-bound metadata.

Same bytes may deduplicate physically, but artifact identity, role,
Run provenance, and `execution_mode` remain distinct. In particular, physical
deduplication never promotes VIRTUAL output into REAL empirical identity.

Operational limits are adapter configuration, not Research/Profile semantics.

## External intake and ResourceProvider

`register_input_file()` and `import_output_file()` accept only regular files
inside explicitly configured intake roots. Symlinks, `..` traversal, device
files, FIFOs, sockets, directories, and paths outside those roots are rejected.
The file is copied/hashed into the store; arbitrary host paths are never
persisted as the canonical locator.

Registered resources receive a stable `resource://sha256/<digest>` locator.
`ResourceProvider.load()` resolves only a registered `reference_id`, checks any
Context Pack locator/digest against registration, re-hashes the actual bytes,
and fails closed on corruption. `BoundedResourceAccess` still enforces the
Run's authorized Context Pack references before the provider is reached.

Resource registration is operational intake only. It is not Source
verification, Evidence adoption, or Research State mutation.

## Crash and restart behavior

All Run projection/history, immutable execution documents, resource
registrations, and artifact metadata survive process restart. A process crash
may leave a Run in `RUNNING`; the store does not guess that it completed or
failed. `describe_run()` reports the persisted status and last event so the
runtime/Human recovery policy can decide what to do.

Only orphan staging cleanup is provided. Historical artifact GC, backup,
archive, repair, and publication/export are out of scope.

## Integrity doctor

`diagnose_integrity()` is read-only and reports, among other things:

- missing Runs or required immutable documents;
- invalid/gapped/illegal lifecycle histories;
- Run projection vs event-history disagreement;
- missing Handoffs referenced by completed Runs;
- canonical document payload corruption;
- artifact metadata with missing/corrupt blobs;
- dangling artifact Run references.

It never repairs or silently rewrites history.

## OneDrive / shared storage

The execution database and working blob store are local runtime state and are
not designed for OneDrive/SharePoint bidirectional synchronization. Shared
outputs belong to a future explicit export/publish projection from an
authoritative Snapshot or Publication package.

## Future capability families

Roles are intentionally open strings rather than a PoC-specific Core enum.
A future capability can emit, for example, source-code, build, log, and
measurement artifacts through the same sink without adding a Research State
transition kind. Stored code/binaries are bytes only: the store never executes
them and locators must not be concatenated into shell commands.

## Non-goals

This plugin does not implement a concrete Desktop Research, Survey, Delphi,
Case Study, or PoC capability; browser/search or LLM providers; dynamic plugin
loading; production authorization; Work Conversation coordination; automatic
`StateDeltaProposal` adoption; Writer/Publication execution; export/publish;
OneDrive/SharePoint; artifact GC; backup/archive; or legacy deletion.
