# Publication Parallel Lane Contract v0.2

Research and Publication are independent lanes over immutable snapshots. A
Publication update may consume only the current Research State snapshot whose
`publication_eligibility.status` is `ELIGIBLE`, whose `scope` is
`SNAPSHOT_ONLY`, and whose `recorded_research_state_id` equals that current
head. The eligibility also preserves the exact
`reviewed_research_state_id` used by the Human decision. It does not wait for
the Research orchestrator to reach a terminal state; Research continues
without waiting for a Publication update.

Eligibility is requested through a Publication-only Human Decision. That
decision is kept in the Publication State queue and must not block Research's
pending decision queue. When recorded, the Harness stores the Human Decision
ID in a new immutable Research State snapshot that carries the snapshot-bound
eligibility, with the reviewed state as its prior lineage. A later Research
snapshot does not inherit eligibility. Work and the Writer never manufacture
an eligibility ID; a later head requires a new request and Human decision, and
a stale request is rejected rather than retargeted.

The Publication Lane may create or revise a provisional `PublicationState`,
`PublicationStructure`, and `PublicationDraft`. The structure is a
reader-facing projection generated from the current Research State and, when
present, the active versioned `ATTENTION_PUBLICATION_MAP`. A workspace may be
Map-less; in that case the Harness creates a state-only scaffold. Every Map
version is immutable, and only the Human Attention Map Decision changes the
active pointer. Chapter and section add, remove, merge, split, move, and rename operations are valid
Publication Structure deltas and never become Research Lane constraints.

Publication Structure has no authority over Research Questions, method or
protocol selection, Evidence interpretation, or answer acceptance. The
Research Lane does not read a Publication Draft or Publication Feedback as
Research Evidence.

Publication Writer output is a typed `PublicationWriterOutput` envelope. Its
`PublicationDraft` and `PublicationFeedback` are Publication artifacts only.
Feedback is routed through the existing Feedback Router and cannot directly
mutate Research State. Stable and Final Publication statuses still require the
existing Human Decisions; a Writer cannot grant them.

The Trace Store keeps each Publication State snapshot and feedback record
immutable. A newly approved Research snapshot can produce a new provisional
structure and draft without overwriting prior Publication history.
