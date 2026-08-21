import pytest
from pydantic import ValidationError

from misco_harness.models import (
    ArtifactRecord,
    ArtifactRegistry,
    Lane,
    PublicationEligibility,
    PublicationState,
    QuestionRecord,
    ResearchState,
    StateDeltaProposal,
)


def test_models_are_strict_and_versioned() -> None:
    state = ResearchState(state_id="rs-1")
    assert state.schema_version == "0.2"
    with pytest.raises(ValidationError):
        ResearchState(state_id="rs-2", invented=True)


def test_registry_rejects_duplicate_ids() -> None:
    record = ArtifactRecord(
        artifact_id="a-1", path="a.txt", role="ACTIVE_CONTRACT",
        authority="HUMAN_APPROVED_CONTRACT", lane=Lane.RESEARCH,
    )
    with pytest.raises(ValidationError):
        ArtifactRegistry(artifacts=[record, record])


def test_human_semantic_states_require_decision_records() -> None:
    with pytest.raises(ValidationError):
        QuestionRecord(question_id="q", text="question", status="BASELINE")
    with pytest.raises(ValidationError):
        PublicationState(state_id="p", status="STABLE")
    with pytest.raises(ValidationError):
        PublicationState(state_id="p", status="FINAL", stable_decision_id="d-stable")
    with pytest.raises(ValidationError):
        PublicationEligibility(status="ELIGIBLE")
    with pytest.raises(ValidationError):
        PublicationEligibility(status="ELIGIBLE", approved_by="human", decision_id="decision-1")
    eligibility = PublicationEligibility(
        status="ELIGIBLE",
        approved_by="human",
        decision_id="decision-1",
        scope="SNAPSHOT_ONLY",
        reviewed_research_state_id="research-1",
        recorded_research_state_id="research-2",
    )
    assert eligibility.is_snapshot_bound
    with pytest.raises(ValidationError):
        StateDeltaProposal(run_id="r", semantic_changes={"finding": "adopt"})
