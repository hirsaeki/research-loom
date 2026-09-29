# MISCO AI研究 — production project configuration

Issue #336 separates a fresh production project from the historical `probe2`
Workspace. The two are intentionally **not** renamed into one another.

## Fresh start

`project-config.json` is the production Project Config for a new MISCO AI
research Workspace. It contains the project identity, public project objective /
scope, a fresh bootstrap RQ seed, and the production Publication request. It
contains **no legacy/probe RQ**, Evidence, Finding, material, prior virtual-run
feedback, or other legacy/probe research state.

`research_questions.references` is empty. The single seed is a fresh bootstrap
question derived from the current production project objective; it is not copied
from any legacy/probe RQ. A new Workspace creates/adopts its actual RQs through
the normal public candidate -> confirmation -> Human Decision path. Historical
probe2 RQ IDs or text are not a bootstrap mechanism.

The Project Config directly requests only `misco.publication@1.2.0`.
`misco.writer@1.1.0` is selected transitively by the production resolver. There
is no invented MISCO Research/Organization Profile.

`effective-profile-set.json` is a checked-in deterministic projection of:

- `profiles/narrative/misco/profile.json`
- `profiles/publication/misco/profile.json`

A fresh workspace can therefore be initialized through the normal public CLI:

```text
research-loom init \
  --workspace WORKSPACE \
  --project-config projects/misco-ai-2026/project-config.json \
  --effective-profile-set projects/misco-ai-2026/effective-profile-set.json \
  --json
research-loom doctor --workspace WORKSPACE --json
research-loom resume --workspace WORKSPACE --json
```

After init, propose the current RQ/Attention from current operator input through
the existing public actions. Init itself performs no Research State transition.

## Project-local source boundary

The legacy Research Attention / publication map is an approved configuration /
guidance source for the migrated project constraints. It is not Evidence and not
Research Method authority. Its exact repository bytes are pinned in
`project-config.json`.

Legacy/probe research data -- including prior RQs, Evidence, Findings, materials,
and VIRTUAL RUN feedback -- is **validation-only** for this migration. It is not
a production runtime input for a fresh Workspace. If legacy-only research data
must be transferred formally, use the normal intake/capture -> candidate ->
Human Decision path; do not copy it into Project Config, root JSON, or SQLite.

The current Publication formal profile records
`research_group_type_required=false`, so Issue #331's earlier
`INPUT-RESEARCH-GROUP-TYPE` gap does not require a guessed Project Config value
for this current specification. Non-public material permissions remain runtime
inputs only when affected material is actually published.

## Existing probe2 Workspace

The historical Workspace `%TEMP%\\misco-ai-2026-probe2` has durable research
history under project `PRJ-1` and historically retained the title `Fixture
project`. Profile advancement is not allowed to rewrite that project identity,
objective, scope, RQs, materials, snapshots, Decisions, or active Attention.
That is intentional.

Advance only the Profile generation. The checked-in operator request is `probe2-profile-resolve.json`; it replaces only the fixture Narrative/Publication requests and adds the migration-only exact-locator continuity Profile.

`request_additions` is deliberately narrow: it adds an explicit direct Profile
request while preserving all other Project Config semantics. The continuity
Profile carries **only** the already-active `CORE-TRACE-001` exact-locator
strengthening. It does not import synthetic fixture Research-quality defaults
and is not selected by fresh production projects.

Then use the existing public flow:

```text
research-loom profile resolve --workspace WORKSPACE --output TARGET --json projects/misco-ai-2026/probe2-profile-resolve.json
research-loom profile advance --workspace WORKSPACE --json advance.json
research-loom profile history --workspace WORKSPACE --json
research-loom resume --workspace WORKSPACE --json
```

The operator must verify that the same authoritative RQ IDs, materials, active
Attention Map, Snapshot, and historical package/run bindings remain available.
An unactivated Attention candidate remains stale; it is never auto-rebound.
