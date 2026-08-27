from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping

from core.runtime import CommitReceipt, StateTransitionRejected, StateTransitionRequest, canonical_digest


class HumanDecisionError(RuntimeError):
    """Fail-closed operational Human Decision boundary error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class DecisionGateResult:
    status: str
    decision_request: Mapping[str, Any] | None = None
    transition_request: StateTransitionRequest | None = None


@dataclass(frozen=True)
class DecisionResolutionResult:
    status: str
    request: Mapping[str, Any]
    response: Mapping[str, Any]
    commit_receipt: CommitReceipt | None = None
    transition_rejection: StateTransitionRejected | None = None


def request_digest(document: Mapping[str, Any]) -> str:
    payload = deepcopy(dict(document))
    payload.pop("request_digest", None)
    payload.pop("operational_status", None)
    payload.pop("commit_id", None)
    payload.pop("status_detail", None)
    return canonical_digest(payload)


def with_request_digest(document: Mapping[str, Any]) -> dict[str, Any]:
    result = deepcopy(dict(document))
    result["request_digest"] = request_digest(result)
    return result


def response_digest(document: Mapping[str, Any]) -> str:
    payload = deepcopy(dict(document))
    payload.pop("response_digest", None)
    return canonical_digest(payload)


def with_response_digest(document: Mapping[str, Any]) -> dict[str, Any]:
    result = deepcopy(dict(document))
    result["response_digest"] = response_digest(result)
    return result
