from __future__ import annotations

from misco_harness.models import (
    AuditResult,
    DesktopResearchHandoff,
    ResearchHandoff,
    StateDeltaProposal,
    WorkerResult,
)


class ReductionBlocked(RuntimeError):
    pass


def reduce_worker_result(result: WorkerResult, audit: AuditResult) -> tuple[StateDeltaProposal, ResearchHandoff]:
    if result.run_id != audit.run_id:
        raise ReductionBlocked("audit does not belong to the worker result")
    if not audit.passed or any(item.severity == "BLOCKER" for item in audit.issues):
        raise ReductionBlocked("BLOCKER audit issue prevents semantic reduction")

    semantic_candidates = {
        "observed": result.observed,
        "derived": result.derived,
        "interpreted": result.interpreted,
        "question_delta_candidates": result.question_delta_candidate,
    }
    semantic_changes = {key: value for key, value in semantic_candidates.items() if value}
    requires_decision = bool(result.observed or result.derived or result.interpreted or result.question_delta_candidate)
    minority_warnings = [
        issue for issue in result.issues
        if isinstance(issue, dict) and issue.get("kind") == "minority_warning"
    ]
    question_reasons = [
        item.get("reason", item) if isinstance(item, dict) else item
        for item in result.question_delta_candidate
    ]
    proposal = StateDeltaProposal(
        run_id=result.run_id,
        operational_changes={"worker_run_completed": True},
        semantic_changes=semantic_changes,
        requires_human_decision=requires_decision,
        preserved_counterevidence=result.counterevidence,
        preserved_unknowns=result.unknown,
        preserved_scope_limits=result.scope_limits,
        preserved_evidence_gaps=result.evidence_gap_hypotheses,
        preserved_question_overlaps=result.question_overlaps,
    )
    handoff = ResearchHandoff(
        run_id=result.run_id,
        current_answer=[*result.observed, *result.derived, *result.interpreted],
        counterevidence=result.counterevidence,
        unknowns=result.unknown,
        scope_limits=result.scope_limits,
        question_overlaps=result.question_overlaps,
        evidence_gap_hypotheses=result.evidence_gap_hypotheses,
        minority_warnings=minority_warnings,
        question_change_reasons=question_reasons,
        back_references=result.back_references,
    )
    return proposal, handoff


def reduce_desktop_research_handoff(
    handoff: DesktopResearchHandoff,
    audit: AuditResult,
) -> tuple[StateDeltaProposal, DesktopResearchHandoff]:
    if handoff.run_id != audit.run_id:
        raise ReductionBlocked("audit does not belong to the Desktop Research Handoff")
    if not audit.passed or any(item.severity == "BLOCKER" for item in audit.issues):
        raise ReductionBlocked("BLOCKER audit issue prevents Desktop Research reduction")
    proposal = StateDeltaProposal(
        run_id=handoff.run_id,
        operational_changes={"desktop_research_handoff_validated": True},
        semantic_changes={
            "question_impact": handoff.question_impact.model_dump(mode="json"),
            "candidate_findings": [item.model_dump(mode="json") for item in handoff.findings],
            "candidate_next_method_options": [item.model_dump(mode="json") for item in handoff.candidate_next_method_options],
        },
        requires_human_decision=True,
        preserved_counterevidence=handoff.counterevidence,
        preserved_unknowns=handoff.unknowns,
        preserved_evidence_gaps=handoff.evidence_gaps,
    )
    return proposal, handoff
