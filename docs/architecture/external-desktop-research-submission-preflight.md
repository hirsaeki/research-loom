# External Desktop Research submission assembly and preflight

Issue #92 keeps operator-authored research content separate from execution bindings that Research Loom already owns.

## Public flow

Prepare the Desktop Research Run, record retrieval attempts, and capture source bytes through the existing public commands. The normal CLI collect path accepts only the research result content:

```bash
research-loom external collect \
  --workspace WORKSPACE \
  --run-id RUN-ID \
  --json research-result.json
```

For callers that need an explicit read-only check before collect, the public Application Facade exposes `preflight_external(run_id, {"research_result": ...})`. Issue #92 does not add a second CLI command just for preflight. The facade preflight does not terminalize the Run, persist the Handoff/result extension, create candidate state output, re-register captures, or change retrieval attempts. Normal `collect` always performs the same assembly and validation again before committing terminal execution output, so safety does not depend on callers invoking preflight first.

The JSON shape is:

```json
{
  "research_result": {
    "validation": {"status": "valid", "issues": []},
    "outputs": {
      "observations": [],
      "evidence_candidates": [],
      "candidate_findings": [],
      "counterevidence": [],
      "conflicts": [],
      "unknowns": [],
      "evidence_gaps": [],
      "candidate_next_actions": [],
      "candidate_next_methods": []
    },
    "capture_ids": ["CAP-..."],
    "citation_details": [],
    "search_trace": {
      "entries": [
        {
          "attempt_id": "ATT-...",
          "related_handoff_output_ids": []
        }
      ]
    },
    "null_results": [],
    "evidence_gap_assessments": [],
    "coverage_assessment": {},
    "candidate_next_method_ids": []
  }
}
```

The operator selects Runs/captures and supplies research claims, citations, limitations, coverage judgments, and links from research outputs to persisted attempts. The operator does **not** supply Run/project/invocation IDs inside the Handoff, input pins, Handoff/extension digests, artifact digests/sizes, verified capture flags, attempt outcomes, implementation provenance, or preserved Context fields. Loom resolves those from the pinned Run, Context Pack, descriptor, stored capture bytes, and append-only attempt ledger.

Explicit internal/binding fields in `research_result` are rejected rather than silently overwritten.

## Validation boundary

Before terminal intake, Loom reuses the canonical Handoff validator and Desktop Research result validator. It also re-opens persisted capture bytes through the verified artifact reader, so digest/size mismatch or missing blobs fail closed.

Correctable submission problems such as malformed research content, bad output references, citation containment mismatch, and coverage inconsistency return diagnostics while the Run remains `RUNNING`; no Handoff/result extension/candidate state output is committed. Correcting only the submission and resending to the same Run is supported.

These cases are deliberately not converted into correctable submission errors:

- a canonical `validation.status=rejected` Handoff (formal research result),
- terminal/aborted Runs,
- stale authorization or pinned execution documents,
- persisted artifact corruption or disappearance,
- genuine storage/runtime failures.

`partial`, `unknown`, `no_relevant_source`, and other canonical bounded-result semantics remain valid research outcomes when their surrounding result is structurally consistent.

## Acceptance mapping

`tests/runtime/test_issue92_external_submission_preflight.py` covers Issue #92 D1-D6. The targeted command is:

```bash
uv run --frozen python -m unittest discover \
  -s tests/runtime \
  -p 'test_issue92_external_submission_preflight.py' \
  -v
```

The test file subclasses the existing production external-intake fixture, so the target executes the six Issue #92 cases plus the four inherited baseline intake tests (10 tests total).

## Ablation procedure

The acceptance suite is also intended to prove that the new guards are material rather than decorative.

1. Baseline: run the targeted command above; D1-D6 must pass.
2. Pre-terminal validation ablation: temporarily bypass `validate_external_submission()` inside the assembled `collect_external()` branch, without changing the fixture. D3 must regress because malformed references/citations/coverage can reach terminal intake and the same `RUNNING` Run can no longer be corrected.
3. Final-collect revalidation ablation: keep a successful preflight unchanged, then temporarily bypass `validate_external_submission()` only in the assembled `collect_external()` branch before submitting a changed research result. D5 must regress because the changed submission reaches terminal intake instead of being rejected while the Run remains `RUNNING`.
4. Restore the production implementation and rerun the baseline target. The baseline D4/D5 cases separately exercise verified persisted-byte reads for one-byte mutation and missing-blob failures.

Do not commit the ablation mutations. If another lower-level guard still catches a particular mutation, record that guard and do not claim the removed check was uniquely responsible.

## Additional review coverage

The additional PR review round is covered by these Issue #92 runtime cases:

- `test_review_round2_resource_basis_is_verified_before_terminal_intake`: source `resource_reference` bytes are verified before terminal intake; one-byte mutation and missing blob both fail hard while the Run stays `RUNNING`.
- `test_review_round2_capture_pair_parent_provenance_fails_closed`: original/text capture lineage, including rendition parent binding, is checked through the same material-pair projection used by public material reads.
- `test_review_round2_whitespace_equivalent_citation_is_accepted`: exact citation text and ASCII-whitespace-only differences share the existing retention matcher; substantive citation drift remains rejectable.
- `test_review_round2_nested_schema_errors_are_correctable`: nested operator-owned shape errors are diagnosed before projection/build helpers can raise raw `KeyError`/`TypeError`, and correction on the same Run succeeds.
- `test_review_round2_real_profile_public_cli_connects_a_through_d`: a real fixture Profile/Project Config path keeps non-empty Attention, guards, and effective constraints in the assembled Handoff, reuses a registered project input across a later RQ adoption, reads captured material after source-file removal, then performs invalid and corrected `external collect` through the public CLI while keeping Research State unchanged and emitting candidate-only Evidence/Finding objects.

The public CLI input for the final step remains the same provider-neutral shape:

```json
{
  "research_result": {
    "validation": {"status": "valid", "issues": []},
    "outputs": {
      "observations": [],
      "evidence_candidates": [],
      "candidate_findings": [],
      "counterevidence": [],
      "conflicts": [],
      "unknowns": [],
      "evidence_gaps": [],
      "candidate_next_actions": [],
      "candidate_next_methods": []
    },
    "capture_ids": ["CAP-..."],
    "citation_details": [],
    "search_trace": {"entries": []},
    "null_results": [],
    "evidence_gap_assessments": [],
    "coverage_assessment": {"dimensions": []},
    "candidate_next_method_ids": []
  }
}
```

Additional ablations were run without changing the fixture: removing the pre-terminal resource verified-read makes the resource mutation/missing-blob test fail, and removing the shared capture-pair parent binding makes the parent-provenance test fail. Both ablation edits were restored before the final baseline.
