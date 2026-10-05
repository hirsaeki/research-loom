# Generated explanatory visuals

Issue #406 captures a host-generated **PNG candidate** using existing Research
Exhibits. It does not call a model API or create a second authority/store.
The host may use an image model, SVG/tool pipeline or another available generator,
then retain its exact final PNG. Unsupported output is an error; there is no
implicit source-visual disguise or successful text fallback.

`capture_explanation_exhibit` / `exhibit explanation` accepts an existing
`package_id`, selected `object_ids` and `exhibit_ids`, exact `output_base64`,
`semantic_changes`, generator identity/version/instruction, and a bounded request:

- `purpose`;
- `allowed_labels` and `allowed_relations` (literal strings, not a graph DSL);
- `must_not_add` (explicit forbidden added meaning).

Research Object refs must match current selected research; selected Exhibit refs
remain working material rather than approved facts. The generation input digest
binds the request, exact semantic refs, generator and instruction. Output PNG
bytes/digest remain immutable. Hidden generator versions may be `not exposed`.

Capture is always a candidate: `review_required`, or `research_required` when new
meaning is declared. It creates no Evidence, Finding, adoption or Research State
mutation. Changing prompt, generator or bytes creates a new Exhibit and preserves
the old one. Package rebuild carries exact selected PNG attachments and contracts.

## Explicit semantic inspection

The host/human must inspect the actual image against the pinned labels, relations
and research. Image readability and a model's self-report cannot establish that
no new meaning was added. `capture_visual_review` / `exhibit review-visual` records
this separate operation as an immutable note Exhibit referencing:

- exact `candidate_id`, content and semantic-contract digests;
- `reviewer.actor_id` and `reviewer.actor_type` (`host` or `human`);
- `disposition`: `existing_meaning_only` or `research_required`;
- any detected `semantic_changes`, rationale and harness-owned review time.

The input is an explicit review attestation, not proof that a person looked at the
image. The host must invoke it only after actual inspection. Ordinary capture
cannot write a review record. Declared research-changing semantics cannot be
waived by a conformant review. Conflicting review notes never resolve by majority
or last writer: revise the candidate or return through normal Research authority.

To pass the reviewed candidate downstream, select both candidate and review note
when rebuilding its Package, along with represented research refs. An orphan or
misbound review fails package validation. The Publication consumer (#408) accepts
only the exact selected candidate with an applicable existing-meaning review;
pending/research-required candidates remain diagnostics. Neither a visual review
nor successful preview constitutes manuscript/release approval.

Unit controls cover exact bytes, immutable regeneration, prompt/generator/output
ablation, missing refs, invalid PNG, attempted generation self-review, new meaning,
conflicting review, and invariant Research State. Synthetic review attestations
are not actual image-semantic or human-layout QA; #409 retains the live acceptance
gate. Syntax/diff checks are local, execution tests use existing CI dependencies.
