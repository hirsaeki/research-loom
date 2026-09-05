# Project Input snapshot reuse

Question Review may reuse an immutable registered Project Input after the active Research Snapshot advances when the input still belongs to the same project and Research Lineage.

The input keeps its original `input_id`, content digest, registration Snapshot, lineage, and provenance. Review does not re-register or rebind the input. Before use, the public review path performs a verified content read, so a missing or modified content-addressed blob fails closed. The resulting KEEP review or material change candidate is bound to the current Review Snapshot by the existing Question Review contract.

Operator sequence:

```text
project input register --expected-snapshot-id S0 --expected-snapshot-digest <S0 digest> ...
# advance Research State through a separate lawful adoption to S1
# close/reopen workspace if desired
research_question.review KEEP ... review_inputs.project_input_ids=[PIN-from-S0]
```

Expected: the KEEP succeeds at S1 without creating another Project Input. `project input show` still reports S0 as the registration Snapshot, while the Question Review result reports S1 as its bound Snapshot.

For REFINE, candidate creation remains candidate-only at S1. Applying that candidate still requires the existing confirmation and `research_revision` Human Decision; only approval creates S2. If the head advances after candidate creation, the stale candidate remains rejected. Same-project/same-lineage checks and verified blob integrity remain mandatory.

## Acceptance and ablation commands

Focused acceptance:

```bash
uv run --frozen python -m unittest discover -s tests/runtime -p 'test_issue90_project_input_snapshot_reuse.py' -v
uv run --frozen python -m unittest discover -s tests/runtime -p 'test_project_input_registration.py' -v
uv run --frozen python -m unittest discover -s tests/runtime -p 'test_research_question_review.py' -v
```

Full runtime CI parity:

```bash
uv run --frozen python -m unittest discover -s tests/runtime -p 'test_*.py' -v
```

Ablation A: temporarily restore the old exact-Snapshot comparison in `LocalApplicationFacade.submit_action`; `test_b1_b2_b3_reuse_keeps_registration_provenance_and_refine_requires_decision` must fail at the reopened S1 KEEP.

Ablation B: temporarily remove the same-lineage rejection; `test_b5_review_path_rejects_unknown_foreign_and_tampered_inputs` must fail because the injected foreign-lineage input is accepted. The normal implementation must pass first; unrelated fixture or dependency failures do not count as an ablation result.
