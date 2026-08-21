import json
from pathlib import Path

import pytest

from misco_harness.models import (
    PublicationEligibility,
    PublicationFeedback,
    PublicationState,
    PublicationStructureChange,
    PublicationWriterOutput,
)
from tests.integration.test_optional_seed import _prepare_workspace


def test_publication_eligibility_decision_is_harness_issued_and_nonblocking(tmp_path: Path) -> None:
    orchestrator = _prepare_workspace(tmp_path, worker_backend="mock")
    pending_publication = orchestrator.request_publication_eligibility()
    decision_id = pending_publication.pending_decision_ids[0]
    assert decision_id.startswith("decision-publication-eligibility-")
    assert orchestrator.status().pending_decision_ids == []

    orchestrator.record_decision(decision_id, choice="ALLOW_PUBLICATION", decided_by="human")
    research = orchestrator._research_state()
    assert research.publication_eligibility is not None
    assert research.publication_eligibility.status == "ELIGIBLE"
    assert research.publication_eligibility.decision_id == decision_id
    refreshed = orchestrator.refresh_publication()
    assert refreshed.source_research_state_id == research.state_id
    research_after_one_step = orchestrator.continue_until_stop(run_limit=1)
    assert research_after_one_step.pending_decision_ids
    assert orchestrator.publication_state().pending_decision_ids == []


def test_pre_p2_unbound_publication_eligibility_is_quarantined_once(tmp_path: Path) -> None:
    orchestrator = _prepare_workspace(tmp_path, worker_backend="mock")
    raw_research = orchestrator.store.read_json("state/research/head.json")
    raw_research["publication_eligibility"] = {
        "status": "ELIGIBLE",
        "approved_by": "legacy-human",
        "decision_id": "legacy-publication-decision",
        "scope": "LEGACY",
    }
    orchestrator.store.write_head("state/research/head.json", raw_research)
    legacy_research_id = raw_research["state_id"]

    migration = orchestrator.migrate_publication_eligibility()

    assert migration["status"] == "COMPLETED"
    migrated_research = orchestrator._research_state()
    assert migrated_research.state_id != legacy_research_id
    assert migrated_research.prior_snapshot_id == legacy_research_id
    assert migrated_research.publication_eligibility is not None
    assert migrated_research.publication_eligibility.status == "NOT_ELIGIBLE"
    assert orchestrator.publication_state().status == "SCAFFOLD"
    assert orchestrator.migrate_publication_eligibility() == migration


def test_publication_refresh_and_writer_feedback_run_without_research_completion(tmp_path: Path) -> None:
    orchestrator = _prepare_workspace(tmp_path, worker_backend="mock")
    initial_research = orchestrator._research_state()
    eligible = initial_research.model_copy(update={
        "state_id": "research-eligible-1",
        "findings": [{"finding_id": "finding-1", "statement": "Provisional finding"}],
        "publication_eligibility": PublicationEligibility(
            status="ELIGIBLE", approved_by="human", decision_id="publication-decision-1",
            reviewed_research_state_id="research-initial", recorded_research_state_id="research-eligible-1",
        ),
    })
    orchestrator.store.snapshot("research", eligible.state_id, eligible)
    orchestrator.store.write_head("state/research/head.json", eligible)
    research_before_publication = orchestrator._research_state().model_dump(mode="json")
    research_orchestrator_state = orchestrator.status()

    first_publication = orchestrator.refresh_publication()
    assert first_publication.status == "PROVISIONAL"
    assert first_publication.source_research_state_id == eligible.state_id
    assert first_publication.structure is not None
    assert first_publication.draft is not None
    assert orchestrator._research_state().model_dump(mode="json") == research_before_publication
    assert orchestrator.status().phase == research_orchestrator_state.phase

    writer_output = PublicationWriterOutput(
        output_id="writer-output-1",
        publication_state=PublicationState(
            state_id="writer-publication-1",
            status="INTEGRATED",
            source_research_state_id=eligible.state_id,
            structure=first_publication.structure,
            draft=first_publication.draft,
        ),
        feedback=[PublicationFeedback(
            feedback_id="feedback-1", type="ARGUMENT_GAP", problem="A gap remains",
            source_research_state_id=eligible.state_id,
        )],
    )
    integrated = orchestrator.apply_publication_writer_output(writer_output)
    assert integrated.status == "INTEGRATED"
    assert integrated.pending_feedback_ids == ["feedback-1"]
    feedback_record = json.loads(
        (tmp_path / ".rh" / "publication" / "feedback" / "feedback-1.json").read_text(encoding="utf-8")
    )
    assert feedback_record["source_publication_state_id"] == first_publication.state_id
    assert feedback_record["source_research_state_id"] == eligible.state_id
    assert orchestrator._research_state().model_dump(mode="json") == research_before_publication

    later_research = eligible.model_copy(update={
        "state_id": "research-eligible-2",
        "findings": [*eligible.findings, {"finding_id": "finding-2", "statement": "Later finding"}],
        "publication_eligibility": None,
    })
    orchestrator.store.snapshot("research", later_research.state_id, later_research)
    orchestrator.store.write_head("state/research/head.json", later_research)
    with pytest.raises(Exception, match="snapshot-bound ELIGIBLE"):
        orchestrator.refresh_publication()
    pending_again = orchestrator.request_publication_eligibility()
    orchestrator.record_decision(pending_again.pending_decision_ids[0], choice="ALLOW_PUBLICATION", decided_by="human")
    recorded_research = orchestrator._research_state()
    recorded_publication = orchestrator.publication_state()
    assert recorded_research.prior_snapshot_id == later_research.state_id
    assert recorded_research.publication_eligibility is not None
    revised = orchestrator.refresh_publication(changes=[
        PublicationStructureChange(action="RENAME", node_ids=["chapter-1"], new_title="Updated context"),
    ])
    assert revised.status == "PROVISIONAL"
    assert revised.source_research_state_id == recorded_research.state_id
    assert revised.prior_snapshot_id == recorded_publication.state_id
    assert next(node for node in revised.structure.nodes if node.node_id == "chapter-1").title == "Updated context"
