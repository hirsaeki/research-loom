import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from misco_harness.audit import audit_desktop_research_handoff
from misco_harness.context_builder import (
    ArtifactAccessPolicy,
    ContextBuilder,
    ContextBuildError,
)
from misco_harness.decision_broker import method_selection_request
from misco_harness.models import (
    ArtifactRecord,
    ArtifactRegistry,
    ContextPackManifest,
    CoverageDimension,
    CoverageStoppingAssessment,
    DesktopResearchContextSpec,
    DesktopResearchEvidence,
    DesktopResearchHandoff,
    EvidenceExcerpt,
    EvidenceGap,
    EvidenceKind,
    FindingRecord,
    Lane,
    NextMethodOption,
    PublicationEligibility,
    QuestionImpact,
    QuestionInput,
    RemainingInformationValue,
    RunManifest,
    SourceQuality,
    SourceType,
    SupportScope,
)
from misco_harness.orchestrator import DiscoveryOrchestrator
from misco_harness.state_reducer import reduce_desktop_research_handoff
from misco_harness.trace_store import sha256_file
from misco_harness.workers import (
    DesktopEvidenceSnapshotError,
    InteractiveWorkResearchBoundary,
)
from tests.integration.test_discovery_cycle import prepare_workspace

POLICY_PATH = Path(__file__).parents[2] / "contracts" / "runtime_artifact_policy.yaml"


def source(root: Path, artifact_id: str, role: str, lane: Lane) -> ArtifactRecord:
    path = root / f"{artifact_id}.txt"
    path.write_text(artifact_id, encoding="utf-8")
    return ArtifactRecord(
        artifact_id=artifact_id,
        path=str(path),
        sha256=sha256_file(path),
        role=role,
        authority="TEST_AUTHORITY",
        lane=lane,
    )


def coverage(
    *,
    stop_recommended: bool = False,
    remaining: RemainingInformationValue = RemainingInformationValue.MEDIUM,
    unresolved_material_evidence_gap_ids: list[str] | None = None,
) -> CoverageStoppingAssessment:
    return CoverageStoppingAssessment(
        dimensions=[CoverageDimension(dimension="definitions", status="COVERED", rationale="independent sources found")],
        saturation="PARTIAL",
        unresolved_material_evidence_gap_ids=(
            ["gap-1"] if unresolved_material_evidence_gap_ids is None else unresolved_material_evidence_gap_ids
        ),
        remaining_information_value=remaining,
        stop_recommended=stop_recommended,
        stopping_rationale="coverage and remaining information value assessment",
        stopping_basis=["COVERAGE", "REMAINING_INFORMATION_VALUE"],
    )


def evidence_capture(**changes: object) -> DesktopResearchEvidence:
    values: dict[str, object] = {
        "evidence_id": "ev-1",
        "source_id": "source-1",
        "source_type": SourceType.PEER_REVIEWED_RESEARCH,
        "source_quality": SourceQuality.HIGH,
        "locator": "p. 4",
        "captured_statement": "Observed pattern",
        "acquired_at": datetime(2026, 8, 17, 1, 2, 3, tzinfo=UTC),
        "text_snapshot": "Observed pattern in the bounded source section.",
        "snapshot_path": "C:/exchange/evidence_snapshots/ev-1.txt",
        "snapshot_sha256": "a" * 64,
        "excerpt_locator_pairs": [EvidenceExcerpt(excerpt="Observed pattern", locator="p. 4")],
        "evidence_kind": EvidenceKind.SUPPORTING,
        "support_scope": SupportScope.DESCRIPTIVE_CONTEXT,
    }
    values.update(changes)
    return DesktopResearchEvidence.model_validate(values)


def handoff(**changes: object) -> DesktopResearchHandoff:
    values: dict[str, object] = {
        "run_id": "run-dr",
        "question_impact": QuestionImpact(status="REFINE_CANDIDATE", rationale="scope remains provisional"),
        "findings": [FindingRecord(finding_id="finding-1", statement="Observed pattern", evidence_ids=["ev-1"], status="CANDIDATE")],
        "evidence": [evidence_capture()],
        "counterevidence": ["Contrary result"],
        "counterevidence_search_summary": "Sought conflicting and null results across allowed source types",
        "unknowns": ["Unknown boundary"],
        "evidence_gaps": [EvidenceGap(gap_id="gap-1", description="Independent effectiveness evidence missing", material=True)],
        "candidate_next_method_options": [NextMethodOption(option_id="method-1", method="SURVEY", rationale="could address gap", addresses_gap_ids=["gap-1"])],
        "coverage": coverage(),
        "back_references": ["source-1"],
        "publication_eligibility": PublicationEligibility(status="NOT_ELIGIBLE"),
    }
    values.update(changes)
    return DesktopResearchHandoff.model_validate(values)


def test_company_primary_source_cannot_claim_independent_effectiveness_without_independent_support() -> None:
    with pytest.raises(ValidationError):
        evidence_capture(
            evidence_id="ev-company",
            source_id="company-page",
            source_type=SourceType.COMPANY_PRIMARY,
            captured_statement="Observed pattern",
            support_scope=SupportScope.INDEPENDENT_EFFECTIVENESS,
        )


def test_work_cannot_launder_a_registered_policy_denied_artifact(tmp_path: Path) -> None:
    orchestrator, _ = prepare_workspace(tmp_path, worker_backend="mock")
    denied = source(tmp_path, "publication-draft", "PUBLICATION_DRAFT", Lane.PUBLICATION)
    registry = orchestrator._registry()
    orchestrator.store.write_head(
        "registry/artifact_registry.json",
        ArtifactRegistry(artifacts=[*registry.artifacts, denied]),
    )
    context = ContextPackManifest(
        pack_id="pack-audit",
        run_id="run-dr",
        event="DESKTOP_RESEARCH",
        lane=Lane.RESEARCH,
        desktop_research_spec=DesktopResearchContextSpec(
            questions=[QuestionInput(question_id="q-1", text="Bounded question", status="BASELINE")],
            allowed_source_types=[SourceType.PEER_REVIEWED_RESEARCH],
            retrieval_scope=["bounded context"],
            forbidden_roles=[],
            coverage_dimensions=["definitions"],
        ),
    )

    audited = orchestrator._audit_desktop_handoff(
        handoff(evidence=[evidence_capture(source_id="publication-draft")], back_references=["publication-draft"]),
        context,
    )

    assert not audited.passed
    assert any(issue.code == "FORBIDDEN_CONTEXT" for issue in audited.issues)


def test_company_primary_source_remains_company_claim_even_with_independent_refs() -> None:
    claim = evidence_capture(
        source_type=SourceType.COMPANY_PRIMARY,
        support_scope=SupportScope.COMPANY_CLAIM,
        independent_support_source_ids=["independent-source"],
    )
    assert claim.support_scope is SupportScope.COMPANY_CLAIM
    low_confidence_claim = evidence_capture(
        source_type=SourceType.COMPANY_PRIMARY,
        source_quality=SourceQuality.LOW_CONFIDENCE,
        support_scope=SupportScope.COMPANY_CLAIM,
    )
    assert low_confidence_claim.support_scope is SupportScope.COMPANY_CLAIM
    with pytest.raises(ValidationError, match="COMPANY_PRIMARY"):
        evidence_capture(
            source_type=SourceType.COMPANY_PRIMARY,
            support_scope=SupportScope.CAUSAL_EFFECT,
            independent_support_source_ids=["independent-source"],
        )


def test_low_confidence_source_classes_are_context_only() -> None:
    for source_type in (
        SourceType.WORKING_PAPER,
        SourceType.PREPRINT,
        SourceType.INDUSTRY_REPORT,
        SourceType.CORPORATE_PUBLICATION,
    ):
        context = evidence_capture(
            source_type=source_type,
            source_quality=SourceQuality.LOW_CONFIDENCE,
            support_scope=SupportScope.DESCRIPTIVE_CONTEXT,
        )
        assert context.source_quality is SourceQuality.LOW_CONFIDENCE
        with pytest.raises(ValidationError, match="LOW_CONFIDENCE"):
            evidence_capture(
                source_type=source_type,
                source_quality=SourceQuality.LOW_CONFIDENCE,
                support_scope=SupportScope.INDEPENDENT_EFFECTIVENESS,
            )
    with pytest.raises(ValidationError, match="flagged LOW_CONFIDENCE"):
        evidence_capture(
            source_type=SourceType.PREPRINT,
            source_quality=SourceQuality.MEDIUM,
            support_scope=SupportScope.DESCRIPTIVE_CONTEXT,
        )


def test_low_trust_social_and_forum_sources_are_leads_or_descriptive_only() -> None:
    lead = evidence_capture(
        source_type=SourceType.SOCIAL_MEDIA,
        source_quality=SourceQuality.LOW_TRUST,
        support_scope=SupportScope.LEAD_ONLY,
    )
    assert lead.source_quality is SourceQuality.LOW_TRUST
    with pytest.raises(ValidationError, match="LOW_TRUST"):
        evidence_capture(
            source_type=SourceType.ONLINE_FORUM,
            source_quality=SourceQuality.LOW_TRUST,
            support_scope=SupportScope.INDEPENDENT_EFFECTIVENESS,
        )
    with pytest.raises(ValidationError, match="flagged LOW_TRUST"):
        evidence_capture(
            source_type=SourceType.SOCIAL_MEDIA,
            source_quality=SourceQuality.MEDIUM,
            support_scope=SupportScope.DESCRIPTIVE_CONTEXT,
        )


def test_low_trust_source_cannot_be_sole_support_for_material_finding() -> None:
    with pytest.raises(ValidationError, match="solely on LOW_TRUST"):
        handoff(
            findings=[FindingRecord(
                finding_id="material-low-trust",
                statement="Unverified lead",
                evidence_ids=["ev-1"],
                material=True,
            )],
            evidence=[evidence_capture(
                source_type=SourceType.ONLINE_FORUM,
                source_quality=SourceQuality.LOW_TRUST,
                support_scope=SupportScope.LEAD_ONLY,
            )],
        )


def test_low_trust_source_cannot_resolve_an_evidence_gap() -> None:
    with pytest.raises(ValidationError, match="cannot resolve an Evidence Gap"):
        handoff(
            evidence=[evidence_capture(
                source_type=SourceType.SOCIAL_MEDIA,
                source_quality=SourceQuality.LOW_TRUST,
                support_scope=SupportScope.DESCRIPTIVE_CONTEXT,
            )],
            evidence_gaps=[EvidenceGap(
                gap_id="gap-1",
                description="Independent effectiveness evidence missing",
                material=True,
                resolved_by_evidence_ids=["ev-1"],
            )],
            coverage=coverage(unresolved_material_evidence_gap_ids=[]),
        )


def test_material_claim_requires_a_source_locator() -> None:
    with pytest.raises(ValidationError):
        evidence_capture(locator="", captured_statement="Observed pattern", material=True)


def test_evidence_capture_schema_version_matches_contract() -> None:
    assert evidence_capture().schema_version == "0.2"
    assert handoff().schema_version == "0.2"


def test_evidence_capture_requires_utc_snapshot_and_excerpt_locator_integrity() -> None:
    with pytest.raises(ValidationError, match="timezone-aware UTC"):
        evidence_capture(acquired_at=datetime.fromisoformat("2026-08-17T01:02:03"))
    with pytest.raises(ValidationError):
        evidence_capture(snapshot_sha256="A" * 64)
    with pytest.raises(ValidationError, match="present in text_snapshot"):
        evidence_capture(excerpt_locator_pairs=[EvidenceExcerpt(excerpt="absent", locator="p. 4")])
    with pytest.raises(ValidationError, match="primary locator"):
        evidence_capture(locator="p. 99")


@pytest.mark.parametrize(
    "missing_field",
    ["source_quality", "acquired_at", "text_snapshot", "snapshot_path", "snapshot_sha256", "excerpt_locator_pairs"],
)
def test_evidence_capture_snapshot_fields_are_required(missing_field: str) -> None:
    values = evidence_capture().model_dump()
    values.pop(missing_field)
    with pytest.raises(ValidationError):
        DesktopResearchEvidence.model_validate(values)


def test_desktop_snapshot_exchange_rejects_hash_and_path_violations(tmp_path: Path) -> None:
    question = source(tmp_path, "question", "RESEARCH_STATE", Lane.RESEARCH)
    contract = source(tmp_path, "desktop-contract", "DESKTOP_RESEARCH_CONTRACT", Lane.CONTROL_PLANE)
    pack = ContextBuilder(tmp_path, tmp_path / "runtime", ArtifactAccessPolicy(POLICY_PATH)).build(
        pack_id="pack-snapshot",
        run_id="run-snapshot",
        event="DESKTOP_RESEARCH",
        lane=Lane.RESEARCH,
        registry=ArtifactRegistry(artifacts=[question, contract]),
        artifact_ids=["question", "desktop-contract"],
        required_ids={"question", "desktop-contract"},
        desktop_research_spec=DesktopResearchContextSpec(
            question=QuestionInput(question_id="q-1", text="Candidate question", status="CANDIDATE"),
            allowed_source_types=[SourceType.PEER_REVIEWED_RESEARCH],
            retrieval_scope=["approved Work research connectors"],
            forbidden_roles=[],
            coverage_dimensions=["counterevidence"],
        ),
    )
    manifest = ContextPackManifest.model_validate_json((pack / "manifest.json").read_text(encoding="utf-8"))
    run_manifest = RunManifest(
        run_id="run-snapshot", task_id="task-snapshot", task_type="DESKTOP_RESEARCH",
        objective="Run bounded research", event="DESKTOP_RESEARCH", lane=Lane.RESEARCH,
        context_pack_id="pack-snapshot", worker_backend="interactive-work",
    )
    exchange = InteractiveWorkResearchBoundary().prepare(pack, manifest, run_manifest, tmp_path / "exchange")
    snapshot = Path(exchange.exchange_directory) / "evidence_snapshots" / "ev-1.txt"
    snapshot.write_text("Observed pattern in the bounded source section.", encoding="utf-8")
    valid = evidence_capture(
        text_snapshot=snapshot.read_text(encoding="utf-8"),
        snapshot_path=str(snapshot.resolve()),
        snapshot_sha256=sha256_file(snapshot),
    )
    invalid_hash = handoff(run_id="run-snapshot", evidence=[valid.model_copy(update={"snapshot_sha256": "b" * 64})])
    result = Path(exchange.expected_output_file)
    result.write_text(invalid_hash.model_dump_json(), encoding="utf-8")
    with pytest.raises(DesktopEvidenceSnapshotError, match="SHA-256 mismatch"):
        InteractiveWorkResearchBoundary().collect(exchange, result)

    invalid_text = handoff(
        run_id="run-snapshot",
        evidence=[valid.model_copy(update={"text_snapshot": "Observed pattern in another section."})],
    )
    result.write_text(invalid_text.model_dump_json(), encoding="utf-8")
    with pytest.raises(DesktopEvidenceSnapshotError, match="text_snapshot does not match"):
        InteractiveWorkResearchBoundary().collect(exchange, result)

    outside = tmp_path / "outside.txt"
    outside.write_text(snapshot.read_text(encoding="utf-8"), encoding="utf-8")
    invalid_path = handoff(run_id="run-snapshot", evidence=[valid.model_copy(update={"snapshot_path": str(outside.resolve())})])
    result.write_text(invalid_path.model_dump_json(), encoding="utf-8")
    with pytest.raises(DesktopEvidenceSnapshotError, match="under exactly"):
        InteractiveWorkResearchBoundary().collect(exchange, result)

    traversal_path = snapshot.parent / ".." / "evidence_snapshots" / "ev-1.txt"
    invalid_traversal = handoff(run_id="run-snapshot", evidence=[valid.model_copy(update={"snapshot_path": str(traversal_path)})])
    result.write_text(invalid_traversal.model_dump_json(), encoding="utf-8")
    with pytest.raises(DesktopEvidenceSnapshotError, match="under exactly"):
        InteractiveWorkResearchBoundary().collect(exchange, result)


def test_desktop_snapshot_is_copied_to_immutable_run_storage(tmp_path: Path) -> None:
    policy = tmp_path / "contracts" / "runtime_artifact_policy.yaml"
    policy.parent.mkdir(parents=True)
    shutil.copyfile(POLICY_PATH, policy)
    orchestrator = DiscoveryOrchestrator(tmp_path)
    run_id = "run-snapshot-copy"
    exchange_root = tmp_path / ".rh" / "work_exchange" / run_id / "evidence_snapshots"
    exchange_root.mkdir(parents=True)
    run_root = tmp_path / ".rh" / "runs" / run_id
    run_root.mkdir(parents=True)
    source_path = exchange_root / "ev-1.txt"
    source_path.write_text("Observed pattern in the bounded source section.", encoding="utf-8")
    capture = evidence_capture(
        text_snapshot=source_path.read_text(encoding="utf-8"),
        snapshot_path=str(source_path.resolve()),
        snapshot_sha256=sha256_file(source_path),
    )
    canonical = orchestrator._materialize_desktop_snapshots(
        handoff(evidence=[capture]), run_id, exchange_root,
    )
    canonical_path = Path(canonical.evidence[0].snapshot_path)
    assert canonical_path == run_root / "evidence_snapshots" / "ev-1.txt"
    assert canonical_path.read_text(encoding="utf-8") == source_path.read_text(encoding="utf-8")
    source_path.write_text("Work exchange may change after collection", encoding="utf-8")
    assert canonical_path.read_text(encoding="utf-8") == "Observed pattern in the bounded source section."


def test_handoff_requires_counterevidence_unknowns_and_evidence_gaps_fields() -> None:
    data = handoff().model_dump()
    data.pop("counterevidence")
    with pytest.raises(ValidationError):
        DesktopResearchHandoff.model_validate(data)


def test_worker_cannot_select_survey_delphi_or_case() -> None:
    with pytest.raises(ValidationError):
        NextMethodOption(
            option_id="method-selected",
            method="DELPHI",
            rationale="worker preference",
            addresses_gap_ids=["gap-1"],
            selected=True,
        )


def test_desktop_worker_cannot_forge_human_approved_finding_or_publication_eligibility() -> None:
    with pytest.raises(ValidationError):
        handoff(findings=[FindingRecord(
            finding_id="forged", statement="forged approval", evidence_ids=["ev-1"],
            status="HUMAN_APPROVED", decision_id="fabricated-decision",
        )])
    with pytest.raises(ValidationError):
        handoff(publication_eligibility=PublicationEligibility(
            status="ELIGIBLE", approved_by="not-a-human", decision_id="fabricated-decision",
        ))


def test_desktop_audit_enforces_context_allowed_source_types() -> None:
    result = handoff(evidence=[evidence_capture(
        source_type=SourceType.SOCIAL_MEDIA,
        source_quality=SourceQuality.LOW_TRUST,
        support_scope=SupportScope.LEAD_ONLY,
    )])
    audit = audit_desktop_research_handoff(
        result,
        allowed_back_references={"source-1"},
        allowed_source_types={SourceType.PEER_REVIEWED_RESEARCH},
    )
    assert not audit.passed
    assert any(item.code == "SOURCE_TYPE_NOT_ALLOWED" for item in audit.issues)


def test_provisional_question_seed_cannot_be_marked_authoritative_without_decision() -> None:
    with pytest.raises(ValidationError):
        QuestionInput(
            question_id="rq-seed",
            text="Seed question",
            status="CANDIDATE",
            authoritative=True,
        )


def test_desktop_research_context_excludes_publication_draft_and_archive_provenance(tmp_path: Path) -> None:
    question = source(tmp_path, "question", "RESEARCH_STATE", Lane.RESEARCH)
    contract = source(tmp_path, "desktop-contract", "DESKTOP_RESEARCH_CONTRACT", Lane.CONTROL_PLANE)
    draft = source(tmp_path, "draft", "PUBLICATION_DRAFT", Lane.PUBLICATION)
    provenance = source(tmp_path, "provenance", "SUPERSEDED_CANONICAL_PROVENANCE", Lane.RESEARCH)
    registry = ArtifactRegistry(artifacts=[question, contract, draft, provenance])
    context_builder = ContextBuilder(tmp_path, tmp_path / "runtime", ArtifactAccessPolicy(POLICY_PATH))
    pack = context_builder.build(
        pack_id="desktop-pack",
        run_id="run-dr",
        event="DESKTOP_RESEARCH",
        lane=Lane.RESEARCH,
        registry=registry,
        artifact_ids=["question", "desktop-contract", "draft", "provenance"],
        required_ids={"question", "desktop-contract"},
        desktop_research_spec=DesktopResearchContextSpec(
            question=QuestionInput(question_id="q-1", text="Candidate question", status="CANDIDATE"),
            allowed_source_types=[SourceType.PEER_REVIEWED_RESEARCH, SourceType.GOVERNMENT_PRIMARY],
            retrieval_scope=["approved Work research connectors"],
            forbidden_roles=["PUBLICATION_DRAFT", "SUPERSEDED_CANONICAL_PROVENANCE"],
            coverage_dimensions=["definitions", "counterevidence", "limitations"],
        ),
    )
    manifest = (pack / "manifest.json").read_text(encoding="utf-8")
    assert '"desktop_research_spec"' in manifest
    assert '"draft"' in manifest
    assert '"provenance"' in manifest
    assert not (pack / "artifacts" / "draft").exists()


def test_desktop_research_context_enforces_bounded_artifact_count(tmp_path: Path) -> None:
    question = source(tmp_path, "question", "RESEARCH_STATE", Lane.RESEARCH)
    contract = source(tmp_path, "desktop-contract", "DESKTOP_RESEARCH_CONTRACT", Lane.CONTROL_PLANE)
    registry = ArtifactRegistry(artifacts=[question, contract])
    spec = DesktopResearchContextSpec(
        question=QuestionInput(question_id="q-1", text="Candidate question", status="CANDIDATE"),
        allowed_source_types=[SourceType.PEER_REVIEWED_RESEARCH],
        retrieval_scope=["approved Work research connectors"],
        forbidden_roles=[],
        coverage_dimensions=["counterevidence"],
        max_context_artifacts=1,
    )
    assert "PUBLICATION_DRAFT" in spec.forbidden_roles
    with pytest.raises(ContextBuildError):
        ContextBuilder(tmp_path, tmp_path / "runtime", ArtifactAccessPolicy(POLICY_PATH)).build(
            pack_id="too-large",
            run_id="run-large",
            event="DESKTOP_RESEARCH",
            lane=Lane.RESEARCH,
            registry=registry,
            artifact_ids=["question", "desktop-contract"],
            required_ids={"question", "desktop-contract"},
            desktop_research_spec=spec,
        )


def test_fixed_source_count_cannot_stop_with_material_gap() -> None:
    with pytest.raises(ValidationError):
        CoverageStoppingAssessment(
            dimensions=[CoverageDimension(dimension="counterevidence", status="GAP", rationale="not searched")],
            saturation="LOW",
            unresolved_material_evidence_gap_ids=["gap-1"],
            remaining_information_value=RemainingInformationValue.HIGH,
            stop_recommended=True,
            stopping_rationale="Reached 10 sources",
            stopping_basis=["COVERAGE"],
            fixed_source_count_reached=10,
        )


def test_reducer_preserves_desktop_handoff_and_broker_routes_method_decision() -> None:
    result = handoff()
    audit = audit_desktop_research_handoff(result, allowed_back_references={"source-1"})
    assert audit.passed
    proposal, preserved = reduce_desktop_research_handoff(result, audit)
    assert preserved.counterevidence == result.counterevidence
    assert preserved.unknowns == result.unknowns
    assert preserved.evidence_gaps == result.evidence_gaps
    assert proposal.preserved_evidence_gaps == result.evidence_gaps
    assert proposal.requires_human_decision

    request = method_selection_request(result, decision_id="decision-method-1")
    assert request.request == "Select the next research method"
    assert request.options[0]["id"] == "method-1"
    assert request.counterevidence == result.counterevidence
    assert request.unknowns == result.unknowns
    assert request.resume_plan == {
        "next_phase": "RESEARCH_PLANNING",
        "next_task": "DESKTOP_RESEARCH_PREPARATION",
    }


def test_desktop_handoff_cannot_relabel_a_registered_publication_artifact_as_a_source() -> None:
    result = handoff(
        back_references=["publication-draft"],
        evidence=[evidence_capture(
            source_id="publication-draft", source_type=SourceType.OTHER,
            locator="fake locator", captured_statement="Observed pattern",
            excerpt_locator_pairs=[EvidenceExcerpt(excerpt="Observed pattern", locator="fake locator")],
        )],
    )
    audit = audit_desktop_research_handoff(
        result,
        allowed_back_references={"publication-draft"},
        forbidden_back_references={"publication-draft"},
    )
    assert not audit.passed
    assert any(item.code == "FORBIDDEN_CONTEXT" for item in audit.issues)


def test_interactive_work_boundary_uses_the_same_context_and_handoff_schema(tmp_path: Path) -> None:
    spec = DesktopResearchContextSpec(
        question=QuestionInput(question_id="q-1", text="Candidate question", status="CANDIDATE"),
        allowed_source_types=[SourceType.PEER_REVIEWED_RESEARCH],
        retrieval_scope=["approved Work research connectors"],
        forbidden_roles=["PUBLICATION_DRAFT"],
        coverage_dimensions=["counterevidence", "limitations"],
    )
    manifest = ContextPackManifest(
        pack_id="pack-work",
        run_id="run-dr",
        event="DESKTOP_RESEARCH",
        lane=Lane.RESEARCH,
        desktop_research_spec=spec,
    )
    pack = tmp_path / "pack"
    pack.mkdir()
    (pack / "manifest.json").write_text(manifest.model_dump_json(), encoding="utf-8")
    boundary = InteractiveWorkResearchBoundary()
    run_manifest = RunManifest(
        run_id="run-dr", task_id="task-dr", task_type="DESKTOP_RESEARCH", objective="Run bounded research",
        event="DESKTOP_RESEARCH", lane=Lane.RESEARCH, context_pack_id="pack-work", worker_backend="interactive-work",
    )
    exchange = boundary.prepare(pack, manifest, run_manifest, tmp_path / "exchange")
    assert exchange.expected_output_schema == "DesktopResearchHandoff"
    assert Path(exchange.task_file).is_file()
    task_text = Path(exchange.task_file).read_text(encoding="utf-8")
    assert "evidence_snapshots" in task_text
    assert "LOW_CONFIDENCE" in task_text
    assert "LOW_TRUST" in task_text
    schema = json.loads(Path(exchange.expected_output_schema_file).read_text(encoding="utf-8"))
    required = set(schema["$defs"]["DesktopResearchEvidence"]["required"])
    assert {"source_quality", "acquired_at", "text_snapshot", "snapshot_path", "snapshot_sha256", "excerpt_locator_pairs"} <= required

    snapshot_path = Path(exchange.exchange_directory) / "evidence_snapshots" / "ev-1.txt"
    snapshot_text = "Observed pattern in the bounded source section."
    snapshot_path.write_text(snapshot_text, encoding="utf-8")
    capture = evidence_capture(
        text_snapshot=snapshot_text,
        snapshot_path=str(snapshot_path.resolve()),
        snapshot_sha256=sha256_file(snapshot_path),
    )
    result_path = Path(exchange.expected_output_file)
    result_path.write_text(handoff(evidence=[capture]).model_dump_json(), encoding="utf-8")
    assert boundary.collect(exchange, result_path) == handoff(evidence=[capture])
