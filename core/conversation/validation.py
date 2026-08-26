from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker
import rfc8785

from .models import ConversationRuntimeError


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = json.loads(
    (ROOT / "core" / "packages" / "work-conversation.schema.json").read_text(encoding="utf-8")
)
_VALIDATOR = Draft202012Validator(CONTRACT, format_checker=FormatChecker())

DIGEST_FIELDS = {
    "conversation_input": "input_digest",
    "action_proposal": "proposal_digest",
    "confirmation_request": "request_digest",
    "confirmation_receipt": "receipt_digest",
    "action_receipt": "receipt_digest",
    "candidate_presentation": "presentation_digest",
}
DIGEST_ERRORS = {
    "conversation_input": "CONV-INPUT-DIGEST-001",
    "action_proposal": "CONV-PROPOSAL-DIGEST-001",
    "confirmation_request": "CONV-CONFIRMATION-REQUEST-DIGEST-001",
    "confirmation_receipt": "CONV-CONFIRMATION-RECEIPT-DIGEST-001",
    "action_receipt": "CONV-ACTION-RECEIPT-DIGEST-001",
    "candidate_presentation": "CONV-PRESENTATION-DIGEST-001",
}


def canonical_digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(rfc8785.dumps(value)).hexdigest()


def document_digest(document: Mapping[str, Any]) -> str:
    message_type = str(document["message_type"])
    field = DIGEST_FIELDS[message_type]
    payload = deepcopy(dict(document))
    payload.pop(field, None)
    return canonical_digest(payload)


def with_document_digest(document: Mapping[str, Any]) -> dict[str, Any]:
    result = deepcopy(dict(document))
    field = DIGEST_FIELDS[str(result["message_type"])]
    result[field] = document_digest(result)
    return result


def state_binding(state) -> dict[str, Any]:
    snapshot = state.current_snapshot
    return {
        "state_id": str(snapshot["id"]),
        "revision": int(snapshot.get("revision", 0)),
        "content_digest": str(snapshot["content_digest"]),
    }


def research_context_binding(state) -> dict[str, Any]:
    snapshot = state.current_snapshot
    return {
        "project_config_digest": state.project_config_digest,
        "effective_profile_set_digest": state.effective_profile_set_digest,
        "research_snapshot": {
            "snapshot_id": str(snapshot["id"]),
            "revision": int(snapshot.get("revision", 0)),
            "content_digest": str(snapshot["content_digest"]),
        },
    }


class WorkConversationValidator:
    def validate(self, document: Mapping[str, Any]) -> None:
        errors = sorted(
            _VALIDATOR.iter_errors(document),
            key=lambda error: tuple(str(item) for item in error.absolute_path),
        )
        if errors:
            error = errors[0]
            path = ".".join(str(item) for item in error.absolute_path) or "$"
            raise ConversationRuntimeError(
                "CONV-AUDIT-001", f"PR10 schema violation at {path}: {error.message}"
            )
        message_type = str(document["message_type"])
        field = DIGEST_FIELDS[message_type]
        if document[field] != document_digest(document):
            raise ConversationRuntimeError(
                DIGEST_ERRORS[message_type], f"invalid {message_type} digest"
            )
        if message_type == "action_proposal":
            payload = document["action"]["payload"]
            if document["action"]["payload_digest"] != canonical_digest(payload):
                raise ConversationRuntimeError(
                    "CONV-PROPOSAL-DIGEST-001", "Action Proposal payload digest is invalid"
                )
