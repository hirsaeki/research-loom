from __future__ import annotations

from copy import deepcopy
import re
from threading import RLock
from typing import Any, Mapping

from core.conversation import ActionDefinition, ConversationRuntimeError, HarnessServiceResult
from core.runtime import ObjectRef, StateDeltaProposal, TransitionAction, TransitionKind, canonical_digest

from .visual_need_facade import LocalApplicationFacade as _BaseLocalApplicationFacade

_ACTION_REGISTRATION_LOCK = RLock()
_ACTION_TYPE = "research.evidence.qualify"
_PAYLOAD_CONTRACT = "research-evidence-qualification@0.1.0"
_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")
_MAX_ID_LENGTH = 256
_MAX_RATIONALE_LENGTH = 8_192
_MAX_EXCERPT_LENGTH = 65_536


def research_evidence_qualification_payload(payload: Mapping[str, Any]) -> None:
    allowed = {"evidence_id", "expected_revision", "expected_digest", "rationale", "excerpt"}
    if not isinstance(payload, Mapping) or set(payload) - allowed:
        raise ValueError("research.evidence.qualify contains unknown fields")
    if set(payload) < {"evidence_id", "expected_revision", "expected_digest", "rationale"}:
        raise ValueError(
            "research.evidence.qualify requires evidence_id, expected_revision, expected_digest and rationale"
        )
    evidence_id = payload.get("evidence_id")
    if not isinstance(evidence_id, str) or not evidence_id.strip() or len(evidence_id) > _MAX_ID_LENGTH:
        raise ValueError("evidence_id must be a bounded non-empty ID")
    revision = payload.get("expected_revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise ValueError("expected_revision must be a non-negative integer")
    digest = payload.get("expected_digest")
    if not isinstance(digest, str) or _DIGEST_RE.fullmatch(digest) is None:
        raise ValueError("expected_digest must be a canonical sha256 digest")
    rationale = payload.get("rationale")
    if (
        not isinstance(rationale, str)
        or not rationale.strip()
        or len(rationale) > _MAX_RATIONALE_LENGTH
    ):
        raise ValueError("rationale must be a bounded non-empty string")
    if "excerpt" in payload:
        excerpt = payload["excerpt"]
        if (
            not isinstance(excerpt, str)
            or not excerpt.strip()
            or len(excerpt.encode("utf-8")) > _MAX_EXCERPT_LENGTH
        ):
            raise ValueError("excerpt must be a bounded non-empty UTF-8 string")


def _current_evidence(state: Any, evidence_id: str) -> Mapping[str, Any]:
    evidence = next(
        (
            item
            for item in state.effective_objects()
            if item.get("kind") == "evidence"
            and item.get("id") == evidence_id
            and item.get("project_id") == state.project_ref
        ),
        None,
    )
    if evidence is None:
        raise ConversationRuntimeError(
            "EVIDENCE-QUALIFICATION-001",
            f"evidence_id must resolve to current Evidence: {evidence_id}",
        )
    return evidence


class ResearchEvidenceQualificationHandler:
    """Create one exact Evidence verification candidate; authority remains generic."""

    def __init__(self, store: Any, id_provider: Any) -> None:
        self._store = store
        self._ids = id_provider

    def execute(
        self,
        payload: Mapping[str, Any],
        *,
        state: Any,
        actor: Any,
        proposal: Mapping[str, Any],
    ) -> HarnessServiceResult:
        del actor
        research_evidence_qualification_payload(payload)
        evidence = _current_evidence(state, str(payload["evidence_id"]))
        actual_digest = canonical_digest(evidence)
        if (
            int(evidence.get("revision", -1)) != int(payload["expected_revision"])
            or actual_digest != payload["expected_digest"]
        ):
            raise ConversationRuntimeError(
                "EVIDENCE-QUALIFICATION-STALE-001",
                "Evidence qualification input does not match the current Evidence revision/digest",
            )

        status = evidence.get("verification_status")
        requested_excerpt = payload.get("excerpt")
        if status == "verified":
            if requested_excerpt is not None and requested_excerpt != evidence.get("excerpt"):
                raise ConversationRuntimeError(
                    "EVIDENCE-QUALIFICATION-001",
                    "already verified Evidence cannot be revised through the qualification operation",
                )
            return HarnessServiceResult(
                result_reference=str(evidence["id"]),
                data={
                    "qualification_status": "ALREADY_VERIFIED",
                    "evidence_id": str(evidence["id"]),
                    "revision": int(evidence["revision"]),
                    "evidence_digest": actual_digest,
                },
                research_state_mutation_performed=False,
            )
        if status != "unverified":
            raise ConversationRuntimeError(
                "EVIDENCE-QUALIFICATION-001",
                f"only unverified Evidence may enter this qualification path; current status is {status!r}",
            )

        revised = deepcopy(dict(evidence))
        revised["revision"] = int(evidence["revision"]) + 1
        revised["verification_status"] = "verified"
        if requested_excerpt is not None:
            revised["excerpt"] = str(requested_excerpt)

        transition_action = TransitionAction(
            TransitionKind.VERIFY_EVIDENCE,
            {"object": revised},
            decision_refs=(),
            source_refs=(),
        )
        provenance = {
            "producer": "research.evidence.qualify@0.1.0",
            "source_action_proposal": {
                "proposal_id": str(proposal["proposal_id"]),
                "proposal_digest": str(proposal["proposal_digest"]),
            },
            "source_input_id": str(proposal["source"]["input_id"]),
            "source_evidence": {
                "id": str(evidence["id"]),
                "revision": int(evidence["revision"]),
                "digest": actual_digest,
            },
            "excerpt_supplied": requested_excerpt is not None,
            "project_config": {
                "ref": state.project_config_ref,
                "digest": state.project_config_digest,
            },
        }
        candidate = StateDeltaProposal(
            proposal_id=self._ids.new("SDP-"),
            project_ref=state.project_ref,
            lineage_ref=state.lineage_ref,
            source_refs=(),
            proposed_actions=(transition_action,),
            affected_refs=(ObjectRef("evidence", str(evidence["id"])),),
            rationale=str(payload["rationale"]),
            required_human_decision_kinds=("evidence_qualification",),
            current_snapshot_ref=str(state.current_snapshot["id"]),
            current_snapshot_digest=str(state.current_snapshot["content_digest"]),
            provenance=provenance,
            candidate_only=True,
        ).with_calculated_digest()
        candidate_wire = {
            "proposal_id": candidate.proposal_id,
            "project_ref": candidate.project_ref,
            "lineage_ref": candidate.lineage_ref,
            "source_refs": [],
            "proposed_actions": [
                {
                    "kind": transition_action.kind.value,
                    "payload": deepcopy(dict(transition_action.payload)),
                    "decision_refs": [],
                    "source_refs": [],
                }
            ],
            "affected_refs": [{"kind": "evidence", "id": str(evidence["id"])}],
            "rationale": candidate.rationale,
            "required_human_decision_kinds": list(candidate.required_human_decision_kinds),
            "current_snapshot_ref": candidate.current_snapshot_ref,
            "current_snapshot_digest": candidate.current_snapshot_digest,
            "provenance": deepcopy(provenance),
            "candidate_only": True,
            "proposal_digest": candidate.proposal_digest,
        }
        self._store.store_state_delta_proposal(candidate.proposal_id, candidate_wire)
        return HarnessServiceResult(
            result_reference=candidate.proposal_id,
            data={
                "qualification_status": "CANDIDATE_CREATED",
                "evidence_id": str(evidence["id"]),
                "source_revision": int(evidence["revision"]),
                "source_digest": actual_digest,
                "candidate_revision": int(revised["revision"]),
                "state_delta_proposal_id": candidate.proposal_id,
                "state_delta_proposal": deepcopy(candidate_wire),
            },
            research_state_mutation_performed=False,
        )


class LocalApplicationFacade(_BaseLocalApplicationFacade):
    """Public Evidence qualification ingress over the existing Human Decision gate."""

    def list_actions(self) -> Mapping[str, Any]:
        self._ensure_evidence_qualification_action()
        return super().list_actions()

    def submit_action(self, draft_input: Mapping[str, Any]) -> Mapping[str, Any]:
        self._ensure_evidence_qualification_action()
        return super().submit_action(draft_input)

    def _ensure_evidence_qualification_action(self) -> None:
        coordinator = self._application.coordinator
        action_registry = coordinator._actions
        service_registry = coordinator._services
        with _ACTION_REGISTRATION_LOCK:
            existing = {
                definition.action_type: definition
                for definition in coordinator.action_definitions()
            }
            definition = existing.get(_ACTION_TYPE)
            if definition is None:
                action_registry.register(
                    ActionDefinition(
                        _ACTION_TYPE,
                        _PAYLOAD_CONTRACT,
                        "read_only",
                        "harness_service",
                        False,
                        human_decision_required=False,
                        service_id=_ACTION_TYPE,
                        payload_validator=research_evidence_qualification_payload,
                    )
                )
            elif (
                definition.payload_contract != _PAYLOAD_CONTRACT
                or definition.effect != "read_only"
                or definition.route_kind != "harness_service"
                or definition.confirmation_required
                or definition.service_id != _ACTION_TYPE
            ):
                raise RuntimeError("research.evidence.qualify action registration conflict")

            try:
                service_registry.resolve(_ACTION_TYPE)
            except ConversationRuntimeError as exc:
                if exc.code != "CONV-ROUTE-001":
                    raise
                service_registry.register(
                    _ACTION_TYPE,
                    ResearchEvidenceQualificationHandler(
                        self._application.conversation_store,
                        self._application.ids,
                    ),
                )
