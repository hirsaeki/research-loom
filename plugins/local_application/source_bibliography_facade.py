from __future__ import annotations

from copy import deepcopy
import re
from threading import RLock
from typing import Any, Mapping

from core.conversation import ActionDefinition, ConversationRuntimeError, HarnessServiceResult
from core.runtime import ObjectRef, StateDeltaProposal, TransitionAction, TransitionKind, canonical_digest

from .evidence_qualification_facade import LocalApplicationFacade as _BaseLocalApplicationFacade

_ACTION_REGISTRATION_LOCK = RLock()
_ACTION_TYPE = "research.source.bibliography"
_PAYLOAD_CONTRACT = "research-source-bibliography@0.1.0"
_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")
_BIBLIOGRAPHIC_FIELDS = (
    "title",
    "publisher_or_author",
    "publication_or_update_date",
    "version_or_revision",
)
_MAX_ID_LENGTH = 256
_MAX_RATIONALE_LENGTH = 8_192
_MAX_METADATA_LENGTH = 4_096


def research_source_bibliography_payload(payload: Mapping[str, Any]) -> None:
    allowed = {"source_id", "expected_revision", "expected_digest", "rationale", *_BIBLIOGRAPHIC_FIELDS}
    if not isinstance(payload, Mapping) or set(payload) - allowed:
        raise ValueError("research.source.bibliography contains unknown fields")
    required = {"source_id", "expected_revision", "expected_digest", "rationale"}
    if set(payload) < required:
        raise ValueError(
            "research.source.bibliography requires source_id, expected_revision, expected_digest and rationale"
        )
    source_id = payload.get("source_id")
    if not isinstance(source_id, str) or not source_id.strip() or len(source_id) > _MAX_ID_LENGTH:
        raise ValueError("source_id must be a bounded non-empty ID")
    revision = payload.get("expected_revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise ValueError("expected_revision must be a non-negative integer")
    digest = payload.get("expected_digest")
    if not isinstance(digest, str) or _DIGEST_RE.fullmatch(digest) is None:
        raise ValueError("expected_digest must be a canonical sha256 digest")
    rationale = payload.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip() or len(rationale) > _MAX_RATIONALE_LENGTH:
        raise ValueError("rationale must be a bounded non-empty string")
    supplied = [field for field in _BIBLIOGRAPHIC_FIELDS if field in payload]
    if not supplied:
        raise ValueError("research.source.bibliography requires at least one bibliographic field")
    for field in supplied:
        value = payload[field]
        if not isinstance(value, str) or not value.strip() or len(value) > _MAX_METADATA_LENGTH:
            raise ValueError(f"{field} must be a bounded non-empty string")


def _current_source(state: Any, source_id: str) -> Mapping[str, Any]:
    source = next(
        (
            item
            for item in state.effective_objects()
            if item.get("kind") == "source"
            and item.get("id") == source_id
            and item.get("project_id") == state.project_ref
        ),
        None,
    )
    if source is None:
        raise ConversationRuntimeError(
            "SOURCE-BIBLIOGRAPHY-001",
            f"source_id must resolve to current Source: {source_id}",
        )
    return source


class ResearchSourceBibliographyHandler:
    """Create one exact Source bibliographic revision candidate."""

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
        research_source_bibliography_payload(payload)
        source = _current_source(state, str(payload["source_id"]))
        actual_digest = canonical_digest(source)
        if (
            int(source.get("revision", -1)) != int(payload["expected_revision"])
            or actual_digest != payload["expected_digest"]
        ):
            raise ConversationRuntimeError(
                "SOURCE-BIBLIOGRAPHY-STALE-001",
                "Source bibliography input does not match the current Source revision/digest",
            )

        updates = {field: str(payload[field]) for field in _BIBLIOGRAPHIC_FIELDS if field in payload}
        changed = {field: value for field, value in updates.items() if source.get(field) != value}
        if not changed:
            return HarnessServiceResult(
                result_reference=str(source["id"]),
                data={
                    "bibliography_status": "ALREADY_CURRENT",
                    "source_id": str(source["id"]),
                    "revision": int(source["revision"]),
                    "source_digest": actual_digest,
                },
                research_state_mutation_performed=False,
            )

        revised = deepcopy(dict(source))
        revised["revision"] = int(source["revision"]) + 1
        revised.update(changed)

        transition_action = TransitionAction(
            TransitionKind.REVISE_OBJECT,
            {"object": revised},
            decision_refs=(),
            source_refs=(),
        )
        provenance = {
            "producer": "research.source.bibliography@0.1.0",
            "source_action_proposal": {
                "proposal_id": str(proposal["proposal_id"]),
                "proposal_digest": str(proposal["proposal_digest"]),
            },
            "source_input_id": str(proposal["source"]["input_id"]),
            "source_revision": {
                "id": str(source["id"]),
                "revision": int(source["revision"]),
                "digest": actual_digest,
            },
            "updated_fields": sorted(changed),
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
            affected_refs=(ObjectRef("source", str(source["id"])),),
            rationale=str(payload["rationale"]),
            required_human_decision_kinds=(),
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
            "affected_refs": [{"kind": "source", "id": str(source["id"])}],
            "rationale": candidate.rationale,
            "required_human_decision_kinds": [],
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
                "bibliography_status": "CANDIDATE_CREATED",
                "source_id": str(source["id"]),
                "source_revision": int(source["revision"]),
                "source_digest": actual_digest,
                "candidate_revision": int(revised["revision"]),
                "updated_fields": sorted(changed),
                "state_delta_proposal_id": candidate.proposal_id,
                "state_delta_proposal": deepcopy(candidate_wire),
            },
            research_state_mutation_performed=False,
        )


class LocalApplicationFacade(_BaseLocalApplicationFacade):
    """Public Source bibliography ingress over the existing candidate/apply path."""

    def list_actions(self) -> Mapping[str, Any]:
        self._ensure_source_bibliography_action()
        return super().list_actions()

    def submit_action(
        self, draft_input: Mapping[str, Any], *, view: str | None = None
    ) -> Mapping[str, Any]:
        self._ensure_source_bibliography_action()
        return super().submit_action(draft_input, view=view)

    def _ensure_source_bibliography_action(self) -> None:
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
                        payload_validator=research_source_bibliography_payload,
                    )
                )
            elif (
                definition.payload_contract != _PAYLOAD_CONTRACT
                or definition.effect != "read_only"
                or definition.route_kind != "harness_service"
                or definition.confirmation_required
                or definition.service_id != _ACTION_TYPE
            ):
                raise RuntimeError("research.source.bibliography action registration conflict")

            try:
                service_registry.resolve(_ACTION_TYPE)
            except ConversationRuntimeError as exc:
                if exc.code != "CONV-ROUTE-001":
                    raise
                service_registry.register(
                    _ACTION_TYPE,
                    ResearchSourceBibliographyHandler(
                        self._application.conversation_store,
                        self._application.ids,
                    ),
                )
