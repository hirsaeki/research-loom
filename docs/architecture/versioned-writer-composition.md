# Versioned evidence-linked Writer Composition

Issue #80 adds a narrow production path between Research Package 0.2.0 and later Writer execution. It does not run an LLM, ingest prose, import Writing Feedback, mutate Research State, or implement a patch/graph editing engine.

```text
Research Package 0.2.0
  -> whole composition JSON
  -> immutable v1
  -> export/edit whole proposal
  -> immutable v2
  -> diff
  -> explicit version selection
  -> detached one-section Writer input
```

Each saved composition pins the immutable Research Package, project, Research Lineage, Research Snapshot, and resolved Effective Profile Set. Advancing Research HEAD in the same lineage does not rewrite or invalidate the saved pin. A revision of an existing composition series must name the latest base version and digest; stale revisions fail closed and are not rebased automatically. Rebinding to a new Research Package requires a new composition series.

Section contracts keep stable section IDs, hierarchy/order, heading, reader question, purpose, one-or-many Narrative stages and section purposes, intended messages, supplied research/material/exhibit/gap references, counter-review/qualifier/limitation references, citations, prohibited claims, unresolved items, transitions, and a section digest. Unknown stages/purposes, broken references, Narrative dependency violations, or loss of required adverse/qualifying material fail closed. Missing Narrative `requires` are instead persisted as unmet diagnostics so an in-progress outline can be saved without pretending the prerequisite is satisfied.

## Operator flow

Create v1 from an externally edited JSON proposal:

```text
research-loom writer-composition capture --workspace WORKSPACE --package-id RP-ID --json composition-v1.json
research-loom writer-composition list --workspace WORKSPACE --json
research-loom writer-composition show --workspace WORKSPACE --composition-id COMP-ID --version 1 --json
```

Export the exact whole proposal, edit it, then import v2:

```text
research-loom writer-composition export --workspace WORKSPACE --composition-id COMP-ID --version 1 --output composition-v2.json --json
# edit composition-v2.json, including change_reason
research-loom writer-composition capture --workspace WORKSPACE --package-id RP-ID --json composition-v2.json
research-loom writer-composition diff --workspace WORKSPACE --composition-id COMP-ID --from-version 1 --to-version 2 --json
```

Importing v2 does not change the selected Writer version. Select an exact version/digest separately:

```text
research-loom writer-composition select --workspace WORKSPACE --composition-id COMP-ID --version 2 --digest sha256:... --json
```

Export one selected section as a detached input:

```text
research-loom writer-composition section-input --workspace WORKSPACE --composition-id COMP-ID --section-id SEC-001 --output section-input --json
```

`section-input/section-writer-input.json` contains the selected Section Contract, its digest, compact outline context, exact needed material text with original capture locator/digest metadata, exact Research Exhibits, unresolved gaps, supplied research objects, Profile constraints, and immutable source pins. `manifest.json` records output path, size, digest, and a manifest digest. The export is atomic and never overwrites an existing path. The directory can be read after the original Workspace and Research Package directory are unavailable.

The export explicitly records that Evidence verification, Finding/Recommendation adoption, and Research State mutation did not occur. Writer prose import belongs to #78; research-side Writing Feedback import belongs to #79.
