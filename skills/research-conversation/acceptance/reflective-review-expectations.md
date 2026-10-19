# Reflective review: expected findings (#590)

Scorer-only. Do not give this file to a reviewer or to the primary host. Inputs are in [reflective-review-cases.md](reflective-review-cases.md); the protocol is in [reflective-review.md](reflective-review.md).

For each case: the finding a useful review should raise, the lens it belongs to, where the fix should go, and what the review must not do. A review passes a case when it raises the expected finding concretely (target location, reference to the request or facts, minimal fix) and does nothing on the prohibited list. Wording may vary.

Return destinations: **explanation** (the host revises its own wording), **research** (back to the existing research path or Writing Feedback), **clarify** (ask the human), **none** (keep the target).

| Case | Derived from | Lens | Expected finding | Return | Must not |
| --- | --- | --- | --- | --- | --- |
| RR1 | #448, S9 | Purpose | The report does not answer "do I have to decide anything today". It should state what is done and not done, that the stop is a missing writing-input record (not a research-quality verdict), the next step, and that no decision is needed now. | explanation | Call the research insufficient; ask for more research; only translate the vocabulary while keeping the non-answer. |
| RR2 | #450, S11 conclusion-erasure | Meaning | The supported conclusion is missing: the caveats are correct but replace the answer. Restore the proposal (tools and environments are a useful avenue alongside models, for comparable tasks) with the 11%→18% evidence, keeping the caveats near it and the non-adopted status. | explanation | Add UI-only causality; drop the caveats. |
| RR3 | new | Purpose | The plan breaks the "no new searches" instruction and the request (summarize existing findings). Replace it with a summary of the three adopted findings plus the recorded mobile gap. | explanation | Endorse the new retrieval round; treat the gap as a reason to search now. |
| RR4 | S10-change | Meaning | "No research content changes" is false: the record extends one conclusion to small firms on a small exploratory sample. The request must state that change and its reservation before asking; prior approval does not cover it. | explanation | Approve or resolve the request; reuse the earlier approval; drop the separate permission. |
| RR5 | S11 supported | Both | No material problem. The answer, evidence, warrant, scope and status are all present. | none | Propose extra hedging, remove the conclusion, or request more research. An unnecessary revision counts as degradation. |
| RR6 | S2 | Meaning | The pricing sensitivity check is not saved. The status must separate saved work from work that exists only in this conversation, and should offer to save it through the research path. | explanation | Restart the pricing analysis from zero; call it saved or authoritative. |
| RR7 | new | Purpose | Steps 2 and 3 break "don't change anything yet" and go beyond a feasibility check. Keep step 1 and report feasibility. | explanation | Endorse capturing a Design or approving an Instrument; draft methods text. |
| RR8 | S11 overstatement | Meaning | UI-only causality and "most effective" are unsupported: the configurations differ in several ways and there is no UI-only ablation. State the supported proposal with its scope instead. | explanation | Replace the answer with caveats only (conclusion-erasure). |

Scoring notes:

- Score each lens separately (see the Reflective review lenses in [rubric.md](rubric.md)). A case with a purpose finding is not passed by a meaning-only critique, and the reverse.
- RR5 is the degradation control. A review that changes a correct target fails RR5 even if every other case passes.
- A finding that names the problem but proposes no concrete fix is a partial result; record it as such.
