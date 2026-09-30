# AIの進化とそれがもたらすMISCO企業への影響 — production project configuration

Issue #336 separates a fresh production project from the historical `probe2`
Workspace. The two are intentionally **not** renamed into one another.

## Fresh start

`project-config.json` is the production Project Config for the MISCO M3 2026
research project (`misco-m3-2026`, 「AIの進化とそれがもたらすMISCO企業への影響」).
It contains the approved project identity, public project objective / scope, a
fresh bootstrap RQ seed, and the production Publication request. It
contains **no legacy/probe RQ**, Evidence, Finding, material, prior virtual-run
feedback, or other legacy/probe research state.

`research_questions.references` is empty. The single seed is a fresh bootstrap
question derived from the current production project objective; it is not copied
from any legacy/probe RQ. A new Workspace creates/adopts its actual RQs through
the normal public candidate -> confirmation -> Human Decision path. Historical
probe2 RQ IDs or text are not a bootstrap mechanism.

The Project Config directly requests only `misco.publication@1.3.0`.
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

Then use the existing public flow. For the actual local acceptance, prefer the checked-in deterministic PowerShell probe so the before/after reads, target inspection, advancement and invariance checks are captured without manually copying IDs:

```powershell
.\projects\misco-ai-2026\Invoke-Probe2ProfileMigration.ps1 `
  -ExpectedHead <40-character-main-HEAD>
```

The script defaults to `%TEMP%\misco-ai-2026-probe2`, requires a clean checkout and the provisioned `.venv`, fails closed unless the repository HEAD exactly matches `-ExpectedHead`, verifies the checked-in resolve-request digest, records only public CLI reads, resolves and inspects the exact target generation, performs `profile advance`, then reopens through new CLI processes. It writes `before/`, `target-generation/`, `after/`, per-command stdout/stderr, and `probe-result.json` under `%TEMP%\research-loom-probe2-misco-migration-<HEAD>`. Evidence is never overwritten: a repeat run uses the next `-rerun-NN` directory. If the Workspace already exposes the exact production target, the script reconstructs that target from public Profile history and requires `profile advance` to return `NOOP`, matching the idempotent previous Probe style.

It automatically verifies that project semantics, Research Snapshot, authoritative/candidate RQs, active/effective Attention, materials, research inputs, Exhibits, historical Research Packages and Writer compositions are unchanged; the target contains only the continuity Research Profile plus production Writer/Publication; the first application adds exactly one append-only advancement event while an exact rerun adds none; and the migration source generation remains readable. The script never edits Workspace JSON/SQLite and never re-intakes existing authoritative Loom research.

### Durable replacement migration acceptance

The original `%TEMP%\misco-ai-2026-probe2` operator Workspace was later found
to have lost its required Parent files to OS temporary-storage cleanup. That
loss is retained as negative operator evidence; it is **not** repaired by
fabricating `workspace-binding.json`, Research State, or other authoritative
files. `%TEMP%` is therefore not a supported location for an authoritative
long-lived Loom Workspace.

For the replacement F7/G3 live migration acceptance, use the deterministic
durable probe:

```powershell
.\projects\misco-ai-2026\New-MiscoMigrationProbe.ps1 `
  -ExpectedHead <40-character-main-HEAD> `
  -Workspace D:\wsroot\scratch\loom-workspaces\probes\misco-profile-migration
```

The script refuses an OS-TEMP Workspace, requires a clean full-history checkout
and the provisioned `.venv`, and never edits managed Workspace JSON/SQLite
directly. On a new durable Workspace it extracts the exact production
`misco.publication@1.2.0` Project Config/EPS from pinned Git commit
`f31efa68c56377fedd3216fd506d2807d55194e0`, initializes through the public
launcher, adopts one bounded migration RQ through confirmation + Human Decision,
activates one Attention map while retaining a second unactivated candidate,
registers one operator-supplied Project Input, and builds a Research Package plus
a two-section Writer Composition whose validation remains intentionally
incomplete. It does not synthesize Evidence, Findings, external-source retrieval,
or research conclusions.

The same script then resolves and advances only the Publication Profile request
from `1.2.0` to `1.3.0`, reopens through new public CLI processes, and verifies
that project semantics, lineage, Research Snapshot, authoritative RQ, active and
stale Attention, Project Input, historical Research Package, and Writer
Composition remain exact. The archived Package must continue to pin the old
`1.2.0` generation while the current Workspace generation exposes
`misco.publication@1.3.0`. The first run requires `ADVANCED`; rerunning the exact
Workspace reconstructs the current target from public Profile history, requires
`NOOP`, and appends no event. Evidence is written beside the durable Workspace
under `_evidence/`, never under `%TEMP%`.

The historical `Invoke-Probe2ProfileMigration.ps1` remains useful only if an
exact complete backup of the original Probe2 Workspace is restored. Its failure
on the damaged `%TEMP%` directory must not be relabeled as a migration pass.

The underlying public commands remain:

```text
research-loom profile resolve --workspace WORKSPACE --output TARGET --json projects/misco-ai-2026/probe2-profile-resolve.json
research-loom profile advance --workspace WORKSPACE --json advance.json
research-loom profile history --workspace WORKSPACE --json
research-loom resume --workspace WORKSPACE --json
```

The operator must verify that the same authoritative RQ IDs, materials, active
Attention Map, Snapshot, and historical package/run bindings remain available.
An unactivated Attention candidate remains stale; it is never auto-rebound.
