import pytest

from misco_harness.audit import audit_worker_result
from misco_harness.models import ArtifactRef, ContextPackManifest, Lane, WorkerResult
from misco_harness.state_reducer import ReductionBlocked, reduce_worker_result


def context() -> ContextPackManifest:
    return ContextPackManifest(
        pack_id="pack-1", run_id="run-1", event="RESEARCH_RUN", lane=Lane.RESEARCH,
        must_include=[ArtifactRef(artifact_id="source", path="artifacts/source.txt", sha256="a" * 64)],
        forbidden_context=["draft"],
    )


def complete_result(**changes: object) -> WorkerResult:
    values: dict[str, object] = {
        "run_id": "run-1", "observed": ["observation"], "derived": ["derivation"],
        "interpreted": ["candidate finding"], "counterevidence": ["counter"],
        "unknown": ["unknown"], "scope_limits": ["one setting"],
        "question_delta_candidate": [{"question": "new?", "reason": "scope mismatch"}],
        "back_references": ["source"],
        "issues": [{"kind": "minority_warning", "message": "minority view"}],
    }
    values.update(changes)
    return WorkerResult.model_validate(values)


def test_audit_blocks_forbidden_context_and_reducer_cannot_commit() -> None:
    result = complete_result(back_references=["source", "draft"])
    audit = audit_worker_result(result, context())
    assert not audit.passed
    assert {item.code for item in audit.issues} >= {"FORBIDDEN_CONTEXT", "MISSING_BACK_REFERENCE"}
    with pytest.raises(ReductionBlocked):
        reduce_worker_result(result, audit)


def test_reducer_preserves_compaction_sensitive_fields_exactly() -> None:
    result = complete_result()
    audit = audit_worker_result(result, context())
    assert audit.passed
    proposal, handoff = reduce_worker_result(result, audit)
    assert proposal.preserved_counterevidence == result.counterevidence
    assert proposal.preserved_unknowns == result.unknown
    assert proposal.preserved_scope_limits == result.scope_limits
    assert handoff.counterevidence == result.counterevidence
    assert handoff.unknowns == result.unknown
    assert handoff.scope_limits == result.scope_limits
    assert handoff.minority_warnings == result.issues
    assert handoff.question_change_reasons == ["scope mismatch"]
    assert proposal.requires_human_decision


def test_substantive_output_without_back_reference_is_blocked() -> None:
    result = complete_result(back_references=[])
    audit = audit_worker_result(result, context())
    assert not audit.passed
    assert any(item.code == "MISSING_BACK_REFERENCE" and item.severity == "BLOCKER" for item in audit.issues)


def test_operational_only_result_does_not_force_semantic_decision() -> None:
    result = complete_result(observed=[], derived=[], interpreted=[], question_delta_candidate=[])
    audit = audit_worker_result(result, context())
    proposal, _ = reduce_worker_result(result, audit)
    assert not proposal.requires_human_decision


def test_audit_blocks_unsupported_strengthening_and_human_only_adoption() -> None:
    unsupported = complete_result(observed=[], derived=[], interpreted=[{"claim": "strong conclusion"}])
    unsupported_audit = audit_worker_result(unsupported, context())
    assert any(item.code == "UNSUPPORTED_STRENGTHENING" and item.severity == "BLOCKER" for item in unsupported_audit.issues)
    adoption = complete_result(interpreted=[{"kind": "METHOD_SELECTION", "selected": True, "status": "ADOPTED"}])
    adoption_audit = audit_worker_result(adoption, context())
    codes = {item.code for item in adoption_audit.issues}
    assert {"HUMAN_DECISION_VIOLATION", "METHOD_RESPONSIBILITY_VIOLATION"} <= codes
    assert not adoption_audit.passed
