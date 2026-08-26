from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Mapping
import uuid

from core.conversation import (
    ActionDefinition,
    ActionRegistry,
    CapabilityActionMaterializerRegistry,
    CapabilityDescriptorRegistry,
    HarnessServiceRegistry,
    HarnessServiceResult,
    ResearchCoordinator,
    canonical_digest,
)
from core.execution import (
    AuthorizationDecision,
    CapabilityContextExtensionRegistry,
    CapabilityExecutionService,
    CapabilityRegistry,
    ExecutionIssue,
)
from core.runtime import (
    Actor,
    CanonicalResearchObjectSchemaValidator,
    CapabilityNormalizationBoundary,
    StateTransitionRequest,
    StateTransitionService,
    TransitionAction,
    TransitionKind,
)
from plugins.desktop_research import (
    DesktopResearchContextValidator,
    DesktopResearchConversationMaterializer,
    DesktopResearchExternalAdapter,
    DesktopResearchNormalizer,
)
from plugins.local_conversation_store import LocalConversationStore
from plugins.local_execution_store import (
    LocalCapabilityContextExtensionStore,
    LocalExecutionStore,
    LocalOperationalTraceStore,
)
from plugins.sqlite_state_store import SQLiteResearchStateRepository


ROOT = Path(__file__).resolve().parents[2]
DESCRIPTOR_PATH = ROOT / "core/packages/desktop-research/desktop-research-capability-descriptor.json"
RESEARCH_SCHEMA_PATH = ROOT / "core/models/research-object.schema.json"


class SystemClock:
    def now(self) -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class UUIDIdProvider:
    def new(self, prefix: str) -> str:
        return prefix + uuid.uuid4().hex


class LocalStaticAuthorizationProvider:
    """Small local PR9 authorization boundary; unrelated to Conversation confirmation."""

    def evidence_for(self, proposal, materialization, *, invocation_id, run_id):
        resources = tuple(
            str(item["reference_id"]) for item in materialization.context_pack["resources"]
        )
        evidence = {
            "authorization_id": "AUTH-" + uuid.uuid4().hex,
            "capability_id": proposal["route"]["capability"]["capability_id"],
            "function_id": proposal["route"]["capability"]["function_id"],
            "execution_modes": [materialization.execution_mode],
            "resource_reference_ids": list(resources),
            "invocation_id": invocation_id,
            "run_id": run_id,
        }
        evidence["authorization_digest"] = canonical_digest(evidence)
        return evidence

    def validate(self, evidence, *, invocation, context_pack, now):
        payload = deepcopy(dict(evidence))
        supplied = str(payload.pop("authorization_digest", ""))
        expected = canonical_digest(payload)
        required = tuple(str(item["reference_id"]) for item in context_pack["resources"])
        valid = (
            supplied == expected
            and evidence.get("capability_id") == invocation["capability"]["capability_id"]
            and evidence.get("function_id") == invocation["capability"]["function_id"]
            and invocation["execution_mode"] in evidence.get("execution_modes", ())
            and set(required).issubset(set(evidence.get("resource_reference_ids", ())))
            and evidence.get("invocation_id") == invocation["invocation_id"]
            and evidence.get("run_id") == invocation["run_id"]
        )
        if valid:
            return AuthorizationDecision(True, tuple(evidence.get("resource_reference_ids", ())))
        return AuthorizationDecision(
            False,
            (),
            (ExecutionIssue("CAP-AUTHORIZATION-001", "local runtime authorization evidence is invalid"),),
        )


class ResearchStatusHandler:
    def execute(self, payload, *, state, actor, proposal):
        kinds = payload.get("kinds")
        objects = [deepcopy(dict(item)) for item in state.effective_objects()]
        if kinds:
            allowed = set(str(item) for item in kinds)
            objects = [item for item in objects if str(item.get("kind")) in allowed]
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
            },
            research_state_mutation_performed=False,
        )


class RunAbortHandler:
    def __init__(self, execution_service) -> None:
        self._execution = execution_service

    def execute(self, payload, *, state, actor, proposal):
        run_id = str(payload["run_id"])
        run = self._execution.abort(run_id, reason=str(payload.get("reason") or "explicit conversational run.abort"))
        return HarnessServiceResult(
            result_reference=run.run_id,
            data={"run_id": run.run_id, "run_status": run.status.value},
            research_state_mutation_performed=False,
        )


class StateDeltaApplyHandler:
    """Materialize an already-produced PR20 candidate into the existing transition service input."""

    def __init__(self, store, clock, ids) -> None:
        self._store = store
        self._clock = clock
        self._ids = ids

    def execute(self, payload, *, state, actor, proposal):
        candidate_id = str(payload["state_delta_proposal_id"])
        candidate = self._store.load_state_delta_proposal(candidate_id)
        if candidate is None:
            raise KeyError(f"unknown StateDeltaProposal: {candidate_id}")
        if candidate.get("candidate_only") is not True:
            raise ValueError("only candidate-only StateDeltaProposal input is accepted")
        if (
            candidate.get("project_ref") != state.project_ref
            or candidate.get("lineage_ref") != state.lineage_ref
            or candidate.get("current_snapshot_ref") != state.current_snapshot["id"]
            or candidate.get("current_snapshot_digest") != state.current_snapshot["content_digest"]
        ):
            raise ValueError("StateDeltaProposal is stale or bound to a different Research State")
        decision_refs = tuple(str(item) for item in payload.get("decision_reference_ids", ()))
        actions = []
        for raw in candidate.get("proposed_actions", ()):
            kind = TransitionKind(str(raw["kind"]))
            candidate_decisions = tuple(str(item) for item in raw.get("decision_refs", ()))
            actions.append(TransitionAction(
                kind=kind,
                payload=deepcopy(dict(raw.get("payload", {}))),
                decision_refs=candidate_decisions or decision_refs,
                source_refs=tuple(str(item) for item in raw.get("source_refs", ())),
            ))
        if not actions:
            raise ValueError("StateDeltaProposal has no proposed actions")
        request = StateTransitionRequest(
            transition_id=self._ids.new("TR-"),
            project_ref=state.project_ref,
            lineage_ref=state.lineage_ref,
            expected_head_snapshot_ref=str(state.current_snapshot["id"]),
            expected_head_snapshot_digest=str(state.current_snapshot["content_digest"]),
            actor=Actor(str(actor["actor_id"]), str(actor["actor_type"])),
            actions=tuple(actions),
            project_config_ref=state.project_config_ref,
            project_config_digest=state.project_config_digest,
            effective_profile_set_ref=state.effective_profile_set_ref,
            effective_profile_set_digest=state.effective_profile_set_digest,
            authorization_evidence=tuple(str(item) for item in payload.get("authorization_evidence", ())),
            idempotency_key=str(payload.get("idempotency_key") or self._ids.new("IDEMP-")),
            submitted_at=self._clock.now(),
            new_snapshot_id=self._ids.new("SNP-"),
            commit_id=self._ids.new("COM-"),
            audit_event_id=self._ids.new("AUD-"),
            source_refs=tuple(str(item) for item in candidate.get("source_refs", ())),
        ).with_calculated_digest()
        return HarnessServiceResult(
            result_reference=candidate_id,
            data={"candidate_proposal_id": candidate_id},
            state_transition_request=request,
            research_state_mutation_performed=False,
        )


def _validate_status_payload(payload: Mapping[str, Any]) -> None:
    allowed = {"kinds"}
    if set(payload) - allowed:
        raise ValueError("research.status payload contains unknown fields")
    if "kinds" in payload and not isinstance(payload["kinds"], list):
        raise ValueError("research.status kinds must be an array")


def _validate_desktop_payload(payload: Mapping[str, Any]) -> None:
    allowed = {
        "question_id", "purpose", "resource_reference_ids", "coverage_dimensions", "desktop_policy"
    }
    if set(payload) - allowed:
        raise ValueError("desktop_research.investigate payload contains unknown fields")
    if not isinstance(payload.get("question_id"), str) or not payload["question_id"]:
        raise ValueError("desktop_research.investigate requires question_id")
    if "resource_reference_ids" in payload and not isinstance(payload["resource_reference_ids"], list):
        raise ValueError("resource_reference_ids must be an array of pre-registered IDs")


def _validate_abort_payload(payload: Mapping[str, Any]) -> None:
    if set(payload) - {"run_id", "reason"} or not isinstance(payload.get("run_id"), str):
        raise ValueError("run.abort requires only run_id and optional reason")


def _validate_apply_payload(payload: Mapping[str, Any]) -> None:
    allowed = {"state_delta_proposal_id", "decision_reference_ids", "authorization_evidence", "idempotency_key"}
    if set(payload) - allowed or not isinstance(payload.get("state_delta_proposal_id"), str):
        raise ValueError("state.apply_candidate payload is invalid")


class LocalResearchApplication:
    """One explicit production-local composition of PR20-25 services and adapters."""

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
        schema = json.loads(RESEARCH_SCHEMA_PATH.read_text(encoding="utf-8"))
        self.state_transition_service = StateTransitionService(
            self.state_repository,
            schema_validator=CanonicalResearchObjectSchemaValidator(schema),
        )

        self.execution_store = LocalExecutionStore(self.root / "execution")
        catalog = {key: deepcopy(dict(value)) for key, value in (resource_catalog or {}).items()}
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

        self.conversation_store = LocalConversationStore(self.root / "conversation.db")
        actions = ActionRegistry()
        actions.register(ActionDefinition(
            "research.status", "research-status-query@0.1.0", "read_only", "harness_service", False,
            service_id="research.status", payload_validator=_validate_status_payload,
        ))
        actions.register(ActionDefinition(
            "desktop_research.investigate", "desktop-research-action@0.1.0", "read_only", "capability_invocation", False,
            capability_id="desktop-research", capability_version="0.1.0", function_id="investigate",
            execution_mode="real", materializer_id="desktop_research.investigate@0.1.0",
            execution_style="external", payload_validator=_validate_desktop_payload,
        ))
        actions.register(ActionDefinition(
            "run.abort", "run-abort-action@0.1.0", "state_changing", "harness_service", True,
            service_id="run.abort", payload_validator=_validate_abort_payload,
        ))
        actions.register(ActionDefinition(
            "state.apply_candidate", "state-delta-adoption-action@0.1.0", "state_changing", "harness_service", True,
            human_decision_required=True, service_id="state.apply_candidate", payload_validator=_validate_apply_payload,
        ))

        services = HarnessServiceRegistry()
        services.register("research.status", ResearchStatusHandler())
        services.register("run.abort", RunAbortHandler(self.capability_execution_service))
        services.register("state.apply_candidate", StateDeltaApplyHandler(self.conversation_store, self.clock, self.ids))

        materializers = CapabilityActionMaterializerRegistry()
        materializers.register(DesktopResearchConversationMaterializer(
            effective_profile_set_provider=effective_profile_set_provider,
            resource_catalog=catalog,
            resource_roles=resource_roles,
        ))
        descriptors = CapabilityDescriptorRegistry()
        descriptors.register(descriptor)

        def active_lineage(project_ref: str) -> str:
            if seed_state is not None and seed_state.project_ref == project_ref:
                # load through persistence below so process restart uses the DB, not the seed object
                pass
            row = self.state_repository.load_state_view(project_ref, self._active_lineage_for(project_ref))
            return row.active_lineage_ref

        self.coordinator = ResearchCoordinator(
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
        )

    def _active_lineage_for(self, project_ref: str) -> str:
        # Local application currently has one active lineage per project; obtain it
        # from the persisted project_active_lineage index without exposing SQL to
        # the generic Coordinator. The repository's public state-view API still
        # owns every semantic read. This helper resolves only the routing key.
        connection = getattr(self.state_repository, "_connection", None)
        if connection is None:
            raise KeyError(project_ref)
        row = connection.execute(
            "SELECT active_lineage_ref FROM project_active_lineage WHERE project_ref=?",
            (project_ref,),
        ).fetchone()
        if row is None:
            raise KeyError(project_ref)
        return str(row["active_lineage_ref"])

    def close(self) -> None:
        self.conversation_store.close()
        self.operational_store.close()
        self.context_extension_store.close()
        self.execution_store.close()
        self.state_repository.close()
