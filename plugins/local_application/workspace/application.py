from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.conversation import (
    ActionDefinition,
    ActionRegistry,
    CapabilityActionMaterializerRegistry,
    CapabilityDescriptorRegistry,
    HarnessServiceRegistry,
    canonical_digest,
)
from core.decision import HumanDecisionService
from core.decision.conversation import DecisionAwareResearchCoordinator
from core.execution import (
    AuthorizationDecision,
    CapabilityContextExtensionRegistry,
    CapabilityExecutionService,
    CapabilityRegistry,
    ExecutionIssue,
)
from core.resources import resource_path
from core.runtime import (
    CanonicalResearchObjectSchemaValidator,
    CapabilityNormalizationBoundary,
    StateTransitionService,
)
from core.runtime.ports import RepositoryError
from plugins.desktop_research import (
    DesktopResearchContextValidator,
    DesktopResearchConversationMaterializer,
    DesktopResearchExternalAdapter,
    DesktopResearchNormalizer,
)
from plugins.local_application.workspace.research_question_batch import (
    ResearchQuestionProposeManyHandler,
    research_question_propose_many_payload,
)
from plugins.local_attention_store import LocalAttentionStore
from plugins.local_conversation_store import LocalConversationStore
from plugins.local_decision_store import LocalHumanDecisionStore
from plugins.local_execution_store import (
    LocalCapabilityContextExtensionStore,
    LocalExecutionStore,
    LocalOperationalTraceStore,
)
from plugins.sqlite_state_store import SQLiteResearchStateRepository

from .research_attention_handlers import (
    EffectiveResearchAttentionProvider,
    ResearchAttentionActivateHandler,
    ResearchAttentionProposeHandler,
    ResearchAttentionStatusHandler,
    _attention_activate_payload,
    _attention_proposal_payload,
    _attention_status_payload,
)
from .research_handlers import (
    ResearchQuestionProposeHandler,
    ResearchStatusHandler,
    RunAbortHandler,
    StateDeltaApplyHandler,
    _abort_payload,
    _apply_payload,
    _desktop_payload,
    _rq_proposal_payload,
    _status_payload,
)

DESCRIPTOR_PATH = resource_path(
    "core/packages/desktop-research/desktop-research-capability-descriptor.json"
)
RESEARCH_SCHEMA_PATH = resource_path("core/models/research-object.schema.json")
ATTENTION_STORE_NAME = "attention.sqlite3"


class SystemClock:
    def now(self) -> str:
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class UUIDIdProvider:
    def new(self, prefix: str) -> str:
        return prefix + uuid.uuid4().hex


class LocalStaticAuthorizationProvider:
    """Local PR9 authorization boundary, deliberately independent of PR10 confirmation."""

    def evidence_for(self, proposal, materialization, *, invocation_id, run_id):
        resources = [
            str(item["reference_id"]) for item in materialization.context_pack["resources"]
        ]
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
        return AuthorizationDecision(
            False,
            (),
            (
                ExecutionIssue(
                    "CAP-AUTHORIZATION-001", "local runtime authorization evidence is invalid"
                ),
            ),
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
        self.effective_attention = EffectiveResearchAttentionProvider(
            self.attention_store,
            profile_history_root=self.root / "profile-history",
        )

        self.execution_store = LocalExecutionStore(self.root / "execution")
        catalog = {}
        for reference_id, value in (resource_catalog or {}).items():
            metadata = deepcopy(dict(value))
            existing_reference_id = metadata.get("reference_id")
            if existing_reference_id is not None and str(existing_reference_id) != str(
                reference_id
            ):
                raise ValueError(f"resource catalog identity mismatch: {reference_id}")
            metadata["reference_id"] = str(reference_id)
            catalog[str(reference_id)] = metadata
        for reference_id, content in (resource_bytes or {}).items():
            if reference_id not in catalog:
                raise ValueError(f"resource bytes require catalog metadata: {reference_id}")
            registered = self.execution_store.register_input_bytes(reference_id, content)
            catalog[reference_id]["digest"] = registered.digest
            catalog[reference_id]["locator"] = registered.storage_locator
        self.context_extension_store = LocalCapabilityContextExtensionStore(
            self.execution_store.root
        )
        self.operational_store = LocalOperationalTraceStore(
            self.execution_store.root, self.execution_store
        )

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
            context_extension_registry=CapabilityContextExtensionRegistry(
                (DesktopResearchContextValidator(),)
            ),
            context_extension_store=self.context_extension_store,
        )

        actions = ActionRegistry()
        actions.register(
            ActionDefinition(
                "research.status",
                "research-status-query@0.1.0",
                "read_only",
                "harness_service",
                False,
                service_id="research.status",
                payload_validator=_status_payload,
            )
        )
        actions.register(
            ActionDefinition(
                "research_question.propose",
                "research-question-proposal@0.1.0",
                "read_only",
                "harness_service",
                False,
                human_decision_required=False,
                service_id="research_question.propose",
                payload_validator=_rq_proposal_payload,
            )
        )
        actions.register(
            ActionDefinition(
                "research_question.propose_many",
                "research-question-batch-proposal@0.1.0",
                "read_only",
                "harness_service",
                False,
                human_decision_required=False,
                service_id="research_question.propose_many",
                payload_validator=research_question_propose_many_payload,
            )
        )
        actions.register(
            ActionDefinition(
                "research_attention.status",
                "research-attention-status@0.1.0",
                "read_only",
                "harness_service",
                False,
                human_decision_required=False,
                service_id="research_attention.status",
                payload_validator=_attention_status_payload,
            )
        )
        actions.register(
            ActionDefinition(
                "research_attention.propose",
                "research-attention-proposal@0.1.0",
                "read_only",
                "harness_service",
                False,
                human_decision_required=False,
                service_id="research_attention.propose",
                payload_validator=_attention_proposal_payload,
            )
        )
        actions.register(
            ActionDefinition(
                "research_attention.activate_candidate",
                "research-attention-activation@0.1.0",
                "state_changing",
                "harness_service",
                True,
                human_decision_required=False,
                service_id="research_attention.activate_candidate",
                payload_validator=_attention_activate_payload,
            )
        )
        actions.register(
            ActionDefinition(
                "desktop_research.investigate",
                "desktop-research-action@0.1.0",
                "read_only",
                "capability_invocation",
                False,
                capability_id="desktop-research",
                capability_version="0.1.0",
                function_id="investigate",
                execution_mode="real",
                materializer_id="desktop_research.investigate@0.1.0",
                execution_style="external",
                payload_validator=_desktop_payload,
            )
        )
        actions.register(
            ActionDefinition(
                "run.abort",
                "run-abort-action@0.1.0",
                "state_changing",
                "harness_service",
                True,
                service_id="run.abort",
                payload_validator=_abort_payload,
            )
        )
        # The exact candidate may or may not require a Decision. Static Conversation
        # metadata cannot truthfully decide that; PR20 authority validation does.
        actions.register(
            ActionDefinition(
                "state.apply_candidate",
                "state-delta-adoption-action@0.1.0",
                "state_changing",
                "harness_service",
                True,
                human_decision_required=False,
                service_id="state.apply_candidate",
                payload_validator=_apply_payload,
            )
        )

        services = HarnessServiceRegistry()
        services.register("research.status", ResearchStatusHandler(self.human_decisions))
        services.register(
            "research_question.propose",
            ResearchQuestionProposeHandler(self.conversation_store, self.ids),
        )
        services.register(
            "research_question.propose_many",
            ResearchQuestionProposeManyHandler(self.conversation_store, self.ids),
        )
        services.register(
            "research_attention.status", ResearchAttentionStatusHandler(self.effective_attention)
        )
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
        services.register(
            "state.apply_candidate",
            StateDeltaApplyHandler(self.conversation_store, self.human_decisions),
        )

        materializers = CapabilityActionMaterializerRegistry()
        materializers.register(
            DesktopResearchConversationMaterializer(
                effective_profile_set_provider=effective_profile_set_provider,
                effective_attention_provider=self.effective_attention,
                resource_catalog=catalog,
                resource_roles=resource_roles,
            )
        )
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
