from __future__ import annotations

from copy import deepcopy
import json
from typing import Any, Mapping

from core.conversation import ConversationRuntimeError
from core.conversation.validation import WorkConversationValidator
from core.runtime import canonical_digest
from plugins.local_conversation_store.resume import state_delta_proposal_for_project
from plugins.local_conversation_store.synthesis import (
    list_synthesis_candidate_rows,
    load_synthesis_candidate_row,
)
from plugins.local_decision_store.resume import decision_request_for_project

from .argument_facade import research_argument_proposal_payload
from .conversation_view import (
    ConversationViewError,
    normalize_view,
    project_action_result,
    project_collect,
    project_confirmation_result,
    project_decision_result,
    project_replay,
    project_resume,
    project_run,
    project_status,
    project_synthesis_list,
    project_synthesis_show,
    projection_unavailable,
)
from .facade import LocalApplicationError
from .candidate_projection import build_candidate_projection
from .recommendation_facade import (
    LocalApplicationFacade as _BaseLocalApplicationFacade,
    research_recommendation_proposal_payload,
)

_KIND_BY_PRODUCER = {
    "research.recommendation.propose@0.1.0": "recommendation",
    "research.argument.propose@0.1.0": "argument",
}
_ACTION_BY_KIND = {
    "recommendation": "research.recommendation.propose",
    "argument": "research.argument.propose",
}
_ERROR = "SYNTHESIS-CANDIDATE-001"
_LABEL_LIMIT = 160
_VALIDATOR = WorkConversationValidator()


def _decode_json(raw: Any, *, message: str) -> Mapping[str, Any]:
    if not isinstance(raw, str):
        raise ConversationRuntimeError(_ERROR, message)
    try:
        value = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ConversationRuntimeError(_ERROR, message) from exc
    if not isinstance(value, Mapping):
        raise ConversationRuntimeError(_ERROR, message)
    return value


def _safe_kind(raw: Any) -> str | None:
    try:
        value = json.loads(str(raw))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(value, Mapping):
        return None
    provenance = value.get("provenance")
    producer = provenance.get("producer") if isinstance(provenance, Mapping) else None
    return _KIND_BY_PRODUCER.get(str(producer))


def _semantic_object(candidate: Mapping[str, Any], *, expected_kind: str, project_id: str) -> Mapping[str, Any]:
    actions = candidate.get("proposed_actions")
    if not isinstance(actions, list) or len(actions) != 1:
        raise ConversationRuntimeError(_ERROR, "synthesis candidate action structure is invalid")
    action = actions[0]
    if not isinstance(action, Mapping) or action.get("kind") != "CREATE_OBJECT":
        raise ConversationRuntimeError(_ERROR, "synthesis candidate action is not a supported object creation")
    payload = action.get("payload")
    obj = payload.get("object") if isinstance(payload, Mapping) else None
    if not isinstance(obj, Mapping):
        raise ConversationRuntimeError(_ERROR, "synthesis candidate object is malformed")
    object_id = obj.get("id")
    if (
        obj.get("kind") != expected_kind
        or obj.get("project_id") != project_id
        or not isinstance(object_id, str)
        or not object_id
    ):
        raise ConversationRuntimeError(_ERROR, "synthesis candidate object identity is invalid")
    affected = candidate.get("affected_refs")
    if not isinstance(affected, list) or not any(
        isinstance(ref, Mapping)
        and ref.get("kind") == expected_kind
        and ref.get("id") == object_id
        for ref in affected
    ):
        raise ConversationRuntimeError(_ERROR, "synthesis candidate affected_refs do not bind its object")
    return obj


def _validate_semantics(kind: str, obj: Mapping[str, Any], source_payload: Mapping[str, Any]) -> None:
    try:
        normalized = (
            research_recommendation_proposal_payload(source_payload)
            if kind == "recommendation"
            else research_argument_proposal_payload(source_payload)
        )
    except (TypeError, ValueError) as exc:
        raise ConversationRuntimeError(_ERROR, "synthesis candidate source payload is invalid") from exc

    if kind == "recommendation":
        if (
            obj.get("statement") != normalized["statement"]
            or obj.get("finding_ids") != normalized["finding_ids"]
            or obj.get("conditions", []) != normalized["conditions"]
            or obj.get("scope", []) != normalized["scope"]
            or obj.get("adoption_state") != "approved"
        ):
            raise ConversationRuntimeError(_ERROR, "Recommendation candidate does not match its source proposal")
        return

    required = ("conclusion", "warrant")
    list_fields = (
        "question_ids",
        "premise_claim_ids",
        "finding_ids",
        "evidence_ids",
        "counter_review_ids",
        "implications",
    )
    if any(obj.get(field) != normalized[field] for field in required):
        raise ConversationRuntimeError(_ERROR, "Argument candidate does not match its source proposal")
    if any(obj.get(field) != normalized[field] for field in list_fields):
        raise ConversationRuntimeError(_ERROR, "Argument candidate does not match its source proposal")
    for field in ("conclusion_claim_id", "qualifier"):
        if obj.get(field) != normalized.get(field):
            raise ConversationRuntimeError(_ERROR, "Argument candidate does not match its source proposal")


def _validated_candidate_row(
    row: Mapping[str, Any],
    *,
    project_id: str,
    expected_kind: str | None = None,
) -> tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any], str]:
    candidate = _decode_json(row.get("payload_json"), message="stored synthesis candidate is unreadable")
    candidate_id = str(row.get("proposal_id") or "")
    if not candidate_id or candidate.get("proposal_id") != candidate_id:
        raise ConversationRuntimeError(_ERROR, "synthesis candidate identity is invalid")
    if candidate.get("project_ref") != project_id or candidate.get("candidate_only") is not True:
        raise ConversationRuntimeError(_ERROR, "synthesis candidate does not belong to the requested project")
    basis = deepcopy(dict(candidate))
    supplied_digest = basis.pop("proposal_digest", None)
    if not isinstance(supplied_digest, str) or canonical_digest(basis) != supplied_digest:
        raise ConversationRuntimeError(_ERROR, "synthesis candidate digest is invalid")

    provenance = candidate.get("provenance")
    if not isinstance(provenance, Mapping):
        raise ConversationRuntimeError(_ERROR, "synthesis candidate provenance is malformed")
    producer = str(provenance.get("producer") or "")
    kind = _KIND_BY_PRODUCER.get(producer)
    if kind is None or (expected_kind is not None and kind != expected_kind):
        raise ConversationRuntimeError(_ERROR, "synthesis candidate producer is not supported")

    source_binding = provenance.get("source_action_proposal")
    if not isinstance(source_binding, Mapping):
        raise ConversationRuntimeError(_ERROR, "synthesis candidate source proposal binding is malformed")
    source = _decode_json(row.get("source_payload_json"), message="source Action Proposal does not resolve")
    _VALIDATOR.validate(source)
    if source.get("project_id") != project_id:
        raise ConversationRuntimeError(_ERROR, "source Action Proposal belongs to another project")
    if (
        source.get("proposal_id") != source_binding.get("proposal_id")
        or source.get("proposal_digest") != source_binding.get("proposal_digest")
    ):
        raise ConversationRuntimeError(_ERROR, "synthesis candidate source proposal binding is invalid")
    source_action = source.get("action")
    if not isinstance(source_action, Mapping) or source_action.get("action_type") != _ACTION_BY_KIND[kind]:
        raise ConversationRuntimeError(_ERROR, "synthesis candidate source action type is invalid")
    source_payload = source_action.get("payload")
    if not isinstance(source_payload, Mapping):
        raise ConversationRuntimeError(_ERROR, "synthesis candidate source payload is malformed")

    obj = _semantic_object(candidate, expected_kind=kind, project_id=project_id)
    _validate_semantics(kind, obj, source_payload)
    return candidate, source, obj, kind


def _label(value: str) -> str:
    normalized = " ".join(value.split())
    safe = "".join(character if character.isprintable() else "?" for character in normalized)
    if len(safe) <= _LABEL_LIMIT:
        return safe
    return safe[: _LABEL_LIMIT - 1] + "…"


def _semantic_content(kind: str, candidate: Mapping[str, Any], obj: Mapping[str, Any]) -> dict[str, Any]:
    if kind == "recommendation":
        return {
            "statement": str(obj["statement"]),
            "finding_ids": deepcopy(list(obj.get("finding_ids", ()))),
            "conditions": deepcopy(list(obj.get("conditions", ()))),
            "scope": deepcopy(list(obj.get("scope", ()))),
            "rationale": str(candidate.get("rationale") or ""),
        }
    return {
        "conclusion": str(obj["conclusion"]),
        "warrant": str(obj["warrant"]),
        "question_ids": deepcopy(list(obj.get("question_ids", ()))),
        "conclusion_claim_id": deepcopy(obj.get("conclusion_claim_id")),
        "premise_claim_ids": deepcopy(list(obj.get("premise_claim_ids", ()))),
        "finding_ids": deepcopy(list(obj.get("finding_ids", ()))),
        "evidence_ids": deepcopy(list(obj.get("evidence_ids", ()))),
        "qualifier": deepcopy(obj.get("qualifier")),
        "counter_review_ids": deepcopy(list(obj.get("counter_review_ids", ()))),
        "implications": deepcopy(list(obj.get("implications", ()))),
        "rationale": str(candidate.get("rationale") or ""),
    }


def _resume_item(item: Mapping[str, Any]) -> dict[str, Any]:
    result = {
        key: deepcopy(item[key])
        for key in ("candidate_id", "kind", "availability", "label", "created_at", "issues")
        if key in item
    }
    projection = item.get("candidate_projection")
    if isinstance(projection, Mapping):
        result["candidate_position"] = {
            "candidate_only": bool(projection.get("candidate_only")),
            "proposal_id": deepcopy(projection.get("proposal_id")),
            "bound_lineage_ref": deepcopy(projection.get("bound_lineage_ref")),
            "bound_to_current_lineage": bool(projection.get("bound_to_current_lineage")),
            "bound_snapshot": deepcopy(projection.get("bound_snapshot")),
            "bound_to_current_snapshot": bool(projection.get("bound_to_current_snapshot")),
            "subjects": [
                {
                    "subject": deepcopy(subject.get("subject")),
                    "current_value_present": subject.get("current_value") is not None,
                }
                for subject in projection.get("subjects", ())
                if isinstance(subject, Mapping)
            ],
        }
    return result


class LocalApplicationFacade(_BaseLocalApplicationFacade):
    """Public bounded discovery for saved Recommendation and Argument candidates."""

    def list_synthesis_candidates(
        self,
        *,
        kind: str | None = None,
        limit: int = 20,
        cursor: str | None = None,
        view: str | None = None,
    ) -> Mapping[str, Any]:
        selected = self._public_view(view)
        page = list_synthesis_candidate_rows(
            self._application.conversation_store,
            self._project_id,
            kind=kind,
            limit=limit,
            cursor=cursor,
        )
        state = self._current_state_view()
        items: list[dict[str, Any]] = []
        degraded = bool(page["collection_incomplete"])
        for row in page["rows"]:
            candidate_id = str(row.get("proposal_id") or "")
            row_kind = _safe_kind(row.get("payload_json"))
            try:
                candidate, source, obj, validated_kind = _validated_candidate_row(
                    row,
                    project_id=self._project_id,
                    expected_kind=kind,
                )
                projection = build_candidate_projection(candidate, state)
            except ConversationRuntimeError as exc:
                degraded = True
                items.append({
                    "candidate_id": candidate_id,
                    "kind": row_kind,
                    "availability": "UNAVAILABLE",
                    "issues": [{"code": exc.code, "message": exc.message}],
                })
                continue
            label_source = str(obj["statement"] if validated_kind == "recommendation" else obj["conclusion"])
            items.append({
                "candidate_id": candidate_id,
                "kind": validated_kind,
                "availability": "AVAILABLE",
                "label": _label(label_source),
                "created_at": str(source["created_at"]),
                "candidate_projection": projection,
            })

        issues = []
        if page["collection_incomplete"]:
            issues.append({
                "code": "SYNTHESIS-CANDIDATE-COLLECTION-001",
                "message": "candidate collection may be incomplete because an unattributable stored proposal is malformed",
            })
        detail = {
            "status": "DEGRADED" if degraded else "OK",
            "project_id": self._project_id,
            "items": items,
            "truncated": bool(page["truncated"]),
            "next_cursor": page["next_cursor"],
            "issues": issues,
        }
        return detail if selected == "detail" else self._read_projection(
            detail, project_synthesis_list, operation="synthesis-candidate.list"
        )

    def show_synthesis_candidate(
        self, candidate_id: str, *, view: str | None = None
    ) -> Mapping[str, Any]:
        selected = self._public_view(view)
        row = load_synthesis_candidate_row(self._application.conversation_store, candidate_id)
        if row is None:
            raise ConversationRuntimeError(_ERROR, "synthesis candidate does not resolve")
        candidate, source, obj, kind = _validated_candidate_row(
            row,
            project_id=self._project_id,
        )
        detail = {
            "status": "OK",
            "project_id": self._project_id,
            "candidate_id": str(candidate["proposal_id"]),
            "kind": kind,
            "created_at": str(source["created_at"]),
            "source_action_proposal": {
                "proposal_id": str(source["proposal_id"]),
                "created_at": str(source["created_at"]),
            },
            "content": _semantic_content(kind, candidate, obj),
            "candidate_projection": build_candidate_projection(candidate, self._current_state_view()),
        }
        return detail if selected == "detail" else self._read_projection(
            detail, project_synthesis_show, operation="synthesis-candidate.show"
        )

    def show_candidate(self, candidate_id: str) -> Mapping[str, Any]:
        """Return one exact persisted candidate without rebinding or rewriting it."""
        if not isinstance(candidate_id, str) or not candidate_id:
            raise ConversationRuntimeError(
                "APPLICATION-CANDIDATE-DETAIL-001", "candidate_id is required"
            )
        candidate = state_delta_proposal_for_project(
            self._application.conversation_store,
            self._project_id,
            candidate_id,
        )
        if candidate is None:
            raise ConversationRuntimeError(
                "APPLICATION-CANDIDATE-DETAIL-001", "candidate does not resolve"
            )
        return {
            "status": "OK",
            "project_id": self._project_id,
            "candidate_id": candidate_id,
            "candidate": deepcopy(candidate),
        }

    def show_human_decision_request(self, request_id: str) -> Mapping[str, Any]:
        """Return one immutable Decision Request plus separate operational lifecycle data."""
        if not isinstance(request_id, str) or not request_id:
            raise ConversationRuntimeError(
                "APPLICATION-DECISION-DETAIL-001", "request_id is required"
            )
        detail = decision_request_for_project(
            self._application.decision_store,
            self._project_id,
            request_id,
        )
        if detail is None:
            raise ConversationRuntimeError(
                "APPLICATION-DECISION-DETAIL-001", "Human Decision Request does not resolve"
            )
        request = detail["request"]
        source = request.get("source_state_delta_proposal")
        if not isinstance(source, Mapping):
            raise ConversationRuntimeError(
                "APPLICATION-DECISION-DETAIL-001",
                "Human Decision Request source candidate binding is malformed",
            )
        candidate_id = source.get("proposal_id")
        candidate_digest = source.get("proposal_digest")
        if not isinstance(candidate_id, str) or not candidate_id:
            raise ConversationRuntimeError(
                "APPLICATION-DECISION-DETAIL-001",
                "Human Decision Request source candidate identity is invalid",
            )
        candidate = state_delta_proposal_for_project(
            self._application.conversation_store,
            self._project_id,
            candidate_id,
        )
        if candidate is None or candidate.get("proposal_digest") != candidate_digest:
            raise ConversationRuntimeError(
                "APPLICATION-DECISION-DETAIL-001",
                "Human Decision Request source candidate binding does not resolve",
            )
        return {
            "status": "OK",
            "project_id": self._project_id,
            "request_id": request_id,
            "request": deepcopy(request),
            "operational": deepcopy(detail["operational"]),
        }

    @staticmethod
    def _public_view(view: str | None) -> str:
        try:
            return normalize_view(view)
        except ConversationViewError as exc:
            raise LocalApplicationError("APPLICATION-VIEW-001", str(exc)) from exc

    @staticmethod
    def _read_projection(detail: Mapping[str, Any], projector, *, operation: str) -> Mapping[str, Any]:
        try:
            return projector(detail)
        except ConversationViewError as exc:
            raise LocalApplicationError(
                "APPLICATION-CONVERSATION-VIEW-001",
                f"{operation} conversation projection is unavailable: {exc}",
            ) from exc

    @staticmethod
    def _after_operation_projection(
        detail: Mapping[str, Any], projector, *, operation: str, **kwargs: Any
    ) -> Mapping[str, Any]:
        try:
            return projector(detail, **kwargs)
        except Exception:
            # The operation has already completed. Never fall back to the raw result and
            # never make the caller repeat an effect because only presentation failed.
            return projection_unavailable(
                status=detail.get("status"),
                operation=operation,
                message="Operation completed, but its conversation projection could not be verified.",
                detail=detail,
            )

    def submit_action(
        self, draft_input: Mapping[str, Any], *, view: str | None = None
    ) -> Mapping[str, Any]:
        selected = self._public_view(view)
        detail = super().submit_action(draft_input)
        if selected == "detail":
            return detail
        action_type = draft_input.get("action_type") if isinstance(draft_input, Mapping) else None
        return self._after_operation_projection(
            detail,
            lambda value, **_: project_action_result(
                value, action_type=str(action_type or ""), state=self._current_state_view()
            ),
            operation="action.submit",
        )

    def submit_confirmation(
        self, confirmation: Mapping[str, Any], *, view: str | None = None
    ) -> Mapping[str, Any]:
        selected = self._public_view(view)
        detail = super().submit_confirmation(confirmation)
        if selected == "detail":
            return detail
        return self._after_operation_projection(
            detail, project_confirmation_result, operation="confirmation.submit"
        )

    def resolve_human_decision(
        self, response: Mapping[str, Any], *, view: str | None = None
    ) -> Mapping[str, Any]:
        selected = self._public_view(view)
        detail = super().resolve_human_decision(response)
        if selected == "detail":
            return detail
        return self._after_operation_projection(
            detail, project_decision_result, operation="decision.resolve"
        )

    def collect_external(
        self, run_id: str, submission: Mapping[str, Any], *, view: str | None = None
    ) -> Mapping[str, Any]:
        selected = self._public_view(view)
        detail = super().collect_external(run_id, submission)
        if selected == "detail":
            return detail
        return self._after_operation_projection(
            detail,
            lambda value, **_: project_collect(value, state=self._current_state_view()),
            operation="external.collect",
        )

    def status(self, *, view: str | None = None) -> Mapping[str, Any]:
        selected = self._public_view(view)
        detail = super().status()
        return detail if selected == "detail" else self._read_projection(
            detail, project_status, operation="status"
        )

    def show_run(self, run_id: str, *, view: str | None = None) -> Mapping[str, Any]:
        selected = self._public_view(view)
        detail = super().show_run(run_id)
        return detail if selected == "detail" else self._read_projection(
            detail, project_run, operation="run.show"
        )

    def replay_completed_desktop_research_run(
        self, run_id: str, *, view: str | None = None
    ) -> Mapping[str, Any]:
        selected = self._public_view(view)
        detail = super().replay_completed_desktop_research_run(run_id)
        if selected == "detail":
            return detail
        return self._after_operation_projection(
            detail, project_replay, operation="run.replay"
        )

    def resume_context(
        self, *, limits: Mapping[str, int] | None = None, view: str | None = None
    ) -> Mapping[str, Any]:
        selected = self._public_view(view)
        result = deepcopy(dict(super().resume_context(limits=limits)))
        listing = self.list_synthesis_candidates(limit=20, view="detail")
        result["saved_synthesis_candidates"] = {
            "items": [_resume_item(item) for item in listing["items"]],
            "truncated": bool(listing["truncated"]),
            "next_cursor": listing["next_cursor"],
            "issues": deepcopy(listing["issues"]),
        }
        if listing["status"] == "DEGRADED":
            result["status"] = "DEGRADED"
        return result if selected == "detail" else self._read_projection(
            result, project_resume, operation="resume"
        )
