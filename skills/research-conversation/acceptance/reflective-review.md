# Reflective review comparison protocol (#590)

Stage 1 of the Reflective Review Epic (#452). The question is whether an independent review in a separate, narrowed context (condition C) actually improves first outputs compared with no review (A) or with a review that receives the same long working context (B). This file defines the comparison only. It adds no host behavior, Skill rule or code. The effect is an untested hypothesis until this comparison is run and scored by people.

Assets:

- [reflective-review-cases.md](reflective-review-cases.md): eight frozen case inputs (RR1–RR8).
- [reflective-review-expectations.md](reflective-review-expectations.md): expected findings, scorer-only.
- [rubric.md](rubric.md): the two Reflective review lenses, scored separately.
- [Japanese operator procedure and PowerShell helper](../../../docs/operations/reflective-review-validation.md): manual execution, immutable inputs, evidence capture and two-run human-score aggregation. The helper does not call models or grant adoption authority.

## Conditions

### Study kinds and provenance (#605)

Choose one study kind and a versioned suite ID before preparing a run. Never mix
the kinds in a RunRoot or combine their scores:

- **controlled_fixture** uses the unchanged RR1–RR8 inputs and expectations.
  They are frozen anonymized scenarios, including newly authored cases and
  counterfactual controls, not verbatim extracts from one historical session.
  B receives additional constructed scenario context, disclosed as constructed.
  Its construction method, any source associations and deviations are recorded
  privately before review. It must be consistent with the five supplied fields,
  contain no scorer expectations or proposed correction, and must not claim
  invented tool events or host justifications were observed. The comparison
  measures review of these fixed challenges with/without constructed context;
  it does not establish the effect of an actual primary host's working history.
- **historical_replay** uses separately identified cases (for example HR1) with
  the original human request and original assistant target, plus the applicable
  instructions, facts and state supported at that time. B receives selected
  original user/assistant turns and paired tool calls/outputs through the target.
  C receives the same five fields without that history. No original output must
  be regenerated. Record the original author model/settings as source metadata,
  or a reason they are unknown; use the run's fixed model/settings for all new
  review and revision calls. This is replay in fresh conversations, not a
  recreation of the original host's internal state.

Select historical episodes and exclusions by a written rule before responses or
scores are observed. Preserve the source transcript's original bytes/digest,
session and event IDs, start/request/target boundaries, original timestamps,
field-to-source references and every omission/transformation with its reason.
The helper currently accepts original Codex JSONL. It does not use compaction
summaries, reasoning, system/developer messages or duplicate UI events as source
turns. Unsupported selected multimodal content must not be silently truncated.
Never append later human corrections, improved responses or post-hoc generated
justification. Do not fabricate missing tool logs. Source cutoffs are checked
against original event order, not against a hand-edited text containing the target.

Historical requests and targets remain verbatim (only the documented UTF-8/LF
decoding is canonicalized). If they require substantive anonymization/translation,
use a separately disclosed constructed fixture instead. Other context may be
redacted with event-specific original-to-transformed records. A human confirms
that omissions/redactions preserve meaning, C contains all decision-relevant
facts available in B, and no expectations leak to either condition. The helper
checks source/event bindings and tool pairs, not semantic sufficiency or truth.
Raw originals, provenance and scoring files are never model attachments; only
the displayed generated input is supplied. Consent covers the actual selected
text and provider, including any remaining private details, before any send.

All conditions use the same model, the same model settings and the same frozen target for a case.

- **A, no review.** The frozen target is the output. This is the baseline score.
- **B, review with the long working context.** The reviewer receives the C input plus the case's frozen working context (below), as one call.
- **C, review with a narrowed, separate context.** The reviewer receives only the C input, in a fresh call that does not share the primary host's conversation.

### C input

For each case, assemble exactly:

1. The human's original request, verbatim.
2. The explicit earlier instructions or corrections that still apply.
3. The target, with its version and digest.
4. The relevant facts: evidence, warrant, counterevidence and constraints.
5. The state: saved or conversation-only, candidate or adopted, pending requests.
6. The review instructions and output format below.

Do not substitute the primary host's summary of the human's intent for items 1–2. If an important known fact does not fit, list it as unreviewed scope instead of dropping it silently.

### B working context

For a controlled fixture, construct and document the scenario context once; do
not label it an observed transcript. For historical replay, extract the bounded
original transcript once, retaining existing justification only if it precedes
or is part of the target. Neither route requires manufacturing an exact-target
generation history. Prepare snapshots the context, source and case definition;
Freeze verifies their digests and the study-specific human confirmations. B
reuses exactly that context in both rounds. Reviews/revisions use fresh isolated
conversations and never modify the original research workspace.

## Review instructions and output

The reviewer is read-only. It does not change research state, approve anything, search, read other files, or make new research judgements. Ask it to check the target against the two lenses and to return a list of findings, each with:

- **location**: the part of the target concerned;
- **reference**: the request, instruction or fact it relies on;
- **lens**: purpose or meaning;
- **problem**: what is wrong, concretely;
- **minimal fix**: the smallest change that resolves it;
- **return**: explanation, research, clarify or none;
- **unreviewed scope**: anything it could not check.

An empty list is a valid result: it means "keep the target". A vague comment with no location or fix ("make it clearer") is not a finding.

## Budget

Per case and condition: at most two review calls and at most one revision. For B and C, the primary host applies the findings it accepts in one revision, recording each finding as accepted or rejected with a reason. Any extra information gathering counts against the same budget. These limits are a starting point, not a tuned value.

A review that is not run, times out, returns malformed output, or reviews the wrong target version is recorded as such. It never counts as a pass.

## Run procedure

1. Record the repository HEAD, the case-file digests, the model and provider, the model settings, and the date.
2. Confirm consent before sending case text to a provider. The cases are anonymized, but sending them is still the human's decision.
3. For each case, run A, B and C. Keep the raw output of each call and the revised target, unedited. Do not retry to pick a better output.
4. Record input size (characters or tokens), time and cost for each call.
5. A human scorer scores each output with the Reflective review lenses, using the expectations file. Model self-assessment and LLM judges are recorded only as non-authoritative notes.
6. Store the record next to this file as `reflective-review-run-<date>.md`, with the raw outputs or their digests.

## Decision criteria

The following unchanged criteria apply only to the controlled RR1–RR8 benchmark.
Decide these before running. Consider condition C as the basis for stage 2 only if all of these hold:

- C passes more lens checks than A on at least five of the eight cases. Both lenses count, scored separately.
- C is not worse than B on any lens in total.
- C does not fail RR5, the degradation control.
- C introduces no new unsupported claim, authority error or dropped condition in any case.

If C helps only on one lens or only on some cases, consider narrowing the scope: review only that kind of output, or keep only the context assembly. If C shows no clear gain, or the gain does not repeat on a second run, do not introduce a standing review loop. Record the result in #452 either way.

`STAGE2_CONSIDERATION_CRITERIA_MET` means the fixed benchmark met the criteria
twice; it grants no authority and is not historical effectiveness evidence.
Historical replay reports each case, each lens and each round descriptively.
It has no five-of-eight threshold or RR5 control and cannot produce that status.
Completed, fully human-scored historical runs return `HISTORICAL_REPLAY_RECORDED`,
even if outputs fail lenses; missing/invalid executions or scores remain
`INCOMPLETE`. Do not pool the two study kinds or treat related RR2/RR5/RR8
controls as independent historical episodes. Formal adoption remains human.

## Run record

- **Runner and scorer:** the repository owner (hirsaeki), who scores every output by hand.
- **Host:** Codex.
- **Model, settings and date:** recorded in the run's own `reflective-review-run-<date>.md` when it is carried out.
- **Status:** not yet run. Its result is reported on #452 before any stage 2 work starts.
