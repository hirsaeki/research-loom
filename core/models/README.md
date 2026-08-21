# Canonical research data contracts

PR 3 establishes the first canonical, implementation-neutral research object contract in [`research-object.schema.json`](research-object.schema.json).

The contract intentionally defines **research meaning and references**, not persistence layout, ORM classes, profile policy, Writer behavior, or publication formatting. SQLite tables, Python/Pydantic models, package DTOs, and profile-specific enums may later project onto this contract, but they are not canonicalized here.

## Canonical object set

The schema currently defines:

- `project`
- `research_question`
- `claim`
- `method`
- `source`
- `evidence`
- `analysis`
- `finding`
- `counter_review`
- `argument`
- `contribution`
- `recommendation`
- `next_action`
- `decision`
- `artifact`
- `snapshot`
- `audit_event`

This is a semantic superset of the durable research concepts found across the two legacy trees and the convergence inventory. It deliberately does **not** make every field or quality preference mandatory. Rules that vary by methodology, organization, narrative, or publication target remain profile-owned.

## Contract/version rules

- `schema_version` identifies the canonical object-contract version and is currently `0.1.0`.
- `id` is stable within the repository/application namespace.
- `revision` identifies a version of a mutable research object. Storage engines may implement revisions however they choose.
- A Research Snapshot pins object IDs and revisions; snapshots themselves are immutable.
- Cross-object hard rules live in [`../validators/non-overridable-invariants.yaml`](../validators/non-overridable-invariants.yaml).

## Deliberately not canonicalized here

The following are deferred because they belong outside this PR's Core-contract scope:

- source-quality scoring matrices and method-specific inference rules;
- minimum evidence counts, required limitations, mandatory Counter Review, or gate thresholds;
- organization-specific evidence origins or terminology;
- chapter/section structure, narrative order, Writer paragraph/section contracts, or publication style;
- Research Package / Manuscript Package / Release Manifest wire formats;
- database tables, indexes, migrations, OneDrive/export/publish behavior, or sync policy;
- concrete plugin interfaces and runtime orchestration.

Profiles and later implementations may strengthen the Core contract, but they may not weaken the non-overridable invariants.
