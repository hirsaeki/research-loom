# Research Exhibit registry

Research Exhibit is the project-scoped persistence boundary for useful analytical
representations produced during research discussion and synthesis.

It stores the analysis itself so a later conversation can retrieve the exact saved
content. It is not a generation recipe and `show` never asks an LLM to reconstruct
the artifact.

## Semantic boundary

```text
Research Exhibit exists
!= Evidence verified
!= Finding adopted
!= Recommendation approved
!= Research State mutated
```

An Exhibit is a working analytical artifact such as a table, matrix, text-based
graph specification, or analysis note.

It is deliberately distinct from:

- **Source**: externally acquired material.
- **Evidence**: a qualified extract or observation grounded in a Source.
- **Finding**: a research conclusion with research authority.
- **Execution Artifact**: output owned by one Capability Run.
- **Publication Figure/Table**: a publication object with numbering, caption,
  placement, rendering, rights, or cross-reference semantics.

PR37 does not create those objects from an Exhibit.

## Identity and storage

The first production registry is a small optional SQLite store:

```text
.research-loom/research-exhibits.sqlite3
```

It is not part of `workspace-binding.json`, Research State SQLite, or the execution
artifact store. The registry is additive and lazy:

```text
store absent + status/resume/run show -> existing behavior
store absent + exhibit list           -> empty list, no file creation
store absent + exhibit show           -> unknown Exhibit
first exhibit capture                 -> initialize the store
```

Existing workspaces therefore require no migration.

Exhibits are immutable. There is no update, edit, or delete surface. A revised
analysis is captured as a new Exhibit and may reference prior Exhibits through
`derived_from_exhibit_ids`.

## Supported content

PR37 intentionally supports only bounded analytical content representable as:

- `markdown`
- `json`
- `text`

Supported Exhibit kinds are:

- `table`
- `matrix`
- `graph`
- `note`

Markdown and text digests are SHA-256 over the exact UTF-8 bytes stored. JSON
digests are SHA-256 over the repository's RFC 8785 canonical JSON representation.
The local operational content limit is 1 MiB per Exhibit.

Binary figures, images, PDFs, presentation objects, and generic blob storage are
outside this increment.

## Harness-owned capture fields

The caller supplies the analytical description and content, but Research Loom owns:

- Exhibit identity,
- project identity,
- capture timestamp,
- current lineage/Snapshot binding,
- content digest.

The capture operation resolves every `rq_id` against the current authoritative
approved Research Questions. Optional `source_run_ids` must resolve to Runs in the
current project. Optional `source_artifact_refs` must resolve to artifacts owned by
one of those declared Runs. These links are provenance only; capture never changes
the source Run or adds execution artifacts to a completed Run.

`source_object_ids` remain lightweight provenance references. PR37 does not add a
generic Research Object resolver or collapse candidates and authoritative objects
into a new authority model.

## Public surface

The transport-neutral Application Facade exposes:

```text
capture_exhibit(...)
list_exhibits(...)
show_exhibit(...)
```

The canonical CLI is:

```text
research-loom exhibit capture --workspace PATH --json EXHIBIT.json
research-loom exhibit list --workspace PATH --json
research-loom exhibit list --workspace PATH --rq-id RQ-ID --json
research-loom exhibit show --workspace PATH --exhibit-id EXH-ID --json
```

`capture` persists exact content and metadata. `list` is a metadata-only projection,
bounded to 100 results with an explicit `truncated` flag. `show` returns the exact
saved content and provenance.

`list` and `show` are read-only. `capture` changes only the Research Exhibit
registry. None of these operations create a StateDeltaProposal, Confirmation,
Human Decision, StateTransition, new Research Snapshot, or Run mutation.

## Run and Research State boundaries

An Exhibit may synthesize several Runs or be created directly from a research
conversation. Therefore a Run is never mandatory Exhibit identity.

```text
Desktop Research Run
  -> source capture / retrieval provenance
  -> completed Run

later synthesis
  -> Research Exhibit
     source_run_ids = [...]
     source_artifact_refs = [...]
```

This avoids falsely claiming that a completed Capability Run generated an analysis
which was actually produced later.

The Exhibit also records the active lineage, Snapshot reference, and Snapshot digest
at capture time. Those bindings explain the Research State context in which the
analysis was saved without making the Exhibit a member of Research State.

## Future Writer and Publication use

Writer may later receive selected Research Exhibits through a Research Package, and
Publication may later turn selected analytical material into numbered/rendered
figures or tables. PR37 intentionally adds neither integration. The registry first
establishes only durable capture and exact retrieval.
