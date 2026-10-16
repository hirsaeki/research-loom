# Initial generation conditions

All manuscripts are `SYNTHETIC_TEST_ONLY`. Each condition uses a fresh detached
Codex agent, the same v5 exported input, unchanged Writer Skill at base commit
`861367bebd07f10f38f1d743bac00cb0e2a91bf8`, and `misco.writer@1.2.0`.
The original Skill SHA-256 is
`8666f6fd5787dd6b11ec17b9388cb4252d455b66ce0afaec83e3dbfc65cd08ee`.
The model/configuration exposed to the agents is **inherited Codex default**;
exact service model identity, sampling settings and seeds are unavailable.
Identical requested settings do not establish identical hidden settings.

## Baseline assignment, verbatim

```text
Act as detached Writer for three SYNTHETIC_TEST_ONLY short Japanese manuscripts. Read exactly D:\wsroot\scratch\issue465-467-20261014\skills\writer\SKILL.md (unchanged current Skill), its references/detached-input.md, and detached inputs only at D:\wsroot\scratch\writer-reader-quality-run-20261014-v5\inputs\{synthetic-diagnostic-duplicate-entry-v1,synthetic-concept-flexible-hours-v1,synthetic-comparison-checklist-a8-6-b4-5-v1}\writer-input.json. Do not read acceptance docs, cases.json, other agent drafts, private DB, legacy tree, or other Skills. Treat exported fixed facts/interpretation/recommendation as fictional test input, not real empirical authority. Read all delivered WRITER_* resource bodies once per identical resource, each section contract and resolved research objects; duplicate bodies can be deduplicated after checking identity. Follow exact existing Profile pins/rules, preserve all numbers/conditions/counterresults and supplied selection reasons; no new research. Draft all four selected sections in Japanese, introduction + contiguous method/results middle + final recommendation. Common length target: ~3000–4500 Japanese characters total per case; approximate introduction2pages is a trial guide, not a hard minimum. Choose natural prose that serves the input; no forced blandness or dramatic reversal. Generate ONE initial draft per case; do not iterate to improve prose. Save raw generation as prose-only JSON {sections:[{section_id,content}]} at D:\wsroot\scratch\issue465-467-20261014\docs\acceptance\writer-reader-quality\outputs\baseline\<case_id>.json using apply_patch. Preserve first prose bytes. A transport helper will separately attach exact pins/citations and UNEVALUATED Profile review results; you must not claim semantic/editorial PASS. Return concise English report with paths and material uncertainty. Tools: prefer exec_command login:false for reads. Record actual available model/configuration as inherited Codex default; do not guess exact hidden model or sampling values.
```

The record-only follow-up asked for character counts and preservation without
padding. It did not request another generation. The baseline agent subsequently
returned this assignment text without changing any manuscript.

## Revised condition

The common task above is retained. The revised agent additionally reads and
applies [`revision-instructions.md`](revision-instructions.md), sections Entry,
Progress, Return and Shared editing. Its output directory is `outputs/revised`.
It cannot read baseline manuscripts, cases.json, other acceptance documents,
private storage or other Skills. Counts are reported without length-padding
regeneration. Tool/report-only instructions prohibit delegation and installs.

The trial instruction text is frozen before generation. A later production
Skill change is a separate implementation artifact, not a silent change to the
baseline or revised condition.

## Finite removal conditions

These three conditions are prepared but have not been generated in this run.

After the six baseline/revised outputs are preserved, the representative
comparison case receives three fresh-context, single initial generations.
Each retains the common task, all fixed inputs and Shared editing and omits
exactly one added section: Entry, Progress or Return. The retained instruction
text is copied into each condition's prompt; the agent does not receive the
omitted text or other manuscripts. Residual instructions in the original Skill,
Section Contracts and Profile still apply. These are additional-instruction
removals, not demonstrations that a rhetorical function is absent.

## Interpretation limits

The length target is a guide, not a storage gate. Actual output lengths must be
reported; unequal lengths may affect reading burden and prevent attributing a
difference solely to the added procedures. All first outputs remain unedited,
including omissions or unsupported wording found in later inspection.
Handwritten negative examples and later targeted edits are counted separately.
No independent human reading, continuation behaviour or operational dropout
measurement is supplied by these generations.
