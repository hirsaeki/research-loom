# Canonical research contract convergence

## Purpose

PR 3 performs the first bounded convergence step after the monorepo boundary was established in PR 2. It compares the two imported legacy trees with the current design inventory and promotes only **Core-owned research data contracts** and **non-overridable invariants**.

The legacy trees remain migration sources and are not modified or deleted.

## Inputs compared

### Legacy `research-harness/`

The Harness already contains several strong research semantics:

- distinct Question, Source/Evidence, Finding, Decision, Artifact, and snapshot concepts;
- Source/Evidence provenance with stable locators and captured-content hashes;
- Human Decision requirements for authoritative question/finding transitions;
- immutable state/snapshot lineage;
- a Research/Publication firewall;
- explicit preservation of counter/null/unknown evidence and synthetic isolation.

It also contains policy that is **too specific for Core**, such as source-type quality classes, allowed inference scopes, Writer use modes, quotation rules, and method/study-role restrictions. Those remain legacy policy until a later Profile/Writer convergence PR decides where they belong.

### Legacy `research-profile/`

The Profile tree is mostly organization/publication guidance rather than generic research state. It nevertheless confirms two cross-cutting boundaries that belong in Core:

- publication/writing may consume only research content that has acquired the required research authority;
- Writer/publication output must not invent missing research content or silently make research decisions.

Its chapter map, MISCO terminology, formal document rules, narrative guards, citation presentation, and publication metadata remain outside Core.

### Current convergence inventory

The inventory converges on a generic research graph containing Project, ResearchQuestion, Claim, Method, Source, Evidence, Analysis, Finding, CounterReview, Argument, Contribution, Recommendation, NextAction, Decision, Artifact, and Snapshot concepts. It also explicitly separates:

- universal Core invariants;
- methodology/research-quality rules;
- organization/domain rules;
- narrative/Writer rules;
- publication rules;
- project configuration;
- persistence/export implementation.

PR 3 follows that split rather than copying either legacy implementation wholesale.

## Canonicalization decisions

| Concern | PR 3 decision | Reason |
| --- | --- | --- |
| Project identity | Core contract | Generic container for research state; concrete profile selection/config remains under `projects/`. |
| ResearchQuestion | Core contract | Central research semantic; authoritative adoption/revision/closure remains Human Decision-owned. |
| Claim | Core contract | Keeps hypotheses/claims distinct from Findings. |
| Method | Core contract | Generic representation only; required methods and method protocols are Profile-owned. |
| Source | Core contract | Source identity/provenance is universal. |
| Evidence | Core contract | Must remain distinct from Source and resolve to a source locator. |
| Analysis | Core contract | Provides an explicit transformation layer between Evidence and Finding without prescribing analysis method. |
| MethodResult | Folded into Analysis + Finding for now | The Writer inventory proposed it, but the Core inventory does not require a separate durable entity; avoiding a duplicate result container keeps the semantic floor smaller. |
| Interpretation | Folded into Analysis | Legacy Harness distinguishes it conceptually, but the convergence inventory uses Analysis as the generic interpretation/derivation layer. |
| Finding | Core contract | Must address at least one ResearchQuestion. Evidence-count and limitation requirements are **not** Core invariants. |
| CounterReview | Core contract | Preserves challenge/review as research state without fixing mandatory lenses or thresholds. |
| Argument | Core contract | Bridges supported research meaning without implementing Writer. Must be backed by Finding or Evidence. |
| Contribution | Core contract | Research-level contribution is distinct from publication structure; no publication rendering is defined. |
| Proposition / Model | Deferred as extension candidates | Legacy Harness uses these concepts, while the current Core inventory does not make them mandatory canonical objects. A later bounded PR can add them without changing Source/Evidence/Finding traceability. |
| Recommendation | Core contract | Must trace to at least one Finding. |
| NextAction | Core contract | Represents research work demanded by state without fixing a workflow engine. |
| Decision | Core contract | Records research authority independently of orchestration implementation. |
| Artifact | Core contract | Generic provenance and lane/evidence eligibility only. Formal publication artifact rules are deferred. |
| Snapshot | Core contract | Pins research state for reproducibility; immutable by invariant. |
| AuditEvent | Core contract | Minimal append-only audit record; storage is not prescribed. |
| Release object and Release/Manuscript/Research packages | Deferred | Artifact→Snapshot provenance is canonical now; release/package wire formats touch Writer/Publication integration and should converge separately. |
| Source quality / causal-support matrices | Deferred to Research Profile | Valuable but methodology-dependent; not universal. |
| Chapter map / narrative order | Deferred to Narrative/Profile/Writer | Explicitly provisional in the legacy profile. |
| Publication style / quote / citation rendering | Deferred to Publication | Not research-state semantics. |
| SQLite schema / OneDrive export-publish | Deferred | Persistence/projection implementation is intentionally out of scope. |

## Non-overridable boundary

The normative hard rules are in [`../../core/validators/non-overridable-invariants.yaml`](../../core/validators/non-overridable-invariants.yaml). Profiles and implementations may strengthen them but cannot turn them off.

The key chain established by this PR is:

```text
ResearchQuestion
      ^
      | addressed by
    Finding <--------- Recommendation
      ^                     |
      |                     | must trace to Finding
 Evidence ----> Argument ---+
    |
    v
  Source

Generated/Published Artifact ----> immutable Research Snapshot
```

This is deliberately smaller than the legacy Harness policy surface. The aim of PR 3 is to create a stable semantic floor, not to choose a canonical runtime implementation.

## What this PR does not do

PR 3 does not:

- modify or remove files under `research-harness/` or `research-profile/`;
- create Pydantic/SQLModel models or migrate runtime callers;
- define SQLite tables, migrations, indexes, or OneDrive behavior;
- create concrete Research/Organization/Narrative/Publication profiles;
- implement Writer or Publication skills;
- define Research Package, Manuscript Package, or Release Manifest formats;
- preserve every legacy enum or validation rule as Core policy.

Those remain separate convergence decisions so that each boundary can be reviewed independently.
