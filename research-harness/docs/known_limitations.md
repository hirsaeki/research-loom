# Known limitations and recommended next increment

## Deliberate MVP limits

- The user-facing Discovery Cycle uses deterministic Mock Worker outputs. The
  generic local subprocess adapter is implemented and tested but is not selected
  by the high-level CLI yet.
- Desktop Research now has a Context Pack, source/evidence, stopping, Handoff,
  reducer, Decision Broker, and interactive Work exchange contract. The Harness
  still does not operate the Work UI, automate browsers/search, or claim a
  programmable Work API. A human performs the initial Work research execution
  and returns the structured Handoff.
- Publication Writer integration stops at an independently testable Writer
  Input Bundle and feedback route. It does not invoke RC1.
- The CLI initializes the first Discovery Cycle from explicit Theme,
  Expectations, and optional Seed inputs. Attention intake is intentionally a
  separate explicit batch command (`rh attention ingest`); there is no general
  manifest-driven watcher or implicit repository scan.
- The filesystem Trace Store uses atomic replacement for mutable heads and
  exclusive creation for immutable artifacts. Discovery and Publication
  transitions use owner-token lock files and process-local re-entrancy. An
  orphaned lock is not reclaimed by age; an operator must inspect and release
  it explicitly, with a recorded reason.
- Codex-specific execution is intentionally absent. A future optional adapter
  must inspect the installed CLI help and current official documentation first.

## Current increment boundaries

The completed Work-chat and Recovery increment provides a typed Work-chat
boundary, pending Run abort/replacement, hash-bound Recovery impact and Human
approval, lineage invalidation, new recovery snapshots, and approved replay
through shared Harness services. It still does not operate the Work UI or claim
a programmable Work API.

Use `docs/work_chat_operator_guide.md` and
`docs/harness_recovery_runbook.md` for the supported paths. Keep Evidence
qualification and method selection as Human Decisions, and keep REAL material
isolated from VIRTUAL material unless a Human-approved bridge contract
explicitly defines the relationship. Transition locking is implemented for the
supported Discovery and Publication boundaries, but it is not a distributed
coordination service. Lock status and explicit release are the supported
crash-recovery procedure; automatic age reclamation is intentionally out of
scope.

Publication export and Feedback routing remain independently testable
application boundaries. The CLI exposes the supported Publication Lane
operations but does not expose internal exporter/router modules as commands
without a separate operator contract.

Attention Distillation, `rh archive`, and `rh new` are now supported as typed
Harness boundaries. They still do not operate the Work UI: Work execution uses
the existing Coordinator exchange and Human adoption Decision. Archive bundles
are local filesystem preservation artifacts and are never auto-discovered as
normal research inputs.
