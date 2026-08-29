from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Mapping
import uuid

from core.conversation import (
    ActionDefinition, ActionRegistry, CapabilityActionMaterializerRegistry,
    CapabilityDescriptorRegistry, ConversationRuntimeError, HarnessServiceRegistry,
    HarnessServiceResult, canonical_digest,
)
from core.decision import HumanDecisionService
from core.decision.conversation import DecisionAwareResearchCoordinator
from core.execution import (
    AuthorizationDecision, CapabilityContextExtensionRegistry,
    CapabilityExecutionService, CapabilityRegistry, ExecutionIssue,
)
from core.runtime import (
    CanonicalResearchObjectSchemaValidator, CapabilityNormalizationBoundary,
    ObjectRef, StateDeltaProposal, StateTransitionService, TransitionAction,
    TransitionKind,
)
from core.runtime.ports import RepositoryError
from plugins.desktop_research import (
    DesktopResearchContextValidator, DesktopResearchConversationMaterializer,
    DesktopResearchExternalAdapter, DesktopResearchNormalizer,
)
from plugins.local_attention_store import (
    LocalAttentionStore, LocalAttentionStoreError, attention_map_digest,
)
from plugins.local_conversation_store import LocalConversationStore
from plugins.local_decision_store import LocalHumanDecisionStore
from plugins.local_execution_store import (
    LocalCapabilityContextExtensionStore, LocalExecutionStore, LocalOperationalTraceStore,
)
from plugins.sqlite_state_store import SQLiteResearchStateRepository


ROOT = Path(__file__).resolve().parents[2]
DESCRIPTOR_PATH = ROOT / "core/packages/desktop-research/desktop-research-capability-descriptor.json"
RESEARCH_SCHEMA_PATH = ROOT / "core/models/research-object.schema.json"
ATTENTION_STORE_NAME = "attention.sqlite3"


class SystemClock:
    def now(self) -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class UUIDIdProvider:
    def new(self, prefix: str) -> str:
        return prefix + uuid.uuid4().hex


class LocalStaticAuthorizationProvider:
    """Local PR9 authorization boundary, deliberately independent of PR10 confirmation."""

    def evidence_for(self, proposal, materialization, *, invocation_id, run_id):
        resources = [str(item["reference_id"]) for item in materialization.context_pack["resources"]]
        evidence = {
            "authorization_id": "AUTH-" + uuid.uuid4().hex,
            "capability_id": proposal["route"]["capability"]["capability_id"],
            "function_id": proposal["route"]["capability"]["function_id"],
            "execution_modes": [materialization.execution_mode],
            "resource_reference_ids": resources,
        }
        evidence["authorization_digest"] = canonical_digest(evidence)
        return evidence

    def validate(self, evidence, *, invocation, context_pack, now):
        payload = deepcopy(dict(evidence))
        supplied = str(payload.pop("authorization_digest", ""))
        required = {str(item["reference_id"]) for item in context_pack["resources"]}
        valid = (
            supplied == canonical_digest(payload)
            and evidence.get("capability_id") == invocation["capability"]["capability_id"]
            and evidence.get("function_id") == invocation["capability"]["function_id"]
            and invocation["execution_mode"] in evidence.get("execution_modes", ())
            and required.issubset(set(evidence.get("resource_reference_ids", ())))
        )
        if valid:
            return AuthorizationDecision(True, tuple(evidence.get("resource_reference_ids", ())))
        return AuthorizationDecision(False, (), (
            ExecutionIssue("CAP-AUTHORIZATION-001", "local runtime authorization evidence is invalid"),
        ))


class ResearchStatusHandler:
    def __init__(self, human_decisions) -> None:
        self._human_decisions = human_decisions

    def execute(self, payload, *, state, actor, proposal):
        objects = [deepcopy(dict(item)) for item in state.effective_objects()]
        if payload.get("kinds"):
            allowed = {str(item) for item in payload["kinds"]}
            objects = [item for item in objects if str(item.get("kind")) in allowed]
        pending = []
        for request in self._human_decisions.pending(state.project_ref):
            pending.append({
                "request_id": request["request_id"],
                "source_candidate": deepcopy(request["source_state_delta_proposal"]),
                "subjects": [deepcopy(unit["subject"]) for unit in request["decision_units"]],
                "decision_kinds": list(dict.fromkeys(
                    str(unit["required_decision_kind"]) for unit in request["decision_units"]
                )),
                "snapshot_binding": deepcopy(request["snapshot_binding"]),
                "status": request.get("operational_status", "PENDING"),
            })
        return HarnessServiceResult(
            result_reference=str(state.current_snapshot["id"]),
            data={
                "state": {
                    "snapshot_id": state.current_snapshot["id"],
                    "revision": state.current_snapshot.get("revision", 0),
                    "content_digest": state.current_snapshot["content_digest"],
                    "active_lineage_ref": state.active_lineage_ref,
                },
                "objects": objects,
                "pending_human_decisions": pending,
            },
        )


class ResearchQuestionProposeHandler:
    """Materialize an untrusted typed RQ candidate without mutating Research State."""

    def __init__(self, store, id_provider) -> None:
        self._store = store
        self._ids = id_provider

    def execute(self, payload, *, state, actor, proposal):
        derived_seed_ids = tuple(str(item) for item in payload.get("derived_from_seed_ids", ()))
        configured_seeds = {
            str(item["seed_id"])
            for item in state.project_config.get("research_questions", {}).get("seeds", ())
            if isinstance(item, Mapping) and item.get("seed_id")
        }
        unknown_seeds = sorted(set(derived_seed_ids) - configured_seeds)
        if unknown_seeds:
            raise ValueError(
                "derived_from_seed_ids do not resolve in current Project Config: "
                + ", ".join(unknown_seeds)
            )

        parent_question_id = payload.get("parent_question_id")
        if parent_question_id is not None:
            parent = next(
                (
                    item
                    for item in state.effective_objects()
                    if item.get("kind") == "research_question"
                    and item.get("id") == parent_question_id
                    and item.get("project_id") == state.project_ref
                    and item.get("adoption_state") == "approved"
                ),
                None,
            )
            if parent is None:
                raise ValueError(
                    "parent_question_id must resolve to a current authoritative approved Research Question"
                )

        rq_id = self._ids.new("RQ-")
        rq_candidate: dict[str, Any] = {
            "schema_version": "0.1.0",
            "id": rq_id,
            "kind": "research_question",
            "revision": 0,
            "project_id": state.project_ref,
            "text": str(payload["text"]),
            "acceptance_criteria": list(payload.get("acceptance_criteria", ())),
            "scope_limits": list(payload.get("scope_limits", ())),
            "adoption_state": "approved",
        }
        if "rationale" in payload:
            rq_candidate["rationale"] = str(payload["rationale"])
        if parent_question_id is not None:
            rq_candidate["parent_question_id"] = str(parent_question_id)

        transition_action = TransitionAction(
            TransitionKind.CREATE_OBJECT,
            {"object": rq_candidate},
            decision_refs=(),
            source_refs=(),
        )
        provenance: dict[str, Any] = {
            "producer": "research_question.propose@0.1.0",
            "source_action_proposal": {
                "proposal_id": str(proposal["proposal_id"]),
                "proposal_digest": str(proposal["proposal_digest"]),
            },
            "source_input_id": str(proposal["source"]["input_id"]),
            "project_config": {
                "ref": state.project_config_ref,
                "digest": state.project_config_digest,
            },
        }
        if derived_seed_ids:
            provenance["project_config_seed_ids"] = list(derived_seed_ids)

        candidate = StateDeltaProposal(
            proposal_id=self._ids.new("SDP-"),
            project_ref=state.project_ref,
            lineage_ref=state.lineage_ref,
            source_refs=(),
            proposed_actions=(transition_action,),
            affected_refs=(ObjectRef("research_question", rq_id),),
            rationale=str(
                payload.get("rationale")
                or "Research Question candidate proposed through bounded semantic ingress."
            ),
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
            "source_refs": list(candidate.source_refs),
            "proposed_actions": [{
                "kind": transition_action.kind.value,
                "payload": deepcopy(dict(transition_action.payload)),
                "decision_refs": list(transition_action.decision_refs),
                "source_refs": list(transition_action.source_refs),
            }],
            "affected_refs": [{"kind": "research_question", "id": rq_id}],
            "rationale": candidate.rationale,
            "required_human_decision_kinds": list(candidate.required_human_decision_kinds),
            "current_snapshot_ref": candidate.current_snapshot_ref,
            "current_snapshot_digest": candidate.current_snapshot_digest,
            "provenance": deepcopy(dict(candidate.provenance)),
            "candidate_only": True,
            "proposal_digest": candidate.proposal_digest,
        }
        self._store.store_state_delta_proposal(candidate.proposal_id, candidate_wire)
        return HarnessServiceResult(
            result_reference=candidate.proposal_id,
            data={
                "state_delta_proposal_id": candidate.proposal_id,
                "research_question_candidate": deepcopy(rq_candidate),
                "state_delta_proposal": deepcopy(candidate_wire),
            },
            research_state_mutation_performed=False,
        )


class EffectiveResearchAttentionProvider:
    """Resolve complete effective guidance without changing Project Config or Research State."""

    def __init__(self, store: LocalAttentionStore) -> None:
        self._store = store

    def active(self, state) -> Mapping[str, Any] | None:
        try:
            active = self._store.load_active(state.project_ref)
        except LocalAttentionStoreError as exc:
            raise ConversationRuntimeError(exc.code, exc.message) from exc
        if active is None:
            return None
        document = active["map"]
        if (
            document["project_id"] != state.project_ref
            or document["project_config"]["ref"] != state.project_config_ref
            or document["project_config"]["digest"] != state.project_config_digest
        ):
            raise ConversationRuntimeError(
                "ATTENTION-STALE-001", "active Attention Map is bound to a different Project Config"
            )
        return active

    def resolve(self, state):
        active = self.active(state)
        source_items = (
            active["map"]["items"]
            if active is not None
            else state.project_config.get("research_attention", ())
        )
        return active, deepcopy(list(source_items))

    def __call__(self, state):
        return self.resolve(state)[1]


class ResearchAttentionStatusHandler:
    def __init__(self, effective_attention: EffectiveResearchAttentionProvider) -> None:
        self._effective = effective_attention

    def execute(self, payload, *, state, actor, proposal):
        active, effective_attention = self._effective.resolve(state)
        return HarnessServiceResult(
            result_reference=(str(active["map_id"]) if active is not None else state.project_config_ref),
            data={
                "baseline": {
                    "project_config_digest": state.project_config_digest,
                    "items": deepcopy(list(state.project_config.get("research_attention", ()))),
                },
                "active_map": (
                    {
                        "map_id": str(active["map_id"]),
                        "map_digest": str(active["map_digest"]),
                        "activation_id": str(active["activation_id"]),
                    }
                    if active is not None else None
                ),
                "effective_attention": effective_attention,
            },
            research_state_mutation_performed=False,
        )


def _current_authoritative_rq_ids(state) -> set[str]:
    return {
        str(item["id"])
        for item in state.effective_objects()
        if item.get("kind") == "research_question"
        and item.get("project_id") == state.project_ref
        and item.get("adoption_state") in {"approved", "revised"}
    }


def _validate_attention_references(items, state) -> None:
    resource_ids = {
        str(item["reference_id"])
        for item in state.project_config.get("resource_references", ())
        if isinstance(item, Mapping) and item.get("reference_id")
    }
    seed_ids = {
        str(item["seed_id"])
        for item in state.project_config.get("research_questions", {}).get("seeds", ())
        if isinstance(item, Mapping) and item.get("seed_id")
    }
    rq_ids = _current_authoritative_rq_ids(state)
    attention_ids = [str(item["attention_id"]) for item in items]
    if len(attention_ids) != len(set(attention_ids)):
        raise ConversationRuntimeError("ATTENTION-IDENTITY-001", "Attention IDs must be unique")
    for item in items:
        unknown_resources = set(map(str, item.get("source_reference_ids", ()))) - resource_ids
        if unknown_resources:
            raise ConversationRuntimeError(
                "ATTENTION-REF-001",
                "Attention source_reference_ids do not resolve: " + ", ".join(sorted(unknown_resources)),
            )
        unknown_seeds = set(map(str, item.get("related_question_seed_ids", ()))) - seed_ids
        if unknown_seeds:
            raise ConversationRuntimeError(
                "ATTENTION-REF-001",
                "Attention related_question_seed_ids do not resolve: " + ", ".join(sorted(unknown_seeds)),
            )
        unknown_rqs = set(map(str, item.get("related_question_ids", ()))) - rq_ids
        if unknown_rqs:
            raise ConversationRuntimeError(
                "ATTENTION-REF-001",
                "Attention related_question_ids do not resolve to current authoritative Research Questions: "
                + ", ".join(sorted(unknown_rqs)),
            )


class ResearchAttentionProposeHandler:
    """Build and persist one immutable complete effective Attention snapshot."""

    def __init__(self, store, effective_attention, id_provider, clock) -> None:
        self._store = store
        self._effective = effective_attention
        self._ids = id_provider
        self._clock = clock

    def execute(self, payload, *, state, actor, proposal):
        active, effective_items = self._effective.resolve(state)
        items = [deepcopy(dict(item)) for item in effective_items]
        by_id = {str(item["attention_id"]): item for item in items}

        for addition in payload.get("additions", ()):
            attention_id = self._ids.new("ATT-")
            if attention_id in by_id:
                raise ConversationRuntimeError(
                    "ATTENTION-IDENTITY-001", "Harness-generated Attention ID collides with current effective Attention"
                )
            item: dict[str, Any] = {
                "attention_id": attention_id,
                "statement": str(addition["statement"]),
                "disposition": "active",
            }
            for field in (
                "rationale", "source_reference_ids", "related_question_ids",
                "related_question_seed_ids", "projection_hints",
            ):
                if field in addition:
                    item[field] = deepcopy(addition[field])
            items.append(item)
            by_id[attention_id] = item

        for change in payload.get("dispositions", ()):
            attention_id = str(change["attention_id"])
            item = by_id.get(attention_id)
            if item is None:
                raise ConversationRuntimeError(
                    "ATTENTION-UNKNOWN-001", f"unknown effective Attention ID: {attention_id}"
                )
            item["disposition"] = str(change["disposition"])
            if "disposition_reason" in change:
                item["disposition_reason"] = str(change["disposition_reason"])
            elif item["disposition"] == "active":
                item.pop("disposition_reason", None)

        for change in payload.get("links", ()):
            attention_id = str(change["attention_id"])
            item = by_id.get(attention_id)
            if item is None:
                raise ConversationRuntimeError(
                    "ATTENTION-UNKNOWN-001", f"unknown effective Attention ID: {attention_id}"
                )
            for field in ("related_question_ids", "related_question_seed_ids"):
                if field in change:
                    item[field] = list(change[field])

        _validate_attention_references(items, state)
        base = (
            {
                "source": "active_map",
                "map_id": str(active["map_id"]),
                "map_digest": str(active["map_digest"]),
            }
            if active is not None else {"source": "project_config_baseline"}
        )
        candidate: dict[str, Any] = {
            "schema_version": "0.1.0",
            "map_id": self._ids.new("ATTMAP-"),
            "project_id": state.project_ref,
            "project_config": {
                "ref": state.project_config_ref,
                "digest": state.project_config_digest,
            },
            "base": base,
            "items": items,
            "provenance": {
                "source_action_proposal_id": str(proposal["proposal_id"]),
                "source_action_proposal_digest": str(proposal["proposal_digest"]),
                "source_input_id": str(proposal["source"]["input_id"]),
            },
            "created_at": self._clock.now(),
        }
        candidate["map_digest"] = attention_map_digest(candidate)
        try:
            self._store.store_map(candidate)
        except LocalAttentionStoreError as exc:
            raise ConversationRuntimeError(exc.code, exc.message) from exc
        return HarnessServiceResult(
            result_reference=str(candidate["map_id"]),
            data={"attention_map": deepcopy(candidate), "active_map_changed": False},
            research_state_mutation_performed=False,
        )


class ResearchAttentionActivateHandler:
    def __init__(self, store, id_provider, clock) -> None:
        self._store = store
        self._ids = id_provider
        self._clock = clock

    def execute(self, payload, *, state, actor, proposal):
        map_id = str(payload["attention_map_id"])
        try:
            candidate = self._store.load_map(map_id)
        except LocalAttentionStoreError as exc:
            raise ConversationRuntimeError(exc.code, exc.message) from exc
        if candidate is None:
            raise ConversationRuntimeError("ATTENTION-MAP-UNKNOWN-001", f"unknown Attention Map: {map_id}")
        if (
            candidate["project_id"] != state.project_ref
            or candidate["project_config"]["ref"] != state.project_config_ref
            or candidate["project_config"]["digest"] != state.project_config_digest
        ):
            raise ConversationRuntimeError(
                "ATTENTION-STALE-001", "Attention Map is bound to a different current project/configuration"
            )
        try:
            event = self._store.activate(
                project_id=state.project_ref,
                map_id=map_id,
                activation_id=self._ids.new("ATTACT-"),
                actor_id=str(actor.get("actor_id", "")),
                source_action_proposal=proposal,
                activated_at=self._clock.now(),
            )
        except LocalAttentionStoreError as exc:
            raise ConversationRuntimeError(exc.code, exc.message) from exc
        return HarnessServiceResult(
            result_reference=str(event["activation_id"]),
            data={
                "activation": deepcopy(event),
                "active_map": {
                    "map_id": str(candidate["map_id"]),
                    "map_digest": str(candidate["map_digest"]),
                    "activation_id": str(event["activation_id"]),
                },
            },
            research_state_mutation_performed=False,
        )


class RunAbortHandler:
    def __init__(self, execution_service) -> None:
        self._execution = execution_service

    def execute(self, payload, *, state, actor, proposal):
        run = self._execution.abort(
            str(payload["run_id"]),
            reason=str(payload.get("reason") or "explicit conversational run.abort"),
        )
        return HarnessServiceResult(
            result_reference=run.run_id,
            data={"run_id": run.run_id, "run_status": run.status.value},
            research_state_mutation_performed=False,
        )


class StateDeltaApplyHandler:
    """Gate an exact PR20 candidate through dynamic PR20 DecisionRequirements."""

    def __init__(self, store, human_decisions) -> None:
        self._store = store
        self._human_decisions = human_decisions

    def execute(self, payload, *, state, actor, proposal):
        candidate_id = str(payload["state_delta_proposal_id"])
        candidate = self._store.load_state_delta_proposal(candidate_id)
        if candidate is None:
            raise KeyError(f"unknown StateDeltaProposal: {candidate_id}")
        gate = self._human_decisions.gate_candidate(
            candidate,
            state=state,
            actor=actor,
            source_action_proposal=proposal,
        )
        if gate.status == "READY_TO_COMMIT":
            return HarnessServiceResult(
                result_reference=candidate_id,
                data={"candidate_proposal_id": candidate_id, "decision_required": False},
                state_transition_request=gate.transition_request,
            )
        request = gate.decision_request
        return HarnessServiceResult(
            result_reference=str(request["request_id"]),
            data={
                "candidate_proposal_id": candidate_id,
                "decision_required": True,
                "decision_request": deepcopy(dict(request)),
            },
            research_state_mutation_performed=False,
        )


def _status_payload(payload: Mapping[str, Any]) -> None:
    if set(payload) - {"kinds"} or ("kinds" in payload and not isinstance(payload["kinds"], list)):
        raise ValueError("research.status payload is invalid")


def _rq_proposal_payload(payload: Mapping[str, Any]) -> None:
    allowed = {
        "text", "rationale", "acceptance_criteria", "scope_limits",
        "parent_question_id", "derived_from_seed_ids",
    }
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError(
            "research_question.propose payload contains unknown fields: "
            + ", ".join(sorted(str(item) for item in unknown))
        )
    text = payload.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("research_question.propose requires non-empty text")
    if "rationale" in payload and (
        not isinstance(payload["rationale"], str) or not payload["rationale"].strip()
    ):
        raise ValueError("rationale must be a non-empty string")
    if (
        "parent_question_id" in payload
        and payload["parent_question_id"] is not None
        and (
            not isinstance(payload["parent_question_id"], str)
            or not payload["parent_question_id"].strip()
        )
    ):
        raise ValueError("parent_question_id must be null or a non-empty string")
    for field in ("acceptance_criteria", "scope_limits", "derived_from_seed_ids"):
        if field not in payload:
            continue
        value = payload[field]
        if not isinstance(value, list) or any(
            not isinstance(item, str) or not item.strip() for item in value
        ):
            raise ValueError(f"{field} must be an array of non-empty strings")
    seed_ids = payload.get("derived_from_seed_ids", ())
    if len(seed_ids) != len(set(seed_ids)):
        raise ValueError("derived_from_seed_ids must not contain duplicates")


def _attention_status_payload(payload: Mapping[str, Any]) -> None:
    if payload:
        raise ValueError("research_attention.status payload must be empty")


def _string_list(value, field: str) -> None:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{field} must be an array of non-empty strings")
    if len(value) != len(set(value)):
        raise ValueError(f"{field} must not contain duplicates")


def _attention_proposal_payload(payload: Mapping[str, Any]) -> None:
    allowed = {"additions", "dispositions", "links", "rationale"}
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError(
            "research_attention.propose payload contains unknown fields: "
            + ", ".join(sorted(str(item) for item in unknown))
        )
    operations = 0
    additions = payload.get("additions", [])
    dispositions = payload.get("dispositions", [])
    links = payload.get("links", [])
    for name, value in (("additions", additions), ("dispositions", dispositions), ("links", links)):
        if not isinstance(value, list):
            raise ValueError(f"{name} must be an array")
        operations += len(value)
    if not operations:
        raise ValueError("research_attention.propose requires at least one bounded operation")
    if "rationale" in payload and (
        not isinstance(payload["rationale"], str) or not payload["rationale"].strip()
    ):
        raise ValueError("rationale must be a non-empty string")

    addition_allowed = {
        "statement", "rationale", "source_reference_ids", "related_question_ids",
        "related_question_seed_ids", "projection_hints",
    }
    for item in additions:
        if not isinstance(item, Mapping) or set(item) - addition_allowed:
            raise ValueError("addition contains unknown or forbidden fields")
        if not isinstance(item.get("statement"), str) or not item["statement"].strip():
            raise ValueError("addition requires non-empty statement")
        if "rationale" in item and not isinstance(item["rationale"], str):
            raise ValueError("addition rationale must be a string")
        for field in ("source_reference_ids", "related_question_ids", "related_question_seed_ids"):
            if field in item:
                _string_list(item[field], field)
        if "projection_hints" in item and not isinstance(item["projection_hints"], list):
            raise ValueError("projection_hints must be an array")

    seen_dispositions: set[str] = set()
    for item in dispositions:
        if not isinstance(item, Mapping) or set(item) - {"attention_id", "disposition", "disposition_reason"}:
            raise ValueError("disposition update contains unknown fields")
        if set(item) < {"attention_id", "disposition"}:
            raise ValueError("disposition update requires attention_id and disposition")
        attention_id = item.get("attention_id")
        if not isinstance(attention_id, str) or not attention_id.strip() or attention_id in seen_dispositions:
            raise ValueError("disposition attention_id must be unique and non-empty")
        seen_dispositions.add(attention_id)
        disposition = item.get("disposition")
        if disposition not in {"active", "dropped", "out_of_scope"}:
            raise ValueError("invalid Attention disposition")
        reason = item.get("disposition_reason")
        if disposition in {"dropped", "out_of_scope"} and (
            not isinstance(reason, str) or not reason.strip()
        ):
            raise ValueError("dropped/out_of_scope Attention requires disposition_reason")
        if reason is not None and (not isinstance(reason, str) or not reason.strip()):
            raise ValueError("disposition_reason must be a non-empty string")

    seen_links: set[str] = set()
    for item in links:
        if not isinstance(item, Mapping) or set(item) - {
            "attention_id", "related_question_ids", "related_question_seed_ids"
        }:
            raise ValueError("link update contains unknown fields")
        attention_id = item.get("attention_id")
        if not isinstance(attention_id, str) or not attention_id.strip() or attention_id in seen_links:
            raise ValueError("link attention_id must be unique and non-empty")
        seen_links.add(attention_id)
        if not ({"related_question_ids", "related_question_seed_ids"} & set(item)):
            raise ValueError("link update requires at least one relation field")
        for field in ("related_question_ids", "related_question_seed_ids"):
            if field in item:
                _string_list(item[field], field)


def _attention_activate_payload(payload: Mapping[str, Any]) -> None:
    if set(payload) != {"attention_map_id"}:
        raise ValueError("research_attention.activate_candidate accepts only attention_map_id")
    if not isinstance(payload.get("attention_map_id"), str) or not payload["attention_map_id"].strip():
        raise ValueError("attention_map_id must be a non-empty string")


def _desktop_payload(payload: Mapping[str, Any]) -> None:
    allowed = {"question_id", "purpose", "resource_reference_ids", "coverage_dimensions", "desktop_policy"}
    if set(payload) - allowed or not isinstance(payload.get("question_id"), str) or not payload["question_id"]:
        raise ValueError("desktop_research.investigate payload is invalid")
    if "resource_reference_ids" in payload and not isinstance(payload["resource_reference_ids"], list):
        raise ValueError("resource_reference_ids must be pre-registered IDs")


def _abort_payload(payload: Mapping[str, Any]) -> None:
    if set(payload) - {"run_id", "reason"} or not isinstance(payload.get("run_id"), str):
        raise ValueError("run.abort requires run_id and optional reason")


def _apply_payload(payload: Mapping[str, Any]) -> None:
    if set(payload) != {"state_delta_proposal_id"} or not isinstance(payload.get("state_delta_proposal_id"), str):
        raise ValueError(
            "state.apply_candidate accepts only state_delta_proposal_id; "
            "Decision refs are derived by the Human Decision Gate"
        )


class LocalResearchApplication:
    """Explicit production-local composition root for PR20-30."""

    def __init__(
        self,
        root: str | Path,
        *,
        resolver,
        effective_profile_set_provider,
        seed_state=None,
        clock=None,
        id_provider=None,
        authorization_provider=None,
        resource_catalog: Mapping[str, Mapping[str, Any]] | None = None,
        resource_roles: Mapping[str, str] | None = None,
        resource_bytes: Mapping[str, bytes] | None = None,
    ) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.clock = clock or SystemClock()
        self.ids = id_provider or UUIDIdProvider()
        self.authorization = authorization_provider or LocalStaticAuthorizationProvider()

        self.state_repository = SQLiteResearchStateRepository(self.root / "research-state.sqlite3")
        if seed_state is not None:
            self.state_repository.initialize_from_validated_state_view(seed_state)
        research_schema = json.loads(RESEARCH_SCHEMA_PATH.read_text(encoding="utf-8"))
        self.state_transition_service = StateTransitionService(
            self.state_repository,
            schema_validator=CanonicalResearchObjectSchemaValidator(research_schema),
        )

        # Conversation documents provide the immutable source bindings for Decision
        # Requests, but the Decision lifecycle remains in its own operational DB.
        self.conversation_store = LocalConversationStore(self.root / "conversation.db")
        self.decision_store = LocalHumanDecisionStore(self.root / "decision.db")
        self.human_decisions = HumanDecisionService(
            store=self.decision_store,
            state_provider=self.state_repository,
            state_transition_service=self.state_transition_service,
            clock=self.clock,
            source_binding_provider=self.conversation_store,
        )

        # PR30 guidance storage is additive and lazy. Merely opening an older workspace
        # or reading baseline status must not create or migrate this optional DB.
        self.attention_store = LocalAttentionStore(self.root / ATTENTION_STORE_NAME)
        self.effective_attention = EffectiveResearchAttentionProvider(self.attention_store)

        self.execution_store = LocalExecutionStore(self.root / "execution")
        catalog = {}
        for reference_id, value in (resource_catalog or {}).items():
            metadata = deepcopy(dict(value))
            existing_reference_id = metadata.get("reference_id")
            if existing_reference_id is not None and str(existing_reference_id) != str(reference_id):
                raise ValueError(f"resource catalog identity mismatch: {reference_id}")
            metadata["reference_id"] = str(reference_id)
            catalog[str(reference_id)] = metadata
        for reference_id, content in (resource_bytes or {}).items():
            if reference_id not in catalog:
                raise ValueError(f"resource bytes require catalog metadata: {reference_id}")
            registered = self.execution_store.register_input_bytes(reference_id, content)
            catalog[reference_id]["digest"] = registered.digest
            catalog[reference_id]["locator"] = registered.storage_locator
        self.context_extension_store = LocalCapabilityContextExtensionStore(self.execution_store.root)
        self.operational_store = LocalOperationalTraceStore(self.execution_store.root, self.execution_store)

        descriptor = json.loads(DESCRIPTOR_PATH.read_text(encoding="utf-8"))
        capability_registry = CapabilityRegistry()
        capability_registry.register(DesktopResearchExternalAdapter(), descriptor)
        normalizer = DesktopResearchNormalizer(
            self.execution_store,
            self.context_extension_store,
            self.execution_store,
            self.operational_store,
        )
        self.capability_execution_service = CapabilityExecutionService(
            capability_registry,
            self.execution_store,
            self.state_repository,
            self.authorization,
            self.execution_store,
            CapabilityNormalizationBoundary((normalizer,)),
            self.clock,
            artifact_store=self.execution_store,
            context_extension_registry=CapabilityContextExtensionRegistry((DesktopResearchContextValidator(),)),
            context_extension_store=self.context_extension_store,
        )

        actions = ActionRegistry()
        actions.register(ActionDefinition(
            "research.status", "research-status-query@0.1.0", "read_only", "harness_service", False,
            service_id="research.status", payload_validator=_status_payload,
        ))
        actions.register(ActionDefinition(
            "research_question.propose", "research-question-proposal@0.1.0", "read_only", "harness_service", False,
            human_decision_required=False, service_id="research_question.propose",
            payload_validator=_rq_proposal_payload,
        ))
        actions.register(ActionDefinition(
            "research_attention.status", "research-attention-status@0.1.0", "read_only", "harness_service", False,
            human_decision_required=False, service_id="research_attention.status",
            payload_validator=_attention_status_payload,
        ))
        actions.register(ActionDefinition(
            "research_attention.propose", "research-attention-proposal@0.1.0", "read_only", "harness_service", False,
            human_decision_required=False, service_id="research_attention.propose",
            payload_validator=_attention_proposal_payload,
        ))
        actions.register(ActionDefinition(
            "research_attention.activate_candidate", "research-attention-activation@0.1.0",
            "state_changing", "harness_service", True,
            human_decision_required=False, service_id="research_attention.activate_candidate",
            payload_validator=_attention_activate_payload,
        ))
        actions.register(ActionDefinition(
            "desktop_research.investigate", "desktop-research-action@0.1.0", "read_only", "capability_invocation", False,
            capability_id="desktop-research", capability_version="0.1.0", function_id="investigate",
            execution_mode="real", materializer_id="desktop_research.investigate@0.1.0",
            execution_style="external", payload_validator=_desktop_payload,
        ))
        actions.register(ActionDefinition(
            "run.abort", "run-abort-action@0.1.0", "state_changing", "harness_service", True,
            service_id="run.abort", payload_validator=_abort_payload,
        ))
        # The exact candidate may or may not require a Decision. Static Conversation
        # metadata cannot truthfully decide that; PR20 authority validation does.
        actions.register(ActionDefinition(
            "state.apply_candidate", "state-delta-adoption-action@0.1.0", "state_changing", "harness_service", True,
            human_decision_required=False, service_id="state.apply_candidate", payload_validator=_apply_payload,
        ))

        services = HarnessServiceRegistry()
        services.register("research.status", ResearchStatusHandler(self.human_decisions))
        services.register(
            "research_question.propose",
            ResearchQuestionProposeHandler(self.conversation_store, self.ids),
        )
        services.register("research_attention.status", ResearchAttentionStatusHandler(self.effective_attention))
        services.register(
            "research_attention.propose",
            ResearchAttentionProposeHandler(
                self.attention_store, self.effective_attention, self.ids, self.clock
            ),
        )
        services.register(
            "research_attention.activate_candidate",
            ResearchAttentionActivateHandler(self.attention_store, self.ids, self.clock),
        )
        services.register("run.abort", RunAbortHandler(self.capability_execution_service))
        services.register("state.apply_candidate", StateDeltaApplyHandler(self.conversation_store, self.human_decisions))

        materializers = CapabilityActionMaterializerRegistry()
        materializers.register(DesktopResearchConversationMaterializer(
            effective_profile_set_provider=effective_profile_set_provider,
            effective_attention_provider=self.effective_attention,
            resource_catalog=catalog,
            resource_roles=resource_roles,
        ))
        descriptors = CapabilityDescriptorRegistry()
        descriptors.register(descriptor)

        self.coordinator = DecisionAwareResearchCoordinator(
            resolver=resolver,
            store=self.conversation_store,
            state_provider=self.state_repository,
            state_transition_service=self.state_transition_service,
            capability_execution_service=self.capability_execution_service,
            action_registry=actions,
            harness_services=services,
            capability_materializers=materializers,
            descriptors=descriptors,
            authorization_evidence_provider=self.authorization,
            clock=self.clock,
            id_provider=self.ids,
            lineage_resolver=self._active_lineage_for,
            human_decisions=self.human_decisions,
        )

    def resolve_human_decision(self, response: Mapping[str, Any]):
        """Resolve only an explicit structured Human Decision response."""
        return self.human_decisions.resolve(response)

    def _active_lineage_for(self, project_ref: str) -> str:
        try:
            return self.state_repository.load_active_lineage_ref(project_ref)
        except RepositoryError as exc:
            raise KeyError(project_ref) from exc

    def close(self) -> None:
        self.conversation_store.close()
        self.operational_store.close()
        self.context_extension_store.close()
        self.execution_store.close()
        self.decision_store.close()
        self.state_repository.close()
