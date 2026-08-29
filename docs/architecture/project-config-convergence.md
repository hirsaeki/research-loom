# Project Config contract convergence

## Status

PR 8 establishes the canonical Project Config boundary above the contracts fixed by PR 3–7. The convergence promotes only project-local declarative semantics shared by the two legacy implementations and the design inventory. Legacy trees remain unchanged.

## Ownership decision

Project Config answers **what this particular research project is configured to pursue and preserve**. It owns:

- project identity, title, objective, scope, and out-of-scope statements;
- adopted Research Question references plus pre-adoption question seeds;
- direct requests for Research / Organization / Narrative / Publication Profiles;
- Communication Brief;
- Research Attention;
- project-specific requirements, prohibitions, and must-not-claim guards;
- input/source/artifact references;
- capability availability and project-level permission hints;
- configuration provenance and deterministic digest.

It does not own reusable research-quality, organization, narrative, or publication policy. It also does not own authoritative Research State, method selection, runtime capability enforcement, SQLite/storage, or CLI temporary override precedence.

## Convergence from legacy behavior

The legacy Attention intake contract treats an active Attention Map as guidance only: not Evidence, method authority, answer authority, or Publication release authority. The legacy Research Attention / Initial Publication Map likewise separates stable research attention from a provisional reader-facing chapter tree and explicitly forbids choosing Survey/Delphi/Case merely because a chapter exists.

PR 8 keeps those implementation-independent semantics and drops the concrete project map. Canonical `research_attention` can preserve a project issue, reference question seeds, and carry a non-normative projection hint. It cannot carry an answer or selected method. `dropped` / `out_of_scope` dispositions require a reason.

The legacy runtime artifact policy also makes file existence distinct from runtime access. PR 8 therefore models resource references and capability permission posture only as hints; it does not promote the legacy runtime-policy matrix into Project Config.

The prior design inventory places concrete theme/RQs/scope and communication intent in Project Config while reusable research method policy, organization rules, narrative structure, and publication formatting remain in Profiles. PR 8 makes that division executable.

## Project Config is not Core Project state

Core already owns the canonical `project` and `research_question` research objects. Project Config does not duplicate their runtime revision or adoption semantics.

`project.project_id` is the project identity used to initialize/locate the Core Project object. A `research_questions.references[]` entry points to a Core ResearchQuestion ID. A `research_questions.seeds[]` entry is only pre-adoption question-forming material; it has no `revision`, `adoption_state`, answer, method, Finding, or Decision fields.

This preserves PR 3 Human Decision ownership of authoritative research adoption and revision.

## Project guards are not Profile constraints

`project_constraints.requirements`, `prohibitions`, and `must_not_claim` are project-local guards. They are conjunctive project restrictions applied in addition to the Core floor and Effective Profile Set. They do not enter `effective_constraints`, have no `merge_strategy`, and cannot replace or weaken a Core invariant or reusable Profile rule.

Project-specific facts and guards therefore cannot flow backwards into reusable Profiles merely because a project uses them.

No ordering against future CLI temporary overrides is defined in this PR.

## Direct Profile request bridge

Project Config groups direct requests by category for human readability:

```text
Project Config
  profile_requests.research      ┐
  profile_requests.organization  │ flatten, lossless
  profile_requests.narrative     ├─────────────────────> Effective Profile Set.requested_profiles
  profile_requests.publication   ┘
```

Only direct requests cross this bridge. PR 4 remains authoritative for the finite candidate universe, `extends` / `requires`, version solving, dependency closure, effective Profiles, constraint composition, and provenance.

The synthetic fixture demonstrates this intentionally: Project Config directly requests the Narrative and Publication fixtures only; the existing PR 4 Effective Profile Set additionally contains Organization and Research Profiles introduced transitively. Those transitive selections are never written back as Project requests.

## Communication Brief

Communication Brief carries project-local audience, purpose/desired decision, core message, must-include items, and tone. Project-specific prohibited claims have one canonical home under `project_constraints.must_not_claim` rather than being duplicated inside the brief.

Publication template, citation style, output format, file naming, rendering, and release requirements remain Publication Profile concerns. Narrative ordering remains Narrative Profile-owned.

## Research Attention

Research Attention contract:

```text
Attention may preserve an issue/question candidate        YES
Attention may shape question formation/coverage           YES
Attention may answer an RQ                                NO
Attention may choose a Research Method                    NO
Dropped/out-of-scope Attention may disappear silently     NO
Literal chapter/publication placement may be a hint       YES, normative=false only
```

This contract permits a later Writer/Project projection to use provisional reader-routing information without turning chapter layout into research ownership, workflow order, or method authority.

`research_attention` is the immutable Project Config baseline. A later active runtime Attention Map may supply the complete Effective Research Attention snapshot used by future research capability contexts without mutating Project Config or changing `configuration_digest`; runtime Attention Maps remain outside both Project Config and Core Research State.

## Resource and capability hints

`resource_references` can identify project inputs or existing/planned Core Source/Artifact objects by locator/object ID. Reference registration does not qualify content as Evidence and does not grant runtime access.

`capability_hints` records availability plus project posture (`unspecified`, `no_project_objection`, `human_approval_required`, `project_prohibited`). These values are intentionally weaker than runtime authorization. Capability availability or project posture must not select Research Method.

Executable Desktop Research / Survey / Delphi / Case behavior and concrete runtime permission checks remain later implementation work.

## Configuration provenance and digest

Project Config may reference source inputs used to derive the configuration and prior configuration digests. `configuration_digest` is content-bound deterministically:

1. omit the `configuration_digest` field;
2. serialize the remaining Project Config using RFC 8785 JCS;
3. SHA-256 the canonical bytes;
4. encode as `sha256:<lowercase hex>`.

The digest identifies declarative configuration content only; it is not a Research Snapshot, database revision, or publication manifest.

## Executable specification

PR 8 adds:

- `projects/contracts/project-config.schema.json`;
- `projects/contracts/project-config-semantics.{yaml,schema.json}`;
- synthetic Project Config fixtures;
- a thin fixture-only Project Config oracle;
- `tests/contracts/test_project_config_contracts.py` integrated into the stable PR 5 `contract-checks` suite.

Regression coverage includes schema boundaries, deterministic digest, local reference integrity, Core Project/RQ/Source/Artifact binding, project identity domains, scope overlap, direct Profile request identity, lossless Project Config → Effective Profile Set request binding, Attention non-authority, non-normative projection hints, project-guard/Profile separation, resource-reference non-Evidence semantics, and capability-hint non-authorization semantics.

## Explicit non-goals

This PR does not add:

- a concrete MISCO Project Config or Organization Profile;
- a concrete MISCO chapter/publication map fixture;
- a runtime Profile resolver;
- SQLite/export/publish behavior;
- Writer or Publication implementation;
- Desktop Research / Survey / Delphi / Case execution;
- runtime capability/permission enforcement;
- CLI temporary override precedence.
