# Durable payload ownership and portable store tree

Issue #163 audits current production persistence against one repository-wide rule:

> Every durable Loom payload must belong to one Loom-managed Parent Durable Store Root tree, and Loom must be able to resolve and verify that payload from durable metadata plus that tree without depending on an original intake path, scratch file, caller-owned temporary file, ordinary export projection, or former host absolute path.

This is a storage-ownership and portability rule, not a request for one universal database, one universal CAS, or one storage technology for every domain.

## Target model

The workspace durable state should form one tree rather than a forest of unrelated durable roots:

```text
Parent Durable Store Root
├─ parent/workspace storage metadata
├─ durable child / leaf
│  ├─ metadata / index / SQLite
│  └─ required managed payload bytes, when not inline
├─ durable child / leaf
└─ ...
```

For a non-inline payload, the required resolution chain is:

```text
Parent Durable Store Root
  -> parent metadata / declared child location
  -> child durable store
  -> stable object/artifact identity + domain metadata
  -> store-relative locator or deterministic digest/ID-derived location
  -> verified payload bytes
```

For an inline canonical payload, the final steps collapse into the durable record itself.

A path being below `.research-loom` is useful but is not sufficient on its own. The Parent durability unit, natural child boundary, resolution chain, and integrity behavior must be explicit enough that the data can be preserved and reopened correctly.

## Current Parent candidate and concrete tree violation

Audit baseline: `main@9dfe3e978c45b5bfe34ae66ce8595eb52efe9006`.

The current implementation already has a natural dedicated Parent candidate:

```text
<workspace>/.research-loom/
```

Most Loom-owned durable stores live below it. That makes a migration to the target model substantially smaller than inventing a new storage framework.

However, two workspace-owned documents required by `LocalWorkspace.open()` are currently persisted outside that Parent candidate:

```text
<workspace>/project-config.json
<workspace>/effective-profile-set.json
```

`workspace-binding.json` points to them, `open()` reads and digest-validates them, Profile advancement rewrites them, and Writer/Virtual Runner paths consume the effective Profile Set. Therefore they are durable workspace dependencies, not disposable intake files.

If `.research-loom/` is the Parent Durable Store Root, these two files are a **confirmed tree-membership violation**. #193 owns the structural correction. Their original caller-supplied input files remain intake; the persisted workspace-owned copies are durable.

## Parent discovery is also incomplete

The current `.research-loom/workspace-binding.json` `storage` map registers only:

- `research_state`;
- `conversation`;
- `decision`;
- `execution_root` / `execution`;
- `context_extensions`;
- `operational_trace`.

Other current production durable children/leaves already live below `.research-loom/` but are found only from application conventions, including:

- `attention.sqlite3`;
- `profile-history/`;
- `research-exhibits.sqlite3`;
- `survey-registry.sqlite3`;
- `survey-response-registry.sqlite3`;
- `survey-analysis-registry.sqlite3`;
- `project-inputs/`;
- `writer-compositions/`;
- `research-packages/`.

This does not make their internal payload layouts wrong. It means the Parent tree is only partly self-describing: a whole-Parent durability/doctor operation cannot determine every initialized durable child from parent metadata, and disappearance of some lazy stores can be confused with “never initialized”. #193 owns this Parent-to-child discovery/missing-state gap.

## Storage classes remain intentionally heterogeneous

The tree model does not require internal homogenization.

Valid durable leaves/children of the Parent Durable Store Root include:

1. **inline canonical payload** — bounded JSON/text persisted inside the owning SQLite/registry record;
2. **managed artifact payload** — opaque/large/non-reproducible bytes stored inside a child managed file/CAS boundary with stable identity plus digest/size;
3. **immutable managed file/package payload** — deterministic managed files below a child root with integrity metadata.

Non-durable workspace-adjacent classes are explicitly outside the Parent tree:

4. **export projection** — derived external output, never a durable child or authority;
5. **intake / scratch** — caller/operator/tool input, disposable after successful managed persistence.

Do not move large binary payloads into SQLite merely for uniformity, and do not force bounded canonical JSON/text into CAS merely for visual symmetry.

## Durable, portable, and authoritative are different dimensions

```text
durable != authoritative
portable != authoritative
imported != adopted
```

Persisting, moving, backing up, restoring, or importing an Exhibit, Dataset, Aggregate, Composition, Research Package, capture, or other payload does not verify Evidence, adopt a Finding/Recommendation, answer an RQ, or commit Research State. Existing Human Decision / State Transition semantics remain the authority boundary.

For an authority/release gate that depends on non-reproducible payload, managed persistence must occur before the gate:

```text
generation / acquisition
  -> intake / scratch
  -> managed durable tree
  -> stable identity + digest
  -> proposal / release candidate
  -> authority gate
```

A gate must never turn an arbitrary filesystem path into durable authority.

## Current-production inventory

| Durable family / path | Parent membership | Natural child / leaf | Metadata -> payload resolution | Parent discovery | Independent child portability | Integrity / authority | Disposition |
|---|---|---|---|---|---|---|---|
| Workspace binding | inside `.research-loom` | Parent metadata leaf: `workspace-binding.json` | binding document directly carries workspace/project/storage locators and pins | n/a: this is the Parent metadata | not required | binding shape/version validated; no Research authority by itself | **conforming Parent metadata, but currently incomplete inventory** |
| Persisted Project Config | **outside `.research-loom`** at workspace root | durable JSON leaf required by workspace open/profile advancement | binding locator -> root-level JSON -> digest validation | binding does identify it, but outside Parent | not required | digest-bound; configuration persistence is not Research adoption | **structural violation -> #193** |
| Persisted Effective Profile Set | **outside `.research-loom`** at workspace root | durable JSON leaf required by workspace open and downstream Profile/Writer use | binding locator -> root-level JSON -> digest validation | binding does identify it, but outside Parent | not required | digest-bound; Profile persistence does not itself adopt Research conclusions | **structural violation -> #193** |
| Research State revisions / Snapshots | inside Parent | SQLite leaf `research-state.sqlite3` | registered `research_state` -> object/revision or Snapshot key -> inline canonical record | **registered** | not required | canonical object/member/Snapshot digests and revision pins; authority only through State Transition/Human Decision | **conforming** |
| Conversation store | inside Parent | SQLite leaf `conversation.db` | registered leaf -> durable conversation records | **registered** | not required | schema/integrity checks; conversational persistence is not Research authority | **conforming** |
| Human Decision store | inside Parent | SQLite leaf `decision.db` | registered leaf -> durable decision records | **registered** | not required | decision semantics remain explicit authority input | **conforming** |
| Research Attention | inside Parent | SQLite leaf `attention.sqlite3` | domain identity -> inline durable attention records | **not registered; code convention** | not required | durable planning/control state; separate from Research object adoption | **Parent discovery gap -> #193** |
| Profile advancement history | inside Parent | managed `profile-history/` subtree | Profile advancement metadata/events/generation records under deterministic child root | **not registered; code convention** | not required | historical profile advancement facts; authority semantics unchanged | **Parent discovery gap -> #193** |
| Execution / external material / renditions | inside Parent under `execution/` | multi-file child root: `execution.db` + `blobs/sha256/...` + committed execution-side SQLite leaves; staging transient | `artifact_id` / resource identity -> SQLite metadata -> `storage_locator` + digest/size -> store-local managed blob -> verified bytes | `execution_root` and core execution leaves **registered** | **required use case**: copied child root should be openable read-only after staging for #165 | digest/size/binding verification; capture durability is candidate provenance, not Evidence/Finding adoption | **current shape matches target; independent portability contract tracked by #160** |
| Legacy execution metadata with missing backing content | inside execution child metadata, required bytes unavailable | same execution child | metadata resolves expected identity/digest but backing bytes are missing/unprovable | execution child registered | unavailable source must remain unavailable | metadata presence never implies content health; no fabricated recovery | **legacy-unavailable; #127/#157/#158, durability #160** |
| Research Exhibit | inside Parent | inline SQLite leaf `research-exhibits.sqlite3` | `exhibit_id` -> SQLite immutable `document_json`; source refs are provenance, not backing content | **not registered; code convention** | no current independent-portability requirement | Exhibit/content digest + project/RQ/Snapshot binding; not Evidence/Finding/Recommendation authority | **payload layout conforming; Parent discovery gap -> #193** |
| Project Input | inside Parent | multi-file child root `project-inputs/` with SQLite metadata + digest-derived `blobs/` | `input_id` -> metadata `content_digest` + length -> child-root digest path -> verified bytes; original `source_path` provenance only | **not registered; code convention** | no current independent-portability requirement | SHA-256/length/project/role/lineage/Snapshot binding; does not adopt Research State | **payload layout conforming; Parent discovery gap -> #193** |
| Survey Design / Instrument | inside Parent | inline SQLite leaf `survey-registry.sqlite3` | project + design/questionnaire identity/version -> inline `document_json` | **not registered; code convention** | not required | immutable identity/version/content digests; persistence does not create Evidence/Finding authority | **payload layout conforming; Parent discovery gap -> #193** |
| Survey canonical Response / Dataset / rejected input | inside Parent | inline SQLite leaf `survey-response-registry.sqlite3` | response/Dataset identity -> inline canonical/raw/entry JSON rows | **not registered; code convention** | not required | Instrument/raw/canonical/Dataset digests and origin/epistemic status; no Research State mutation | **payload layout conforming; Parent discovery gap -> #193** |
| Survey AnalysisSpec / AggregateResult | inside Parent | inline SQLite leaf `survey-analysis-registry.sqlite3` | spec/result identity -> inline canonical `document_json` rows | **not registered; code convention** | not required | deterministic content digests and Dataset/Instrument/Spec pins; analytical durability is not research adoption | **payload layout conforming; Parent discovery gap -> #193** |
| Writer Composition versions / selection history | inside Parent | managed file child root `writer-compositions/` | `composition_id` + version -> deterministic managed JSON version; source Research Package ID/digest is resolved and revalidated from sibling Package child | **not registered; code convention** | not required; Writer child may depend on sibling durable Package child when whole Parent is preserved | composition/section/package digests and immutable source pins; exposition planning only | **whole-Parent model is suitable; Parent discovery gap -> #193** |
| Detached one-section Writer input | outside Parent intentionally | export projection | self-contained exported manifest/section payload | n/a | external handoff only | manifest/output digests and source pins; no Research State mutation | **conforming projection, not a durable-tree dependency** |
| Research Package managed package | inside Parent | managed file child root `research-packages/`; one immutable package directory per `package_id` | `package_id` -> deterministic child path -> `research-package.json` -> relative attachment paths + digest/size -> verified package files | **not registered; code convention** | not currently required independently; package export is the external projection | package + attachment digests/sizes and exact source pins; preview/candidate content remains non-authoritative | **payload layout conforming; Parent discovery gap -> #193** |
| Research Package export | outside Parent intentionally | export projection | verified managed package -> staging -> detached output | n/a | projection already self-contained for handoff | verification preserves package bytes/digests; export is not Publication Release | **conforming projection** |
| Publication preview contract | no production durable payload store | not implemented durable child | no production durable release payload to resolve | n/a | n/a | Preview is diagnostic, not release authority | **not implemented** |
| Final Publication candidate/release/rendered payload | no production implementation | not implemented | none | n/a | n/a | do not invent release/storage semantics before implementation exists | **not implemented** |

## What #193 must fix, and what it must not fix

The repository-wide structural problem is now narrow and concrete:

1. make all workspace-owned durable dependencies descendants/leaves of one dedicated Parent Durable Store Root;
2. move or otherwise bring the persisted Project Config and Effective Profile Set into that Parent tree while preserving their current digest/binding semantics;
3. make Parent metadata sufficiently self-describing to know which current durable children/leaves have been initialized/used;
4. distinguish “never initialized optional child” from “known durable child now missing/degraded”;
5. keep child locators root-relative/backend-relative so whole-Parent move/reopen does not require host-path rewrites.

#193 must **not** merge all domain stores into one DB, invent one generic CAS, or make every child independently importable. Existing domain-local layouts that already resolve their payload correctly should remain.

## Execution/material child portability: #160

The execution/material subtree has an additional concrete use case beyond ordinary Parent membership:

```text
copied execution/material child root
  -> stage under destination workspace intake
  -> open staged copy independently/read-only
  -> read its SQLite metadata
  -> resolve store-local blobs
  -> verify exact selected material
```

That stronger child-root contract is tracked by #160. The existing `execution.db + blobs` physical shape already matches it closely; #160 should verify/formalize path-independent move/restore/read-only opening rather than redesign the storage technology.

The Parent and child contracts are compatible:

```text
whole workspace durability: Parent Root includes execution/material child
selected cross-workspace reuse: #165 stages a copied source root under destination intake, then consumes that staged copy
```

Independent child portability does not create a second competing Parent tree.

## Cross-workspace intake: #165

The canonical #165 workflow is not a live reference to an arbitrary external previous-workspace path. It first creates a stable workspace-local intake snapshot:

```text
previous workspace / backup / portable child root
  -> copy/stage into destination workspace dedicated intake area
  -> original external source may disappear
  -> open staged copy read-only
  -> source SQLite/domain metadata
  -> selected Run/capture/material identity
  -> staged store-local verified bytes
  -> copy selected material into destination Parent tree
  -> new destination material identity/provenance
  -> current Desktop Research Run
```

The dedicated intake area is outside the destination Parent Durable Store Root. It is disposable input, not destination durability. A full previous workspace/root container or the smaller independently portable execution/material child may be staged; use the smallest self-contained unit that preserves the metadata and bytes needed for exact verification.

After staging succeeds, import reads only the staged copy. The original source path is no longer part of the operation. After destination import commits, the staged intake tree may also be deleted without breaking destination material read/use.

A direct import from an arbitrary external live path is therefore not the canonical MVP. It may be considered later only if a concrete need justifies the added consistency/lifecycle semantics.

Old Snapshot/Lineage/Run/Finding/candidate authority remains provenance only and is never imported as current authority.

#165 depends on the **staged source-root capability** from #160, not on every unrelated child store becoming independently portable and not on closing the whole #163 umbrella.

## Legacy truthfulness and liveness

Missing/corrupt backing content must remain distinguishable from healthy payload. Legacy identity must not be fabricated from filenames, nearby files, URLs, semantic similarity, or mere metadata presence.

At the same time, historical failure must not become unrelated operational blockage. Parent/child integrity checks should fail closed only for the durable child/payload that is actually required by the requested operation.

A lazy optional child that was never initialized is not corruption. A child that Parent metadata proves existed but is now absent is degraded. An old workspace whose prior child existence cannot be proven remains legacy-ambiguous rather than being retroactively invented.

## Issue decomposition after this audit

No additional storage Issue is needed beyond the current focused set:

- **#193** — make workspace durability one hierarchical Parent Durable Store Root tree and correct current tree/discovery violations;
- **#160** — formalize the execution/material subtree as a portable self-contained child Durable Store Root, including independent read-only source opening after staging/copy;
- **#165** — stage a previous source root under destination workspace intake, then import selected verified material from that stable read-only copy into the destination Parent tree without authority carryover;
- **#158 / #127 / #157** — retain their narrower material-health/recovery/discovery responsibilities.

This decomposition intentionally avoids a new universal storage framework.

## Re-audit trigger

Re-audit when a production path adds a new durable payload/store family or changes ownership/resolution semantics. New durable state should join the Parent tree deliberately rather than appearing only as another hard-coded workspace path.
