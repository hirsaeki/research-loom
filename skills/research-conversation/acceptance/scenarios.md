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
