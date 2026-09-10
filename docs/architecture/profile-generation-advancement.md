# Project / Profile generation advancement

Issue #128 adds a narrow production path for advancing an existing local Workspace to a later Project/Profile binding without rewriting historical research provenance.

The path is explicit. Research Package, Writer, and other downstream readers do not synthesize missing Profile semantics. Historical Runs, packages, Snapshots, Decisions, captures, and Exhibits keep the pins they were created with.

## PA0 target generation for the Composition Smoke

The Probe2-style legacy Workspace directly requests:

- `fixture.narrative` / `narrative` / `1.0.0`
- `fixture.publication` / `publication` / `1.0.0`

`profiles/fixtures/valid/narrative.profile.json` provides only the older `narrative.semantic_stages` constraint. It is intentionally left unchanged as the historical Profile generation.

The current canonical technical-smoke target is `profiles/fixtures/narrative/valid/generic-narrative.profile.json`, whose identity is `fixture.generic-narrative@1.0.0`. It provides the five Narrative definitions required by Research Package 0.2.0:

- `narrative.stages.definitions`
- `narrative.dependencies.required`
- `narrative.section_purposes.definitions`
- `narrative.preservation.required_content`
- `narrative.connections.preserve`

Because the Profile ID changes from `fixture.narrative` to `fixture.generic-narrative`, this particular migration cannot be an EPS-only refresh. The Project Config direct Narrative request must change mechanically at the same time as the Effective Profile Set. The generic fixture is an executable technical-smoke Profile; it is **not** a declaration that the legacy MISCO Writer/Publication source pack has been fully migrated.

The production resolver consumes an explicit finite set of canonical Profile manifest files under `profiles/`, resolves direct and transitive version requirements, composes the Effective Profile Set, validates canonical Narrative semantics/Core strengthening, and pins every selected manifest by exact SHA-256. An advancement re-runs that resolution and accepts the proposed EPS only when the exact document is reproduced.

## Legacy publication-writer responsibility mapping

`research-profile/` remains a migration source. Issue #128 only maps the responsibilities needed to understand the A2 transition; it does not migrate the full Human-approved source pack.

| Legacy source | Current responsibility / convergence status | Issue #128 treatment |
| --- | --- | --- |
| `03_RHETORICAL_PATTERN_LIBRARY.md` | Narrative `section_purposes` captures reusable reader-facing purpose semantics. Conditional `APPLIES_WHEN`, suggested sequence, skip rules, and rhetorical pattern selection are Writer-runtime concerns and are not yet a production Writer implementation. | Do not copy the pattern library into the generic Narrative fixture. Keep Writer-specific remainder as follow-up. |
| `04_PHASE_SPECIFIC_WRITING_RULES.md` | Narrative stages, authority prohibitions, preservation rules, and connection preservation cover the reusable semantic/read-only boundary. Actual phase-specific prose transformations and QA remain Writer responsibilities. | Reuse canonical Narrative semantics for A2; do not claim complete Writer migration. |
| `06_CONTENT_AND_NARRATIVE_GUARDS.md` | The reusable prohibitions against inventing research conclusions/links, fixed chapter/model/recommendation structures, and dropping qualifiers/counterevidence are represented by Narrative authority/preservation/connection semantics plus the Core research authority boundary. Project-specific literal structure remains non-canonical by design. | This is the principal already-converged legacy source for the A2 Narrative boundary. |
| `07_FORMAL_RENDERING_RULES.md` | Publication owns template/style, citations, numbering, layout, DOCX/PDF rendering, filenames, and render validation. A production Publication renderer/profile migration is not established by the current technical fixture. | Unconverged runtime detail; follow-up, not an A2 blocker. |
| `08_EDITORIAL_QA_CHECKLIST.md` | Some “do not create research meaning” checks are covered by the Narrative/Writer authority boundary. Detailed editorial/render QA belongs to Writer/Publication execution. | Unconverged runtime detail; follow-up. |
| `10_SKILL_ASSEMBLY_SPEC.md` | The documented Harness -> Writer -> Publication ownership split exists, and versioned Writer composition exists, but the legacy runtime assembly sequence/pattern selector/phase writer/formal renderer/QA is not a production Writer+Publication runtime. | Unconverged orchestration/runtime detail; follow-up. |

The unresolved items above are not silently discarded, but they are also not pulled into this Profile-generation migration simply to make A2 pass.

## Public operator flow

Prepare the exact target generation first. The manifest list is the finite production resolution input; every path must point to a canonical manifest under this checkout's `profiles/` tree.

Example `profile-resolve.json` for the Probe2-style technical smoke:

```json
{
  "profile_manifest_files": [
    "profiles/fixtures/valid/publication.profile.json",
    "profiles/fixtures/valid/organization.profile.json",
    "profiles/fixtures/valid/research-strict.profile.json",
    "profiles/fixtures/valid/research-base.profile.json",
    "profiles/fixtures/narrative/valid/generic-narrative.profile.json"
  ],
  "request_replacements": [
    {
      "from": {
        "profile_id": "fixture.narrative",
        "profile_type": "narrative",
        "version": "1.0.0"
      },
      "to": {
        "profile_id": "fixture.generic-narrative",
        "profile_type": "narrative",
        "version": "1.0.0"
      }
    }
  ]
}
```

Run:

```text
research-loom profile resolve \
  --workspace WORKSPACE \
  --output TARGET_GENERATION \
  --json profile-resolve.json
```

The output directory is created once and contains exact `project-config.json`, `effective-profile-set.json`, and `resolution.json` documents. Inspect them before applying. `resolution.json` records whether the Project Config request changed and the exact manifest pins used for resolution.

Apply the generated pair explicitly:

```json
{
  "project_config_file": "TARGET_GENERATION/project-config.json",
  "effective_profile_set_file": "TARGET_GENERATION/effective-profile-set.json",
  "profile_manifest_files": [
    "profiles/fixtures/valid/publication.profile.json",
    "profiles/fixtures/valid/organization.profile.json",
    "profiles/fixtures/valid/research-strict.profile.json",
    "profiles/fixtures/valid/research-base.profile.json",
    "profiles/fixtures/narrative/valid/generic-narrative.profile.json"
  ],
  "origin": "composition-smoke-a2-recovery"
}
```

```text
research-loom profile advance --workspace WORKSPACE --json profile-advance.json
research-loom profile history --workspace WORKSPACE --json
research-loom status --workspace WORKSPACE --json
research-loom resume --workspace WORKSPACE --json
```

If the current direct requests already admit a newer compatible Profile version, `request_replacements` may be empty. In that route the Project Config document/digest remains exact and only the EPS binding advances.

## Validation boundary

Advancement fails before commit when any of the following is observed:

- invalid Project Config or Effective Profile Set schema/digest;
- target Project Config requests and EPS `requested_profiles` do not match;
- the supplied EPS is not exactly reproducible from the supplied canonical manifests;
- the same Profile type/id/version is presented with different manifest content;
- a previously strengthened Core invariant is weakened;
- an executable target constraint makes current authoritative state invalid;
- Project Config changes extend beyond the permitted Profile-request/provenance evolution.

A successful advancement changes only the current Project/Profile binding. It does not verify Evidence, adopt Findings/Recommendations, mutate Research objects, or emit a new Research Snapshot.

## History, atomicity, and recovery

Before changing the current binding, the exact old and target Project Config/EPS documents are retained under `.research-loom/profile-history/generations/`. A successful advancement adds one append-only event under `.research-loom/profile-history/events/` with old/new digests, Project/Lineage, application time/origin, and the unchanged Research Snapshot binding.

The current root Project Config, Effective Profile Set, workspace binding, and active Research State binding are advanced as one recoverable operation. A pending marker records enough old state to restore the previous binding. Workspace open performs deterministic recovery when a prior advancement stopped before its success marker was cleared. The same exact target applied again is a no-op and does not add another event, Snapshot, or Decision.

Historical run/package/artifact records are never rewritten to the new generation.

## Composition Smoke continuation

After a successful Probe2 advancement, resume A2 on the **same Workspace** and with the **same RQ/material/Exhibit selection**:

```text
research-loom research-package build ...
research-loom research-package show ...
research-loom research-package export ...
research-loom research-package verify ...
```

The detached package must contain the five Narrative paths and the new Project/Profile pins while preserving the selected historical material text and Research Exhibit content. A successful technical smoke does not establish full legacy MISCO Writer/Publication convergence.
