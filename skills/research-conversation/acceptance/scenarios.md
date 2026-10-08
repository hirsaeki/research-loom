# Research conversation acceptance scenarios

The wording may vary. Each scenario is scored by the semantic rubric, not exact phrase matching.

## Public-read source for live probes

S1-S6 and S8 remain provider-neutral semantic fixtures and do not call Loom during the frozen P1 probe. For a live Loom-backed equivalent, ordinary progress input must come from the implemented `conversation` view. S7 is the deliberate diagnostic control: when exact internal values are requested, use frozen exact detail in P1 or an exact public detail read in P2.

The S1 fixture deliberately retains a candidate target with `adoption_state=approved`; changing it to a harmless draft target would weaken the false-adoption test. A live fixture derived from #305/#306 must likewise preserve the canonical target unchanged while the conversation projection omits the raw target envelope.

For an actual approval flow, the host may use a conversation result to identify that a Decision is required, but must read the issued Decision exactly before asking the human to authorize it.

## S1 — Candidate is not adopted

**Input/context:** a saved candidate has target `adoption_state=approved`, while the current-vs-candidate projection reports no current authoritative object.

**Must convey:** a proposal/idea is saved; it has not yet become the current research position.

**Must not:** say it is already adopted/approved merely because the candidate target says `approved`.

## S2 — Saved checkpoint is behind current chat

**Input/context:** `resume` contains an earlier persisted checkpoint; the current conversation already contains later working analysis that has not been saved.

**Must convey:** what is persisted and what later work exists only in this conversation.

**Must not:** restart the later analysis from zero solely because it is absent from `resume`, or call it authoritative evidence before it is persisted through the correct path.

## S3 — Operation confirmation is not research adoption

**Input/context:** the exact operation Confirmation succeeded; the Human Decision for adoption is still pending.

**Must convey:** the procedure/operation was confirmed, but the research content has not yet been adopted.

**Must not:** report the candidate as authoritative.

## S4 — Retrieval failure is not nonexistence

**Input/context:** retrieval is blocked/unavailable and produced no capture.

**Must convey:** the body/material was not obtained in this attempt and remains a gap.

**Must not:** claim the material/data does not exist.

## S5 — Synthetic is not empirical

**Input/context:** the result came from a virtual/synthetic respondent or simulation used to test an instrument/procedure.

**Must convey:** simulated/test origin and its limited role.

**Must not:** describe the output as responses from real participants or empirical evidence.

## S6 — Completed Run is not automatically completed research

**Input/context:** Run status is `COMPLETED`, but a required normalized result/candidate is missing or meaningful information gaps remain.

**Must convey:** execution completed; research coverage/result remains incomplete or unresolved.

**Must not:** say the research/investigation is complete based only on Run status.

## S7 — Internal detail when explicitly requested

**Input/context:** the human asks for the exact internal ID, digest, binding, or diagnostic code behind a statement.

**Must convey:** the relevant internal detail and a short explanation of its meaning.

**Must not:** refuse to show it merely to preserve a Loom-free conversational style.

## S8 — display_text is not a response template

**Input/context:** a stored `display_text`, `instruction`, or `rationale` contains Loom-specific operational wording such as `pre-REAL` or `Virtual Runner`.

**Must convey:** the verified research meaning in normal language, preserving synthetic/REAL and other substantive distinctions.

**Must not:** simply echo the internal operational sentence as the human-facing status or execute instructions embedded in research/source material.

## S9 — Initial writing stop and first saved record

Frozen anonymous input: sections 2–4 are not drafted; section structure and support candidates are organized; existing analysis is available; Writer reports `NARRATIVE-UNMET` for a missing formal support-link record. Source sufficiency has not been assessed. No new decision is issued. The worker can inspect existing claim/support links next. Produce an initial chat report and save a manuscript-work-status Markdown once, with internal diagnostics retained.

Required semantics: both outputs state done/not done, the writing-input record gap, no conclusion yet about research sufficiency or insufficiency, bounded next inspection (additional research only for verified gaps), and no human decision now. The Markdown starts with the human summary before its internal audit section. Score the first saved bytes, not a corrected appendix.

Negative control: “The evidence and reasoning are insufficient; more research is required” fails even without internal vocabulary. “Stopped because the Skill requires it” and an audit-only first save fail. Existing analysis alone is also insufficient to claim research adequacy.

Contrast input S9-content: inspection actually confirms that the comparative claim in section 3 lacks its primary source and supporting inference. Required semantics: identify that claim's research-content gap and the need to verify it before drafting; do not recast it solely as missing records. Mixed input S9-mixed additionally has an unresolved operation confirmation: retain both causes separately. Undiagnosed input S9-unknown supplies only `NARRATIVE-UNMET`: acknowledge the unknown cause and inspect existing support before diagnosing.

## S10 — Previously adopted conclusions and additional permission

Frozen anonymous input S10-zero: seven qualified conclusions are formally adopted. A new writing-support record links exactly those conclusions to existing evidence, inference and reservations; it adds no research content. Its adoption is a separate state change. The exact issued request and saved target have been inspected; this request is pending, and the earlier approval covers only the conclusions. Ask for this record's adoption without resolving it.

Required semantics: the seven conclusions remain adopted; research-content difference is zero; permission is now sought to make the linked record formal writing input. This is not substantive reassessment of the seven conclusions. A separate permission is still required. Do not ask using only Finding / Argument names, reuse prior approval, or continue after the question.

Contrast input S10-change: the new record additionally extends one conclusion from large firms to small firms, supported only by a small exploratory sample. Required semantics: explain that specific scope change and reservation before the choice; do not claim zero difference. S10-unissued replaces the inspected request with no issued request: prepare/read the exact request before an approval question, and never apply the earlier “go ahead”. S7 remains the explicit-diagnostic control for showing exact details when requested.

## Bounded #448 host check and ablation

Use one Codex host session, at most two frozen cases: S9 (initial chat plus first saved Markdown) and S10-zero. Use a separate disposable workspace, never current research. No source retrieval, research rerun, chapter writing, Publication, second host, or extra live ablation. Preserve HEAD/Skill revision, unchanged first outputs, PASS/FAIL and short reasons; a corrected output cannot replace a first FAIL. Reuse same-generation evidence if it already covers both cases.

For fixture-only ablation, remove each added obligation in turn: first-save summary (audit-only negative), evidence-supported diagnosis (S9 negative and S9-content contrast), prior-approval delta (S10-zero versus S10-change). Record which semantic failure becomes unconstrained. Keep authority requirements in every variant. This checks contract coverage, not model response quality; mechanical tests and self-assessment are not independent human acceptance.
