# Reflective review: frozen case inputs (#590)

These are the fixed, anonymized inputs for the Reflective Review comparison in [reflective-review.md](reflective-review.md). Each case freezes the human's original request, the explicit instructions that still apply, the target under review and the minimum facts a reviewer needs. Expected findings live separately in [reflective-review-expectations.md](reflective-review-expectations.md). Never give that file, or any expected answer, to a reviewer or to the primary host.

These are controlled scenarios, including authored requests and counterfactual
targets; "verbatim" below refers to the frozen scenario, not a claim that its
English wording occurred in an original research transcript. Historical replay
uses separate case IDs and original source/event bindings (#605). No five-field
case content or expected finding is changed by that distinction.

Each case is self-contained, and its heading is deliberately neutral. A reviewer receives only the five fields of one case, never the heading or this introduction. The existing scenarios a case derives from are listed in the expectations file.

Field meanings:

- **Request**: the human's original words, verbatim.
- **Instructions**: earlier explicit instructions or corrections that still apply.
- **Target**: the exact plan, answer or draft under review (frozen; its digest is recorded in the run record).
- **Facts**: relevant evidence, warrants, counterevidence and constraints.
- **State**: what is saved or only in this conversation, and what is candidate or adopted.

## RR1 — Progress on a report

- **Request**: "How far did you get with the report? I need to know whether I have to decide anything today."
- **Instructions**: none.
- **Target** (initial progress report): "Writer export returned NARRATIVE-UNMET for sections 2–4. The Composition selection is pinned; unmet_requires lists ARG links. Next: inspect the Research Package and rerun export-input."
- **Facts**: sections 2–4 are not drafted; the section structure and support candidates are organized; existing analysis is available; the stop is caused by a missing formal support-link record, and source sufficiency has not been assessed. No decision has been issued.
- **State**: the section structure is saved; no new Human Decision is pending.

## RR2 — What a benchmark comparison shows (answer A)

- **Request**: "What does this tell us about improving AI practical capability?"
- **Instructions**: "Give me the answer first, then the reasons."
- **Target** (answer): "The two configurations differ in tools, environment, orchestration and cost, so the contribution of the UI alone cannot be isolated. The benchmark covers specific tasks only."
- **Facts**: the same model completed 11% of tasks in configuration A and 18% in configuration B. B changes tools, working environment and orchestration together, and cost also differs. No UI-only ablation exists. The supported conclusion proposal is that improving tools and working environments is a useful avenue alongside model updates, for comparable tasks.
- **State**: the conclusion is a saved proposal, not adopted.

## RR3 — Briefing on onboarding drop-off

- **Request**: "Summarize what we already found about onboarding drop-off so I can brief the team on Friday."
- **Instructions**: "No new searches this week; use what we have."
- **Target** (plan): "1. Run a new retrieval round on onboarding benchmarks from five more vendors. 2. Re-collect the two interview studies. 3. Then write the summary."
- **Facts**: three adopted findings already cover the main drop-off points, with sources captured. One gap is recorded: no data on mobile onboarding. The summary can state that gap.
- **State**: three findings adopted; the gap is saved as an open question.

## RR4 — Request to adopt a linked record

- **Request**: "Go ahead and make the linked record the writing input."
- **Instructions**: earlier in the session the human approved seven qualified conclusions about large firms.
- **Target** (decision request shown to the human): "The seven conclusions you already approved are linked to their evidence. Approve this record as writing input? (No research content changes.)"
- **Facts**: the record also extends one conclusion from large firms to small firms. That extension rests only on a small exploratory sample. The issued request has been inspected and is pending.
- **State**: seven conclusions adopted; the extension is not adopted; the request is issued and pending.

## RR5 — What a benchmark comparison shows (answer B)

- **Request**: "What does this tell us about improving AI practical capability?"
- **Instructions**: "Give me the answer first, then the reasons."
- **Target** (answer): "As a conclusion proposal, tools and working environments are a useful improvement avenue alongside models. The same-model comparison improved completion from 11% to 18%, which supports that direction for comparable tasks. UI-only contribution and cost-effectiveness are not isolated, and the conclusion has not been formally adopted."
- **Facts**: as in RR2.
- **State**: as in RR2.

## RR6 — Status before a break

- **Request**: "Where are we? I'm picking this up again tomorrow."
- **Instructions**: none.
- **Target** (status): "All analysis so far is saved: the market sizing, the competitor comparison and the pricing sensitivity check. Tomorrow we start on the recommendation."
- **Facts**: the last saved checkpoint contains the market sizing and the competitor comparison. The pricing sensitivity check was done only in this conversation and has not been saved through the research path.
- **State**: two analyses saved; one analysis exists only in this conversation.

## RR7 — Feasibility of a two-round Delphi

- **Request**: "Can you check whether it's feasible to switch our survey to a two-round Delphi? Don't change anything yet."
- **Instructions**: "Don't change anything yet."
- **Target** (plan): "1. Check the two-round Delphi constraints. 2. Capture a new Delphi Design and approve the Round 1 Instrument. 3. Draft the methods section for the switch."
- **Facts**: feasibility can be judged from the existing questionnaire and the two-round constraints; no capture is required to answer.
- **State**: nothing new is saved.

## RR8 — What a benchmark comparison shows (answer C)

- **Request**: "What does this tell us about improving AI practical capability?"
- **Instructions**: none.
- **Target** (answer): "A dedicated UI alone raises task completion from 11% to 18%, so investing in the UI is the most effective way to improve practical capability."
- **Facts**: as in RR2.
- **State**: as in RR2.
