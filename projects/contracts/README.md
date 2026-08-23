# Canonical Project Config contracts

Project Config is the declarative, project-local input boundary above Core and Profile contracts. It records what one research project is about, which reusable Profiles it directly requests, which issues must remain visible, and which project-local communication/guard/resource/capability hints apply.

It is **not** authoritative Research State, a Profile, a profile resolver output, a runtime permission database, or a CLI override layer.

## Files

- `project-config.schema.json` — structural Project Config envelope.
- `project-config-semantics.yaml` — normative ownership, boundary, Profile bridge, Attention, and digest semantics.
- `project-config-semantics.schema.json` — schema for the semantics catalog.

## Core boundary

`project.project_id`, title/objective/scope, and Research Question references/seeds may be used to initialize or locate Core research objects. Project Config does not carry Core object revision/adoption state and cannot approve, reject, revise, qualify, or answer authoritative Research State.

A Research Question **reference** points at an adopted/managed Core question by ID and must resolve to a Core ResearchQuestion in the same project when the target Core state is available for binding. A Research Question **seed** is project-local candidate text for question formation. A seed is not a Core `research_question`, has no adoption state, and is not an answer.

Project-local guards are applied in addition to Core and resolved Profile semantics. They are not `effective_constraints`, have no Profile merge strategy, and cannot weaken Core invariants or reusable Profile requirements.

## Profile bridge

The four `profile_requests` categories are a readable grouping of **direct PR 4 Profile requests** only. Flattening the categories yields `Effective Profile Set.requested_profiles` losslessly.

Dependencies selected through Profile `extends` / `requires` are owned by PR 4 resolution and are not written back into Project Config. Project Config therefore does not own candidate universes, dependency expansion, selected versions, Effective Profile composition, or constraint precedence.

CLI temporary override precedence remains undefined.

## Research Attention

Research Attention preserves project issues or question candidates that must not disappear silently. It may shape question formation and coverage checks, but it cannot answer a Research Question or select a Research Method.

An Attention item may be `active`, `dropped`, or `out_of_scope`. Dropped/out-of-scope items require a reason. Literal chapter/headline/publication-location information is permitted only as `projection_hints` with `normative: false`.

The generic fixture deliberately contains no concrete MISCO chapter map or concrete organization policy.

## Resources and capabilities

A configured input/source/artifact reference is a pointer only: it is not Evidence and grants no runtime access. Capability availability and permission values are also hints only. In particular, `no_project_objection` does not mean runtime authorization, and capability availability cannot choose a Research Method.

Runtime access enforcement and executable Desktop Research / Survey / Delphi / Case capabilities remain outside this contract.

## Digest

`configuration_digest` is `sha256:` plus SHA-256 of RFC 8785 JCS bytes of the complete Project Config with `configuration_digest` itself omitted. This provides deterministic configuration identity without defining a database row, runtime state revision, or package wire format beyond this contract.
