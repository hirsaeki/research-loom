# Production self-contained Research Package

Issue #77 adds a bounded, read-only production projection from persisted Research Loom state and selected working material to the canonical Harness→Writer Research Package. It does not add Outline, Writer, Publication, Capability Run, Handoff, or LLM execution.

> **Superseded (#504):** Writer and Publication now consume the Package: see [Versioned Writer Composition](versioned-writer-composition.md) and [Deterministic Publication release](deterministic-publication-release.md).

## Public flow

`research-package build` selects one Snapshot/RQ plus explicit Research Objects, Run candidates, Exhibits, Project Inputs, verified Desktop Research text renditions, and unresolved gaps. The resulting immutable package is available through `list` and `show`, then can be `export`ed as `research-package.json`, deterministic `research-package.md`, and exact attachments. `research-package verify --input DIR` validates the exported package without opening the source Workspace, DB, network, or original intake path.

The source Snapshot remains authoritative. Historical Run/Exhibit/Input bindings remain historical; selected candidate Handoff outputs remain candidate-only. Package build/export performs no Evidence verification, Finding/Recommendation adoption, Research Freeze, source-Run mutation, or Publication release.

## Canonical contract

`core/packages/writer-publication/research-package.schema.json` remains the only Research Package contract. Existing reference-only `0.1.0` packages retain their old meaning. Self-contained packages use `0.2.0`, adding resolved bodies, exact working material, attachment manifests and deterministic projections.

Resolved profile data includes the persisted Effective Profile constraints and an exact bundled copy of `profiles/contracts/narrative-semantics.yaml`. Narrative semantics are supplied as resolved definitions rather than requiring downstream Profile rediscovery.

## Authority and epistemic boundary

REAL in-progress packages remain REAL-origin but preview-only and non-release. VIRTUAL-origin packages remain `SYNTHETIC_TEST_ONLY`, `preview_only=true`, `authoritative_research_freeze=false`, and `release_eligible=false`. Initial production behavior rejects REAL/VIRTUAL mixing. A production Virtual Runner can remain pinned to a REAL authoritative Snapshot; the package preserves that Snapshot mode exactly and derives the synthetic origin from selected persisted Run/material provenance instead of relabeling the Snapshot. A legitimate unresolved research gap can be packaged; unknown IDs, contradictory pins, foreign project/lineage bindings, missing bodies, and digest mismatches fail as integrity/input errors rather than being relabeled as research gaps.

## Bounds and export safety

Package selection has no fixed item-count ceilings for Research Objects, Runs, Exhibits, Project Inputs, verified source materials, or gaps. Exhibit provenance traversal deduplicates shared parents and guards cycles. A single build retains at most 1 MiB per attachment and 64 MiB across attachments so the in-memory staging operation remains bounded; it checks the aggregate incrementally before retaining each attachment. The detached package output is capped at 128 MiB and is verified in staging before atomic publication. If a package exceeds an operation budget, the build reports the applicable bound and the caller can split the explicit selection across multiple Packages and retry; source records remain unchanged and a failed build leaves no partial Package. Selected content is never silently truncated. Export refuses existing targets and managed `.research-loom` locations, stages in the destination parent, verifies the staged package, and publishes it atomically; failed output is not treated as success.
