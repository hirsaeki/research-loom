# Managed payload ownership boundary

Issue #163 records one repository-wide persistence rule without introducing a universal storage framework.

## Contract

A durable Loom object must not require an unmanaged workspace path, scratch/intake file, caller-owned temporary file, or ordinary export projection in order to be used, verified, or reproduced.

Use the smallest natural storage class for the payload:

1. **inline canonical payload** — bounded structured JSON/text stored by the owning durable registry;
2. **managed artifact payload** — opaque, large, binary, or non-reproducible bytes stored inside a Loom-managed artifact/blob boundary and referenced by stable identity plus digest;
3. **export projection** — a disposable filesystem rendering derived from managed state/content, never authority by location alone;
4. **intake / scratch** — caller/tool/operator input used only during capture/import and never authority merely because it exists under a workspace.

Persistence and research authority are independent:

```text
durable != authoritative
```

Persisting an Exhibit, Dataset, Aggregate, Composition, Research Package, capture, or rendered working artifact never verifies Evidence, adopts a Finding/Recommendation, answers an RQ, or commits Research State. Existing Human Decision / State Transition boundaries remain authoritative.

For a gate that depends on non-reproducible payload, bytes must already be managed and integrity-bound before the candidate reaches the gate:

```text
generation / acquisition
  -> intake / scratch
  -> managed persistence
  -> stable identity + digest
  -> proposal / release candidate
  -> authority gate
```

A gate must not promote an arbitrary filesystem path into durable authority.

Legacy truthfulness is equally important: when managed backing bytes cannot be proven, report the payload as unavailable. Do not reconstruct identity from filenames, neighboring files, URLs, or semantic similarity.

## Payload-resolution invariant

Being somewhere below `.research-loom` is not sufficient by itself. A durable object must have a stable lookup chain from durable workspace/object metadata to the content required to use or verify it.

For file-backed payloads, the target model is:

```text
workspace durable metadata
  -> registered store identity + root-relative locator
  -> durable object metadata / stable object identity
  -> managed relative locator or deterministic digest/ID-derived location
  -> verified bytes
```

The physical host path is operational configuration, not content identity or research provenance. A store may derive a content path from a verified digest/ID instead of storing the literal path in every row; what matters is that the store root is durably registered and the payload can be resolved without an arbitrary external path.

This preserves the original SQLite/files responsibility split without forcing storage uniformity:

- SQLite/registries own structured identity, relations, history, indexes, pins, digests, and store/object metadata;
- managed files/CAS own bytes that should not be embedded into SQLite merely for uniformity;
- export/publish files remain projections rather than authority.

A deterministic code convention alone is weaker than a workspace persistence contract. In particular, if a later-added durable store exists only because application code knows a hard-coded `.research-loom/...` path, workspace metadata cannot distinguish that store from an unknown/unmanaged path or comprehensively diagnose its disappearance.

## Workspace storage-root audit

Audit baseline: `main@9dfe3e978c45b5bfe34ae66ce8595eb52efe9006`.

The current `workspace-binding.json` `storage` map registers these roots:

- `research_state`;
- `conversation`;
- `decision`;
- `execution_root` / `execution`;
- `context_extensions`;
- `operational_trace`.

Later production stores are instead located by application constants/conventions and are not represented in that durable workspace storage map:

- `attention.sqlite3`;
- `research-exhibits.sqlite3`;
- `survey-registry.sqlite3`;
- `survey-response-registry.sqlite3`;
- `survey-analysis-registry.sqlite3`;
- `project-inputs/`;
- `writer-compositions/`;
- `research-packages/`.

This is a concrete workspace-level ownership/discoverability gap, tracked by #193. It does **not** mean those domain stores need to be merged into one database or rewritten internally.

## Current-production inventory

| Object / production path | Durable owner / metadata | Payload resolution chain | Workspace-root registration | Integrity binding | Authority relation | Disposition |
|---|---|---|---|---|---|---|
| Research State object revisions / Snapshots | registered Research State SQLite store | registered `research_state` root -> object/revision or Snapshot key -> canonical JSON row | **registered** in `workspace-binding.json` | canonical object/member/Snapshot digests and revision pins | State is authoritative only through existing Human Decision / State Transition semantics. | **conforming** |
| Research Exhibit | `LocalResearchExhibitStore`; immutable document and index metadata are inline in SQLite | `exhibit_id` -> SQLite `document_json`; no external body is required | **not registered**; store file is found by `.research-loom/research-exhibits.sqlite3` convention | Exhibit/content digest, project/RQ/Snapshot binding | Durable working analysis only; explicitly not Evidence/Finding/Recommendation authority. | Object payload is sound; **workspace store-root registration gap (#193)** |
| Desktop Research original capture / UTF-8 rendition | execution SQLite artifact metadata + execution/material managed blob store | registered execution root -> `artifact_id` -> `storage_locator` + digest/size -> root-relative managed blob -> verified bytes | **registered** through `execution_root` / `execution` | artifact identity, digest, size, Run/capture pairing, parent provenance, exact locator | Capture durability is candidate provenance only; Evidence/Finding adoption remains separate. | **conforming for managed captures** |
| Legacy / missing historical material backing | execution/material diagnostics and recovery surfaces | historical metadata resolves expected artifact identity/digest, but backing blob is absent/unprovable | execution store is registered, but required legacy payload is unavailable | managed binding cannot be proven | Must stay historical/unavailable; must not be fabricated or silently treated as current managed content. | **legacy-unavailable**; #127/#157/#158, durability #160 |
| Project Input | `LocalProjectInputStore` SQLite metadata + managed blob tree | `input_id` -> `content_digest` + byte length -> digest-derived blob path under Project Input root -> verified bytes; `source_path` is provenance only | **not registered**; root is derived as `.research-loom/project-inputs` in code | SHA-256, byte length, project/role/lineage/Snapshot binding | Durable project working input; does not adopt Research State. | Object-to-bytes chain is sound; **workspace store-root registration gap (#193)** |
| Survey Instrument / design | `LocalSurveyStore` SQLite registry | project + questionnaire/design identity/version -> inline `document_json` | **not registered**; DB path comes from `.research-loom/survey-registry.sqlite3` convention | content digests, immutable revision/identity pins | Instrument is authoritative for response semantics, but persistence itself does not create Evidence/Finding authority. | Inline payload is sound; **workspace store-root registration gap (#193)** |
| Survey canonical response / Dataset, including rejected input | `LocalSurveyResponseStore` SQLite registry | response/Dataset identity -> inline canonical/raw/entry JSON rows | **not registered**; DB path comes from `.research-loom/survey-response-registry.sqlite3` convention | Instrument pins, raw/canonical digests, dataset content/registry identity | Explicit origin/epistemic status; no Research State mutation. | Inline payload is sound; **workspace store-root registration gap (#193)** |
| Survey AnalysisSpec / AggregateResult | `LocalSurveyAnalysisStore` SQLite registry | AnalysisSpec/Aggregate identity -> inline `document_json` | **not registered**; DB path comes from `.research-loom/survey-analysis-registry.sqlite3` convention | deterministic content digests plus Dataset/Instrument/AnalysisSpec pins | Durable analytical result only; aggregation cannot promote results to Evidence/Finding authority. | Inline payload is sound; **workspace store-root registration gap (#193)** |
| Writer Composition versions / selection history | immutable JSON files in the Writer managed root; no SQLite object registry | `composition_id` + version -> deterministic `writer-compositions/<id>/versions/<version>.json`; selection -> sibling `selection.json`; source Research Package pin is verified on load | **not registered**; root is hard-coded as `.research-loom/writer-compositions` | composition/section/package digests and immutable source pins | Exposition planning only; no Evidence verification or Finding/Recommendation adoption. | Managed/deterministic, but resolution begins from a code path convention; **workspace store-root registration gap (#193)** |
| Detached one-section Writer input | Writer composition service export | self-contained export directory -> manifest -> exact section input | projection; intentionally outside managed state | manifest/output digests and source pins | Export does not mutate Research State; it is not authority. | **conforming projection** |
| Research Package 0.2.0 managed package | immutable managed package directory; package JSON carries attachment metadata | `package_id` -> deterministic `research-packages/<package_id>` root -> `research-package.json` -> relative attachment paths + digest/size -> verified package files | **not registered**; root is hard-coded as `.research-loom/research-packages` | package digest, attachment digests/sizes, exact Snapshot/Run/Exhibit/Input/material pins | Read-only in-progress package; candidate Handoff content remains candidate-only and release ineligible unless separately authorized. | Internal package locator chain is sound after root resolution; **workspace store-root registration gap (#193)** |
| Research Package export | `ResearchPackageService.export` | verified managed package -> staging -> external output copy | projection; not a managed source root | package/manifest/attachment verification | Export is not a release or Research authority transition. | **conforming projection** |
| Publication preview artifacts described by PR18 contracts | preview/convergence contract only | no production durable release payload store | N/A | N/A in production | Preview is diagnostic and explicitly not Publication Release. | **not implemented** |
| Final Publication candidate/release/rendered payload | none in current production code | no production final DOCX/PDF/release-payload store exists to resolve | N/A | N/A | Do not invent a storage defect or generic artifact layer for a future runtime. | **not implemented** |

`attention.sqlite3` is also a production durable store located by convention and omitted from the current workspace storage map. It is not a payload family named in #163's object inventory, but it is included in #193 because the workspace-level registration contract should not knowingly omit an existing durable store.

## Concrete findings and disposition

The repository does **not** justify one universal payload DB, one generic CAS, or moving every file into SQLite. The useful common rule is metadata-driven resolution of owned stores and payloads.

Two concrete classes of work remain:

1. **Historical execution/material backing can be unavailable even when metadata survives.** Existing focused work owns that boundary:
   - #127 — exact retained-material diagnosis/recovery;
   - #157 — non-authoritative source filename hints and self-contained recovery discovery;
   - #158 — truthful material backing-content health;
   - #160 — execution/material store durability unit and whole-root backup/move/restore contract;
   - #165 — controlled reuse of verified material into a fresh workspace without authority carryover.
2. **Workspace durable-store metadata is incomplete.** Later production stores are owned only through hard-coded root conventions rather than the workspace storage map. #193 owns the minimal fix: register/track current durable store roots and make initialized-vs-missing state diagnosable, while preserving each domain's current internal storage layout.

The second finding corrects the earlier, weaker conclusion that all managed-domain paths were simply conforming because they lived below `.research-loom`.

## Gate audit

The audited production boundaries preserve the intended authority ordering:

- Desktop Research copies acquired bytes into managed execution/material storage before downstream candidate use.
- Project Input copies intake bytes into managed content-addressed blobs before later package use.
- Survey capture normalizes/persists response content before aggregation.
- Writer Composition persists whole immutable proposals before selection or detached section export.
- Research Package build copies selected exact bodies/attachments into a managed immutable package before export.

None of those operations, by persistence alone, performs Evidence verification, Finding/Recommendation adoption, Research State mutation, or Publication Release.

The workspace store-root registration fix in #193 must likewise remain operational metadata only. It must not become a new authority gate.

## Liveness boundary

Managed-payload integrity may fail closed on an identity/digest/pin mismatch. Historical failure, an unavailable legacy backing blob, or an unrelated missing optional store is not by itself a reason to block valid new work.

#193 therefore needs to distinguish:

- a store that was never initialized and is legitimately absent;
- a store durably known to have been initialized but is now missing/degraded;
- legacy workspaces where prior use cannot be proven from durable metadata.

Do not solve this by making every possible lazy store mandatory on every workspace.

The #163 umbrella remains non-blocking for narrower downstream work. In particular, #165 can proceed when its source-byte, destination-managed-copy, and no-authority-carryover prerequisites are verified.

## Re-audit trigger

Update this inventory when a production path starts persisting a new payload/store family or changes ownership/resolution semantics. New durable stores should not be added only as hard-coded `.research-loom/...` conventions without corresponding workspace-level ownership metadata.
