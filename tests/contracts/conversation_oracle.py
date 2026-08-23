from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
from typing import Any

import rfc8785

DIGEST_FIELDS = {
    "conversation_input": "input_digest",
    "action_proposal": "proposal_digest",
    "confirmation_request": "request_digest",
    "confirmation_receipt": "receipt_digest",
    "action_receipt": "receipt_digest",
    "candidate_presentation": "presentation_digest",
}

ID_FIELDS = {
    "conversation_input": "input_id",
    "action_proposal": "proposal_id",
    "confirmation_request": "confirmation_request_id",
    "confirmation_receipt": "confirmation_receipt_id",
    "action_receipt": "action_receipt_id",
    "candidate_presentation": "presentation_id",
}


def canonical_digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(rfc8785.dumps(value)).hexdigest()


def document_digest(document: dict[str, Any]) -> str:
    field = DIGEST_FIELDS[document["message_type"]]
    payload = deepcopy(document)
    payload.pop(field, None)
    return canonical_digest(payload)


def refresh_document_digest(document: dict[str, Any]) -> None:
    field = DIGEST_FIELDS[document["message_type"]]
    document[field] = document_digest(document)


def payload_digest(proposal: dict[str, Any]) -> str:
    return canonical_digest(proposal["action"]["payload"])


def binding(proposal: dict[str, Any]) -> dict[str, str]:
    return {
        "proposal_id": proposal["proposal_id"],
        "proposal_digest": proposal["proposal_digest"],
    }


def action_binding(proposal: dict[str, Any]) -> dict[str, str]:
    return {
        "action_type": proposal["action"]["action_type"],
        "payload_digest": proposal["action"]["payload_digest"],
    }


def _index(flow):
    result = {}
    for document in flow["documents"]:
        message_type = document["message_type"]
        identifier = document[ID_FIELDS[message_type]]
        result.setdefault(message_type, {})[identifier] = document
    return result


def _duplicates(flow):
    seen = set()
    for document in flow["documents"]:
        key = (
            document["message_type"],
            document[ID_FIELDS[document["message_type"]]],
        )
        if key in seen:
            return True
        seen.add(key)
    return False


def _same(a, b):
    return rfc8785.dumps(a) == rfc8785.dumps(b)


def _parse_time(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _candidate(handoff, kind, candidate_id):
    key = (
        "candidate_next_actions"
        if kind == "next_action"
        else "candidate_next_methods"
    )
    return next(
        (
            item
            for item in handoff["outputs"][key]
            if item["proposal_id"] == candidate_id
        ),
        None,
    )


def _proposal_for_source(index, input_id):
    return [
        proposal
        for proposal in index.get("action_proposal", {}).values()
        if proposal["source"].get("source_type") == "human_input"
        and proposal["source"].get("input_id") == input_id
    ]


def _research_binding_from_invocation(invocation):
    return {
        "project_config_digest": invocation["pins"]["project_config"][
            "configuration_digest"
        ],
        "effective_profile_set_digest": invocation["pins"][
            "effective_profile_set"
        ]["content_digest"],
        "research_snapshot": invocation["pins"]["research_snapshot"],
    }


def conversation_semantic_error(flow, invocation, handoff):
    if _duplicates(flow):
        return "CONV-AUDIT-001"

    for document in flow["documents"]:
        digest_field = DIGEST_FIELDS[document["message_type"]]
        if document[digest_field] != document_digest(document):
            return {
                "conversation_input": "CONV-INPUT-DIGEST-001",
                "action_proposal": "CONV-PROPOSAL-DIGEST-001",
                "confirmation_request": "CONV-CONFIRMATION-REQUEST-DIGEST-001",
                "confirmation_receipt": "CONV-CONFIRMATION-RECEIPT-DIGEST-001",
                "action_receipt": "CONV-ACTION-RECEIPT-DIGEST-001",
                "candidate_presentation": "CONV-PRESENTATION-DIGEST-001",
            }[document["message_type"]]
        if (
            document["message_type"] == "action_proposal"
            and document["action"]["payload_digest"] != payload_digest(document)
        ):
            return "CONV-PROPOSAL-DIGEST-001"

    index = _index(flow)
    inputs = index.get("conversation_input", {})
    proposals = index.get("action_proposal", {})
    requests = index.get("confirmation_request", {})
    confirmations = index.get("confirmation_receipt", {})
    receipts = index.get("action_receipt", {})
    presentations = index.get("candidate_presentation", {})

    for proposal in proposals.values():
        source = proposal["source"]
        effect = proposal["action"]["effect"]
        if source["source_type"] == "human_input":
            input_document = inputs.get(source["input_id"])
            if input_document is None:
                return "CONV-NATURAL-LANGUAGE-AUTHORITY-001"
            if (
                input_document["project_id"] != proposal["project_id"]
                or input_document["conversation_id"] != proposal["conversation_id"]
                or input_document["actor"] != proposal["initiating_actor"]
            ):
                return "CONV-NATURAL-LANGUAGE-AUTHORITY-001"
            classification = input_document["classification"]
            if classification == "QUERY":
                if effect != "read_only" or proposal["commitment_mode"] != "commit_requested":
                    return "CONV-CLASSIFICATION-001"
            elif classification == "PROPOSAL":
                if proposal["commitment_mode"] != "proposal_only":
                    return "CONV-CLASSIFICATION-001"
            elif classification == "COMMITTABLE_ACTION":
                if proposal["commitment_mode"] != "commit_requested":
                    return "CONV-CLASSIFICATION-001"
            else:
                return "CONV-CLASSIFICATION-001"
        else:
            if (
                proposal["commitment_mode"] != "proposal_only"
                or proposal["route"]["route_type"] != "unresolved"
            ):
                return "CONV-PROPOSAL-ONLY-001"
            if (
                source["candidate_kind"] == "next_method"
                and not proposal["human_decision_boundary"]["required"]
            ):
                return "CONV-HUMAN-DECISION-001"

        if (
            proposal["commitment_mode"] == "commit_requested"
            and proposal["route"]["route_type"] == "unresolved"
        ):
            return "CONV-ROUTE-001"
        if effect == "read_only":
            if proposal["confirmation_policy"]["required_on_commit"]:
                return "CONV-READONLY-001"
        elif not proposal["confirmation_policy"]["required_on_commit"]:
            return "CONV-CONFIRMATION-BINDING-001"

    for input_document in inputs.values():
        classification = input_document["classification"]
        sourced = _proposal_for_source(index, input_document["input_id"])
        if classification in {"QUERY", "PROPOSAL", "COMMITTABLE_ACTION"} and len(sourced) > 1:
            return "CONV-NATURAL-LANGUAGE-AUTHORITY-001"
        if classification in {"CONFIRMATION", "CANCEL"} and sourced:
            return "CONV-CLASSIFICATION-001"

    expected_research = _research_binding_from_invocation(invocation)
    for proposal in proposals.values():
        route = proposal["route"]
        if route["route_type"] != "capability_invocation":
            continue
        if route["invocation_contract"] != "capability-invocation@0.1.0":
            return "CONV-ROUTE-001"
        if not _same(route["capability"], invocation["capability"]):
            return "CONV-PIN-001"
        if (
            route["execution_mode"] != invocation["execution_mode"]
            or not _same(route["context_pack"], invocation["context_pack"])
        ):
            return "CONV-PIN-001"
        research_binding = proposal["bindings"].get("research_context")
        if research_binding is None or not _same(research_binding, expected_research):
            return "CONV-PIN-001"

    for request in requests.values():
        proposal = proposals.get(request["proposal_binding"]["proposal_id"])
        if proposal is None or not _same(request["proposal_binding"], binding(proposal)):
            return "CONV-CONFIRMATION-BINDING-001"
        if (
            proposal["action"]["effect"] != "state_changing"
            or proposal["commitment_mode"] != "commit_requested"
        ):
            return "CONV-CONFIRMATION-BINDING-001"
        if (
            request["actor_binding"]["actor_type"] != "human"
            or request["actor_binding"] != proposal["initiating_actor"]
        ):
            return "CONV-CONFIRMATION-BINDING-001"
        if (
            not _same(request["action_binding"], action_binding(proposal))
            or not _same(request["state_binding"], proposal["bindings"]["current_state"])
        ):
            return "CONV-CONFIRMATION-BINDING-001"
        proposal_research = proposal["bindings"].get("research_context")
        request_research = request.get("research_context_binding")
        if proposal_research is None:
            if request_research is not None:
                return "CONV-CONFIRMATION-BINDING-001"
        elif request_research is None or not _same(proposal_research, request_research):
            return "CONV-CONFIRMATION-BINDING-001"
        if _parse_time(request["issued_at"]) >= _parse_time(request["expires_at"]):
            return "CONV-CONFIRMATION-EXPIRED-001"

    request_uses = {}
    for confirmation in confirmations.values():
        request_id = confirmation["request_binding"]["confirmation_request_id"]
        request = requests.get(request_id)
        if (
            request is None
            or confirmation["request_binding"]["request_digest"]
            != request["request_digest"]
        ):
            return "CONV-CONFIRMATION-BINDING-001"
        proposal = proposals.get(confirmation["proposal_binding"]["proposal_id"])
        if (
            proposal is None
            or not _same(confirmation["proposal_binding"], request["proposal_binding"])
            or not _same(confirmation["proposal_binding"], binding(proposal))
        ):
            return "CONV-CONFIRMATION-BINDING-001"
        if (
            confirmation["actor"]["actor_type"] != "human"
            or confirmation["actor"] != request["actor_binding"]
        ):
            return "CONV-CONFIRMATION-BINDING-001"
        if (
            not _same(confirmation["action_binding"], request["action_binding"])
            or not _same(confirmation["observed_state"], request["state_binding"])
        ):
            return "CONV-CONFIRMATION-BINDING-001"
        if request.get("research_context_binding") is None:
            if confirmation.get("research_context_binding") is not None:
                return "CONV-CONFIRMATION-BINDING-001"
        elif not _same(
            confirmation.get("research_context_binding"),
            request["research_context_binding"],
        ):
            return "CONV-CONFIRMATION-BINDING-001"
        if _parse_time(confirmation["confirmed_at"]) >= _parse_time(request["expires_at"]):
            return "CONV-CONFIRMATION-EXPIRED-001"
        matching_inputs = [
            item
            for item in inputs.values()
            if item["classification"] == "CONFIRMATION"
            and item["target"]["target_id"] == request_id
            and item["actor"] == confirmation["actor"]
        ]
        if len(matching_inputs) != 1:
            return "CONV-CONFIRMATION-BINDING-001"
        request_uses[request_id] = request_uses.get(request_id, 0) + 1
        if request_uses[request_id] > 1:
            return "CONV-CONFIRMATION-REPLAY-001"

    for receipt in receipts.values():
        proposal = proposals.get(receipt["proposal_binding"]["proposal_id"])
        if proposal is None or not _same(receipt["proposal_binding"], binding(proposal)):
            return "CONV-AUDIT-001"
        if (
            not _same(receipt["action_binding"], action_binding(proposal))
            or receipt["effect"] != proposal["action"]["effect"]
        ):
            return "CONV-AUDIT-001"
        if receipt["effect"] == "read_only":
            if (
                receipt.get("confirmation_receipt_binding") is not None
                or receipt["research_state_mutation_performed"]
                or not _same(receipt["state_before"], receipt["state_after"])
            ):
                return "CONV-READONLY-001"
        if receipt["status"] == "cancelled":
            source = inputs.get(receipt["source_input_id"])
            if source is None or source["classification"] != "CANCEL":
                return "CONV-CANCEL-001"
            target = source["target"]
            if target["target_type"] == "proposal":
                if (
                    target["target_id"] != proposal["proposal_id"]
                    or proposal["commitment_mode"] != "proposal_only"
                ):
                    return "CONV-CANCEL-001"
            elif target["target_type"] == "confirmation_request":
                request = requests.get(target["target_id"])
                if (
                    request is None
                    or request["proposal_binding"]["proposal_id"]
                    != proposal["proposal_id"]
                    or any(
                        confirmation["request_binding"]["confirmation_request_id"]
                        == target["target_id"]
                        for confirmation in confirmations.values()
                    )
                ):
                    return "CONV-CANCEL-001"
            else:
                return "CONV-CANCEL-001"
            if (
                receipt["execution"]["execution_type"] != "none"
                or receipt["research_state_mutation_performed"]
                or not _same(receipt["state_before"], receipt["state_after"])
            ):
                return "CONV-CANCEL-001"
        elif proposal["commitment_mode"] == "proposal_only":
            return "CONV-PROPOSAL-ONLY-001"

        if receipt["effect"] == "state_changing" and receipt["status"] == "succeeded":
            confirmation_binding = receipt.get("confirmation_receipt_binding")
            if confirmation_binding is None:
                return "CONV-AUDIT-001"
            confirmation = confirmations.get(
                confirmation_binding["confirmation_receipt_id"]
            )
            if (
                confirmation is None
                or confirmation["receipt_digest"]
                != confirmation_binding["receipt_digest"]
            ):
                return "CONV-AUDIT-001"
            request = requests.get(
                confirmation["request_binding"]["confirmation_request_id"]
            )
            if (
                request is None
                or not _same(receipt["state_before"], request["state_binding"])
                or receipt.get("research_context_binding")
                != request.get("research_context_binding")
            ):
                return "CONV-AUDIT-001"

        route = proposal["route"]
        execution = receipt["execution"]
        if receipt["status"] == "succeeded" and route["route_type"] == "harness_service":
            if (
                execution["execution_type"] != "harness_service"
                or execution["service_id"] != route["service_id"]
            ):
                return "CONV-AUDIT-001"
        if (
            receipt["status"] == "succeeded"
            and route["route_type"] == "capability_invocation"
        ):
            if (
                execution["execution_type"] != "capability_invocation"
                or execution["invocation_contract"] != "capability-invocation@0.1.0"
            ):
                return "CONV-ROUTE-001"
            if (
                execution["invocation_id"] != invocation["invocation_id"]
                or execution["invocation_digest"] != invocation["invocation_digest"]
            ):
                return "CONV-ROUTE-001"
            if "handoff" in execution and (
                execution["handoff"]["handoff_id"] != handoff["handoff_id"]
                or execution["handoff"]["handoff_digest"]
                != handoff["handoff_digest"]
            ):
                return "CONV-ROUTE-001"
            if receipt["research_state_mutation_performed"]:
                return "CONV-ROUTE-001"

    for presentation in presentations.values():
        handoff_binding = presentation["handoff_binding"]
        if (
            handoff_binding["handoff_id"] != handoff["handoff_id"]
            or handoff_binding["handoff_digest"] != handoff["handoff_digest"]
            or handoff_binding["invocation_id"] != handoff["invocation_id"]
        ):
            return "CONV-HANDOFF-PRESENTATION-001"
        candidate = presentation["candidate"]
        if (
            _candidate(
                handoff,
                candidate["candidate_kind"],
                candidate["candidate_proposal_id"],
            )
            is None
        ):
            return "CONV-HANDOFF-PRESENTATION-001"
        proposal = proposals.get(presentation["proposal_binding"]["proposal_id"])
        if proposal is None or not _same(
            presentation["proposal_binding"], binding(proposal)
        ):
            return "CONV-HANDOFF-PRESENTATION-001"
        source = proposal["source"]
        if (
            source["source_type"] != "capability_handoff_candidate"
            or source["handoff_id"] != handoff["handoff_id"]
            or source["handoff_digest"] != handoff["handoff_digest"]
            or source["candidate_kind"] != candidate["candidate_kind"]
            or source["candidate_proposal_id"]
            != candidate["candidate_proposal_id"]
        ):
            return "CONV-HANDOFF-PRESENTATION-001"
        if (
            proposal["commitment_mode"] != "proposal_only"
            or proposal["route"]["route_type"] != "unresolved"
        ):
            return "CONV-PROPOSAL-ONLY-001"
        if (
            candidate["candidate_kind"] == "next_method"
            and not proposal["human_decision_boundary"]["required"]
        ):
            return "CONV-HUMAN-DECISION-001"

    return None


def apply_semantic_case(flow, case):
    result = deepcopy(flow)
    message_type = case["target"]["message_type"]
    target_id = case["target"]["id"]
    target = next(
        document
        for document in result["documents"]
        if document["message_type"] == message_type
        and document[ID_FIELDS[message_type]] == target_id
    )
    op = case["mutation"]["op"]
    if op == "set":
        cursor = target
        for part in case["mutation"]["path"][:-1]:
            cursor = cursor[part]
        cursor[case["mutation"]["path"][-1]] = deepcopy(case["mutation"]["value"])
        if case.get("rehash_payload") and message_type == "action_proposal":
            target["action"]["payload_digest"] = payload_digest(target)
        if case.get("rehash"):
            refresh_document_digest(target)
    elif op == "duplicate":
        duplicate = deepcopy(target)
        if "new_id" in case["mutation"]:
            duplicate[ID_FIELDS[message_type]] = case["mutation"]["new_id"]
            refresh_document_digest(duplicate)
        result["documents"].append(duplicate)
    else:
        raise ValueError(f"unsupported semantic mutation: {op}")
    return result
