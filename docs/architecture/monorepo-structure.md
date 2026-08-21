# Target monorepo structure

## Purpose

This document establishes the canonical destination for convergence of the two legacy implementations imported in PR 1. PR 2 creates boundaries only: it does **not** migrate, deduplicate, rename, or reinterpret legacy implementation content.

## Canonical layout

```text
research-loom/
├─ core/
│  ├─ models/
│  ├─ services/
│  ├─ validators/
│  ├─ workflow/
│  ├─ provenance/
│  └─ packages/
│
├─ profiles/
│  ├─ research/
│  ├─ organization/
│  ├─ narrative/
│  └─ publication/
│
├─ plugins/
│
├─ skills/
│  ├─ writer/
│  └─ publication/
│
├─ projects/
│
├─ research-harness/   # legacy baseline; migration source
└─ research-profile/   # legacy baseline; migration source
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

Owns transformation workflows above the research state.

- `writer/` consumes a versioned Research Package and produces outline/manuscript packages plus structured writing feedback.
- `publication/` consumes a validated Manuscript Package and deterministically produces publication artifacts and a release manifest.

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
                  ├─ Manuscript Package
                  └─ Writing Feedback Package ──> research workflow routing
                  │
                  v
             Publication
                  │
                  └─ Release Manifest ──> provenance registration
```

The research state remains authoritative for what is justified. Writer owns how approved state is argued and expressed. Publication owns deterministic formalization and release checks; it does not alter research meaning.

## Storage/publication boundary

Storage technology is not fixed by this structural PR. The intended architecture keeps the canonical transactional research state separate from generated interchange/publication views. A local database may remain authoritative while JSON/YAML/Markdown, shared folders, or later adapters are projections produced through explicit export/publish contracts.

## Legacy convergence policy

`research-harness/` and `research-profile/` are frozen migration sources until later PRs deliberately move responsibilities into canonical destinations.

For each convergence PR:

1. Select one bounded responsibility or contract.
2. Inventory both legacy implementations for that responsibility.
3. Choose or define the canonical target under the structure above.
4. Migrate with behavior/contract tests where applicable.
5. Update callers to the canonical location.
6. Remove legacy copies only after parity and references are verified.

Do not perform opportunistic cleanup across unrelated boundaries while migrating one concern.

## Non-goals of PR 2

PR 2 intentionally does not:

- move or rename files under either legacy directory;
- choose winners among duplicated models/contracts/skills;
- merge Python packaging or dependency definitions;
- alter runtime behavior;
- create concrete MISCO/project content merely to fill directories;
- change storage or publication implementations;
- remove legacy code.

Those are subsequent convergence decisions and should remain reviewable as separate PRs.
