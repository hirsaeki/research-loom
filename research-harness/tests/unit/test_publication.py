import json
from pathlib import Path

import pytest

from misco_harness.fake_writer import FakeWriterAdapter
from misco_harness.feedback_router import FeedbackRouteError, route_feedback
from misco_harness.models import (
    ArtifactRecord,
    ArtifactRegistry,
    Lane,
    PublicationEligibility,
    PublicationFeedback,
    PublicationState,
)
from misco_harness.publication_exporter import (
    PublicationExporter,
    PublicationExportError,
)
from misco_harness.trace_store import sha256_file


def artifact(tmp_path: Path, artifact_id: str, role: str, lane: Lane) -> ArtifactRecord:
    path = tmp_path / f"{artifact_id}.json"
    path.write_text(json.dumps({"id": artifact_id}), encoding="utf-8")
    return ArtifactRecord(
        artifact_id=artifact_id, path=str(path), sha256=sha256_file(path), role=role,
        authority="TEST", lane=lane,
    )


def eligibility() -> PublicationEligibility:
    return PublicationEligibility(
        status="ELIGIBLE", approved_by="human", decision_id="decision-1",
        reviewed_research_state_id="rs-1", recorded_research_state_id="rs-1",
    )


def test_exporter_builds_minimal_approved_bundle_with_integrated_ceiling(tmp_path: Path) -> None:
    research = artifact(tmp_path, "research", "RESEARCH_STATE", Lane.RESEARCH)
    clean = artifact(tmp_path, "clean", "CLEAN_PUBLICATION_SOURCE", Lane.PUBLICATION)
    pack = PublicationExporter(tmp_path / "runtime").export(
        bundle_id="bundle-1", research_snapshot_id="rs-1",
        publication_state=PublicationState(state_id="ps-1"), eligibility=eligibility(),
        registry=ArtifactRegistry(artifacts=[research, clean]), artifact_ids=["research", "clean"],
        approved_artifact_ids={"research"}, primary_exposition_map={"finding-1": "results"},
    )
    manifest = json.loads((pack / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["output_status_ceiling"] == "INTEGRATED"
    assert {item["artifact_id"] for item in manifest["input_refs"]} == {"research", "clean"}
    assert not any("unknown" in item for item in manifest["input_refs"])
    assert (pack / "publication_state.json").is_file()


@pytest.mark.parametrize("role", ["PUBLICATION_DRAFT", "PUBLICATION_FEEDBACK", "HISTORICAL_CALIBRATION_SOURCE", "SIMULATION_PROVENANCE"])
def test_exporter_rejects_contamination_and_hidden_provenance(tmp_path: Path, role: str) -> None:
    bad = artifact(tmp_path, "bad", role, Lane.PUBLICATION)
    with pytest.raises(PublicationExportError):
        PublicationExporter(tmp_path / "runtime").export(
            bundle_id=f"bundle-{role}", research_snapshot_id="rs-1",
            publication_state=PublicationState(state_id="ps-1"), eligibility=eligibility(),
            registry=ArtifactRegistry(artifacts=[bad]), artifact_ids=["bad"], approved_artifact_ids={"bad"},
            primary_exposition_map={},
        )


def test_exporter_rejects_unapproved_research_and_unapproved_eligibility(tmp_path: Path) -> None:
    research = artifact(tmp_path, "research", "RESEARCH_STATE", Lane.RESEARCH)
    exporter = PublicationExporter(tmp_path / "runtime")
    with pytest.raises(PublicationExportError):
        exporter.export(
            bundle_id="bundle-unapproved", research_snapshot_id="rs-1",
            publication_state=PublicationState(state_id="ps-1"), eligibility=eligibility(),
            registry=ArtifactRegistry(artifacts=[research]), artifact_ids=["research"],
            approved_artifact_ids=set(), primary_exposition_map={},
        )
    with pytest.raises(PublicationExportError):
        exporter.export(
            bundle_id="bundle-ineligible", research_snapshot_id="rs-1",
            publication_state=PublicationState(state_id="ps-1"),
            eligibility=PublicationEligibility(status="NOT_ELIGIBLE"),
            registry=ArtifactRegistry(artifacts=[]), artifact_ids=[], approved_artifact_ids=set(),
            primary_exposition_map={},
        )


def test_feedback_routes_are_exhaustive_and_never_evidence() -> None:
    feedback = PublicationFeedback(feedback_id="fb-1", type="ARGUMENT_GAP", problem="gap")
    route = route_feedback(feedback)
    assert route.destination == "RESEARCH_SYNTHESIS"
    assert not route.evidence_eligible
    with pytest.raises(FeedbackRouteError):
        route_feedback(PublicationFeedback(feedback_id="fb-x", type="UNKNOWN", problem="orphan"))


def test_fake_writer_stops_at_integrated_and_emits_routable_feedback(tmp_path: Path) -> None:
    research = artifact(tmp_path, "research", "RESEARCH_STATE", Lane.RESEARCH)
    bundle = PublicationExporter(tmp_path / "runtime").export(
        bundle_id="bundle-fake", research_snapshot_id="rs-1",
        publication_state=PublicationState(state_id="ps-1"), eligibility=eligibility(),
        registry=ArtifactRegistry(artifacts=[research]), artifact_ids=["research"],
        approved_artifact_ids={"research"}, primary_exposition_map={},
    )
    output = FakeWriterAdapter().run(bundle, output_state_id="ps-integrated")
    assert output.publication_state.status == "INTEGRATED"
    assert route_feedback(output.feedback[0]).destination == "RESEARCH_SYNTHESIS"
