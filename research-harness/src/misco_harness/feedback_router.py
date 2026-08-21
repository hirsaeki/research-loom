from __future__ import annotations

from dataclasses import dataclass

from misco_harness.models import PublicationFeedback


class FeedbackRouteError(RuntimeError):
    pass


@dataclass(frozen=True)
class FeedbackRoute:
    feedback_id: str
    destination: str
    evidence_eligible: bool = False


ROUTES = {
    "ARGUMENT_GAP": "RESEARCH_SYNTHESIS",
    "QUESTION_SCOPE_AMBIGUITY": "QUESTION_REVIEW",
    "MISSING_RESEARCH_INPUT": "RESEARCH",
    "ACADEMIC_QA_REQUIRED": "ACADEMIC_QA_HUMAN",
    "MODEL_REVISION_UNRESOLVED": "MODEL_REVIEW",
    "PRIMARY_EXPOSITION_CONFLICT": "PUBLICATION_ORCHESTRATOR",
    "FORMAL_METADATA_MISSING": "PUBLICATION_OPS_HUMAN",
}


def route_feedback(feedback: PublicationFeedback) -> FeedbackRoute:
    destination = ROUTES.get(feedback.type)
    if destination is None:
        raise FeedbackRouteError(f"publication feedback type {feedback.type!r} has no registered route")
    return FeedbackRoute(feedback_id=feedback.feedback_id, destination=destination)
