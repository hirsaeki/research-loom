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

## Current-production inventory

Audit baseline: `main@9dfe3e978c45b5bfe34ae66ce8595eb52efe9006`.

| Object / production path | Owner | Storage class | Required payload | Arbitrary-path dependency after capture? | Integrity binding | Authority relation | Disposition |
|---|---|---|---|---|---|---|---|
| Research State object revisions / Snapshots | state repository / transition service | inline canonical payload | canonical object bodies, member refs, snapshot metadata | No. State reads use persisted revisions/Snapshots; semantic locators are not backing-file authority. | canonical object/member/Snapshot digests and revision pins | State is authoritative only through existing Human Decision / State Transition semantics. | **conforming** |
| Research Exhibit | `LocalResearchExhibitStore` | inline canonical payload | exact bounded markdown/json/text plus provenance | No. `show` returns the exact saved body; source Run/artifact refs are provenance, not backing content. | Exhibit/content digest, project/RQ/Snapshot binding | Durable working analysis only; explicitly not Evidence/Finding/Recommendation authority. | **conforming** |
| Desktop Research original capture / UTF-8 rendition | execution artifact store and managed external-original retention | managed artifact payload | exact original bytes and rendition bytes needed for content read/citation verification | No. Public `show`/`export` verifies managed artifacts and never falls back to intake path/network/OCR/LLM regeneration. | artifact identity, digest, size, Run/capture pairing, parent provenance, exact locator | Capture durability is candidate provenance only; Evidence/Finding adoption remains separate. | **conforming for managed captures** |
| Legacy / missing historical material backing | execution/material diagnostics and recovery surfaces | unavailable legacy | historical metadata may exist while required bytes do not | N/A | managed binding cannot be proven | Must stay historical/unavailable; must not be fabricated or silently treated as current managed content. | **legacy-unavailable**; tracked by #127/#157/#158 and durability work #160 |
| Project Input | `LocalProjectInputStore` | managed artifact payload + inline registry metadata | exact registered bytes | No. `source_path` is provenance only; registration copies bytes into content-addressed managed blobs and verifies them on read. | SHA-256, byte length, project/role/lineage/Snapshot binding | Durable project working input; does not adopt Research State. | **conforming** |
| Survey Instrument / design | `LocalSurveyStore` | inline canonical payload | exact canonical Instrument/design documents | No | content digests, immutable revision/identity pins | Instrument is authoritative for response semantics, but persistence itself does not create Evidence/Finding authority. | **conforming** |
| Survey canonical response / Dataset, including rejected input | `LocalSurveyResponseStore` | inline canonical payload | canonical response, exact raw intake envelope where required, validation/rejection metadata | No. Producer files are normalized at intake; persisted inspection reads the registry. | Instrument pins, raw/canonical digests, dataset content/registry identity | Explicit origin/epistemic status; `verified_evidence_claimed=false`, no Research State mutation. | **conforming** |
| Survey AnalysisSpec / AggregateResult | `LocalSurveyAnalysisStore` | inline canonical payload | exact AnalysisSpec and aggregate result content | No | deterministic RFC 8785 content digests plus Dataset/Instrument/AnalysisSpec pins | Durable analytical result only; aggregation cannot promote synthetic or REAL results to Evidence/Finding authority. | **conforming** |
| Writer Composition versions / selection history | Writer composition managed workspace store | inline canonical payload | exact immutable composition versions, indexes and selection events | No. External JSON is intake/edit surface; captured versions are copied into the managed composition root. | composition/section/package digests and immutable source pins | Exposition planning only; no Evidence verification or Finding/Recommendation adoption. | **conforming** |
| Detached one-section Writer input | Writer composition service | export projection | exact selected section plus bundled needed material/exhibits/gaps/profile constraints | No durable object depends on the detached directory. The export is intentionally self-contained for downstream use. | manifest/output digests and source pins | Export does not mutate Research State; it is not authority. | **conforming projection** |
| Research Package 0.2.0 managed package | `ResearchPackageService` managed `.research-loom` root | managed bounded package payload | package JSON/Markdown plus exact selected attachments/material text | No. Build copies exact selected content into the package; `show` verifies the managed package and export copies from it. | package digest, attachment digests/sizes, exact Snapshot/Run/Exhibit/Input/material pins | Read-only in-progress package; candidate Handoff content remains candidate-only and release ineligible unless separately authorized. | **conforming** |
| Research Package export | `ResearchPackageService.export` | export projection | copy of verified managed package | No; source package remains managed. Export refuses overwrite and managed-state destinations and verifies staging before atomic publish. | package/manifest/attachment verification | Export is not a release or Research authority transition. | **conforming projection** |
| Publication preview artifacts described by PR18 contracts | preview/convergence contract only | not implemented as production durable release store | preview manuscript/artifact manifest semantics are defined, but final renderer/release persistence is not implemented | N/A | N/A in production | Preview is diagnostic and explicitly not Publication Release. | **not implemented** |
| Final Publication candidate/release/rendered payload | none in current production code | not implemented | no production final DOCX/PDF/release-payload store exists to audit | N/A | N/A | Do not invent a storage defect or generic artifact layer for a future runtime. | **not implemented** |

## Concrete findings and disposition

The current production paths above do **not** justify a new repository-wide payload store, CAS abstraction, generic blob registry, or gate framework.

The concrete historical-material problem remains narrower: a durable execution/history record can truthfully outlive required backing bytes. Existing focused work already owns that boundary:

- #127 — exact retained-material diagnosis/recovery;
- #157 — non-authoritative source filename hints and self-contained recovery discovery;
- #158 — truthful material backing-content health;
- #160 — execution/material store durability unit and whole-root backup/move/restore contract;
- #165 — controlled reuse of verified material into a fresh workspace without authority carryover.

Those issues are not absorbed by this inventory. Other conforming domains are not rewritten for symmetry.

No additional confirmed current-production violation was found in Survey, Exhibit, Writer Composition, Research Package, or a final Publication runtime: the first four already own the content they require, while final Publication release storage is not implemented.

## Gate audit

The audited production boundaries preserve the intended ordering:

- Desktop Research copies acquired bytes into managed execution/material storage before downstream candidate use.
- Project Input copies intake bytes into managed content-addressed blobs before later package use.
- Survey capture normalizes/persists response content before aggregation.
- Writer Composition persists whole immutable proposals before selection or detached section export.
- Research Package build copies selected exact bodies/attachments into a managed immutable package before export.

None of those operations, by persistence alone, performs Evidence verification, Finding/Recommendation adoption, Research State mutation, or Publication Release.

## Liveness boundary

Managed-payload integrity may fail closed on an identity/digest/pin mismatch. Historical failure or unavailable legacy backing is not, by itself, a reason to block unrelated new work.

This umbrella is therefore not a prerequisite for every downstream feature. In particular, #165 can proceed when its narrower source-byte, destination-managed-copy, and no-authority-carryover prerequisites are verified, even if unrelated Survey/Publication storage work remains absent or unaudited in the future.

## Re-audit trigger

Update this inventory only when a production path starts persisting a new payload family or changes ownership semantics. Do not design storage for hypothetical payloads in advance.
