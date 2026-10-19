# Target monorepo structure

## Purpose

Terms are defined in the [glossary](../glossary.md).

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
│
├─ profiles/
│  ├─ contracts/
│  ├─ research/
│  ├─ organization/  # reserved; no organization profile yet
│  ├─ narrative/
│  └─ publication/
│
├─ plugins/          # local Application Facade + CLI, stores, capabilities
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

Organization-specific behavior in the local application lives in its own top layer, `plugins/local_application/misco/`. Generic code reaches it only through an extension point such as `PublicationDialect`, which the composition root maps to the organization's Profile id. `tests/contracts/test_misco_isolation.py` fails if generic code under `core/` or `plugins/` names MISCO in a string literal, or imports the MISCO layer anywhere except the composition root.

### `skills/`

Owns host-loaded workflows above the research state. Hosts load a Skill explicitly; Skills reach the harness only through the public CLI / Application Facade.

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

### Inside `plugins/`

Plugin packages (each top-level package or module under `plugins/`) also depend in one direction only. From the bottom up:

1. `_infra/`: file locks, atomic writes, SQLite PRAGMAs, clock. It imports no other plugin.
2. Shared layout and contracts: `local_workspace_layout`, `local_store_schemas`, `application_errors`.
3. Durable and domain stores and their validation: `local_durable_store`, the `local_*_store` modules, `survey_validation`, `survey_response`, `survey_analysis`, `research_visual_semantics`, and similar.
4. Capabilities: `desktop_research`, `survey_virtual_runner`, and similar.
5. `local_application/`: the Application Facade, services and CLI, which compose everything below.

A lower layer never imports a higher one, not even inside a function. No package imports another package's private (`_`-prefixed) names. Shared helpers move down a layer instead. `tests/contracts/test_plugin_layering.py` enforces both rules: no import cycle between plugin packages, and no cross-package private import.

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

`research-harness/` and `research-profile/` were removed in #500 after #499 re-pointed their last references; the `legacy-archive-2026` tag keeps them. The legacy files the migration ledger and the Project Config pin are kept byte for byte in `docs/migration/misco-legacy-sources/`, and the ledger tests verify them there.

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
