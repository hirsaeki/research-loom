from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from misco_harness.models import (
    AuditIssue,
    AuditResult,
    AttentionDistillationHandoff,
    ContextPackManifest,
    DesktopResearchHandoff,
    EvidenceStatus,
    ProvenanceAuditHandoff,
    ProvenanceAuditPlan,
    ResearchState,
    SourceType,
    StudyRole,
    WorkerResult,
    WorkExecutionRequest,
    WriterUseMode,
)
from misco_harness.workers.work import (
    validate_provenance_snapshot_directory,
    validate_source_capture_exchange,
)


def audit_worker_result(result: WorkerResult, context: ContextPackManifest) -> AuditResult:
    issues: list[AuditIssue] = []
    if result.run_id != context.run_id:
        issues.append(AuditIssue(code="RUN_ID_MISMATCH", severity="BLOCKER", message="Worker result does not belong to this Context Pack"))
    forbidden = set(context.forbidden_context)
    contaminated = sorted(forbidden.intersection(result.back_references))
    if contaminated:
        issues.append(AuditIssue(code="FORBIDDEN_CONTEXT", severity="BLOCKER", message=f"Forbidden artifacts referenced: {contaminated}"))
    allowed = {ref.artifact_id for ref in context.must_include + context.retrieve_on_demand}
    missing = sorted(set(result.back_references).difference(allowed))
    if missing:
        issues.append(AuditIssue(code="MISSING_BACK_REFERENCE", severity="BLOCKER", message=f"Unregistered Context Pack references: {missing}"))
    if (result.observed or result.derived or result.interpreted) and not result.back_references:
        issues.append(AuditIssue(code="MISSING_BACK_REFERENCE", severity="BLOCKER", message="Substantive output has no back-reference"))
    if not result.counterevidence:
        issues.append(AuditIssue(code="COUNTEREVIDENCE_NOT_REPORTED", severity="MAJOR", message="Worker did not explicitly report counterevidence"))
    if not result.unknown:
        issues.append(AuditIssue(code="UNKNOWNS_NOT_REPORTED", severity="MAJOR", message="Worker did not explicitly report unknowns"))
    if result.interpreted and not (result.observed or result.derived):
        issues.append(AuditIssue(
            code="UNSUPPORTED_STRENGTHENING", severity="BLOCKER",
            message="Interpretation is present without an observed or derived basis",
        ))
    for value in [*result.interpreted, *result.question_delta_candidate]:
        if not isinstance(value, dict):
            continue
        status = str(value.get("status", "")).upper()
        kind = str(value.get("kind", "")).upper()
        if status in {"ADOPTED", "ACCEPTED", "BASELINE", "STABLE", "FINAL"} and not value.get("decision_id"):
            issues.append(AuditIssue(
                code="HUMAN_DECISION_VIOLATION", severity="BLOCKER",
                message=f"Worker attempted Human-only semantic status {status} without a Decision ID",
            ))
        if kind == "METHOD_SELECTION" and value.get("selected") is True and not value.get("decision_id"):
            issues.append(AuditIssue(
                code="METHOD_RESPONSIBILITY_VIOLATION", severity="BLOCKER",
                message="Worker attempted to select a method without a Human Decision ID",
            ))
    issues.extend(_declared_issues(result.issues))
    return AuditResult(run_id=result.run_id, passed=not any(item.severity == "BLOCKER" for item in issues), issues=issues)


def audit_attention_distillation_handoff(
    handoff: AttentionDistillationHandoff,
    context: ContextPackManifest,
    *,
    drop_artifact_ids: set[str],
) -> AuditResult:
    issues: list[AuditIssue] = []
    if handoff.run_id != context.run_id:
        issues.append(AuditIssue(code="RUN_ID_MISMATCH", severity="BLOCKER", message="Attention Handoff does not belong to this Context Pack"))
    allowed = {ref.artifact_id for ref in context.must_include + context.retrieve_on_demand}
    referenced = set(handoff.back_references)
    missing_refs = sorted(referenced.difference(allowed))
    if missing_refs:
        issues.append(AuditIssue(code="MISSING_BACK_REFERENCE", severity="BLOCKER", message=f"Attention Handoff references artifacts outside its Context Pack: {missing_refs}"))
    if set(handoff.used_artifact_ids).intersection(handoff.excluded_artifact_ids):
        issues.append(AuditIssue(code="DUPLICATE_DROP_CLASSIFICATION", severity="BLOCKER", message="Attention drop artifacts cannot be both used and excluded"))
    classified = set(handoff.used_artifact_ids).union(handoff.excluded_artifact_ids)
    if classified != drop_artifact_ids:
        issues.append(AuditIssue(
            code="DROP_COVERAGE_MISMATCH",
            severity="BLOCKER",
            message=f"Attention Handoff must classify exactly the drop artifacts; missing={sorted(drop_artifact_ids - classified)}, extra={sorted(classified - drop_artifact_ids)}",
        ))
    if set(handoff.excluded_artifact_ids).difference(handoff.exclusion_reasons):
        issues.append(AuditIssue(code="EXCLUSION_REASON_MISSING", severity="BLOCKER", message="Every excluded drop artifact requires a reason"))
    expected_hash = hashlib.sha256(handoff.candidate_map_markdown.encode("utf-8")).hexdigest()
    if expected_hash != handoff.candidate_map_sha256:
        issues.append(AuditIssue(code="CANDIDATE_MAP_HASH_MISMATCH", severity="BLOCKER", message="Candidate Attention Map SHA-256 does not match its UTF-8 content"))
    if not handoff.items:
        issues.append(AuditIssue(code="EMPTY_ATTENTION_CANDIDATE", severity="MAJOR", message="Attention Distillation produced no candidate items"))
    for item in handoff.items:
        if item.operation == "REMOVE_CANDIDATE" and not handoff.uncertainty:
            issues.append(AuditIssue(code="REMOVAL_WITHOUT_UNCERTAINTY", severity="MAJOR", message=f"Removal candidate {item.attention_id!r} has no uncertainty or review note"))
    if handoff.evidence_eligible or handoff.may_determine_method or handoff.may_determine_answer:
        issues.append(AuditIssue(code="ATTENTION_AUTHORITY_ESCALATION", severity="BLOCKER", message="Attention Distillation cannot grant Evidence, method, or answer authority"))
    return AuditResult(run_id=handoff.run_id, passed=not any(item.severity == "BLOCKER" for item in issues), issues=issues)


def audit_desktop_research_handoff(
    handoff: DesktopResearchHandoff,
    *,
    allowed_back_references: set[str],
    forbidden_back_references: set[str] | None = None,
    allowed_source_types: set[SourceType] | None = None,
) -> AuditResult:
    issues: list[AuditIssue] = []
    # v0.3 separates immutable SourceCaptures from EvidenceCitations. Keep
    # this branch additive so immutable v0.2 handoffs remain auditable.
    if handoff.source_captures or handoff.evidence_citations:
        captures = {item.capture_id: item for item in handoff.source_captures}
        citations = {item.evidence_id: item for item in handoff.evidence_citations}
        if len(captures) != len(handoff.source_captures):
            issues.append(AuditIssue(code="DUPLICATE_CAPTURE_ID", severity="BLOCKER", message="SourceCapture IDs must be unique"))
        if len(citations) != len(handoff.evidence_citations):
            issues.append(AuditIssue(code="DUPLICATE_EVIDENCE_ID", severity="BLOCKER", message="EvidenceCitation IDs must be unique"))
        missing_captures = sorted({item.capture_id for item in handoff.evidence_citations}.difference(captures))
        if missing_captures:
            issues.append(AuditIssue(code="MISSING_CAPTURE_REFERENCE", severity="BLOCKER", message=f"Missing SourceCaptures: {missing_captures}"))
        missing_finding_refs = sorted({evidence_id for finding in handoff.findings for evidence_id in finding.evidence_ids}.difference(citations))
        if missing_finding_refs:
            issues.append(AuditIssue(code="MISSING_CITATION_REFERENCE", severity="BLOCKER", message=f"Findings reference missing EvidenceCitations: {missing_finding_refs}"))
        if allowed_source_types is not None:
            disallowed = sorted({item.source_type.value for item in handoff.evidence_citations if item.source_type not in allowed_source_types})
            if disallowed:
                issues.append(AuditIssue(code="SOURCE_TYPE_NOT_ALLOWED", severity="BLOCKER", message=f"EvidenceCitation source types outside Context Pack: {disallowed}"))
        for citation in handoff.evidence_citations:
            if citation.evidence_status is not EvidenceStatus.VERIFIED and citation.writer_use_mode not in {WriterUseMode.LEAD_ONLY, WriterUseMode.BLOCKED}:
                issues.append(AuditIssue(code="UNVERIFIED_WRITER_USE", severity="BLOCKER", message=f"Evidence {citation.evidence_id} uses a publication mode while unverified"))
            if citation.writer_use_mode is WriterUseMode.AGGREGATE_SYNTHESIS and not citation.included_source_ids:
                issues.append(AuditIssue(code="AGGREGATE_TRACEABILITY_MISSING", severity="BLOCKER", message=f"Aggregate Evidence {citation.evidence_id} has no included source trace"))
            if citation.study_role in {StudyRole.NARRATIVE_REVIEW, StudyRole.SCOPING_REVIEW} and citation.support_scope.value in {"INDEPENDENT_EFFECTIVENESS", "CAUSAL_EFFECT"}:
                issues.append(AuditIssue(code="REVIEW_INFERENCE_VIOLATION", severity="BLOCKER", message=f"Review Evidence {citation.evidence_id} overreaches its allowed inference"))
            if citation.study_role in {StudyRole.SYSTEMATIC_REVIEW, StudyRole.META_ANALYSIS, StudyRole.SCOPING_REVIEW, StudyRole.NARRATIVE_REVIEW, StudyRole.UMBRELLA_REVIEW}:
                missing_originals = sorted(set(citation.included_source_ids).difference({item.source_id for item in captures.values()}))
                if missing_originals:
                    issues.append(AuditIssue(code="REVIEW_ORIGINAL_NOT_CAPTURED", severity="BLOCKER", message=f"Review {citation.evidence_id} names uncaptured originals: {missing_originals}"))
        if handoff.research_brief is not None:
            brief = handoff.research_brief
            represented_roles = {item.study_role for item in handoff.evidence_citations if item.evidence_status is EvidenceStatus.VERIFIED}
            represented_claims = {claim for item in handoff.evidence_citations for claim in item.claim_types}
            for claim_type in brief.claim_types_to_test:
                if claim_type not in represented_claims:
                    issues.append(AuditIssue(code="CLAIM_TYPE_UNEVALUATED", severity="MAJOR", message=f"Research Brief claim type was not explicitly evaluated: {claim_type.value}"))
            for claim_type, required_roles in brief.study_role_requirements.items():
                if required_roles and not represented_roles.intersection(required_roles):
                    issues.append(AuditIssue(code="REQUIRED_STUDY_ROLE_MISSING", severity="BLOCKER", message=f"Required study role missing for {claim_type}"))
            if not handoff.counterevidence_search_summary.strip():
                issues.append(AuditIssue(code="COUNTEREVIDENCE_NOT_ASSESSED", severity="BLOCKER", message="Research Brief requires an explicit counterevidence search record"))
        elif not handoff.counterevidence_search_summary.strip():
            issues.append(AuditIssue(code="COUNTEREVIDENCE_NOT_ASSESSED", severity="BLOCKER", message="v0.3 Desktop Research must report how counterevidence was sought"))
        allowed = set(allowed_back_references)
        allowed.update(item.source_id for item in captures.values())
        contaminated = sorted(set(handoff.back_references).intersection(forbidden_back_references or set()))
        if contaminated:
            issues.append(AuditIssue(code="FORBIDDEN_CONTEXT", severity="BLOCKER", message=f"Forbidden artifacts referenced: {contaminated}"))
        missing = sorted(set(handoff.back_references).difference(allowed))
        if missing:
            issues.append(AuditIssue(code="MISSING_BACK_REFERENCE", severity="BLOCKER", message=f"Unregistered Context Pack references: {missing}"))
        finding_by_id = {item.finding_id: item for item in handoff.findings}
        for finding in finding_by_id.values():
            refs = [citations[item] for item in finding.evidence_ids if item in citations]
            if any(item.evidence_status is not EvidenceStatus.VERIFIED for item in refs):
                issues.append(AuditIssue(
                    code="FINDING_UNVERIFIED_SUPPORT",
                    severity="BLOCKER" if finding.material else "MAJOR",
                    message=f"Finding {finding.finding_id} is supported by non-VERIFIED Evidence",
                ))
            if (
                finding.material
                and any(item.study_role in {StudyRole.NARRATIVE_REVIEW, StudyRole.SCOPING_REVIEW} for item in refs)
                and not any(item.study_role in {StudyRole.PRIMARY_RESEARCH, StudyRole.SYSTEMATIC_REVIEW, StudyRole.META_ANALYSIS} for item in refs)
            ):
                issues.append(AuditIssue(code="REVIEW_ONLY_MATERIAL_FINDING", severity="BLOCKER", message=f"Material Finding {finding.finding_id} relies only on review-level evidence"))
        return AuditResult(
            run_id=handoff.run_id,
            passed=not any(item.severity == "BLOCKER" for item in issues),
            issues=issues,
            metrics={
                "capture_success": len(captures),
                "citation_count": len(citations),
                "independent_support_units": len({
                    (f"overlap:{item.overlap_group_id}" if item.overlap_group_id else f"source:{captures[item.capture_id].source_id}")
                    for item in citations.values() if item.capture_id in captures
                }),
                "verified": sum(item.evidence_status is EvidenceStatus.VERIFIED for item in citations.values()),
                "lead_only": sum(item.evidence_status is EvidenceStatus.LEAD_ONLY for item in citations.values()),
                "claim_not_supported": sum(item.evidence_status.value == "CLAIM_NOT_SUPPORTED" for item in citations.values()),
                "capture_unavailable": sum(item.evidence_status.value == "CAPTURE_UNAVAILABLE" for item in citations.values()),
            },
        )
    contaminated = sorted(set(handoff.back_references).intersection(forbidden_back_references or set()))
    if contaminated:
        issues.append(AuditIssue(
            code="FORBIDDEN_CONTEXT",
            severity="BLOCKER",
            message=f"Desktop Research Handoff references forbidden registered artifacts: {contaminated}",
        ))
    missing = sorted(set(handoff.back_references).difference(allowed_back_references))
    if missing:
        issues.append(AuditIssue(
            code="MISSING_BACK_REFERENCE",
            severity="BLOCKER",
            message=f"Desktop Research Handoff references sources outside its Context Pack: {missing}",
        ))
    if not handoff.counterevidence_search_summary.strip():
        issues.append(AuditIssue(
            code="COUNTEREVIDENCE_NOT_ASSESSED",
            severity="BLOCKER",
            message="Desktop Research must report how counterevidence was sought",
        ))
    if allowed_source_types is not None:
        disallowed = sorted({item.source_type.value for item in handoff.evidence if item.source_type not in allowed_source_types})
        if disallowed:
            issues.append(AuditIssue(
                code="SOURCE_TYPE_NOT_ALLOWED",
                severity="BLOCKER",
                message=f"Desktop Research Evidence uses source types outside its Context Pack: {disallowed}",
            ))
    return AuditResult(
        run_id=handoff.run_id,
        passed=not any(item.severity == "BLOCKER" for item in issues),
        issues=issues,
    )


def audit_provenance_audit_handoff(
    handoff: ProvenanceAuditHandoff,
    plan: ProvenanceAuditPlan,
    baseline: ResearchState,
    context: ContextPackManifest,
    snapshot_root,
) -> AuditResult:
    """Audit a legacy Evidence repair without reducing it into Research State."""
    issues: list[AuditIssue] = []
    if handoff.source_captures or handoff.evidence_citations:
        target_ids = {item.evidence_id for item in plan.target_evidence}
        citation_ids = {item.evidence_id for item in handoff.evidence_citations}
        unresolved_ids = {item.evidence_id for item in handoff.unresolved}
        if citation_ids.union(unresolved_ids) != target_ids or citation_ids.intersection(unresolved_ids):
            issues.append(AuditIssue(code="TARGET_SET_MISMATCH", severity="BLOCKER", message="v0.3 Capture/Citation result must partition the closed-world target set"))
        if handoff.run_id != context.run_id:
            issues.append(AuditIssue(code="RUN_ID_MISMATCH", severity="BLOCKER", message="Provenance Audit Handoff does not belong to this Context Pack"))
        if handoff.baseline_state_id != plan.baseline_snapshot.state_id:
            issues.append(AuditIssue(code="BASELINE_MISMATCH", severity="BLOCKER", message="Provenance Audit Handoff references a different baseline Research State"))
        if handoff.source_manifest_id != "provenance-audit-plan":
            issues.append(AuditIssue(code="PLAN_BACK_REFERENCE_MISMATCH", severity="BLOCKER", message="Provenance Audit Handoff must reference the registered repair plan"))
        allowed = {ref.artifact_id for ref in context.must_include + context.retrieve_on_demand}
        missing = sorted(set(handoff.back_references).difference(allowed))
        if missing:
            issues.append(AuditIssue(code="MISSING_BACK_REFERENCE", severity="BLOCKER", message=f"Provenance Handoff references sources outside its Context Pack: {missing}"))
        try:
            validate_source_capture_exchange(
                handoff,
                WorkExecutionRequest(
                    run_id=handoff.run_id,
                    context_pack=".",
                    manifest=".",
                    task_file=".",
                    exchange_directory=str(Path(snapshot_root).parent.resolve()),
                    expected_output_schema="ProvenanceAuditHandoff",
                    expected_output_schema_file=".",
                    expected_output_file=".",
                ),
            )
        except (OSError, ValueError, RuntimeError) as error:
            issues.append(AuditIssue(code="CAPTURE_VALIDATION_FAILED", severity="BLOCKER", message=str(error)))
        for citation in handoff.evidence_citations:
            if citation.evidence_status is not EvidenceStatus.VERIFIED:
                issues.append(AuditIssue(code="UNVERIFIED_REPAIR", severity="MAJOR", message=f"Citation {citation.evidence_id} remains {citation.evidence_status.value}"))
            target = next((item for item in plan.target_evidence if item.evidence_id == citation.evidence_id), None)
            if target is not None and (
                citation.source_type is not target.source_type
                or citation.support_scope is not target.support_scope
                or citation.excerpt_locator != target.locator
            ):
                issues.append(AuditIssue(code="SOURCE_SCOPE_CHANGED", severity="BLOCKER", message=f"Citation {citation.evidence_id} changed source identity or locator"))
        return AuditResult(
            run_id=handoff.run_id,
            passed=not any(item.severity == "BLOCKER" for item in issues),
            issues=issues,
            metrics={
                "capture_success": len(handoff.source_captures),
                "citation_count": len(handoff.evidence_citations),
                "independent_support_units": len({
                    (f"overlap:{item.overlap_group_id}" if item.overlap_group_id else f"source:{next((capture.source_id for capture in handoff.source_captures if capture.capture_id == item.capture_id), item.capture_id)}")
                    for item in handoff.evidence_citations
                }),
                "verified": sum(item.evidence_status is EvidenceStatus.VERIFIED for item in handoff.evidence_citations),
                "lead_only": sum(item.evidence_status is EvidenceStatus.LEAD_ONLY for item in handoff.evidence_citations),
                "claim_not_supported": sum(item.evidence_status.value == "CLAIM_NOT_SUPPORTED" for item in handoff.evidence_citations),
                "capture_unavailable": sum(item.evidence_status.value == "CAPTURE_UNAVAILABLE" for item in handoff.evidence_citations),
            },
        )
    target_by_id = {item.evidence_id: item for item in plan.target_evidence}
    selected_baseline = [
        item
        for item in baseline.evidence
        if isinstance(item, dict)
        and item.get("evidence_id") in target_by_id
        and item.get("schema_version") == plan.selection.legacy_schema_version
        and all(field not in item for field in plan.selection.missing_capture_fields)
    ]
    baseline_by_id = {str(item.get("evidence_id")): item for item in selected_baseline}
    if len(selected_baseline) != plan.selection.actual_count or set(baseline_by_id) != set(target_by_id):
        issues.append(AuditIssue(
            code="LEGACY_SELECTION_MISMATCH", severity="BLOCKER",
            message="The baseline no longer contains the planned closed-world legacy selection",
        ))
    if handoff.run_id != context.run_id:
        issues.append(AuditIssue(
            code="RUN_ID_MISMATCH", severity="BLOCKER",
            message="Provenance Audit Handoff does not belong to this Context Pack",
        ))
    if handoff.baseline_state_id != plan.baseline_snapshot.state_id:
        issues.append(AuditIssue(
            code="BASELINE_MISMATCH", severity="BLOCKER",
            message="Provenance Audit Handoff references a different baseline Research State",
        ))
    if handoff.source_manifest_id != "provenance-audit-plan":
        issues.append(AuditIssue(
            code="PLAN_BACK_REFERENCE_MISMATCH", severity="BLOCKER",
            message="Provenance Audit Handoff must reference the registered repair plan",
        ))
    allowed = {ref.artifact_id for ref in context.must_include + context.retrieve_on_demand}
    missing = sorted(set(handoff.back_references).difference(allowed))
    if missing:
        issues.append(AuditIssue(
            code="MISSING_BACK_REFERENCE", severity="BLOCKER",
            message=f"Provenance Audit Handoff references sources outside its Context Pack: {missing}",
        ))
    forbidden = set(context.forbidden_context)
    contaminated = sorted(forbidden.intersection(handoff.back_references))
    if contaminated:
        issues.append(AuditIssue(
            code="FORBIDDEN_CONTEXT", severity="BLOCKER",
            message=f"Provenance Audit Handoff references forbidden context: {contaminated}",
        ))

    target_ids = set(target_by_id)
    if set(handoff.target_evidence_ids) != target_ids:
        issues.append(AuditIssue(
            code="TARGET_SET_MISMATCH", severity="BLOCKER",
            message="Provenance Audit Handoff does not cover the closed-world target set exactly",
        ))
    if not set(handoff.target_evidence_ids).issubset(baseline_by_id):
        missing_baseline = sorted(target_ids.difference(baseline_by_id))
        issues.append(AuditIssue(
            code="BASELINE_EVIDENCE_MISSING", severity="BLOCKER",
            message=f"Target Evidence is absent from the baseline Research State: {missing_baseline}",
        ))

    try:
        validate_provenance_snapshot_directory(handoff, snapshot_root)
    except (OSError, ValueError, RuntimeError) as error:
        issues.append(AuditIssue(
            code="SNAPSHOT_VALIDATION_FAILED", severity="BLOCKER", message=str(error),
        ))

    for evidence in handoff.evidence:
        target = target_by_id.get(evidence.evidence_id)
        baseline_item = baseline_by_id.get(evidence.evidence_id)
        if target is None or baseline_item is None:
            continue
        if evidence.source_id != target.source_id or evidence.source_type != target.source_type:
            issues.append(AuditIssue(
                code="SOURCE_IDENTITY_CHANGED", severity="BLOCKER",
                message=f"Evidence {evidence.evidence_id} changed source identity",
            ))
        if evidence.locator != target.locator or evidence.support_scope != target.support_scope:
            issues.append(AuditIssue(
                code="SOURCE_SCOPE_CHANGED", severity="BLOCKER",
                message=f"Evidence {evidence.evidence_id} changed locator or support scope",
            ))
        baseline_quality = baseline_item.get("source_quality")
        if baseline_quality is not None:
            quality_rank = {"LOW_TRUST": 0, "LOW_CONFIDENCE": 1, "MEDIUM": 2, "HIGH": 3}
            if quality_rank.get(evidence.source_quality.value, -1) > quality_rank.get(str(baseline_quality), -1):
                issues.append(AuditIssue(
                    code="SOURCE_QUALITY_UPGRADED", severity="BLOCKER",
                    message=f"Evidence {evidence.evidence_id} upgraded source quality during repair",
                ))
        for field in (
            "captured_statement", "evidence_kind", "material",
            "independent_support_source_ids", "limitations",
        ):
            expected = baseline_item.get(field)
            actual = getattr(evidence, field)
            if expected is not None and actual != expected:
                issues.append(AuditIssue(
                    code="RESEARCH_MEANING_CHANGED", severity="BLOCKER",
                    message=f"Evidence {evidence.evidence_id} changed preserved field {field}",
                ))
        if evidence.verification_status != "VERIFIED":
            issues.append(AuditIssue(
                code="UNVERIFIED_RECORD", severity="BLOCKER",
                message=f"Resolved Evidence {evidence.evidence_id} is not marked VERIFIED",
            ))

    for unresolved in handoff.unresolved:
        target = target_by_id.get(unresolved.evidence_id)
        if target is None:
            continue
        if unresolved.attempted_locator and unresolved.attempted_locator != target.locator:
            issues.append(AuditIssue(
                code="UNLISTED_SOURCE_LOCATOR", severity="BLOCKER",
                message=f"Unresolved Evidence {unresolved.evidence_id} used a locator outside the plan",
            ))

    return AuditResult(
        run_id=handoff.run_id,
        passed=not any(item.severity == "BLOCKER" for item in issues),
        issues=issues,
    )


def _declared_issues(values: list[Any]) -> list[AuditIssue]:
    output: list[AuditIssue] = []
    for value in values:
        if not isinstance(value, dict):
            continue
        code = value.get("code")
        severity = value.get("severity")
        message = value.get("message")
        if isinstance(code, str) and severity in {"BLOCKER", "MAJOR", "MINOR"} and isinstance(message, str):
            output.append(AuditIssue(code=code, severity=severity, message=message))
    return output
