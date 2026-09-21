# Production two-round Delphi lifecycle

Issues #252 and #253 complete the #223 vertical slice: exact Instrument-use
approval, immutable late-response revisions, and mode/scale-aware analysis. The
existing Delphi registry remains the only store; this is not an N-round engine or
a new primary-research framework.

## Authority and public entry points

Research Questions must first be adopted through the existing public Core Human
Decision path. A Delphi Design references those Questions. Instrument approval is
then a **scoped human decision to use one exact questionnaire**, not a Core
Research State adoption. Like the existing Publication release boundary, it uses
an immutable request and an explicit human response; it does not synthesize a
Core transition, seed a Decision database, adopt a Finding, or approve stopping.
The request and receipt are inspectable documents in the existing Delphi SQLite
registry, alongside Designs, Instruments, Round results and Feedback.

The public sequence is:

```text
Delphi Design + panel + adopted Research Questions
  -> Instrument approval-request -> inspect full exact target
  -> human approval-resolve -> receipt + approved Instrument, one transaction
  -> Round 1 capture rev1 -> late-response capture rev2 (rev1 retained)
  -> Feedback built from an explicitly selected Round 1 revision
  -> Round 2 Instrument request -> human approval of exact dependencies
  -> Round 2 capture -> comparison against its pinned Round 1 revision
  -> explicitly selected stop/continue candidate, not research adoption
```

The CLI is `research-loom delphi`; every command accepts `--workspace WORKSPACE`.
Input commands take `--json FILE` (or `--json -` for stdin); read commands take
`--json`. For example, after Design capture:

```sh
research-loom delphi instrument approval-request --workspace WORKSPACE --json proposal.json
research-loom delphi instrument approval-show --workspace WORKSPACE --request-id DLAR-... --json
research-loom delphi instrument approval-resolve --workspace WORKSPACE --json response.json
research-loom delphi instrument show --workspace WORKSPACE --instrument-id DLI-R1 --version 1.0.0 --json
research-loom delphi round capture --workspace WORKSPACE --json round1.json
research-loom delphi round show --workspace WORKSPACE --round-result-id DLR-PANEL-1-R1 --version 1 --json
research-loom delphi feedback build --workspace WORKSPACE --round-result-id DLR-PANEL-1-R1 --version 2 --json
research-loom delphi inspect --workspace WORKSPACE --panel-id PANEL-1 --limit 25 --offset 0 --json
```

An approval proposal contains `delphi_design_id`, `delphi_design_version`,
`panel_id`, `instrument`, `human_actor_id`, and (for Round 2) `derived_from`.
The service returns `request_id`, `request_digest`, and the complete future
approved `request.target_document`. It assigns the approval ID and recomputes
the Instrument digest **before** asking for approval. These are previewed target
fields, not an assertion that a human has already approved anything. The request
also binds the current Research Snapshot, Design, project, panel, Instrument
ID/version/content and all Round 2 dependencies. The caller must inspect that
exact target and use its returned Instrument digest for subsequent capture.

The response has exactly four fields:

```json
{
  "request_id": "DLAR-...",
  "request_digest": "sha256:...",
  "actor": {"actor_id": "the-requested-human-actor", "actor_type": "human"},
  "choice": "approve_exact"
}
```

`decline` is the other permitted choice. The actor is an explicit caller-provided
human assertion, as with the other local CLI decision boundaries; this is not a
new login/authentication service. A different actor, request digest, target,
panel/project, Instrument version or content cannot reuse the approval.

Repeated exact proposals reuse their first request, including its nonce and
capture metadata. Receipt and approved Instrument commit in one existing SQLite
transaction. Repeating the same response after response loss reuses that effect;
a conflicting response cannot change a prior decision. A stale pending approval
must be re-requested against current Research State, but may still be declined.
Already committed decisions can be replayed after State advances without
rewriting their original Snapshot. Missing committed target records require exact
store recovery, not silent recreation from a receipt. ID-only legacy Core
Decision references no longer authorize **new** Instrument/response intake.

## Late responses and exact lineage

Each response is embedded in its immutable Round result and binds the exact
project, panel, round sequence, Instrument ID/version/digest, and item revision.
A new cumulative response set creates the next positive integer result version
under the existing write transaction. Earlier answers and expected participants
for the same Instrument must remain unchanged; changing or removing them is a
conflict, not a late response. Exact resends return their already saved version,
even when newer results exist. There is no mutable head or partial answer write.

Public `round show`, `feedback build`, and `round recalculate` accept `--version`.
Omitting it means **version 1**, preserving the original single-version behavior;
it never silently selects the newest result. Use bounded `inspect` to discover
versions: follow `next_offset` while `truncated` is true. The returned `documents`
page includes all Delphi kinds; per-kind arrays are projections of that page,
not complete histories. Inspection has no total-history cap.

Round 2 `derived_from` binds `prior_instrument_id`, `prior_instrument_version`,
`prior_instrument_digest`, `prior_round_result_id`, `prior_round_result_version`,
`prior_round_result_digest`, `feedback_id`, and `feedback_digest`. An omitted
`prior_round_result_version` means 1 for compatibility. Retained item identities
also bind their prior item revision and exact controlled Feedback. Neither
ordering nor a later Round 1 result can change the dependency of an existing
Round 2 Instrument, Feedback or stopping candidate.

## Comparable statistics, not a common float pool

Numeric answers are grouped by **item + response mode + declared scale**. The
optional Instrument item field `response_scales` is a narrow extension of the
existing additional-properties contract, validated by the production facade:

```json
{
  "response_modes": ["rating", "probability", "confidence"],
  "response_scales": {
    "rating": {"scale_id": "agreement-1-to-5", "minimum": 1, "maximum": 5},
    "probability": {"scale_id": "probability-0-to-1", "minimum": 0, "maximum": 1},
    "confidence": {"scale_id": "confidence-0-to-100", "minimum": 0, "maximum": 100}
  }
}
```

Each declared numeric scale requires a nonempty `scale_id` and finite increasing
bounds. Modes must be permitted by that item. Numeric answers must be finite
canonical JSON numbers, not booleans, and within declared bounds. No unit/range
is guessed from a mode name, and no implicit normalization or rescaling occurs.
Unknown scales preserve positions but report `scale_not_declared` and no numeric
summary. All-missing groups report `no_answers`, not measured agreement.

`mode_summaries` retains each field and its own denominator, positions, missing
value count and comparable disagreement. Rating 5 and probability 0.8 therefore
produce two separate groups, never median 2.9. The compatibility top-level
`numeric_summary` is present only for a single declared numeric mode with a known
scale. Rankings remain a separate categorical-position group. Rationale,
missing/not-applicable/prefer-not-to-answer states and minority positions are
retained. `disagreement_assessed` distinguishes unknown/no-data from observed
agreement; a false disagreement flag alone is not evidence of agreement.

Cross-round numeric comparisons require the same participant/item, shared mode,
exact scale declaration, and unchanged item text/type. Changed scales, changed
item meaning, missing declarations or unshared modes are listed as incomparable,
not pooled into stability. Multiple numeric fields contribute separate comparable
opinion entries. Feedback retains these mode-specific summaries without copying
participant IDs into its structured positions/rationale entries. Free-text
rationales are preserved, not an assurance that their own text is anonymous.

## Historical recalculation and stopping

Existing immutable results and Feedback remain readable, even if produced by the
old mixed-mode algorithm. Building new Feedback or a stopping candidate from
legacy statistics is rejected with a `round recalculate` instruction:

```sh
research-loom delphi round recalculate --workspace WORKSPACE --round-result-id DLR-PANEL-1-R1 --version 1 --json
```

Recalculation validates and reuses only the exact historical Instrument, expected
participants and responses. It never adds answers, invents an approval, adopts a
Finding, or overwrites the old result. It writes a new result version with
`analysis_contract=delphi-mode-scales@1` and an exact `recalculated_from` binding.
Repeating the source-version request reuses that recalculation; requesting an
already-current version is a no-op. New answers against a legacy ID-only approved
Instrument require a newly approved Instrument identity, not the recalculation
exception. Unrecoverable/invalid source facts remain a diagnostic.

Stopping accepts `--round-result-id` and `--version`. Without explicit selection,
it proceeds only when the panel has exactly one Round 2 result. It uses that
result's pinned comparison basis, Design goals, maximum approved round count,
attrition and missingness. Unassessed disagreement cannot satisfy a disagreement
goal. A maximum-round cap can still be the stated reason for a stopping
*candidate*, but no research conclusion or stop is adopted without the existing
authoritative Human Decision boundary.

## Recovery, implementation ownership and validation

`cli.py` dispatches directly to the existing Delphi facade. The facade owns
Design/Instrument/response validation, dependency closure and public selection.
`delphi_instrument_approval.py` owns scoped requests/receipts;
`delphi_analysis.py` is pure mode-aware analysis and Feedback projection.
`local_delphi_store.py` owns exact immutable documents and transactionally assigns
result versions or commits an approval effect. No additional facade override,
scheduler, mutable version registry, or parallel response store is introduced.

A new registry is published only after its schema commits, using a no-overwrite
same-directory hard link. Registered missing/corrupt stores follow the existing
optional-child/Parent recovery contract. Reads never create an empty registry;
opening an existing incompatible database does not run schema repair. Quiesce
and restore the exact Parent/store backup for lost facts; do not remove metadata
or fabricate historical Decisions. SQLite rollback handles injected write faults;
OS/SQLite locks release on process termination. Real power-loss and every native
Windows failure ordering are not claimed by mocked interruption tests.

Acceptance covers the fresh public CLI lifecycle, wrong pins/actors, stale and
repeated requests, atomic rollback/response loss, concurrent resends, late
responses, explicit Feedback/Round 2 selection, legacy recalculation, mixed and
same-scale controls, unknown scales, invalid/nonfinite values, all-missing and
bounded inspection. A dedicated Windows CI job runs the existing two-round tests
and both new acceptance suites. Baseline probes on unmodified code reproduce
ID-only approval reuse across a changed version, mixed median 2.9, and rejection
of a later response. The saved synthetic legacy fixture records that old output;
it is a recovery test source, never a production approval-seeding procedure.
