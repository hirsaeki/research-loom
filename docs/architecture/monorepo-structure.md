# Target monorepo structure

## Purpose

This document defines the canonical layout and ownership boundaries of the repository. It was introduced in PR 2 as the convergence target for the two legacy implementations imported in PR 1; the layout below reflects the repository as it stands now, and the original PR 2 scope is kept at the end as a historical note.

## Canonical layout

```text
research-loom/
├─ core/
│  ├─ runtime/       # research state, transitions, validation
│  ├─ execution/     # capability execution and context packs
│  ├─ conversation/  # Work Conversation service
│  ├─ decision/      # Human Decision Gate
│  ├─ packages/      # versioned package / capability schemas
│  ├─ models/        # research object schema
│  ├─ validators/    # non-overridable invariants (data)
│  └─ fixtures/
│     (workflow/, provenance/, services/ are empty placeholders; see #497)
│
├─ profiles/
│  ├─ contracts/
│  ├─ research/
│  ├─ organization/  # empty placeholder
│  ├─ narrative/
│  └─ publication/
│
├─ plugins/          # local application facade + CLI, stores, capabilities
│
├─ skills/
│  ├─ research-conversation/
│  ├─ writer/
│  └─ publication/
│
├─ projects/
│  ├─ contracts/
│  └─ <project>/     # e.g. misco-ai-2026
│
├─ docs/             # architecture, operations, acceptance, migration
├─ tests/            # contracts/ and runtime/
├─ scripts/          # operational and CI helpers
│
├─ research-harness/ # legacy; reference only, removal tracked in #500
└─ research-profile/ # legacy; reference only, removal tracked in #500
```

Concrete profiles and projects belong below these category boundaries. Expected examples include `generic-research`, empirical/case-study research profiles, organization profiles, narrative profiles such as IMRaD or hypothesis-model-validation, publication profiles, and project-specific configuration. They should be introduced by convergence PRs rather than populated speculatively in this structural PR.

## Ownership boundaries

### `core/`

Owns generic research semantics and invariants that should hold independently of organization, topic, narrative, or publication format. Typical responsibilities include research objects, relation services, state transitions, provenance, auditability, validators, phase/gate mechanics, snapshots, and versioned package contracts.

Core must not encode organization names, a fixed chapter layout, a particular research topic, document templates, or a required organization-specific method.

### `profiles/`

Owns declarative policy and composition. Profiles are separated by concern so research-method rules do not become entangled with organization rules or document formatting.

- `research/` — methodological requirements and research-quality rules
- `organization/` — organization/domain terminology, constraints, gates, and disclosure rules
- `narrative/` — argument/narrative stages and semantic section requirements
- `publication/` — output format, template, citation, numbering, rendering, and release checks

Project-specific research questions and current-year themes do not belong in reusable profiles.

### `plugins/`

Owns imperative extensions that cannot be expressed as declarative profile data: custom importers/exporters, source adapters, organization-specific calculations, anonymization, or external-system integration.

Plugins extend narrow core interfaces. Merely changing terminology or requiring a field should not require plugin code.

### `skills/`

Owns host-loaded workflows above the research state. Hosts load a skill explicitly; skills reach the harness only through the public CLI / application facade.

- `research-conversation/` guides a human-facing research session (Codex or ChatGPT Work) through the public surfaces.
- `writer/` consumes detached Writer input built from a pinned Research Package and returns manuscript revisions plus structured writing feedback.
- `publication/` turns an approved manuscript into deterministic publication previews and checks, ending in a bound human release decision.

Skills must not bypass package/contracts to reach directly into the canonical research database. Writing feedback is a routing signal, not research evidence and not a direct mutation of research state.

### `projects/`

Owns one project's configuration and inputs: concrete research questions, scope, selected profile composition, communication brief, project data/source references, and generated artifacts. Project configuration composes reusable profiles; it does not redefine generic core invariants.

## Dependency direction

The intended direction is deliberately one-way:

```text
projects ──compose──> profiles
    │                  │
    ├───────────────> skills ──consume packages──> core
    │                  │
    └───────────────> plugins ──extend───────────> core
                       │
profiles ──interpreted by────────────────────────> core
```

Rules:

1. `core` has no dependency on organization, narrative, publication, project, or legacy implementation modules.
2. Profiles are declarative inputs interpreted through stable core contracts; profiles do not import projects.
3. Plugins depend only on explicit extension points/contracts, not on project internals.
4. Writer/publication skills consume versioned packages/contracts rather than the internal database schema.
5. Projects compose the pieces but project-specific logic must not leak back into reusable layers.

## Research → writing → publication boundary

The target flow is:

```text
Canonical Research State
        │
        └─ Research Package (snapshot/version pinned)
                  │
                  v
               Writer
                  │
                  ├─ Manuscript revision
                  └─ Writing feedback ──> research workflow routing
                  │
                  v
             Publication
                  │
                  └─ Release decision (human) ──> provenance registration
```

The research state remains authoritative for what is justified. Writer owns how approved state is argued and expressed. Publication owns deterministic formalization and release checks; it does not alter research meaning.

## Storage/publication boundary

The current local implementation persists canonical state in SQLite stores under `plugins/`. The architecture keeps the canonical transactional research state separate from generated interchange/publication views. A local database may remain authoritative while JSON/YAML/Markdown, shared folders, or later adapters are projections produced through explicit export/publish contracts.

## Legacy convergence policy

`research-harness/` and `research-profile/` are frozen reference material. Canonical code no longer imports them; the remaining references (a Project Config pin and migration ledger tests) are being re-pointed in #499 before the trees are removed in #500.

For each convergence PR:

1. Select one bounded responsibility or contract.
2. Inventory both legacy implementations for that responsibility.
3. Choose or define the canonical target under the structure above.
4. Migrate with behavior/contract tests where applicable.
5. Update callers to the canonical location.
6. Remove legacy copies only after parity and references are verified.

Do not perform opportunistic cleanup across unrelated boundaries while migrating one concern.

## Historical note: scope of PR 2

When this document was introduced, PR 2 intentionally did not:

- move or rename files under either legacy directory;
- choose winners among duplicated models/contracts/skills;
- merge Python packaging or dependency definitions;
- alter runtime behavior;
- create concrete MISCO/project content merely to fill directories;
- change storage or publication implementations;
- remove legacy code.

Those were left to subsequent convergence PRs.
