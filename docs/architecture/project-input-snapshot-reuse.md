# Project Input snapshot reuse

Question Review may reuse an immutable registered Project Input after the active Research Snapshot advances when the input still belongs to the same project and Research Lineage.

The input keeps its original `input_id`, content digest, registration Snapshot, lineage, and provenance. Review does not re-register or rebind the input. Before use, the public review path verifies the content-addressed blob, so a missing or modified blob fails closed. The resulting KEEP review or material change candidate is bound to the current Review Snapshot by the existing Question Review contract.

## Operator sequence

Assume the workspace is already initialized and an authoritative Research Question exists through the normal adoption flow. Read the current public Snapshot first and carry its `snapshot_id` and `content_digest` into registration:

```bash
./research-loom resume --workspace "$WS" --json

cat <<'JSON' | ./research-loom research-input register --workspace "$WS" --json -
{
  "file": "/absolute/path/inside/workspace/theme.md",
  "role": "theme",
  "expected_snapshot_id": "S0",
  "expected_snapshot_digest": "sha256:<S0-digest>",
  "provenance": {"supplied_by": "operator"}
}
JSON
```

Keep the returned `project_input.input_id` (for example `PIN-from-S0`). Advance Research State through a separate lawful adoption to S1; do not re-register the Project Input. The workspace may be closed and reopened. Then submit the KEEP review through the existing action surface:

```bash
cat <<'JSON' | ./research-loom action submit --workspace "$WS" --json -
{
  "action_type": "research_question.review",
  "actor_id": "H",
  "payload": {
    "operation": "KEEP",
    "question_ids": ["RQ-authoritative"],
    "rationale": "review supplied theme",
    "review_inputs": {"project_input_ids": ["PIN-from-S0"]}
  }
}
JSON

./research-loom research-input show \
  --workspace "$WS" \
  --input-id "PIN-from-S0" \
  --format metadata \
  --json
```

Expected: the KEEP succeeds at S1 without creating another Project Input. The Review result reports S1 as its `bound_snapshot`, while `research-input show` still reports S0 as the immutable registration Snapshot for the same `input_id`.

For REFINE, candidate creation remains candidate-only at S1. Applying that candidate still requires the existing confirmation and `research_revision` Human Decision; only approval creates S2. If the head advances after candidate creation, the stale candidate remains rejected. Same-project/same-lineage checks and verified blob integrity remain mandatory.

## Acceptance and ablation evidence

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

The production implementation at `36474071f8a8775d99a4b0eb9b874a5e8ec37846` was also checked with bounded Sandbox-only mutations. The mutations were restored immediately after each run and are not present in the production diff.

Control:

```bash
python -m unittest \
  tests.runtime.test_issue90_project_input_snapshot_reuse.Issue90ProjectInputSnapshotReuseTests.test_b1_b2_b3_reuse_keeps_registration_provenance_and_refine_requires_decision \
  -v
```

Result: PASS (`Ran 1 test ... OK`).

Ablation A — temporarily restored the former exact-Snapshot comparison in `plugins/local_application/project_input_facade.py`, immediately after current binding resolution, so a Review input also had to match current `snapshot_id` and `snapshot_digest`. Running the same B1/B2/B3 test returned exit 1 at the intended reopened S1 KEEP. The observed error was `APPLICATION-PROJECT-INPUT-STALE-001` with `Question Review references project inputs that are not bound to the exact current Snapshot: PIN-...`.

Ablation B — temporarily removed only the `foreign_lineage` rejection block from `LocalApplicationFacade.submit_action`. Then:

```bash
python -m unittest \
  tests.runtime.test_issue90_project_input_snapshot_reuse.Issue90ProjectInputSnapshotReuseTests.test_b5_review_path_rejects_unknown_foreign_and_tampered_inputs \
  -v
```

returned exit 1 at the intended lineage assertion: `AssertionError: LocalApplicationError not raised`. This demonstrates that the same-lineage guard is what preserves the B5 rejection. After both ablations, `git diff --exit-code -- plugins/local_application/project_input_facade.py` was clean.
