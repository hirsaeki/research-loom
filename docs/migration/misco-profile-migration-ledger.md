# MISCO legacy Profile migration ledger

Status: **Issue #331 design inventory**
Baseline: `main@1ea6ad38fcf09eab24e44aa7e5bb4b6afec90578` (2026-09-28)
Machine-readable ledger: [`misco-profile-migration-ledger/index.json`](misco-profile-migration-ledger/index.json)

This ledger fixes the migration boundary for #332–#337. It does **not** change runtime behavior and is not evidence that migration is complete.

## 1. Inventory result

The ledger pins 44 source files by SHA-256 and classifies the relevant content into project/publication/support plus six bounded Writer shards:

- `project.json`: all three legacy manifest entries, the Research Attention / initial publication map headings, and the non-canonical Virtual Run feedback headings.
- `writer-01.json` … `writer-06.json`: the approved Writer-facing runtime rules, input contract, rhetorical patterns, negative narrative guards, terminology firewall, editorial QA, assembly views, and synthetic example specifications.
- `publication.json`: formal Publication rules and the formal-rendering view, including the runtime reflections of the four resolved Human Review decisions.
- `support.json`: Layer B audit provenance, Layer C Human Review/decision provenance, legacy consumer references, and current Core/Profile protections that must not be reimplemented.

All files under `MISCO_Publication_Clean_Source_Pack_v1.0.2_HUMAN_APPROVED/` are enumerated, including `MANIFEST.json`, validation material, the Layer C DOCX support artifact, and every manifest-listed file. The pack's 51 `PUB-*` runtime rule IDs are represented exactly once as policy identities. `01_PUBLICATION_STYLE_CONTRACT.md` is recorded as an alias representation of the JSON contract rather than as a second rule set.

## 2. Migration decisions

### 2.1 Already converged: preserve, do not rebuild

The following are current-system protections or canonical semantics, not payload to copy out of legacy files:

- Core provenance, identity, immutable history, candidate/authoritative separation, and Human Decision invariants.
- Profile composition: same-type `extends`, cross-type `requires`, and no cross-category last-write-wins.
- Generic Research Quality semantics already represented by `profiles/contracts/research-quality-policy.yaml`.
- Generic Narrative read-only/preservation semantics already represented by `profiles/contracts/narrative-semantics.yaml`.
- Production enforcement of machine-representable effective constraints before authoritative commit.
- Writer/Publication's read-only relationship to authoritative Research State.

#332–#337 may connect to these boundaries, but must not create a second resolver, second authority model, or duplicate Core guard set.

### 2.2 Research / Organization

The approved Publication pack is **not** a source of generic Research quality semantics. Generic source/evidence/claim/finding quality has already converged into the current Research Profile contract.

#332 should create real Research / Organization manifests only for concrete reusable constraints still absent from production. #333 then proves those constraints reach real research operations and quality checks. MISCO terminology or handling policy belongs to Organization Profile only when it is reusable across MISCO projects; the 2026 topic, concrete questions, current attention, and provisional chapter placement do not.

### 2.3 Narrative / Writer

The approved pack mixes reusable prohibitions with rendering behavior:

- reusable prohibitions already overlapping canonical Narrative semantics remain current-protection/regression boundaries;
- rhetorical patterns, phase-specific prose transformations, reader-facing terminology, editorial QA, and input/return rules are Writer responsibilities;
- literal chapter ordering in the Attention map is project-specific and does not become a reusable Narrative stage graph;
- synthetic few-shot specifications stay synthetic. They are tests/examples, never Evidence or runtime authority.

#334 consumes the current Narrative contract plus only the missing approved Writer behavior. It must not make Writer a research-decision producer.

### 2.4 Publication

Formal layout, figure/table presentation, citation/display, footnotes, outer document structure, permission/anonymization checks, and formal-spec-driven rendering belong to Publication Profile / Publication Skill (#335).

The four Human Review decisions are preserved, not re-voted:

| Decision | Preserved meaning | Runtime consequence |
|---|---|---|
| HD-01 = A | page/font/indent settings come from the current formal specification original | missing formal input → `HUMAN_DECISION_REQUIRED`; do not infer values |
| HD-02 = A | bibliography placement follows the current formal specification original | same missing-input behavior as HD-01 |
| HD-03 = B | long raw URLs use a separately human-approved reader-facing display profile | the concrete display pattern is still an input; do not invent it |
| HD-04 = B | color-figure QA is conditional | apply only when color figures are actually used |

Layer C is decision provenance. The runtime source remains the corresponding Layer A reflection.

### 2.5 Project Config / Attention / Outline

`research_attention_and_initial_publication_map.md` explicitly states that Attention is not Evidence, does not choose methods, does not determine answers, and that its chapter tree is provisional. Its migration target is therefore #336's project/Attention/outline binding, not reusable Research/Narrative/Publication policy.

`virtual_run_feedback_v0.1.md` is explicitly non-canonical Project Knowledge. It can be bound as project input where useful, but must not be silently promoted into reusable Profile constraints. A reusable promotion would require a separate authority decision.

## 3. Runtime / audit / review separation

```text
Layer A  -> approved runtime source material
Layer B  -> audit/provenance only
Layer C  -> Human Review / decision provenance only
```

The legacy generated Writer Skill and its source index are migration references, not a new authority source. New production runtime must resolve current Profile manifests and current consumers; it must not import the old `research-profile/` or legacy `research-harness/.codex/skills/misco-publication-writer` tree as hidden authority.

## 4. Consumer / acceptance matrix

| Material | Declared | Reaches production input today | Evaluated today | Publicly explainable today | Migration owner |
|---|---:|---:|---:|---:|---|
| Current Profile composition contract | yes | yes | yes | yes | already preserved |
| Generic Research Quality semantics | yes | only via current/synthetic effective constraints | partial | partial | #332 / #333 |
| Generic Narrative semantics | yes | fixture/spec paths exist; no production MISCO Narrative manifest | fixture-level | not end-to-end | #332 / #334 |
| 51 approved `PUB-*` rules | yes, legacy Layer A | legacy Writer only | legacy checks only | no current production Profile proof | #334 / #335 |
| Rhetorical / phase / terminology Writer rules | yes, legacy Layer A | legacy Writer only | legacy checks | no | #334 |
| Formal rendering / citation / display rules | yes, legacy Layer A | legacy Publication path only | incomplete without formal inputs | partial | #335 |
| Project Attention map | yes | legacy Harness path | current Attention lifecycle exists, but no MISCO migration binding | partial | #336 |
| Virtual Run feedback | yes, non-canonical | not reusable Profile input | n/a | n/a | #336 |
| Layer B provenance | yes | intentionally no | audit only | audit only | #337 |
| Layer C Human Review / HD decisions | yes | intentionally no as runtime rules | decision provenance | audit only | #335 / #337 |

A rule is not considered “applied” merely because it is declared or can be injected by a test helper. Completion requires current production manifest resolution, consumer delivery, the relevant machine/Host/Human check, and an explainable public result.

## 5. Missing formal inputs

Four concrete input gaps are recorded in `index.json`. None is permission to guess:

1. current MISCO formal specification original or approved `formal_spec_profile`;
2. the human-approved long-URL reader-facing display profile selected by HD-03 (the concrete pattern is not present in the pack);
3. `research_group_type` or equivalent metadata when formal outer structure branches on it; and
4. permission/anonymization/original-review status for non-public interview/internal material when it is published.

These gaps block only the operation that actually requires them. A missing Publication-only input must not block unrelated source collection, research candidate creation, or other research work.

## 6. Child-Issue scope after inventory

- **#332 — production Profile assets / resolver connection:** create actual Research, Organization, Narrative, and Publication manifests/assets with the current resolver. Do not copy Layer B/C into runtime constraints.
- **#333 — Research / Organization application:** make configured research-quality/organization rules affect real research operations and checks without weakening Core floors.
- **#334 — Narrative / Writer application:** consume canonical Narrative semantics plus the approved Writer transformation/QA rules; keep Writer read-only and synthetic examples synthetic.
- **#335 — Publication application:** apply formal/citation/display/permission rules and surface missing formal inputs instead of inventing values.
- **#336 — project/workspace migration:** bind MISCO project-specific Attention, outline hints, production config, and non-canonical project knowledge; explicitly advance existing workspaces without rewriting historical pins.
- **#337 — integrated acceptance / audit:** prove research → package → multi-section writing → single-section revision → publication preview with real Profiles, plus an ablation and preserved audit/decision provenance.

The dependency graph in #330 remains valid; this inventory narrows payload, it does not add a new framework or new dependencies.

## 7. Validation and bounded ablation

`tests/contracts/test_misco_profile_migration_ledger.py` verifies source digests, complete Source Pack membership, exact 51-rule identity coverage, Layer B/C runtime exclusion, project/manifest classification, child-Issue assignment, and the explicit missing-input boundaries.

The test also performs two ledger-only controls:

- removing one required canonical `PUB-*` item produces a coverage failure;
- adding another representation alias to the same canonical item does **not** create a second policy identity.

That ablation demonstrates only that the inventory catches omission without double-counting representations. It does not claim that #332–#337 runtime effects already exist.
