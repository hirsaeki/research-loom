import json
from pathlib import Path

import pytest

from misco_harness.context_builder import (
    ArtifactAccessPolicy,
    ContextBuilder,
    EvidencePolicyViolation,
    ModeContamination,
    UnknownArtifact,
)
from misco_harness.models import ArtifactRecord, ArtifactRegistry, Lane
from misco_harness.trace_store import sha256_file

POLICY_PATH = Path(__file__).parents[2] / "contracts" / "runtime_artifact_policy.yaml"


def artifact(root: Path, artifact_id: str, role: str, lane: Lane, *, mode: str | None = None) -> ArtifactRecord:
    path = root / f"{artifact_id}.txt"
    path.write_text(artifact_id, encoding="utf-8")
    return ArtifactRecord(
        artifact_id=artifact_id,
        path=str(path),
        sha256=sha256_file(path),
        role=role,
        authority="TEST_AUTHORITY",
        lane=lane,
        mode=mode,
    )


def builder(tmp_path: Path) -> ContextBuilder:
    return ContextBuilder(tmp_path, tmp_path / "runtime", ArtifactAccessPolicy(POLICY_PATH))


def manifest(pack: Path) -> dict:
    return json.loads((pack / "manifest.json").read_text(encoding="utf-8"))


def test_question_formation_excludes_seed_then_seed_comparison_includes_it(tmp_path: Path) -> None:
    seed = artifact(tmp_path, "seed", "PRIOR_SEED", Lane.RESEARCH)
    theme = artifact(tmp_path, "theme", "INTAKE_SOURCE", Lane.RESEARCH)
    registry = ArtifactRegistry(artifacts=[seed, theme])
    context_builder = builder(tmp_path)

    independent = context_builder.build(
        pack_id="independent", run_id="run-1", event="QUESTION_FORMATION", lane=Lane.RESEARCH,
        registry=registry, artifact_ids=["theme", "seed"], required_ids={"theme"},
    )
    independent_manifest = manifest(independent)
    assert [item["artifact_id"] for item in independent_manifest["must_include"]] == ["theme"]
    assert independent_manifest["forbidden_context"] == ["seed"]

    comparison = context_builder.build(
        pack_id="comparison", run_id="run-2", event="SEED_COMPARISON", lane=Lane.RESEARCH,
        registry=registry, artifact_ids=["theme", "seed"], required_ids={"theme", "seed"},
    )
    assert {item["artifact_id"] for item in manifest(comparison)["must_include"]} == {"theme", "seed"}
    assert (independent / "manifest.json").read_bytes()


def test_publication_pack_excludes_historical_source_and_includes_clean_source(tmp_path: Path) -> None:
    g1 = artifact(tmp_path, "g1", "HISTORICAL_CALIBRATION_SOURCE", Lane.PUBLICATION)
    clean = artifact(tmp_path, "clean", "CLEAN_PUBLICATION_SOURCE", Lane.PUBLICATION)
    registry = ArtifactRegistry(artifacts=[g1, clean])
    pack = builder(tmp_path).build(
        pack_id="writer", run_id="run-w", event="PUBLICATION_DRAFT", lane=Lane.PUBLICATION,
        registry=registry, artifact_ids=["g1", "clean"], required_ids={"clean"},
    )
    data = manifest(pack)
    assert [item["artifact_id"] for item in data["must_include"]] == ["clean"]
    assert data["forbidden_context"] == ["g1"]
    assert not (pack / "artifacts" / "g1").exists()


@pytest.mark.parametrize("role", ["SUPERSEDED_CANONICAL_PROVENANCE", "SIMULATION_PROVENANCE"])
def test_normal_research_excludes_archive_provenance_roles(tmp_path: Path, role: str) -> None:
    provenance = artifact(tmp_path, "provenance", role, Lane.RESEARCH)
    pack = builder(tmp_path).build(
        pack_id=f"deny-{role}", run_id="run-p", event="RESEARCH_RUN", lane=Lane.RESEARCH,
        registry=ArtifactRegistry(artifacts=[provenance]), artifact_ids=["provenance"],
    )
    assert manifest(pack)["forbidden_context"] == ["provenance"]


def test_unknown_and_unregistered_artifacts_fail_closed(tmp_path: Path) -> None:
    unknown_role = artifact(tmp_path, "mystery", "REFERENCE", Lane.RESEARCH)
    registry = ArtifactRegistry(artifacts=[unknown_role])
    pack = builder(tmp_path).build(
        pack_id="unknown-role", run_id="run-u", event="RESEARCH_RUN", lane=Lane.RESEARCH,
        registry=registry, artifact_ids=["mystery"],
    )
    assert manifest(pack)["forbidden_context"] == ["mystery"]
    with pytest.raises(UnknownArtifact):
        builder(tmp_path).build(
            pack_id="unregistered", run_id="run-x", event="RESEARCH_RUN", lane=Lane.RESEARCH,
            registry=registry, artifact_ids=["absent"],
        )


def test_attention_map_and_publication_draft_cannot_be_research_evidence(tmp_path: Path) -> None:
    attention = artifact(tmp_path, "attention", "ATTENTION_PUBLICATION_MAP", Lane.CONTROL_PLANE)
    draft = artifact(tmp_path, "draft", "PUBLICATION_DRAFT", Lane.PUBLICATION)
    registry = ArtifactRegistry(artifacts=[attention, draft])
    for artifact_id in ("attention", "draft"):
        with pytest.raises(EvidencePolicyViolation):
            builder(tmp_path).build(
                pack_id=f"evidence-{artifact_id}", run_id="run-e", event="QUESTION_FORMATION",
                lane=Lane.RESEARCH, registry=registry, artifact_ids=[artifact_id],
                evidence_input_ids={artifact_id},
            )


def test_mode_mixing_requires_an_explicit_included_bridge(tmp_path: Path) -> None:
    real = artifact(tmp_path, "real", "SOURCE_EVIDENCE", Lane.RESEARCH, mode="REAL")
    virtual = artifact(tmp_path, "virtual", "SOURCE_EVIDENCE", Lane.RESEARCH, mode="VIRTUAL")
    bridge = artifact(tmp_path, "bridge", "MODE_BRIDGE_CONTRACT", Lane.CONTROL_PLANE)
    registry = ArtifactRegistry(artifacts=[real, virtual, bridge])
    context_builder = builder(tmp_path)
    with pytest.raises(ModeContamination):
        context_builder.build(
            pack_id="mixed", run_id="run-m", event="RESEARCH_RUN", lane=Lane.RESEARCH,
            registry=registry, artifact_ids=["real", "virtual"],
        )
    pack = context_builder.build(
        pack_id="bridged", run_id="run-b", event="RESEARCH_RUN", lane=Lane.RESEARCH,
        registry=registry, artifact_ids=["real", "virtual", "bridge"],
        explicit_include_ids={"bridge"}, mode_bridge_artifact_id="bridge",
    )
    assert {item["artifact_id"] for item in manifest(pack)["must_include"]} == {"bridge"}
    assert {item["artifact_id"] for item in manifest(pack)["retrieve_on_demand"]} == {"real", "virtual"}
