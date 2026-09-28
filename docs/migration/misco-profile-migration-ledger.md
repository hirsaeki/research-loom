# MISCO legacy Profile migration ledger

Status: **Issue #331 design inventory**
Baseline: `main@1ea6ad38fcf09eab24e44aa7e5bb4b6afec90578` (2026-09-28)
Machine-readable ledger: [`misco-profile-migration-ledger/index.json`](misco-profile-migration-ledger/index.json)

This document fixes the migration boundary for #332–#337. It does **not** change runtime behavior and it is not evidence that the migration is complete.

## 1. Inventory result

The machine-readable ledger pins every inventoried source by SHA-256 and tracks 246 migration items. It covers:

- the three entries of `research-profile/profile.manifest.json`;
- the Research Attention / Initial Publication Map, including chapter and section attention plus update rules;
- the non-canonical Virtual Run project feedback;
- every file listed by the Human Approved Publication Source Pack manifest;
- all 51 `PUB-*` runtime rules as one rule set, with the JSON and Markdown representations treated as aliases rather than duplicate rules;
- Layer A rhetorical patterns, phase rules, terminology firewall, negative guards, formal rendering policy, editorial QA groups, synthetic few-shot specifications, and Skill assembly steps;
- Layer B audit-only provenance and Layer C Human Review / decision records, including HD-01 through HD-04;
- the relevant legacy Harness distribution / attention / publication-writer responsibilities; and
- the current Profile contracts, Research/Narrative canonical semantics, resolver, runtime validator, Research Package, Writer, and Publication consumers used as migration boundaries.

The ledger deliberately records source files and rules separately. A source file may contain many rules, while JSON/Markdown renderings of the same rule do not create additional policy identity.

## 2. Responsibility decisions

### 2.1 Already converged: do not reimplement

The following are existing current-system boundaries, not migration payload to recreate:

- Core provenance / identity / immutable-history / Human Decision invariants.
- Same-type `extends`, cross-type `requires`, deterministic Profile composition, and no cross-category last-write-wins.
- Generic Research Quality semantics already represented by `profiles/contracts/research-quality-policy.yaml`.
- Generic Narrative read-only / preservation / partial-order semantics already represented by `profiles/contracts/narrative-semantics.yaml`.
- Production enforcement of machine-representable effective constraints before authoritative commit.
- Writer / Publication package boundaries that keep authoritative Research State upstream of writing and release.

#332–#335 may instantiate or consume these boundaries, but must not add a second resolver, a second authority model, or a parallel Core invariant set.

### 2.2 Research / Organization

The legacy Publication pack is **not** the source of generic Research quality rules. Generic source/evidence/claim/finding quality semantics have already converged into the current Research Profile contract.

#332 must create real production Research / Organization profiles only for concrete reusable constraints that are still absent. #333 then proves those constraints reach the research path and quality checks. MISCO organization terminology or handling policy belongs to Organization Profile only when it is reusable across MISCO projects; the 2026 topic, concrete questions, current emphasis, and provisional chapter locations do not.

### 2.3 Narrative / Writer

The Publication Source Pack contains two kinds of material that must remain distinct:

1. reusable semantic prohibitions already overlapping current Narrative semantics, such as not inventing research conclusions, not fixing model/recommendation counts, preserving limitations, and not treating literal chapter order as authority; and
2. rendering/transformation behavior that belongs in Writer, such as rhetorical patterns, phase-specific prose transformations, terminology rendering, chapter navigation, and editorial QA.

The first category is mapped to existing Narrative semantics plus a regression check; the second is assigned to #334. A prose rule is not marked “machine-enforced” merely because it is written in Layer A.

### 2.4 Publication

Formal layout, figure/table presentation, citations/display, footnotes, outer document structure, permission/anonymization checks, and formal-spec-driven output belong to Publication Profile / Publication Skill and are assigned to #335.

Four Human Review decisions are already resolved and must be preserved, not re-voted:

| Decision | Preserved meaning | Runtime consequence |
|---|---|---|
| HD-01 = A | page/font/indent settings come from the current formal specification original | missing formal input => `HUMAN_DECISION_REQUIRED`; do not infer values |
| HD-02 = A | bibliography placement follows the current formal specification original | same missing-input behavior as HD-01 |
| HD-03 = B | long raw URLs use a separately human-approved display profile | the concrete display pattern is still an input; do not invent it |
| HD-04 = B | color-figure QA is conditional | apply only when color figures are actually used |

Layer C is the decision/provenance record. The runtime source remains the corresponding Layer A reflection, not Layer C itself.

### 2.5 Project Config / Attention / Outline

`research_attention_and_initial_publication_map.md` explicitly says that Attention is not Evidence, does not choose methods, does not determine answers, and that the chapter tree is provisional. Therefore its content is assigned to #336 as project-specific Attention / outline hints rather than reusable Narrative or Publication policy.

The Virtual Run feedback is explicitly `PROJECT KNOWLEDGE / NON-CANONICAL FEEDBACK`. Its chapter homes, method flow, and writing observations may be useful project input, but they cannot silently become reusable Profile constraints. #336 may bind them as project knowledge where appropriate; any promotion to reusable policy would require a separate authority decision.

## 3. Runtime / audit / review separation

The legacy approved pack already states the clean separation that the current migration must preserve:

```text
Layer A  -> approved runtime source material
Layer B  -> audit/provenance only
Layer C  -> Human Review / decision provenance only
```

The legacy generated writer Skill and its rule index are migration references, not a new authority source. New production runtime must resolve the current Profile manifests and current Writer/Publication consumers; it must not import the old `research-profile/` tree or legacy `research-harness/.codex/skills/misco-publication-writer` as hidden runtime authority.

Synthetic few-shot specifications are also not policy or Evidence. They are assigned to #334 as synthetic test/example specifications only.

## 4. Application boundary matrix

| Material | Declared | Reaches production input today | Evaluated today | Explainable on public surface today | Migration owner |
|---|---:|---:|---:|---:|---|
| Current Profile composition contract | yes | yes | yes | yes | already preserved |
| Generic Research Quality semantics | yes | only through synthetic/explicit effective constraints | partially | partially | #332 / #333 |
| Generic Narrative semantics | yes | fixture/spec level; no production MISCO narrative profile | fixture-only semantics | no end-to-end MISCO proof | #332 / #334 |
| 51 approved `PUB-*` rules | yes, legacy Layer A | legacy writer only | legacy checks only | no current production Profile proof | #334 / #335 |
| Rhetorical / phase / terminology rules | yes, legacy Layer A | legacy writer only | legacy writer checks | no | #334 |
| Formal rendering policy | yes, legacy Layer A | legacy publication path only | incomplete without formal runtime inputs | partially | #335 |
| Project Attention map | yes, legacy guidance candidate | legacy Harness attention path | current attention lifecycle exists, but no production MISCO migration binding | partially | #336 |
| Virtual Run feedback | yes, non-canonical | not a reusable Profile | n/a | n/a | #336 |
| Layer B provenance | yes | intentionally no | audit only | audit only | #337 |
| Layer C Human Review / HD records | yes | intentionally no | Human decision provenance | audit only | #335 / #337 |

“Fixture-only” is intentionally not reported as runtime application. A rule is only considered applied after a current production manifest resolves it, the consumer receives it, the relevant machine/Host/Human check executes, and the public result can explain the outcome.

## 5. Missing formal inputs

The ledger records four concrete input gaps. None is permission to guess:

1. current MISCO formal specification original or an approved `formal_spec_profile`;
2. the human-approved long-URL reader-facing display profile selected by HD-03;
3. `research_group_type` or equivalent metadata where formal output branches on group type; and
4. permission/anonymization/original-review status for non-public interview/internal material when such material is published.

These gaps should block only the operation that actually needs them. For example, absence of a URL display profile must not prevent unrelated research collection or candidate Finding creation.

## 6. Child-Issue scope after inventory

- **#332 — production Profile assets / resolver connection:** create actual Research, Organization, Narrative, and Publication manifests/assets using the current resolver; do not copy Layer B/C into runtime constraints.
- **#333 — Research / Organization application:** make configured research-quality and organization rules affect real research operations and quality checks while retaining Core floors.
- **#334 — Narrative / Writer application:** consume current Narrative semantics plus the approved Writer transformation/QA rules; keep Writer read-only and keep synthetic examples synthetic.
- **#335 — Publication application:** apply formal/citation/display/permission rules; surface concrete missing formal inputs rather than inventing values.
- **#336 — project / workspace migration:** bind MISCO project-specific Attention, outline hints, and production config; explicitly advance existing workspaces without rewriting historical pins.
- **#337 — integrated acceptance / audit:** prove research -> package -> multi-section writing -> single-section revision -> publication preview with real Profiles, run an ablation, and retain Layer B/C provenance separately from runtime.

The dependency graph in #330 remains valid. This inventory narrows the payload of each child rather than introducing new dependencies.

## 7. Validation and bounded ablation

`tests/contracts/test_misco_profile_migration_ledger.py` verifies:

- all pinned sources still match their recorded SHA-256;
- all Source Pack manifest files are present in the inventory;
- all 51 runtime rule IDs and the Layer A pattern/guard/few-shot IDs are covered exactly once;
- the legacy manifest entries, Map rows, and project-feedback sections are classified;
- Layer B/C and synthetic examples cannot be marked runtime policy;
- every non-final migration class has a child Issue and application boundary; and
- removing a representative required rule creates a coverage error, while adding another representation alias does not create a second policy rule.

This is a ledger-integrity ablation only. It does not claim that #332–#337 runtime behavior already exists.
