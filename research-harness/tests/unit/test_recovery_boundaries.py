import json
from pathlib import Path

import pytest

from misco_harness.cli import main
from misco_harness.context_builder import (
    AccessDenied,
    ArtifactAccessPolicy,
    ContextBuilder,
)
from misco_harness.models import (
    ArtifactRecord,
    ArtifactRegistry,
    Lane,
    PublicationEligibility,
    PublicationState,
)
from misco_harness.publication_exporter import (
    PublicationExporter,
    PublicationExportError,
)
from misco_harness.trace_store import sha256_file
from tests.integration.test_discovery_cycle import prepare_workspace

POLICY = Path(__file__).parents[2] / "contracts" / "runtime_artifact_policy.yaml"


def test_cli_conversation_status_propose_and_confirm_use_typed_service(tmp_path: Path, capsys) -> None:
    prepare_workspace(tmp_path, worker_backend="interactive-work")
    assert main(["--root", str(tmp_path), "conversation", "status"]) == 0
    assert json.loads(capsys.readouterr().out)["state_id"] == "orchestrator-initial"
    assert main([
        "--root", str(tmp_path), "conversation", "propose", "--actor", "human",
        "--action", "STOP_AT_BOUNDARY", "--parameters", '{"reason":"cli test"}',
    ]) == 0
    proposed = json.loads(capsys.readouterr().out)
    confirmation_id = proposed["confirmation_request"]["confirmation_id"]
    assert main([
        "--root", str(tmp_path), "conversation", "confirm", confirmation_id, "--by", "human",
    ]) == 0
    assert json.loads(capsys.readouterr().out)["receipt"]["status"] == "ACCEPTED"


def test_invalidated_artifact_is_excluded_from_normal_context_pack(tmp_path: Path) -> None:
    source = tmp_path / "research.json"
    source.write_text("{}", encoding="utf-8")
    record = ArtifactRecord(
        artifact_id="invalidated-research", path=str(source), sha256=sha256_file(source),
        role="RESEARCH_STATE", authority="RECOVERY", lane=Lane.RESEARCH, status="INVALIDATED",
    )
    with pytest.raises(AccessDenied, match="excluded from normal Context Packs"):
        ContextBuilder(tmp_path, tmp_path / "runtime", ArtifactAccessPolicy(POLICY)).build(
            pack_id="pack-invalidated", run_id="run-invalidated", event="RESEARCH_PLANNING",
            lane=Lane.RESEARCH, registry=ArtifactRegistry(artifacts=[record]),
            artifact_ids=[record.artifact_id], required_ids={record.artifact_id},
        )


def test_stale_publication_cannot_be_exported(tmp_path: Path) -> None:
    eligibility = PublicationEligibility(
        status="ELIGIBLE", approved_by="human", decision_id="decision-publication",
        reviewed_research_state_id="research-1", recorded_research_state_id="research-1",
    )
    state = PublicationState(
        state_id="publication-stale", status="STALE", source_research_state_id="research-1",
        publication_eligibility=eligibility,
    )
    source = tmp_path / "clean.md"
    source.write_text("clean", encoding="utf-8")
    artifact = ArtifactRecord(
        artifact_id="clean", path=str(source), sha256=sha256_file(source), role="CLEAN_PUBLICATION_SOURCE",
        authority="HUMAN_APPROVED", lane=Lane.PUBLICATION,
    )
    with pytest.raises(PublicationExportError, match="Human review is required"):
        PublicationExporter(tmp_path / "output").export(
            bundle_id="bundle-stale", research_snapshot_id="research-1", publication_state=state,
            eligibility=eligibility, registry=ArtifactRegistry(artifacts=[artifact]),
            artifact_ids=["clean"], approved_artifact_ids=set(), primary_exposition_map={},
        )
