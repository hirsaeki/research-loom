# Reflective review comparison protocol (#590)

Stage 1 of the Reflective Review Epic (#452). The question is whether an independent review in a separate, narrowed context (condition C) actually improves first outputs compared with no review (A) or with a review that receives the same long working context (B). This file defines the comparison only. It adds no host behavior, Skill rule or code. The effect is an untested hypothesis until this comparison is run and scored by people.

Assets:

- [reflective-review-cases.md](reflective-review-cases.md): eight frozen case inputs (RR1–RR8).
- [reflective-review-expectations.md](reflective-review-expectations.md): expected findings, scorer-only.
- [rubric.md](rubric.md): the two Reflective review lenses, scored separately.

## Conditions

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

For each case, generate once, in a disposable workspace, a working transcript that contains: the human's request near the start, the tool calls and outputs that produced the target, and the primary host's own justification of the target. Freeze it and record its digest before any review runs. B reuses this frozen transcript for every run. The transcript must not contain the expected findings.

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

Decide these before running. Adopt condition C as the basis for stage 2 only if all of these hold:

- C passes more lens checks than A on at least five of the eight cases. Both lenses count, scored separately.
- C is not worse than B on any lens in total.
- C does not fail RR5, the degradation control.
- C introduces no new unsupported claim, authority error or dropped condition in any case.

If C helps only on one lens or only on some cases, consider narrowing the scope: review only that kind of output, or keep only the context assembly. If C shows no clear gain, or the gain does not repeat on a second run, do not introduce a standing review loop. Record the result in #452 either way.

## Run record

Who runs the comparison, with which host and model, and when: **not yet decided** (to be set on #590 before the run).
