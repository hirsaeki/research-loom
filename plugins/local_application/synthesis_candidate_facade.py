from __future__ import annotations

from copy import deepcopy
import json
from typing import Any, Mapping

from core.conversation import ConversationRuntimeError
from core.conversation.validation import WorkConversationValidator
from core.runtime import canonical_digest
from plugins.local_conversation_store.synthesis import (
    list_synthesis_candidate_rows,
    load_synthesis_candidate_row,
)

from .argument_facade import research_argument_proposal_payload
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
    ) -> Mapping[str, Any]:
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
        return {
            "status": "DEGRADED" if degraded else "OK",
            "project_id": self._project_id,
            "items": items,
            "truncated": bool(page["truncated"]),
            "next_cursor": page["next_cursor"],
            "issues": issues,
        }

    def show_synthesis_candidate(self, candidate_id: str) -> Mapping[str, Any]:
        row = load_synthesis_candidate_row(self._application.conversation_store, candidate_id)
        if row is None:
            raise ConversationRuntimeError(_ERROR, "synthesis candidate does not resolve")
        candidate, source, obj, kind = _validated_candidate_row(
            row,
            project_id=self._project_id,
        )
        return {
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

    def resume_context(self, *, limits: Mapping[str, int] | None = None) -> Mapping[str, Any]:
        result = deepcopy(dict(super().resume_context(limits=limits)))
        listing = self.list_synthesis_candidates(limit=20)
        result["saved_synthesis_candidates"] = {
            "items": [_resume_item(item) for item in listing["items"]],
            "truncated": bool(listing["truncated"]),
            "next_cursor": listing["next_cursor"],
            "issues": deepcopy(listing["issues"]),
        }
        if listing["status"] == "DEGRADED":
            result["status"] = "DEGRADED"
        return result
