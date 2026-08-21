# Workspace Lifecycle Contract v0.1

## Archive

`archive create` is an explicit Human operation. It creates a self-contained
bundle containing the Harness runtime, registered artifact bytes, intake batches,
contract pack, state/Decision/Run/Context history, and a verified payload tree
hash. The source workspace is marked `ARCHIVED` only after the staged bundle is
verified. No prior file, Run, snapshot, Decision, or head is deleted or rewound.

Pending Work, pending Human Decisions, pending Attention drops, or transition
locks block a normal archive. An incomplete archive requires an explicit Human
reason and is marked `INCOMPLETE` in the archive manifest.

After archival, read-only status, validation, and archive verification remain
available. Research, Publication, Work submission, Recovery, and other
state-changing operations fail closed.

Archives are preservation artifacts, not normal Research or Publication
Context. They are not automatically discovered or registered as Evidence.

## New workspace

`rh new` creates a target workspace from an explicit Harness template. The
target must not be a non-empty directory. The command copies only the declared
contract/runtime bootstrap and new intake inputs. It never copies `.rh`, prior
Research or Publication State, Decisions, Runs, Seeds, or old Map versions.

An optional initial drop is registered after initialization and enters the
normal Attention Distillation Work boundary. `rh new` never archives or mutates
another workspace and Work does not create external workspaces.

Distribution and upgrade behavior is defined by
[`distribution_contract.md`](distribution_contract.md). In particular, a new
workspace may record Harness/Profile source provenance and an upgrade may not
overwrite a modified managed file or cross a pending Work/Human boundary.
