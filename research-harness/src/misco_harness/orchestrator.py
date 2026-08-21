from __future__ import annotations

import json
import hashlib
import os
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from misco_harness.audit import (
    audit_attention_distillation_handoff,
    audit_desktop_research_handoff,
    audit_provenance_audit_handoff,
    audit_worker_result,
)
from misco_harness.attention import register_drop
from misco_harness.context_builder import ArtifactAccessPolicy, ContextBuilder
from misco_harness.decision_broker import DecisionBroker, method_selection_request
from misco_harness.evidence_migration import migrate_research_state
from misco_harness.models import (
    ArtifactRecord,
    ArtifactRegistry,
    AttentionDistillationHandoff,
    AttentionMapCandidateItem,
    AuditResult,
    ClaimType,
    ContractRegistryRefresh,
    CoverageDimension,
    CoverageStoppingAssessment,
    DropBatchManifest,
    DecisionKind,
    DecisionRecord,
    DecisionRequest,
    DesktopResearchContextSpec,
    DesktopResearchEvidence,
    DesktopResearchHandoff,
    EvidenceExcerpt,
    EvidenceGap,
    EvidenceKind,
    EvidenceModelMigrationReceipt,
    FindingRecord,
    Lane,
    NextMethodOption,
    OrchestratorState,
    ProposedQuestionBaseline,
    ProvenanceAuditHandoff,
    ProvenanceAuditPlan,
    PublicationEligibility,
    PublicationState,
    PublicationStructureChange,
    PublicationWriterOutput,
    QuestionImpact,
    QuestionInput,
    QuestionRecord,
    RemainingInformationValue,
    ResearchBrief,
    ResearchState,
    RunManifest,
    RuntimePolicyValue,
    SourceCapture,
    SourceQuality,
    SourceType,
    StudyRole,
    SupportScope,
    WorkerResult,
    WorkExecutionRequest,
    utc_now,
)
from misco_harness.publication_lane import (
    PublicationLaneError,
    apply_writer_output,
    refresh_publication_state,
)
from misco_harness.run_manager import RunManager
from misco_harness.state_reducer import (
    ReductionBlocked,
    reduce_desktop_research_handoff,
    reduce_worker_result,
)
from misco_harness.trace_store import (
    HashMismatch,
    TraceStore,
    TraceStoreError,
    sha256_file,
    sha256_tree,
    verify_hash,
)
from misco_harness.workers import (
    DesktopEvidenceSnapshotError,
    InteractiveWorkDiscoveryBoundary,
    InteractiveWorkAttentionBoundary,
    InteractiveWorkProvenanceBoundary,
    InteractiveWorkResearchBoundary,
    MockWorkerAdapter,
    discovery_mock_result,
    validate_desktop_snapshot_directory,
    validate_provenance_snapshot_directory,
    validate_source_capture_exchange,
)
from misco_harness.workspace import archive_workspace, new_workspace, verify_archive


class OrchestratorError(RuntimeError):
    pass


@dataclass(frozen=True)
class NextRunPlan:
    task_type: str
    event: str
    objective: str
    artifact_ids: list[str]
    required_ids: set[str]


_CANONICAL_CONTRACT_SPECS = (
    ("harness-contract", "contracts/research_harness_v0.4.md", "ACTIVE_CONTRACT", Lane.CONTROL_PLANE),
    ("constitution", "contracts/research_constitution.md", "ACTIVE_CONTRACT", Lane.RESEARCH),
    (
        "desktop-research-contract",
        "contracts/capabilities/desktop-research/desktop_research_contract.md",
        "DESKTOP_RESEARCH_CONTRACT",
        Lane.CONTROL_PLANE,
    ),
    (
        "desktop-research-source-policy",
        "contracts/capabilities/desktop-research/source_policy.yaml",
        "DESKTOP_RESEARCH_SOURCE_POLICY",
        Lane.CONTROL_PLANE,
    ),
    ("publication-lane-contract", "contracts/publication_parallel_lane.md", "ACTIVE_CONTRACT", Lane.PUBLICATION),
    ("publication-structure-schema", "contracts/publication_structure.schema.yaml", "ACTIVE_CONTRACT", Lane.PUBLICATION),
    ("runtime-artifact-policy", "contracts/runtime_artifact_policy.yaml", "ACTIVE_CONTRACT", Lane.CONTROL_PLANE),
    (
        "desktop-research-evidence-schema",
        "contracts/capabilities/desktop-research/evidence_capture.schema.yaml",
        "ACTIVE_CONTRACT",
        Lane.CONTROL_PLANE,
    ),
    (
        "provenance-audit-contract",
        "contracts/capabilities/desktop-research/provenance_audit_contract.md",
        "ACTIVE_CONTRACT",
        Lane.IMPLEMENTATION,
    ),
    (
        "attention-distillation-contract",
        "contracts/capabilities/attention-intake/attention_distillation_contract.md",
        "ACTIVE_CONTRACT",
        Lane.CONTROL_PLANE,
    ),
    (
        "workspace-lifecycle-contract",
        "contracts/capabilities/workspace-lifecycle/workspace_lifecycle_contract.md",
        "ACTIVE_CONTRACT",
        Lane.CONTROL_PLANE,
    ),
)


class DiscoveryOrchestrator:
    _held_transition_locks: dict[Path, tuple[str, int]] = {}
    _held_transition_locks_guard = threading.RLock()

    def __init__(self, workspace: Path):
        self.workspace = workspace.resolve()
        self.runtime = self.workspace / ".rh"
        self.store = TraceStore(self.runtime)
        self.builder = ContextBuilder(
            self.workspace,
            self.runtime,
            ArtifactAccessPolicy(self.workspace / "contracts" / "runtime_artifact_policy.yaml"),
        )
        self.run_manager = RunManager(self.store)
        self.decisions = DecisionBroker(self.store)

    def initialize(
        self,
        *,
        theme: Path,
        expectations: Path,
        seed: Path | None = None,
        attention_map: Path | None = None,
        include_default_attention_map: bool = True,
        worker_backend: str,
    ) -> None:
        if (self.runtime / "state" / "orchestrator" / "head.json").exists():
            raise OrchestratorError("workspace is already initialized")
        records = [
            self._record("theme", theme, "INTAKE_SOURCE", Lane.RESEARCH),
            self._record("expectations", expectations, "INTAKE_SOURCE", Lane.RESEARCH),
            self._record("harness-contract", self.workspace / "contracts" / "research_harness_v0.4.md", "ACTIVE_CONTRACT", Lane.CONTROL_PLANE),
            self._record("constitution", self.workspace / "contracts" / "research_constitution.md", "ACTIVE_CONTRACT", Lane.RESEARCH),
            self._record(
                "desktop-research-contract",
                self.workspace / "contracts" / "capabilities" / "desktop-research" / "desktop_research_contract.md",
                "DESKTOP_RESEARCH_CONTRACT",
                Lane.CONTROL_PLANE,
            ),
            self._record(
                "desktop-research-source-policy",
                self.workspace / "contracts" / "capabilities" / "desktop-research" / "source_policy.yaml",
                "DESKTOP_RESEARCH_SOURCE_POLICY",
                Lane.CONTROL_PLANE,
            ),
            self._record(
                "publication-lane-contract",
                self.workspace / "contracts" / "publication_parallel_lane.md",
                "ACTIVE_CONTRACT",
                Lane.PUBLICATION,
            ),
            self._record(
                "publication-structure-schema",
                self.workspace / "contracts" / "publication_structure.schema.yaml",
                "ACTIVE_CONTRACT",
                Lane.PUBLICATION,
            ),
        ]
        for artifact_id, relative_path, role, lane in _CANONICAL_CONTRACT_SPECS:
            if artifact_id in {"attention-distillation-contract", "workspace-lifecycle-contract"}:
                path = self.workspace / relative_path
                if not path.is_file():
                    continue
                records.append(self._record(artifact_id, path, role, lane))
        selected_attention_map = attention_map
        if selected_attention_map is None and include_default_attention_map:
            default_attention_map = self.workspace / "maps" / "research_attention_and_initial_publication_map.md"
            if default_attention_map.is_file():
                selected_attention_map = default_attention_map
        active_attention_map_id = None
        if selected_attention_map is not None:
            records.insert(4, self._record("attention-map", selected_attention_map, "ATTENTION_PUBLICATION_MAP", Lane.CONTROL_PLANE))
            active_attention_map_id = "attention-map"
        if seed is not None:
            records.insert(2, self._record("rq-seed", seed, "PRIOR_SEED", Lane.RESEARCH))
        self.store.write_head("registry/artifact_registry.json", ArtifactRegistry(artifacts=records))
        research = ResearchState(state_id="research-initial")
        orchestrator = OrchestratorState(
            state_id="orchestrator-initial",
            worker_backend=worker_backend,
            active_attention_map_id=active_attention_map_id,
        )
        self.store.snapshot("research", research.state_id, research)
        self.store.write_head("state/research/head.json", research)
        publication = PublicationState(state_id="publication-initial")
        self.store.snapshot("publication", publication.state_id, publication)
        self.store.write_head("state/publication/head.json", publication)
        self.store.snapshot("orchestrator", orchestrator.state_id, orchestrator)
        self.store.write_head("state/orchestrator/head.json", orchestrator)

    def refresh_contract_registry(self) -> ContractRegistryRefresh:
        """Refresh an existing live Registry from the current contract policy.

        This is a Harness-owned ``CONTRACT_MIGRATION_REVIEW`` event. It freezes
        the prior Registry, builds a Context Pack from the refreshed in-memory
        records, and only then advances the live Registry head. Research State,
        Publication State, Human Decisions, and pending Work are never reduced
        or rewritten by this operation.
        """
        with self._discovery_transition_lock():
            state = self.status()
            self._ensure_active(state)
            if state.pending_work:
                raise OrchestratorError("cannot refresh the contract Registry while another Work run is pending")
            # A long-lived API caller may have changed the policy file after
            # constructing the orchestrator; migration always resolves the
            # current on-disk policy rather than a constructor-time snapshot.
            self.builder.policy = ArtifactAccessPolicy(
                self.workspace / "contracts" / "runtime_artifact_policy.yaml",
            )

            registry_path = self.runtime / "registry" / "artifact_registry.json"
            if not registry_path.is_file():
                raise OrchestratorError("live Artifact Registry is missing; initialize the workspace first")
            registry_before = self._registry()
            registry_before_hash = sha256_file(registry_path)
            research_path = self.runtime / "state" / "research" / "head.json"
            research_state = self._research_state()
            research_state_hash = sha256_file(research_path)

            run_id = self._id("run-contract-migration")
            self.store.create_run_dir(run_id)
            before_path = self.store.copy_immutable_file(
                registry_path,
                Path("runs") / run_id / "registry_before.json",
            )

            existing_by_id = {item.artifact_id: item for item in registry_before.artifacts}
            optional_contract_ids = {"attention-distillation-contract", "workspace-lifecycle-contract"}
            canonical_specs = tuple(
                item for item in _CANONICAL_CONTRACT_SPECS
                if item[0] not in optional_contract_ids or (self.workspace / item[1]).is_file()
            )
            canonical_ids = [item[0] for item in canonical_specs]
            canonical_records: dict[str, ArtifactRecord] = {}
            refreshed_ids: list[str] = []
            added_ids: list[str] = []
            changed_policy_ids: list[str] = []
            unchanged_ids: list[str] = []
            for artifact_id, relative_path, role, lane in canonical_specs:
                fresh = self._record(artifact_id, self.workspace / relative_path, role, lane)
                previous = existing_by_id.get(artifact_id)
                if previous is None:
                    canonical_records[artifact_id] = fresh
                    added_ids.append(artifact_id)
                    continue
                canonical_records[artifact_id] = fresh.model_copy(update={
                    "schema_version": previous.schema_version,
                    "authority": previous.authority,
                    "evidence_eligible": previous.evidence_eligible,
                    "may_shape_questions": previous.may_shape_questions,
                    "may_determine_method": previous.may_determine_method,
                    "may_determine_answer": previous.may_determine_answer,
                    "status": previous.status,
                    "supersedes": previous.supersedes,
                    "superseded_by": previous.superseded_by,
                    "mode": previous.mode,
                })
                changed = (
                    previous.path != canonical_records[artifact_id].path
                    or previous.sha256 != canonical_records[artifact_id].sha256
                    or previous.role != canonical_records[artifact_id].role
                    or previous.lane != canonical_records[artifact_id].lane
                    or previous.runtime_policy != canonical_records[artifact_id].runtime_policy
                )
                if changed:
                    refreshed_ids.append(artifact_id)
                else:
                    unchanged_ids.append(artifact_id)
                if previous.runtime_policy != canonical_records[artifact_id].runtime_policy:
                    changed_policy_ids.append(artifact_id)

            updated_records = [
                canonical_records.get(item.artifact_id, item)
                for item in registry_before.artifacts
            ]
            present_ids = {item.artifact_id for item in updated_records}
            updated_records.extend(
                canonical_records[artifact_id]
                for artifact_id in canonical_ids
                if artifact_id not in present_ids
            )
            updated_registry = ArtifactRegistry(artifacts=updated_records)
            after_path = self.store.write_immutable(
                Path("runs") / run_id / "registry_after.json",
                updated_registry,
            )
            registry_after_hash = sha256_file(after_path)

            before_record = ArtifactRecord(
                artifact_id="contract-migration-registry-before",
                path=str(before_path),
                sha256=registry_before_hash,
                role="ACTIVE_CONTRACT",
                authority="HARNESS_MIGRATION_SNAPSHOT",
                lane=Lane.IMPLEMENTATION,
                runtime_policy=self.builder.policy.runtime_policy_for_role("ACTIVE_CONTRACT"),
            )
            migration_registry = ArtifactRegistry(artifacts=[*updated_registry.artifacts, before_record])
            pack_id = self._id("pack-contract-migration")
            artifact_ids = ["contract-migration-registry-before", *canonical_ids]
            pack = self.builder.build(
                pack_id=pack_id,
                run_id=run_id,
                event="CONTRACT_MIGRATION_REVIEW",
                lane=Lane.IMPLEMENTATION,
                registry=migration_registry,
                artifact_ids=artifact_ids,
                required_ids=set(artifact_ids),
                extra_forbidden_context=[
                    "archive/provenance/**",
                    "publication drafts and feedback as research evidence",
                    "Research State semantic changes",
                ],
            )
            context_manifest = self._context_manifest(pack)
            input_refs = [*context_manifest.must_include, *context_manifest.retrieve_on_demand]
            run_manifest = RunManifest(
                run_id=run_id,
                task_id=self._id("task-contract-migration"),
                task_type="CONTRACT_REGISTRY_REFRESH",
                objective="Refresh the live Artifact Registry from the current contract and runtime policy files.",
                event="CONTRACT_MIGRATION_REVIEW",
                lane=Lane.IMPLEMENTATION,
                context_pack_id=pack_id,
                input_refs=input_refs,
                forbidden_context=context_manifest.forbidden_context,
                retrieval_policy=[
                    "Use only the frozen Registry-before snapshot and canonical contract files in this Context Pack.",
                    "Do not inspect archive/provenance or treat Publication materials as Research Evidence.",
                ],
                output_schema="ContractRegistryRefresh",
                stop_conditions=["Any missing, changed, or hash-invalid canonical contract blocks the refresh."],
                worker_backend="harness",
                audit_policy=[
                    "Validate every canonical contract path and SHA-256 against the refreshed Registry.",
                    "Confirm Registry-before and Registry-after are immutable run artifacts.",
                    "Confirm Research State bytes and Human Decision IDs are unchanged.",
                ],
                decision_context=[
                    "This event changes only Registry contract/policy metadata.",
                    "Semantic Research decisions require a separate Human Decision.",
                ],
            )
            self.store.write_immutable(Path("runs") / run_id / "manifest.json", run_manifest)
            if sha256_file(registry_path) != registry_before_hash:
                raise OrchestratorError("live Artifact Registry changed during contract migration; head was not advanced")
            for record in canonical_records.values():
                verify_hash(Path(record.path), record.sha256 or "")
            audit = AuditResult(run_id=run_id, passed=True, issues=[])
            self.store.write_immutable(Path("runs") / run_id / "audit.json", audit)
            receipt = ContractRegistryRefresh(
                run_id=run_id,
                context_pack_id=pack_id,
                registry_before_sha256=registry_before_hash,
                registry_after_sha256=registry_after_hash,
                research_state_id=research_state.state_id,
                research_state_sha256=research_state_hash,
                refreshed_artifact_ids=refreshed_ids,
                added_artifact_ids=added_ids,
                changed_policy_artifact_ids=changed_policy_ids,
                unchanged_artifact_ids=unchanged_ids,
                canonical_artifact_ids=canonical_ids,
                pending_decision_ids=state.pending_decision_ids,
            )
            self.store.write_immutable(Path("runs") / run_id / "contract_registry_refresh.json", receipt)
            self.store.write_immutable(
                Path("runs") / run_id / "trace.json",
                {
                    "run_id": run_id,
                    "event": "CONTRACT_MIGRATION_REVIEW",
                    "status": "COMPLETED",
                    "registry_before_sha256": registry_before_hash,
                    "registry_after_sha256": registry_after_hash,
                    "pending_decision_ids": state.pending_decision_ids,
                },
            )
            self.store.write_immutable(
                Path("runs") / run_id / "completion.json",
                {"run_id": run_id, "status": "COMPLETED", "event": "CONTRACT_MIGRATION_REVIEW"},
            )
            self.store.write_head("registry/artifact_registry.json", updated_registry)
            return receipt

    def migrate_contract_registry(self) -> ContractRegistryRefresh:
        """Compatibility alias for callers that use the migration vocabulary."""
        return self.refresh_contract_registry()

    def migrate_decision_kinds(self, mapping: dict[str, str]) -> dict[str, object]:
        with self._discovery_transition_lock():
            self._ensure_active(self.status())
            typed = {decision_id: DecisionKind(kind) for decision_id, kind in mapping.items()}
            return self.decisions.migrate_legacy_kinds(typed)

    def migrate_publication_eligibility(self) -> dict[str, object]:
        """Quarantine pre-P2 unbound eligibility and require a fresh decision."""
        marker_path = Path("migrations") / "publication-eligibility-v1.json"
        if (self.runtime / marker_path).is_file():
            return self.store.read_json(marker_path)
        with self._discovery_transition_lock(), self._publication_transition_lock():
            self._ensure_active(self.status())
            raw_research = self.store.read_json("state/research/head.json")
            old_research_id = str(raw_research["state_id"])
            raw_eligibility = raw_research.get("publication_eligibility") or {}
            legacy = (
                raw_eligibility.get("status") == "ELIGIBLE"
                and not raw_eligibility.get("reviewed_research_state_id")
            )
            if legacy:
                new_research_id = self._id("research-migrate-eligibility")
                raw_research.update({
                    "state_id": new_research_id,
                    "prior_snapshot_id": old_research_id,
                    "publication_eligibility": PublicationEligibility(
                        status="NOT_ELIGIBLE",
                        scope="LEGACY_UNBOUND_REQUIRES_REVIEW",
                    ).model_dump(mode="json"),
                })
                migrated_research = ResearchState.model_validate(raw_research)
                snapshot_path = self.store.snapshot("research", new_research_id, migrated_research)
                self.store.write_head("state/research/head.json", migrated_research)
                self._register_snapshot(new_research_id, snapshot_path)
            else:
                new_research_id = old_research_id

            raw_publication = self.store.read_json("state/publication/head.json")
            old_publication_id = str(raw_publication["state_id"])
            if legacy:
                new_publication_id = self._id("publication-migrate-eligibility")
                migrated_publication = PublicationState(
                    state_id=new_publication_id,
                    status="SCAFFOLD",
                    source_research_state_id=new_research_id,
                    prior_snapshot_id=old_publication_id,
                )
                self.store.snapshot("publication", new_publication_id, migrated_publication)
                self.store.write_head("state/publication/head.json", migrated_publication)
            else:
                new_publication_id = old_publication_id
            marker = {
                "migration": "publication-eligibility-v1",
                "status": "COMPLETED" if legacy else "NO_OP",
                "legacy_research_state_id": old_research_id,
                "new_research_state_id": new_research_id,
                "legacy_publication_state_id": old_publication_id,
                "new_publication_state_id": new_publication_id,
                "action": "LEGACY_ELIGIBILITY_QUARANTINED_REQUIRES_NEW_HUMAN_DECISION",
            }
            self.store.write_immutable(marker_path, marker)
            return marker

    def migrate_evidence_model(self, state_path: Path | None = None) -> EvidenceModelMigrationReceipt:
        """Create an immutable v0.3 Research State without rewriting v0.2 history."""
        with self._discovery_transition_lock():
            self._ensure_active(self.status())
            source_path = (state_path or (self.runtime / "state" / "research" / "head.json")).resolve()
            prior = ResearchState.model_validate_json(source_path.read_text(encoding="utf-8"))
            run_id = self._id("run-evidence-migration")
            new_state_id = self._id("research")
            self.store.create_run_dir(run_id)
            manifest = RunManifest(
                run_id=run_id,
                task_id=self._id("task-evidence-migration"),
                task_type="EVIDENCE_MODEL_MIGRATION",
                objective="Migrate immutable legacy Evidence into shared SourceCaptures and EvidenceCitations",
                event="EVIDENCE_MODEL_MIGRATION",
                lane=Lane.IMPLEMENTATION,
                output_schema="ResearchState",
                worker_backend="harness",
            )
            self.store.write_immutable(Path("runs") / run_id / "manifest.json", manifest)
            converted, receipt = migrate_research_state(
                prior,
                destination_root=self.runtime / "runs" / run_id,
                run_id=run_id,
                new_state_id=new_state_id,
            )
            prior_hash = sha256_file(source_path)
            snapshot_path = self.store.snapshot("research", new_state_id, converted)
            new_hash = sha256_file(snapshot_path)
            receipt = receipt.model_copy(update={
                "prior_state_sha256": prior_hash,
                "new_state_sha256": new_hash,
                "immutable_history_refs": [str(source_path), prior.state_id],
            })
            self.store.write_immutable(Path("runs") / run_id / "legacy_state.json", prior)
            self.store.write_immutable(Path("runs") / run_id / "research_state.json", converted)
            self.store.write_immutable(Path("runs") / run_id / "migration_receipt.json", receipt)
            self.store.write_immutable(Path("runs") / run_id / "audit.json", AuditResult(run_id=run_id, passed=True, issues=[]))
            self.store.write_immutable(
                Path("runs") / run_id / "completion.json",
                {"run_id": run_id, "status": "COMPLETED", "event": "EVIDENCE_MODEL_MIGRATION"},
            )
            self.store.write_head("state/research/head.json", converted)
            self._register_snapshot(new_state_id, snapshot_path)
            return receipt

    def status(self) -> OrchestratorState:
        return OrchestratorState.model_validate(self.store.read_json("state/orchestrator/head.json"))

    def register_attention_drop(self, source_path: Path, *, registered_by: str) -> DropBatchManifest:
        with self._discovery_transition_lock():
            state = self.status()
            self._ensure_active(state)
            manifest, records = register_drop(
                self.workspace,
                source_path,
                registered_by=registered_by,
                policy=self.builder.policy,
            )
            registry = self._registry()
            self.store.write_head(
                "registry/artifact_registry.json",
                ArtifactRegistry(artifacts=[*registry.artifacts, *records]),
            )
            updated = state.model_copy(update={
                "state_id": self._id("orchestrator"),
                "pending_attention_drop_ids": [*state.pending_attention_drop_ids, manifest.drop_id],
                "prior_snapshot_id": state.state_id,
            })
            self.store.snapshot("orchestrator", updated.state_id, updated)
            self.store.write_head("state/orchestrator/head.json", updated)
            return manifest

    def archive(
        self,
        destination: Path,
        *,
        created_by: str,
        reason: str,
        allow_incomplete: bool = False,
    ):
        with self._discovery_transition_lock():
            return archive_workspace(
                self,
                destination,
                created_by=created_by,
                reason=reason,
                allow_incomplete=allow_incomplete,
            )

    @staticmethod
    def verify_archive(destination: Path):
        return verify_archive(destination)

    def start_provenance_audit(self, plan_path: Path) -> OrchestratorState:
        """Materialize an explicit PROVENANCE_AUDIT Work boundary.

        This registers only the plan, its frozen baseline, and the contracts
        named by the plan. No Research State is reduced or changed here.
        """
        with self._discovery_transition_lock():
            state = self.status()
            self._ensure_active(state)
            if state.worker_backend != "interactive-work":
                raise OrchestratorError("PROVENANCE_AUDIT requires worker_backend='interactive-work'")
            if state.pending_work:
                raise OrchestratorError("cannot start PROVENANCE_AUDIT while another Work run is pending")
            return self._prepare_provenance_audit_locked(state, plan_path)

    def reacquire_provenance_audit(self) -> OrchestratorState:
        """Discard a failed provenance Work run and create a fresh exchange."""
        with self._discovery_transition_lock():
            state = self.status()
            self._ensure_active(state)
            request = state.pending_work
            if request is None or request.expected_output_schema != "ProvenanceAuditHandoff":
                raise OrchestratorError("no pending PROVENANCE_AUDIT Work run can be reacquired")
            if not state.provenance_audit_plan_path:
                raise OrchestratorError("pending PROVENANCE_AUDIT has no registered plan path")
            old_run = request.run_id
            self.store.write_immutable(
                Path("runs") / old_run / "discard.json",
                {"run_id": old_run, "status": "DISCARDED", "reason": "failed provenance submission; fresh Work exchange requested"},
            )
            self.store.write_immutable(
                Path("runs") / old_run / "completion.json",
                {"run_id": old_run, "status": "DISCARDED", "attempt": 1},
            )
            return self._prepare_provenance_audit_locked(
                state,
                Path(state.provenance_audit_plan_path),
                discarded_run_id=old_run,
            )

    def publication_state(self) -> PublicationState:
        return PublicationState.model_validate(self.store.read_json("state/publication/head.json"))

    def refresh_publication(
        self,
        *,
        changes: list[PublicationStructureChange] | None = None,
        draft_sections: dict[str, str] | None = None,
    ) -> PublicationState:
        """Refresh the provisional Publication Lane without advancing Research.

        Publication consumes one immutable Research State snapshot and never
        mutates the Research head or orchestrator phase. Eligibility must be a
        recorded Human-approved status, either on Research State or supplied by
        the caller as the already-recorded decision metadata.
        """
        with self._publication_transition_lock():
            self._ensure_active(self.status())
            research = self._research_state()
            attention = self._active_attention_artifact()
            attention_map_text = None
            attention_map_artifact_id = None
            if attention is not None:
                attention_path = Path(attention.path)
                verify_hash(attention_path, attention.sha256 or "")
                attention_map_text = attention_path.read_text(encoding="utf-8")
                attention_map_artifact_id = attention.artifact_id
            current = self.publication_state()
            try:
                updated = refresh_publication_state(
                    research_state=research,
                    current_state=current,
                    attention_map_text=attention_map_text,
                    attention_map_artifact_id=attention_map_artifact_id,
                    state_id=self._id("publication"),
                    structure_id=self._id("publication-structure"),
                    draft_id=self._id("publication-draft"),
                    changes=changes,
                    draft_sections=draft_sections,
                )
            except PublicationLaneError as error:
                raise OrchestratorError(str(error)) from error
            updated = updated.model_copy(update={"publication_eligibility": research.publication_eligibility})
            self.store.snapshot("publication", updated.state_id, updated)
            self.store.write_head("state/publication/head.json", updated)
            return updated

    def request_publication_eligibility(self) -> PublicationState:
        """Open an optional Publication-only Human Decision.

        This decision lives on PublicationState and therefore does not stop
        Research continuation or add a Research phase.
        """
        with self._publication_transition_lock():
            self._ensure_active(self.status())
            publication = self.publication_state()
            if publication.pending_decision_ids:
                return publication
            research = self._research_state()
            if (
                research.publication_eligibility
                and research.publication_eligibility.status == "ELIGIBLE"
                and research.publication_eligibility.is_snapshot_bound
                and research.publication_eligibility.recorded_research_state_id == research.state_id
            ):
                return publication
            request = self._publication_eligibility_decision(research.state_id)
            return self.decisions.block_publication(
                publication,
                request,
                snapshot_id=self._id("publication"),
            )

    def apply_publication_writer_output(self, output: PublicationWriterOutput) -> PublicationState:
        """Persist a Writer result and Feedback without touching Research State."""
        with self._publication_transition_lock():
            self._ensure_active(self.status())
            current = self.publication_state()
            try:
                updated = apply_writer_output(current, output, state_id=self._id("publication"))
            except PublicationLaneError as error:
                raise OrchestratorError(str(error)) from error
            for feedback in output.feedback:
                feedback = feedback.model_copy(update={
                    "source_publication_state_id": feedback.source_publication_state_id or current.state_id,
                    "source_research_state_id": feedback.source_research_state_id or updated.source_research_state_id,
                })
                self.store.write_immutable(
                    Path("publication") / "feedback" / f"{feedback.feedback_id}.json",
                    feedback,
                )
            self.store.snapshot("publication", updated.state_id, updated)
            self.store.write_head("state/publication/head.json", updated)
            return updated

    def plan(self) -> NextRunPlan | None:
        state = self.status()
        self._ensure_active(state)
        if state.pending_decision_ids or state.pending_work or state.terminal:
            return None
        registry = self._registry()
        ids = {item.artifact_id for item in registry.artifacts}
        if state.pending_attention_drop_ids:
            drop_id = state.pending_attention_drop_ids[0]
            manifest_path = self.runtime / "intake" / "drops" / drop_id / "manifest.json"
            if not manifest_path.is_file():
                raise OrchestratorError(f"registered Attention drop manifest is missing: {drop_id}")
            drop = DropBatchManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
            drop_artifacts = self._drop_artifact_ids(drop.drop_id)
            active_map = self._active_attention_artifact(state)
            artifacts = [
                *drop_artifacts,
                "harness-contract",
                "constitution",
                "attention-distillation-contract",
            ]
            if active_map is not None:
                artifacts.append(active_map.artifact_id)
            return NextRunPlan(
                "ATTENTION_MAP_DISTILLATION",
                "ATTENTION_DISTILLATION",
                f"Distill registered Attention drop {drop.drop_id} into a candidate Attention Map",
                artifacts,
                set(drop_artifacts) | {"harness-contract", "attention-distillation-contract"},
            )
        active_map = self._active_attention_artifact(state)
        map_artifacts = [active_map.artifact_id] if active_map is not None else []
        if state.phase == "QUESTION_FORMATION":
            formation_artifacts = ["theme", "expectations", "harness-contract", "constitution", *map_artifacts]
            # A registered Seed is deliberately selected so the Context
            # Builder records it as forbidden, never as accessible input.
            if self._seed_registered():
                formation_artifacts.insert(2, "rq-seed")
            return NextRunPlan(
                "INDEPENDENT_QUESTION_CANDIDATES", "QUESTION_FORMATION",
                "Generate independent Question Candidates without the provisional Seed",
                formation_artifacts,
                {"theme", "expectations", "harness-contract", "constitution"},
            )
        current = state.current_question_snapshot_id
        if not current or current not in ids:
            raise OrchestratorError("current Research State snapshot is not registered")
        if state.phase == "SEED_COMPARISON":
            return NextRunPlan(
                "SEED_COMPARISON", "SEED_COMPARISON", "Compare the independent candidates with the quarantined Seed",
                [current, "rq-seed", "theme", "harness-contract", "constitution", *map_artifacts], {current, "rq-seed"},
            )
        if state.phase in {"RESEARCH_PLANNING", "METHOD_PROTOCOL_PLANNING"}:
            planning_artifacts = [current, "theme", "expectations", "harness-contract", "constitution", *map_artifacts]
            if self._seed_registered():
                planning_artifacts.insert(2, "rq-seed")
            return NextRunPlan(
                "DESKTOP_RESEARCH_PREPARATION", "RESEARCH_PLANNING", "Prepare a bounded Desktop Research protocol",
                planning_artifacts,
                {current, "harness-contract", "constitution"},
            )
        if state.phase == "DESKTOP_RESEARCH":
            if not state.approved_protocol_decision_id:
                raise OrchestratorError("Desktop Research requires an approved protocol Decision")
            return NextRunPlan(
                "DESKTOP_RESEARCH", "DESKTOP_RESEARCH", "Execute bounded Desktop Research for the approved Question Baseline",
                [current, "theme", "expectations", "harness-contract", "constitution", *map_artifacts, "desktop-research-contract", "desktop-research-source-policy"],
                {current, "constitution", "desktop-research-contract", "desktop-research-source-policy"},
            )
        raise OrchestratorError(f"unknown orchestrator phase {state.phase!r}")

    def continue_until_stop(self, *, run_limit: int = 10) -> OrchestratorState:
        if run_limit < 1:
            raise ValueError("run_limit must be at least 1")
        with self._discovery_transition_lock():
            return self._continue_until_stop_locked(run_limit=run_limit)

    def _continue_until_stop_locked(self, *, run_limit: int) -> OrchestratorState:
        for _ in range(run_limit):
            state = self.status()
            if state.pending_decision_ids or state.pending_work or state.terminal:
                return state
            plan = self.plan()
            if plan is None:
                return state
            self._execute(plan)
        return self.status()

    def record_decision(self, decision_id: str, *, choice: str, decided_by: str, conditions: list[str] | None = None, rationale: str | None = None) -> OrchestratorState:
        self._ensure_active(self.status())
        request = self.decisions.load_request(
            DecisionRequest.model_validate(self.store.read_json(Path("decisions") / decision_id / "request.json"))
        )
        record = DecisionRecord(
            decision_id=decision_id, choice=choice, conditions=conditions or [], rationale=rationale, decided_by=decided_by,
            decision_kind=request.decision_kind,
        )
        if request.decision_kind is DecisionKind.LEGACY_UNCLASSIFIED:
            raise OrchestratorError(
                "legacy Decision Request has no typed decision_kind; run the one-time decision-kind migration first"
            )
        if request.decision_kind is DecisionKind.PUBLICATION_ELIGIBILITY:
            return self._record_publication_eligibility_decision(request, record)
        resumed = self.decisions.record(self.status(), request, record, snapshot_id=self._id("orchestrator"))
        if request.decision_kind is DecisionKind.ATTENTION_MAP_ADOPTION:
            return self._apply_attention_map_decision(resumed, request, record)
        if request.decision_kind is DecisionKind.QUESTION_BASELINE and choice == "ADOPT_PROPOSED_BASELINES":
            resumed = self._commit_question_baseline(resumed, request, decision_id)
        if request.decision_kind is DecisionKind.METHOD_PROTOCOL and choice == "APPROVE":
            resumed = self._link_protocol_decision(resumed, decision_id)
        return resumed

    def attach_prior_seed(self, seed: Path) -> OrchestratorState:
        """Register a prior Seed before independent Work is collected.

        The independent Context Pack is immutable once prepared. Registering
        the Seed only updates the artifact registry; collection then observes
        the registration and schedules a separate comparison Context Pack.
        """
        with self._discovery_transition_lock():
            state = self.status()
            self._ensure_active(state)
            if self._seed_registered():
                raise OrchestratorError("a PRIOR_SEED is already registered")
            if state.phase != "QUESTION_FORMATION":
                raise OrchestratorError(
                    "a PRIOR_SEED may be attached only before independent Question Formation completes"
                )
            if state.pending_decision_ids:
                raise OrchestratorError("cannot attach a PRIOR_SEED while a Human Decision is pending")
            if state.pending_work is not None and state.pending_work.expected_output_schema != "IndependentQuestionFormationHandoff":
                raise OrchestratorError("a PRIOR_SEED may be attached only while independent Question Formation Work is pending")
            record = self._record("rq-seed", seed, "PRIOR_SEED", Lane.RESEARCH)
            registry = self._registry()
            self.store.write_head("registry/artifact_registry.json", ArtifactRegistry(artifacts=[*registry.artifacts, record]))
            return state

    def _prepare_provenance_audit_locked(
        self,
        state: OrchestratorState,
        plan_path: Path,
        *,
        discarded_run_id: str | None = None,
    ) -> OrchestratorState:
        plan_path = plan_path.resolve()
        plan = ProvenanceAuditPlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
        baseline_path = Path(plan.baseline_snapshot.path)
        if not baseline_path.is_absolute():
            baseline_path = self.workspace / baseline_path
        baseline_path = baseline_path.resolve()
        if not baseline_path.is_file():
            raise OrchestratorError(f"PROVENANCE_AUDIT baseline does not exist: {baseline_path}")
        if sha256_file(baseline_path) != plan.baseline_snapshot.sha256:
            raise HashMismatch(
                f"PROVENANCE_AUDIT baseline changed: expected {plan.baseline_snapshot.sha256}, "
                f"got {sha256_file(baseline_path)}"
            )
        baseline = ResearchState.model_validate_json(baseline_path.read_text(encoding="utf-8"))
        if baseline.state_id != plan.baseline_snapshot.state_id:
            raise OrchestratorError("PROVENANCE_AUDIT baseline state_id does not match the plan")

        registry = self._registry()
        registrations = [
            ("provenance-audit-plan", plan_path, "INTAKE_SOURCE", Lane.IMPLEMENTATION),
            ("provenance-baseline", baseline_path, "RESEARCH_STATE", Lane.RESEARCH),
            ("runtime-artifact-policy", self.workspace / "contracts" / "runtime_artifact_policy.yaml", "ACTIVE_CONTRACT", Lane.CONTROL_PLANE),
            ("desktop-research-evidence-schema", self.workspace / "contracts" / "capabilities" / "desktop-research" / "evidence_capture.schema.yaml", "ACTIVE_CONTRACT", Lane.CONTROL_PLANE),
            ("provenance-audit-contract", self.workspace / "contracts" / "capabilities" / "desktop-research" / "provenance_audit_contract.md", "ACTIVE_CONTRACT", Lane.IMPLEMENTATION),
        ]
        updated_artifacts = list(registry.artifacts)
        for artifact_id, path, role, lane in registrations:
            record = self._record(artifact_id, path, role, lane)
            existing = next((item for item in updated_artifacts if item.artifact_id == artifact_id), None)
            if existing is None:
                updated_artifacts.append(record)
            elif existing.path != record.path or existing.sha256 != record.sha256 or existing.role != record.role:
                raise OrchestratorError(f"registered PROVENANCE_AUDIT input {artifact_id!r} changed")
        if len(updated_artifacts) != len(registry.artifacts):
            self.store.write_head("registry/artifact_registry.json", ArtifactRegistry(artifacts=updated_artifacts))

        run_id = plan.proposed_run_id
        if (self.runtime / "runs" / run_id).exists() or (self.runtime / "work_exchange" / run_id).exists():
            run_id = self._id("run-provenance-audit")
        pack_id = plan.proposed_context_pack_id
        if (self.runtime / "context_packs" / pack_id).exists():
            pack_id = self._id("pack-provenance-audit")
        artifact_ids = [
            "provenance-audit-plan", "provenance-baseline", "harness-contract", "constitution",
            "desktop-research-contract", "desktop-research-source-policy", "runtime-artifact-policy",
            "desktop-research-evidence-schema", "provenance-audit-contract",
        ]
        required_ids = {
            "provenance-audit-plan", "provenance-baseline", "desktop-research-evidence-schema",
            "provenance-audit-contract", "desktop-research-source-policy",
        }
        pack = self.builder.build(
            pack_id=pack_id,
            run_id=run_id,
            event="PROVENANCE_AUDIT",
            lane=Lane.IMPLEMENTATION,
            registry=ArtifactRegistry(artifacts=updated_artifacts),
            artifact_ids=artifact_ids,
            required_ids=required_ids,
            extra_forbidden_context=plan.forbidden_context,
        )
        context_manifest = self._context_manifest(pack)
        manifest = RunManifest(
            run_id=run_id,
            task_id=self._id("task-provenance-audit"),
            task_type="PROVENANCE_AUDIT",
            objective=plan.objective,
            event="PROVENANCE_AUDIT",
            lane=Lane.IMPLEMENTATION,
            context_pack_id=pack_id,
            input_refs=[*context_manifest.must_include, *context_manifest.retrieve_on_demand],
            forbidden_context=plan.forbidden_context,
            retrieval_policy=[ref.artifact_id for ref in context_manifest.retrieve_on_demand],
            output_schema="ProvenanceAuditHandoff",
            stop_conditions=[
                "Every target Evidence ID is resolved as verified 0.2 Evidence or explicit UNRESOLVED_GAP",
                "No baseline Research State or semantic Evidence field is changed",
            ],
            worker_backend="interactive-work",
            audit_policy=[
                "Validate the closed-world target partition and baseline semantic preservation",
                "Validate UTF-8 snapshot, SHA-256, excerpt-locator pairs, and path confinement",
            ],
            decision_context=["This event does not select a research method or grant Publication eligibility"],
        )
        self.store.create_run_dir(run_id)
        self.store.write_immutable(Path("runs") / run_id / "manifest.json", manifest)
        exchange = self.runtime / "work_exchange" / run_id
        request = InteractiveWorkProvenanceBoundary().prepare(pack, context_manifest, manifest, exchange)
        self.store.write_immutable(Path("runs") / run_id / "work_execution_required.json", request)
        waiting = state.model_copy(update={
            "state_id": self._id("orchestrator"),
            "execution_state": "WORK_EXECUTION_REQUIRED",
            "pending_work": request,
            "provenance_audit_plan_path": str(plan_path),
            "provenance_audit_run_ids": [
                *state.provenance_audit_run_ids,
                *([discarded_run_id] if discarded_run_id else []),
            ],
            "prior_snapshot_id": state.state_id,
        })
        self.store.snapshot("orchestrator", waiting.state_id, waiting)
        self.store.write_head("state/orchestrator/head.json", waiting)
        return waiting

    def _execute(self, plan: NextRunPlan) -> None:
        state = self.status()
        self._ensure_active(state)
        run_id = self._id("run")
        pack_id = self._id("pack")
        registry = self._registry()
        desktop_spec = self._desktop_research_spec() if plan.event == "DESKTOP_RESEARCH" else None
        lane = Lane.CONTROL_PLANE if plan.event == "ATTENTION_DISTILLATION" else Lane.RESEARCH
        pack = self.builder.build(
            pack_id=pack_id, run_id=run_id, event=plan.event, lane=lane,
            registry=registry, artifact_ids=plan.artifact_ids, required_ids=plan.required_ids,
            desktop_research_spec=desktop_spec,
        )
        context_manifest = self._context_manifest(pack)
        manifest = RunManifest(
            run_id=run_id, task_id=self._id("task"), task_type=plan.task_type, objective=plan.objective,
            event=plan.event, lane=lane, context_pack_id=pack_id,
            input_refs=[*context_manifest.must_include, *context_manifest.retrieve_on_demand],
            forbidden_context=context_manifest.forbidden_context,
            retrieval_policy=[ref.artifact_id for ref in context_manifest.retrieve_on_demand],
            output_schema={
                "INDEPENDENT_QUESTION_CANDIDATES": "IndependentQuestionFormationHandoff",
                "SEED_COMPARISON": "SeedComparisonHandoff",
                "DESKTOP_RESEARCH": "DesktopResearchHandoff",
                "ATTENTION_MAP_DISTILLATION": "AttentionDistillationHandoff",
            }.get(plan.task_type, "WorkerResult"),
            worker_backend=state.worker_backend,
        )
        if state.worker_backend == "interactive-work" and plan.task_type in {
            "INDEPENDENT_QUESTION_CANDIDATES", "SEED_COMPARISON", "DESKTOP_RESEARCH_PREPARATION", "DESKTOP_RESEARCH", "ATTENTION_MAP_DISTILLATION",
        }:
            self.store.create_run_dir(run_id)
            self.store.write_immutable(Path("runs") / run_id / "manifest.json", manifest)
            exchange = self.runtime / "work_exchange" / run_id
            if plan.task_type == "DESKTOP_RESEARCH":
                request = InteractiveWorkResearchBoundary().prepare(pack, context_manifest, manifest, exchange)
            elif plan.task_type == "ATTENTION_MAP_DISTILLATION":
                request = InteractiveWorkAttentionBoundary().prepare(pack, context_manifest, manifest, exchange)
            else:
                request = InteractiveWorkDiscoveryBoundary().prepare(pack, context_manifest, manifest, exchange)
            self.store.write_immutable(Path("runs") / run_id / "work_execution_required.json", request)
            waiting = state.model_copy(update={
                "state_id": self._id("orchestrator"),
                "execution_state": "WORK_EXECUTION_REQUIRED",
                "pending_work": request,
                "prior_snapshot_id": state.state_id,
            })
            self.store.snapshot("orchestrator", waiting.state_id, waiting)
            self.store.write_head("state/orchestrator/head.json", waiting)
            return
        if plan.task_type == "ATTENTION_MAP_DISTILLATION":
            self.store.create_run_dir(run_id)
            self.store.write_immutable(Path("runs") / run_id / "manifest.json", manifest)
            handoff = self._mock_attention_distillation_handoff(run_id, context_manifest, state)
            self._complete_attention_distillation(plan, run_id, handoff, context_manifest, state)
            self.store.write_immutable(
                Path("runs") / run_id / "completion.json",
                {"run_id": run_id, "status": "COMPLETED", "attempt": 1},
            )
            return
        if plan.task_type == "DESKTOP_RESEARCH":
            self.store.create_run_dir(run_id)
            self.store.write_immutable(Path("runs") / run_id / "manifest.json", manifest)
            handoff = self._mock_desktop_handoff(run_id, context_manifest)
            self._complete_desktop_run(plan, run_id, handoff, context_manifest, state)
            self.store.write_immutable(
                Path("runs") / run_id / "completion.json",
                {"run_id": run_id, "status": "COMPLETED", "attempt": 1},
            )
            return
        current = next((item for item in plan.artifact_ids if item.startswith("research-")), None)
        result_template = discovery_mock_result(plan.task_type, run_id, current_snapshot_id=current)
        execution = self.run_manager.execute(manifest, pack, MockWorkerAdapter(result_template))
        if not execution.succeeded or execution.result is None:
            raise OrchestratorError(execution.error or "worker failed")
        self._complete_run(plan, run_id, execution.result, context_manifest, state)

    def collect_work_result(self, run_id: str, result_path: Path, *, run_limit: int = 10) -> OrchestratorState:
        with self._discovery_transition_lock():
            return self._collect_work_result_locked(run_id, result_path, run_limit=run_limit)

    def _collect_work_result_locked(self, run_id: str, result_path: Path, *, run_limit: int = 10) -> OrchestratorState:
        from misco_harness.recovery import LateRunResultRejected, RecoveryService

        try:
            RecoveryService(self.workspace).reject_late_result(run_id)
        except LateRunResultRejected as error:
            raise OrchestratorError(str(error)) from error
        state = self.status()
        self._ensure_active(state)
        request = state.pending_work
        if state.execution_state != "WORK_EXECUTION_REQUIRED" or request is None:
            raise OrchestratorError("no interactive Work execution is pending")
        if request.run_id != run_id:
            raise OrchestratorError(f"pending Work run is {request.run_id!r}, not {run_id!r}")
        if request.context_pack_sha256 is None:
            raise HashMismatch("pending Work request has no frozen Context Pack tree hash")
        actual_pack_digest = sha256_tree(Path(request.context_pack))
        if actual_pack_digest != request.context_pack_sha256:
            raise HashMismatch(
                f"Context Pack tree hash mismatch: expected {request.context_pack_sha256}, got {actual_pack_digest}"
            )
        manifest = RunManifest.model_validate(self.store.read_json(Path("runs") / run_id / "manifest.json"))
        context_pack = Path(request.context_pack)
        context_manifest = self._context_manifest(context_pack)
        plan = NextRunPlan(manifest.task_type, manifest.event, manifest.objective, [], set())
        if manifest.task_type == "ATTENTION_MAP_DISTILLATION":
            try:
                handoff = InteractiveWorkAttentionBoundary().collect(request, result_path)
                self.run_manager.validate_context_pack(manifest, context_pack)
                drop_artifact_ids = {
                    item.artifact_id
                    for item in self._registry().artifacts
                    if item.artifact_id.startswith(f"{handoff.drop_id}-")
                }
                audit = audit_attention_distillation_handoff(
                    handoff,
                    context_manifest,
                    drop_artifact_ids=drop_artifact_ids,
                )
            except (OSError, ValueError, RuntimeError) as error:
                self._record_failed_submission_error(run_id, result_path, error)
                raise ReductionBlocked("Attention Distillation submission validation failed; pending Work run remains active") from error
            if not audit.passed:
                self._record_failed_submission(run_id, handoff, audit)
                raise ReductionBlocked("Attention Distillation audit failed; pending Work run remains active")
            self._complete_attention_distillation(plan, run_id, handoff, context_manifest, state, audit=audit)
            self.store.write_immutable(
                Path("runs") / run_id / "completion.json",
                {"run_id": run_id, "status": "COMPLETED", "attempt": manifest.attempt},
            )
            return self.continue_until_stop(run_limit=run_limit)
        if manifest.task_type == "PROVENANCE_AUDIT":
            try:
                handoff = InteractiveWorkProvenanceBoundary().collect(request, result_path)
                plan_path = Path(state.provenance_audit_plan_path or "")
                repair_plan = ProvenanceAuditPlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
                baseline_path = Path(repair_plan.baseline_snapshot.path)
                if not baseline_path.is_absolute():
                    baseline_path = self.workspace / baseline_path
                baseline_path = baseline_path.resolve()
                if sha256_file(baseline_path) != repair_plan.baseline_snapshot.sha256:
                    raise HashMismatch("PROVENANCE_AUDIT baseline changed while Work was executing")
                baseline = ResearchState.model_validate_json(baseline_path.read_text(encoding="utf-8"))
                audit = audit_provenance_audit_handoff(
                    handoff,
                    repair_plan,
                    baseline,
                    context_manifest,
                    Path(request.exchange_directory) / "evidence_snapshots",
                )
            except (OSError, ValueError, RuntimeError) as error:
                self._record_failed_submission_error(run_id, result_path, error)
                raise ReductionBlocked("PROVENANCE_AUDIT submission validation failed; pending Work run remains active") from error
            if not audit.passed:
                self._record_failed_submission(run_id, handoff, audit)
                raise ReductionBlocked("PROVENANCE_AUDIT audit failed; pending Work run remains active")
            try:
                if handoff.source_captures or handoff.evidence_citations:
                    canonical = self._materialize_provenance_source_captures(
                        handoff,
                        run_id,
                        Path(request.exchange_directory) / "source_captures",
                    )
                else:
                    canonical = self._materialize_provenance_snapshots(
                        handoff,
                        run_id,
                        Path(request.exchange_directory) / "evidence_snapshots",
                    )
            except (OSError, TraceStoreError, DesktopEvidenceSnapshotError) as error:
                self._record_failed_submission_error(run_id, result_path, error)
                raise ReductionBlocked("PROVENANCE_AUDIT snapshot materialization failed; pending Work run remains active") from error
            self._complete_provenance_audit(plan, run_id, canonical, audit, state)
            return self.continue_until_stop(run_limit=run_limit)
        if manifest.task_type == "DESKTOP_RESEARCH":
            try:
                handoff = InteractiveWorkResearchBoundary().collect(request, result_path)
            except DesktopEvidenceSnapshotError as error:
                self._record_failed_submission_error(run_id, result_path, error)
                raise ReductionBlocked("Desktop Research snapshot validation failed; pending Work run remains active") from error
            self.run_manager.validate_context_pack(manifest, context_pack)
            audit = self._audit_desktop_handoff(handoff, context_manifest)
            if not audit.passed:
                self._record_failed_submission(run_id, handoff, audit)
                raise ReductionBlocked("Desktop Research audit failed; pending Work run remains active")
            try:
                if handoff.source_captures or handoff.evidence_citations:
                    canonical = self._materialize_source_captures(
                        handoff,
                        run_id,
                        Path(request.exchange_directory) / "source_captures",
                    )
                else:
                    canonical = self._materialize_desktop_snapshots(
                        handoff,
                        run_id,
                        Path(request.exchange_directory) / "evidence_snapshots",
                    )
            except (DesktopEvidenceSnapshotError, OSError, TraceStoreError) as error:
                self._record_failed_submission_error(run_id, result_path, error)
                raise ReductionBlocked("Desktop Research snapshot materialization failed; pending Work run remains active") from error
            self._complete_desktop_run(plan, run_id, canonical, context_manifest, state, audit=audit)
            self.store.write_immutable(
                Path("runs") / run_id / "completion.json",
                {"run_id": run_id, "status": "COMPLETED", "attempt": manifest.attempt},
            )
        else:
            result = InteractiveWorkDiscoveryBoundary().collect(request, result_path)
            audit = audit_worker_result(result, context_manifest)
            if not audit.passed:
                self._record_failed_submission(run_id, result, audit)
                raise ReductionBlocked("Work result audit failed; pending Work run remains active")
            execution = self.run_manager.collect(manifest, context_pack, result)
            self._complete_run(plan, run_id, execution.result, context_manifest, state)
        return self.continue_until_stop(run_limit=run_limit)

    def _complete_run(
        self,
        plan: NextRunPlan,
        run_id: str,
        result: WorkerResult,
        context_manifest,
        state: OrchestratorState,
    ) -> None:
        with self._discovery_transition_lock():
            self._complete_run_locked(plan, run_id, result, context_manifest, state)

    def _complete_run_locked(
        self,
        plan: NextRunPlan,
        run_id: str,
        result: WorkerResult,
        context_manifest,
        state: OrchestratorState,
    ) -> None:
        audit = audit_worker_result(result, context_manifest)
        self.store.write_immutable(Path("runs") / run_id / "audit.json", audit)
        proposal, handoff = reduce_worker_result(result, audit)
        self.store.write_immutable(Path("runs") / run_id / "state_delta_proposal.json", proposal)
        self.store.write_immutable(Path("runs") / run_id / "research_handoff.json", handoff)
        research = self._research_state()
        snapshot_id = self._id("research")
        updated_research = research.model_copy(update={
            "state_id": snapshot_id,
            "candidate_outputs": [*research.candidate_outputs, {
                "task_type": plan.task_type, "run_id": run_id,
                "observed": result.observed,
                "interpreted": result.interpreted,
                "question_delta_candidate": result.question_delta_candidate,
                "question_overlaps": result.question_overlaps,
                "evidence_gap_hypotheses": result.evidence_gap_hypotheses,
            }],
            "counterevidence": [*research.counterevidence, *result.counterevidence],
            "unknowns": [*research.unknowns, *result.unknown],
            "scope_limits": [*research.scope_limits, *result.scope_limits],
            "question_overlaps": [*research.question_overlaps, *result.question_overlaps],
            "evidence_gap_hypotheses": [*research.evidence_gap_hypotheses, *result.evidence_gap_hypotheses],
            # Publication eligibility is SNAPSHOT_ONLY and never inherits to
            # a later Research State.
            "publication_eligibility": None,
            "prior_snapshot_id": research.state_id,
        })
        snapshot_path = self.store.snapshot("research", snapshot_id, updated_research)
        self.store.write_head("state/research/head.json", updated_research)
        self._register_snapshot(snapshot_id, snapshot_path)
        seed_registered = self._seed_registered()
        next_phase = {
            "INDEPENDENT_QUESTION_CANDIDATES": "SEED_COMPARISON" if seed_registered else "QUESTION_REVIEW",
            "SEED_COMPARISON": "QUESTION_REVIEW",
            "DESKTOP_RESEARCH_PREPARATION": "METHOD_REVIEW",
        }[plan.task_type]
        next_state = state.model_copy(update={
            "state_id": self._id("orchestrator"), "phase": next_phase,
            "completed_steps": [*state.completed_steps, plan.task_type],
            "run_refs": [*state.run_refs, run_id][-20:], "total_run_count": state.total_run_count + 1,
            "current_question_snapshot_id": snapshot_id,
            "execution_state": "READY", "pending_work": None,
            "prior_snapshot_id": state.state_id,
        })
        self.store.snapshot("orchestrator", next_state.state_id, next_state)
        self.store.write_head("state/orchestrator/head.json", next_state)
        if plan.task_type == "SEED_COMPARISON" or (
            plan.task_type == "INDEPENDENT_QUESTION_CANDIDATES" and not seed_registered
        ):
            request = self._question_decision(run_id, result)
            self.decisions.block(next_state, request, snapshot_id=self._id("orchestrator"))
        elif plan.task_type == "DESKTOP_RESEARCH_PREPARATION":
            request = self._method_decision(run_id)
            self.decisions.block(next_state, request, snapshot_id=self._id("orchestrator"))

    def _complete_provenance_audit(
        self,
        plan: NextRunPlan,
        run_id: str,
        handoff: ProvenanceAuditHandoff,
        audit,
        state: OrchestratorState,
    ) -> None:
        """Persist a verified repair without mutating Research State."""
        self.store.write_immutable(Path("runs") / run_id / "audit.json", audit)
        self.store.write_immutable(Path("runs") / run_id / "repair_audit.json", audit)
        self.store.write_immutable(Path("runs") / run_id / "provenance_audit_handoff.json", handoff)
        self.store.write_immutable(Path("runs") / run_id / "repair_result.json", handoff)
        self.store.write_immutable(
            Path("runs") / run_id / "completion.json",
            {"run_id": run_id, "status": "COMPLETED", "attempt": 1},
        )
        updated = state.model_copy(update={
            "state_id": self._id("orchestrator"),
            "completed_steps": [*state.completed_steps, plan.task_type],
            "run_refs": [*state.run_refs, run_id][-20:],
            "provenance_audit_run_ids": [*state.provenance_audit_run_ids, run_id][-20:],
            "execution_state": "READY",
            "pending_work": None,
            "prior_snapshot_id": state.state_id,
        })
        self.store.snapshot("orchestrator", updated.state_id, updated)
        self.store.write_head("state/orchestrator/head.json", updated)

    def _complete_attention_distillation(
        self,
        plan: NextRunPlan,
        run_id: str,
        handoff: AttentionDistillationHandoff,
        context_manifest,
        state: OrchestratorState,
        *,
        audit: AuditResult | None = None,
    ) -> None:
        """Persist a candidate Map and stop at the Human adoption boundary."""
        drop_artifact_ids = set(self._drop_artifact_ids(handoff.drop_id))
        audit = audit or audit_attention_distillation_handoff(
            handoff,
            context_manifest,
            drop_artifact_ids=drop_artifact_ids,
        )
        self.store.write_immutable(Path("runs") / run_id / "audit.json", audit)
        self.store.write_immutable(Path("runs") / run_id / "attention_distillation_handoff.json", handoff)
        candidate_path = self.store.write_immutable_text(
            Path("runs") / run_id / "attention_map_candidate.md",
            handoff.candidate_map_markdown,
        )
        candidate_artifact_id = f"attention-candidate-{run_id}"
        registry = self._registry()
        if not any(item.artifact_id == candidate_artifact_id for item in registry.artifacts):
            candidate_record = ArtifactRecord(
                artifact_id=candidate_artifact_id,
                path=str(candidate_path.resolve()),
                sha256=sha256_file(candidate_path),
                role="ATTENTION_MAP_CANDIDATE",
                authority="WORK_DISTILLED_CANDIDATE",
                lane=Lane.CONTROL_PLANE,
                runtime_policy=self.builder.policy.runtime_policy_for_role("ATTENTION_MAP_CANDIDATE"),
            )
            self.store.write_head(
                "registry/artifact_registry.json",
                ArtifactRegistry(artifacts=[*registry.artifacts, candidate_record]),
            )
        updated = state.model_copy(update={
            "state_id": self._id("orchestrator"),
            "completed_steps": [*state.completed_steps, plan.task_type],
            "run_refs": [*state.run_refs, run_id][-20:],
            "attention_map_run_ids": [*state.attention_map_run_ids, run_id][-20:],
            "pending_attention_drop_ids": [
                item for item in state.pending_attention_drop_ids if item != handoff.drop_id
            ],
            "total_run_count": state.total_run_count + 1,
            "execution_state": "READY",
            "pending_work": None,
            "prior_snapshot_id": state.state_id,
        })
        self.store.snapshot("orchestrator", updated.state_id, updated)
        self.store.write_head("state/orchestrator/head.json", updated)
        request = self._attention_map_decision(handoff, phase=state.phase)
        self.decisions.block(updated, request, snapshot_id=self._id("orchestrator"))

    def _attention_map_decision(self, handoff: AttentionDistillationHandoff, *, phase: str) -> DecisionRequest:
        return DecisionRequest(
            decision_id=self._id("decision-attention-map"),
            decision_kind=DecisionKind.ATTENTION_MAP_ADOPTION,
            request="Review the Work-distilled candidate Attention Map and choose whether to adopt it",
            status_scope="A registered Attention drop was distilled into a non-authoritative candidate; Research meaning is unchanged",
            ai_recommendation="Treat the candidate as routing guidance only and inspect conflicts, uncertainty, exclusions, and back-references before choosing",
            evidence=[item.model_dump(mode="json") for item in handoff.items],
            counterevidence=handoff.conflicts,
            unknowns=handoff.unknowns,
            options=[
                {"id": "ADOPT_CANDIDATE_MAP", "label": "Adopt candidate as a new immutable Map version"},
                {"id": "KEEP_CURRENT_MAP", "label": "Keep the current Map, if any"},
                {"id": "REQUEST_REVISION", "label": "Request another distillation pass for this drop"},
            ],
            downstream_impact=[
                "Adoption changes only the active routing Map pointer and Publication guidance input",
                "The candidate cannot become Evidence, a method, a Question Baseline, a Finding, or an answer",
            ],
            becomes_fixed=["The Human choice and any conditions", "The active Attention Map version when adoption is selected"],
            human_questions=["Which option should be recorded?", "What conditions or rationale apply?"],
            resume_plan={
                "next_phase": phase,
                "candidate_run_id": handoff.run_id,
                "drop_id": handoff.drop_id,
            },
            references=[handoff.run_id, handoff.drop_id, *handoff.back_references],
        )

    def _apply_attention_map_decision(
        self,
        state: OrchestratorState,
        request: DecisionRequest,
        record: DecisionRecord,
    ) -> OrchestratorState:
        run_id = str(request.resume_plan.get("candidate_run_id", ""))
        drop_id = str(request.resume_plan.get("drop_id", ""))
        if not run_id or not drop_id:
            raise OrchestratorError("Attention Map adoption Decision is missing its candidate run or drop reference")
        handoff_path = self.runtime / "runs" / run_id / "attention_distillation_handoff.json"
        if not handoff_path.is_file():
            raise OrchestratorError("Attention Map adoption candidate Handoff is missing")
        handoff = AttentionDistillationHandoff.model_validate_json(handoff_path.read_text(encoding="utf-8"))
        if handoff.drop_id != drop_id or handoff.run_id != run_id:
            raise OrchestratorError("Attention Map adoption Decision references a different candidate")
        registry = self._registry()
        updated_records = list(registry.artifacts)
        current_map = self._active_attention_artifact(state)
        active_map_id = current_map.artifact_id if current_map is not None else None
        if record.choice == "ADOPT_CANDIDATE_MAP":
            map_id = self._id("attention-map")
            map_path = self.store.write_immutable_text(
                Path("attention") / "maps" / f"{map_id}.md",
                handoff.candidate_map_markdown,
            )
            if active_map_id:
                updated_records = [
                    item.model_copy(update={"status": "SUPERSEDED", "superseded_by": map_id})
                    if item.artifact_id == active_map_id else item
                    for item in updated_records
                ]
            map_record = ArtifactRecord(
                artifact_id=map_id,
                path=str(map_path.resolve()),
                sha256=sha256_file(map_path),
                role="ATTENTION_PUBLICATION_MAP",
                authority="HUMAN_APPROVED_GUIDANCE",
                lane=Lane.CONTROL_PLANE,
                runtime_policy=self.builder.policy.runtime_policy_for_role("ATTENTION_PUBLICATION_MAP"),
                may_shape_questions=True,
                supersedes=[active_map_id] if active_map_id else [],
            )
            updated_records.append(map_record)
            active_map_id = map_id
        elif record.choice == "REQUEST_REVISION":
            if drop_id in state.pending_attention_drop_ids:
                raise OrchestratorError("Attention drop is already pending for revision")
        elif record.choice != "KEEP_CURRENT_MAP":
            raise OrchestratorError(f"unsupported Attention Map adoption choice: {record.choice!r}")
        candidate_id = f"attention-candidate-{run_id}"
        updated_records = [
            item.model_copy(update={"status": "ADOPTED"}) if item.artifact_id == candidate_id and record.choice == "ADOPT_CANDIDATE_MAP" else item
            for item in updated_records
        ]
        if updated_records != registry.artifacts:
            self.store.write_head("registry/artifact_registry.json", ArtifactRegistry(artifacts=updated_records))
        final_state = state.model_copy(update={
            "state_id": self._id("orchestrator"),
            "active_attention_map_id": active_map_id,
            "pending_attention_drop_ids": [*state.pending_attention_drop_ids, drop_id]
            if record.choice == "REQUEST_REVISION" else state.pending_attention_drop_ids,
            "prior_snapshot_id": state.state_id,
        })
        self.store.snapshot("orchestrator", final_state.state_id, final_state)
        self.store.write_head("state/orchestrator/head.json", final_state)
        return final_state

    def _mock_attention_distillation_handoff(
        self,
        run_id: str,
        context_manifest,
        state: OrchestratorState,
    ) -> AttentionDistillationHandoff:
        if not state.pending_attention_drop_ids:
            raise OrchestratorError("mock Attention Distillation has no pending drop")
        drop_id = state.pending_attention_drop_ids[0]
        drop_artifact_ids = self._drop_artifact_ids(drop_id)
        active_map = self._active_attention_artifact(state)
        item = AttentionMapCandidateItem(
            attention_id="attention-review-candidate",
            title="Human review of registered Attention intake",
            statement=f"Review the registered material in {drop_id} as routing guidance only.",
            operation="ADD",
            source_refs=drop_artifact_ids,
            uncertainty=["Mock Work does not interpret the source material."],
        )
        markdown = (
            "# Candidate Attention Map\n\n"
            f"- Review the registered material in `{drop_id}` as routing guidance only.\n"
            "- This candidate is not Evidence and does not select a method or answer.\n"
        )
        return AttentionDistillationHandoff(
            run_id=run_id,
            drop_id=drop_id,
            basis_attention_map_id=active_map.artifact_id if active_map is not None else None,
            used_artifact_ids=drop_artifact_ids,
            items=[item],
            candidate_map_markdown=markdown,
            candidate_map_sha256=hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
            conflicts=[],
            unknowns=["Mock Work did not inspect or interpret the drop content."],
            back_references=drop_artifact_ids,
        )

    def _complete_desktop_run(
        self,
        plan: NextRunPlan,
        run_id: str,
        handoff: DesktopResearchHandoff,
        context_manifest,
        state: OrchestratorState,
        *,
        audit=None,
    ) -> None:
        if handoff.source_captures or handoff.evidence_citations:
            validate_source_capture_exchange(
                handoff,
                WorkExecutionRequest(
                    run_id=run_id,
                    context_pack=".",
                    manifest=".",
                    task_file=".",
                    exchange_directory=str((self.runtime / "runs" / run_id).resolve()),
                    expected_output_schema="DesktopResearchHandoff",
                    expected_output_schema_file=".",
                    expected_output_file=".",
                ),
            )
        else:
            validate_desktop_snapshot_directory(
                handoff,
                self.runtime / "runs" / run_id / "evidence_snapshots",
            )
        audit = audit or self._audit_desktop_handoff(handoff, context_manifest)
        self.store.write_immutable(Path("runs") / run_id / "audit.json", audit)
        self.store.write_immutable(Path("runs") / run_id / "desktop_research_handoff.json", handoff)
        proposal, preserved = reduce_desktop_research_handoff(handoff, audit)
        self.store.write_immutable(Path("runs") / run_id / "state_delta_proposal.json", proposal)
        self.store.write_immutable(Path("runs") / run_id / "research_handoff.json", preserved)
        research = self._research_state()
        snapshot_id = self._id("research")
        updated = research.model_copy(update={
            "state_id": snapshot_id,
            "evidence": [*research.evidence, *[item.model_dump(mode="json") for item in handoff.evidence]],
            "source_captures": [*research.source_captures, *[item.model_dump(mode="json") for item in handoff.source_captures]],
            "evidence_citations": [*research.evidence_citations, *[item.model_dump(mode="json") for item in handoff.evidence_citations]],
            "findings": [*research.findings, *[item.model_dump(mode="json") for item in handoff.findings]],
            "counterevidence": [*research.counterevidence, *handoff.counterevidence],
            "unknowns": [*research.unknowns, *handoff.unknowns],
            "evidence_gaps": [*research.evidence_gaps, *[item.model_dump(mode="json") for item in handoff.evidence_gaps]],
            "publication_eligibility": None,
            "prior_snapshot_id": research.state_id,
        })
        snapshot_path = self.store.snapshot("research", snapshot_id, updated)
        self.store.write_head("state/research/head.json", updated)
        self._register_snapshot(snapshot_id, snapshot_path)
        next_state = state.model_copy(update={
            "state_id": self._id("orchestrator"), "phase": "DESKTOP_RESEARCH_REVIEW",
            "completed_steps": [*state.completed_steps, plan.task_type],
            "run_refs": [*state.run_refs, run_id][-20:], "total_run_count": state.total_run_count + 1,
            "current_question_snapshot_id": snapshot_id,
            "execution_state": "READY", "pending_work": None,
            "prior_snapshot_id": state.state_id,
        })
        self.store.snapshot("orchestrator", next_state.state_id, next_state)
        self.store.write_head("state/orchestrator/head.json", next_state)
        request = method_selection_request(handoff, decision_id=self._id("decision-research"))
        request = request.model_copy(update={
            "request": "Review Desktop Research results and select the next research action",
            "references": [run_id, *handoff.back_references],
        })
        self.decisions.block(next_state, request, snapshot_id=self._id("orchestrator"))

    def _materialize_provenance_snapshots(
        self,
        handoff: ProvenanceAuditHandoff,
        run_id: str,
        exchange_snapshot_root: Path,
    ) -> ProvenanceAuditHandoff:
        return self._materialize_snapshots_common(
            handoff,
            run_id,
            exchange_snapshot_root,
            label="PROVENANCE_AUDIT",
            validator=validate_provenance_snapshot_directory,
        )

    def _materialize_provenance_source_captures(
        self,
        handoff: ProvenanceAuditHandoff,
        run_id: str,
        exchange_capture_root: Path,
    ) -> ProvenanceAuditHandoff:
        return self._materialize_source_captures_common(handoff, run_id, exchange_capture_root, label="PROVENANCE_AUDIT")

    def _audit_desktop_handoff(self, handoff: DesktopResearchHandoff, context_manifest):
        allowed = {ref.artifact_id for ref in context_manifest.must_include + context_manifest.retrieve_on_demand}
        registry = {item.artifact_id: item for item in self._registry().artifacts}
        forbidden_roles = set()
        if context_manifest.desktop_research_spec:
            forbidden_roles.update(context_manifest.desktop_research_spec.forbidden_roles)
            forbidden_roles.update(self.builder.policy.denied_roles("DESKTOP_RESEARCH"))
        forbidden = set(context_manifest.forbidden_context)
        forbidden.update(item.artifact_id for item in registry.values() if item.role in forbidden_roles)
        declared_source_ids = {
            item.source_id for item in handoff.evidence
        } | {
            item.source_id for item in handoff.source_captures
        }
        for source_id in declared_source_ids:
            registered = registry.get(source_id)
            if registered is None:
                # External source identities are allowed only as data; they do
                # not become registered Harness artifacts by being declared.
                allowed.add(source_id)
                continue
            decision = self.builder.policy.resolve(registered, "DESKTOP_RESEARCH").decision
            if registered.role in forbidden_roles or decision not in {
                RuntimePolicyValue.INCLUDE,
                RuntimePolicyValue.RETRIEVE,
            } or source_id not in allowed:
                forbidden.add(source_id)
        allowed_source_types = (
            set(context_manifest.desktop_research_spec.allowed_source_types)
            if context_manifest.desktop_research_spec else None
        )
        return audit_desktop_research_handoff(
            handoff,
            allowed_back_references=allowed,
            forbidden_back_references=forbidden,
            allowed_source_types=allowed_source_types,
        )

    def _record_failed_submission(self, run_id: str, result, audit) -> None:
        submission_id = self._id("submission")
        self.store.write_immutable(
            Path("runs") / run_id / "submissions" / f"{submission_id}.json",
            {
                "submission_id": submission_id,
                "run_id": run_id,
                "status": "AUDIT_FAILED",
                "result": result.model_dump(mode="json"),
                "audit": audit.model_dump(mode="json"),
            },
        )

    def _record_failed_submission_error(self, run_id: str, result_path: Path, error: Exception) -> None:
        submission_id = self._id("submission")
        self.store.write_immutable(
            Path("runs") / run_id / "submissions" / f"{submission_id}.json",
            {
                "submission_id": submission_id,
                "run_id": run_id,
                "status": "SUBMISSION_REJECTED",
                "result_path": str(result_path.resolve()),
                "error": f"{type(error).__name__}: {error}",
            },
        )

    def _materialize_desktop_snapshots(
        self,
        handoff: DesktopResearchHandoff,
        run_id: str,
        exchange_snapshot_root: Path,
    ) -> DesktopResearchHandoff:
        return self._materialize_snapshots_common(
            handoff,
            run_id,
            exchange_snapshot_root,
            label="Desktop Research",
            validator=validate_desktop_snapshot_directory,
        )

    def _materialize_source_captures(
        self,
        handoff: DesktopResearchHandoff,
        run_id: str,
        exchange_capture_root: Path,
    ) -> DesktopResearchHandoff:
        """Copy each SourceCapture once through the shared lane-neutral path."""
        return self._materialize_source_captures_common(handoff, run_id, exchange_capture_root, label="Desktop Research")

    def _materialize_snapshots_common(
        self,
        handoff,
        run_id: str,
        exchange_snapshot_root: Path,
        *,
        label: str,
        validator,
    ):
        exchange_root = exchange_snapshot_root.resolve()
        runs_root = (self.runtime / "runs").resolve()
        run_dir = runs_root / run_id
        if run_dir.is_symlink() or not run_dir.is_dir() or run_dir.resolve().parent != runs_root:
            raise DesktopEvidenceSnapshotError(f"{label} run directory is not a regular Harness run: {run_dir}")
        destination_root = run_dir / "evidence_snapshots"
        if destination_root.exists() and destination_root.is_symlink():
            raise DesktopEvidenceSnapshotError(f"{label} destination is a symbolic link: {destination_root}")
        destination_root.mkdir(parents=True, exist_ok=True)
        if destination_root.resolve().parent != run_dir.resolve():
            raise DesktopEvidenceSnapshotError(f"{label} destination escapes its run directory: {destination_root}")
        canonical = []
        created: list[Path] = []
        try:
            for evidence in handoff.evidence:
                raw_source = Path(evidence.snapshot_path)
                if raw_source.is_symlink():
                    raise DesktopEvidenceSnapshotError(f"{label} snapshot source is a symbolic link: {raw_source}")
                source = raw_source.resolve()
                if source.parent != exchange_root or not source.is_file():
                    raise DesktopEvidenceSnapshotError(f"{label} snapshot source is outside the Work exchange: {source}")
                destination = destination_root / f"{evidence.evidence_id}.txt"
                if destination.exists():
                    if destination.is_symlink() or sha256_file(destination) != evidence.snapshot_sha256:
                        raise DesktopEvidenceSnapshotError(f"immutable {label} snapshot differs: {destination}")
                else:
                    self.store.copy_immutable_file(
                        source,
                        Path("runs") / run_id / "evidence_snapshots" / f"{evidence.evidence_id}.txt",
                    )
                    created.append(destination)
                canonical.append(evidence.model_copy(update={"snapshot_path": str(destination.resolve())}))
            normalized = handoff.model_copy(update={"evidence": canonical})
            validator(normalized, destination_root)
            return normalized
        except Exception:
            for path in created:
                path.unlink(missing_ok=True)
            raise

    def _materialize_source_captures_common(self, handoff, run_id: str, exchange_capture_root: Path, *, label: str):
        exchange_root = exchange_capture_root.resolve()
        runs_root = (self.runtime / "runs").resolve()
        run_dir = runs_root / run_id
        if run_dir.is_symlink() or not run_dir.is_dir() or run_dir.resolve().parent != runs_root:
            raise DesktopEvidenceSnapshotError(f"{label} run directory is not a regular Harness run: {run_dir}")
        destination_root = run_dir / "source_captures"
        if destination_root.exists() and destination_root.is_symlink():
            raise DesktopEvidenceSnapshotError(f"{label} SourceCapture destination is a symbolic link: {destination_root}")
        destination_root.mkdir(parents=True, exist_ok=True)
        created: list[Path] = []
        captures = []
        try:
            for capture in handoff.source_captures:
                raw_source_dir = exchange_root / capture.capture_id
                if raw_source_dir.is_symlink():
                    raise DesktopEvidenceSnapshotError(f"{label} SourceCapture directory is a symbolic link: {raw_source_dir}")
                source_dir = raw_source_dir.resolve()
                if source_dir.parent != exchange_root or not source_dir.is_dir():
                    raise DesktopEvidenceSnapshotError(f"{label} SourceCapture directory is invalid: {source_dir}")
                raw_original = Path(capture.original_path)
                raw_text_path = Path(capture.text_snapshot_path)
                if raw_original.is_symlink() or raw_text_path.is_symlink():
                    raise DesktopEvidenceSnapshotError(f"{label} SourceCapture artifacts must not be symbolic links: {capture.capture_id}")
                original = raw_original.resolve()
                text_path = raw_text_path.resolve()
                if original != source_dir / "original" or text_path != source_dir / "text.txt":
                    raise DesktopEvidenceSnapshotError(f"{label} SourceCapture paths are not canonical: {capture.capture_id}")
                destination_dir = destination_root / capture.capture_id
                for source, destination, expected_hash in (
                    (original, destination_dir / "original", capture.original_sha256),
                    (text_path, destination_dir / "text.txt", capture.text_snapshot_sha256),
                ):
                    if destination.exists():
                        if destination.is_symlink() or sha256_file(destination) != expected_hash:
                            raise DesktopEvidenceSnapshotError(f"immutable {label} SourceCapture differs: {destination}")
                    else:
                        self.store.copy_immutable_file(
                            source,
                            Path("runs") / run_id / "source_captures" / capture.capture_id / destination.name,
                        )
                        created.append(destination)
                captures.append(capture.model_copy(update={
                    "original_path": str((destination_dir / "original").resolve()),
                    "text_snapshot_path": str((destination_dir / "text.txt").resolve()),
                }))
            normalized = handoff.model_copy(update={"source_captures": captures})
            validate_source_capture_exchange(
                normalized,
                WorkExecutionRequest(
                    run_id=run_id,
                    context_pack=".",
                    manifest=".",
                    task_file=".",
                    exchange_directory=str(destination_root.parent.resolve()),
                    expected_output_schema=(
                        "ProvenanceAuditHandoff" if isinstance(handoff, ProvenanceAuditHandoff) else "DesktopResearchHandoff"
                    ),
                    expected_output_schema_file=".",
                    expected_output_file=".",
                ),
            )
            return normalized
        except Exception:
            for path in created:
                path.unlink(missing_ok=True)
            raise

    def _desktop_research_spec(self) -> DesktopResearchContextSpec:
        questions = self._research_state().questions
        if not questions:
            raise OrchestratorError("Desktop Research requires an adopted Question Baseline")
        inputs = [QuestionInput(
            question_id=item.question_id, text=item.text, status=item.status,
            authoritative=True, decision_id=item.decision_id,
        ) for item in questions if item.status in {"BASELINE", "REVISED"}]
        if not inputs:
            raise OrchestratorError("Desktop Research requires a Human-approved Question Baseline")
        return DesktopResearchContextSpec(
            question=inputs[0], questions=inputs,
            allowed_source_types=[
                SourceType.PEER_REVIEWED_RESEARCH, SourceType.GOVERNMENT_PRIMARY,
                SourceType.STANDARDS_BODY, SourceType.COMPANY_PRIMARY,
                SourceType.INDEPENDENT_ANALYSIS, SourceType.NEWS_REPORTING,
                SourceType.WORKING_PAPER, SourceType.PREPRINT,
                SourceType.INDUSTRY_REPORT, SourceType.CORPORATE_PUBLICATION,
                SourceType.SOCIAL_MEDIA, SourceType.ONLINE_FORUM, SourceType.OTHER,
            ],
            retrieval_scope=["human-selected Work research capability within the approved source policy"],
            forbidden_roles=[],
            coverage_dimensions=["definitions", "support", "counterevidence", "limitations", "scope", "evidence_gaps"],
            research_brief=ResearchBrief(
                research_objective="Answer the Human-approved Questions with traceable, bounded evidence.",
                approved_questions=[item.text for item in inputs],
                claim_types_to_test=[
                    ClaimType.DEFINITIONAL,
                    ClaimType.DESCRIPTIVE_TREND,
                    ClaimType.INDEPENDENT_EFFECT,
                    ClaimType.CAUSAL_EFFECT,
                ],
                study_role_requirements={
                    ClaimType.DESCRIPTIVE_TREND.value: [
                        StudyRole.SYSTEMATIC_REVIEW,
                        StudyRole.SCOPING_REVIEW,
                        StudyRole.NARRATIVE_REVIEW,
                        StudyRole.PRIMARY_RESEARCH,
                    ],
                    ClaimType.INDEPENDENT_EFFECT.value: [
                        StudyRole.PRIMARY_RESEARCH,
                        StudyRole.META_ANALYSIS,
                    ],
                    ClaimType.CAUSAL_EFFECT.value: [
                        StudyRole.PRIMARY_RESEARCH,
                        StudyRole.META_ANALYSIS,
                    ],
                },
                source_role_requirements={
                    "material_claim": [SourceType.PEER_REVIEWED_RESEARCH, SourceType.GOVERNMENT_PRIMARY],
                },
                inclusion_criteria=["The source must address an approved Question or a declared Evidence Gap."],
                exclusion_criteria=["Do not infer a claim beyond the source's population, design, period, or scope."],
                counterevidence_requirements=["Search for counterevidence, nulls, conflicts, and limitations before recommending stop."],
                capture_requirements=["Capture the source once, preserve the original and UTF-8 full-text rendition, then create citations."],
                coverage_requirements=["Report study-role coverage, source independence, overlap, and transferability."],
                stopping_conditions=["Do not recommend stopping while a material Evidence Gap remains or remaining information value is HIGH."],
                prohibited_inferences=[
                    "A review is not an independent copy of every included primary study.",
                    "Narrative or scoping reviews do not independently establish causal or effectiveness claims.",
                ],
            ),
        )

    def _mock_desktop_handoff(self, run_id: str, context_manifest) -> DesktopResearchHandoff:
        source_id = "mock-source-1"
        snapshot_text = "Mock evidence for deterministic tests"
        snapshot_path = self.store.write_immutable_text(
            Path("runs") / run_id / "evidence_snapshots" / "mock-evidence-1.txt",
            snapshot_text,
        )
        return DesktopResearchHandoff(
            run_id=run_id,
            question_impact=QuestionImpact(status="HUMAN_DECISION_REQUIRED", rationale="Mock evidence cannot settle Question scope"),
            findings=[FindingRecord(finding_id="mock-finding-1", statement="Mock candidate finding", evidence_ids=["mock-evidence-1"])],
            evidence=[DesktopResearchEvidence(
                evidence_id="mock-evidence-1", source_id=source_id, source_type=SourceType.PEER_REVIEWED_RESEARCH,
                source_quality=SourceQuality.HIGH,
                locator="mock locator", captured_statement="Mock evidence for deterministic tests",
                acquired_at=utc_now(), text_snapshot=snapshot_text, snapshot_path=str(snapshot_path.resolve()),
                snapshot_sha256=sha256_file(snapshot_path),
                excerpt_locator_pairs=[EvidenceExcerpt(excerpt=snapshot_text, locator="mock locator")],
                evidence_kind=EvidenceKind.SUPPORTING, support_scope=SupportScope.DESCRIPTIVE_CONTEXT,
            )],
            counterevidence=["Mock counterevidence"],
            counterevidence_search_summary="Deterministic mock counterevidence path exercised",
            unknowns=["Real source coverage not performed"],
            evidence_gaps=[EvidenceGap(gap_id="mock-gap-1", description="Real Desktop Research remains unperformed", material=True)],
            candidate_next_method_options=[NextMethodOption(
                option_id="HOLD", method="HOLD", rationale="Do not infer a real method from mock output", addresses_gap_ids=["mock-gap-1"],
            )],
            coverage=CoverageStoppingAssessment(
                dimensions=[CoverageDimension(dimension="mock", status="GAP", rationale="Deterministic test only")],
                saturation="LOW", unresolved_material_evidence_gap_ids=["mock-gap-1"],
                remaining_information_value=RemainingInformationValue.HIGH, stop_recommended=False,
                stopping_rationale="Mock mode cannot recommend research stopping", stopping_basis=["COVERAGE"],
            ),
            back_references=[source_id], publication_eligibility=PublicationEligibility(status="NOT_ELIGIBLE"),
        )

    def _question_decision(self, run_id: str, result: WorkerResult) -> DecisionRequest:
        proposals = self._proposed_baselines(result)
        return DecisionRequest(
            decision_id=self._id("decision-question"), decision_kind=DecisionKind.QUESTION_BASELINE,
            request="Select the Question Baseline",
            status_scope=(
                "Independent Question Candidates and Seed comparison are complete"
                if self._seed_registered()
                else "Independent Question Candidates are complete; no prior Seed was registered"
            ),
            ai_recommendation="Review the proposed baseline set without treating ordering as authority",
            evidence=[item.model_dump(mode="json") for item in proposals],
            counterevidence=result.counterevidence, unknowns=result.unknown,
            options=[{"id": "ADOPT_PROPOSED_BASELINES", "label": "Adopt proposed baseline set"}, {"id": "REVISE", "label": "Request revision"}],
            downstream_impact=["Desktop Research preparation may start"], becomes_fixed=["Question Baseline"],
            human_questions=["Choice", "Conditions", "Rationale"],
            resume_plan={"by_choice": {
                "ADOPT_PROPOSED_BASELINES": {"next_phase": "RESEARCH_PLANNING", "next_task": "DESKTOP_RESEARCH_PREPARATION"},
                "REVISE": {
                    "next_phase": "SEED_COMPARISON" if self._seed_registered() else "QUESTION_FORMATION",
                    "next_task": "SEED_COMPARISON" if self._seed_registered() else "INDEPENDENT_QUESTION_CANDIDATES",
                },
            }}, references=[run_id], proposed_question_baselines=proposals,
        )

    def _publication_eligibility_decision(self, research_state_id: str) -> DecisionRequest:
        return DecisionRequest(
            decision_id=self._id("decision-publication-eligibility"),
            decision_kind=DecisionKind.PUBLICATION_ELIGIBILITY,
            request="Approve or decline Publication use of the current Research State snapshot",
            status_scope="The current Research State remains provisional and Research may continue independently",
            ai_recommendation="Treat this as a Publication Lane access decision only; it does not approve claims or stabilize the manuscript",
            evidence=[{"research_state_id": research_state_id, "publication_use": "current snapshot only"}],
            counterevidence=["Publication eligibility does not validate Evidence or Findings"],
            unknowns=["Later Research snapshots may supersede this Publication source"],
            options=[
                {"id": "ALLOW_PUBLICATION", "label": "Allow provisional Publication use"},
                {"id": "DECLINE_PUBLICATION", "label": "Decline provisional Publication use"},
            ],
            downstream_impact=[
                "ALLOW_PUBLICATION permits Publication refresh from this snapshot while Research continues",
                "The decision does not select a Research method or change the Research Question",
            ],
            becomes_fixed=["Publication eligibility for this Research State snapshot"],
            human_questions=["Whether this current Research State may be used for provisional Publication"],
            resume_plan={"by_choice": {
                "ALLOW_PUBLICATION": {"next_phase": "CURRENT_RESEARCH_PHASE"},
                "DECLINE_PUBLICATION": {"next_phase": "CURRENT_RESEARCH_PHASE"},
            }},
            references=[research_state_id],
        )

    def _record_publication_eligibility_decision(
        self,
        request: DecisionRequest,
        record: DecisionRecord,
    ) -> OrchestratorState:
        with self._discovery_transition_lock(), self._publication_transition_lock():
            research = self._research_state()
            if request.decision_kind is not DecisionKind.PUBLICATION_ELIGIBILITY:
                raise OrchestratorError("Decision Request is not a Publication Eligibility request")
            if len(request.references) != 1 or request.references[0] != research.state_id:
                raise OrchestratorError(
                    "Publication eligibility request is stale; the reviewed Research State is no longer the head"
                )
            publication = self.publication_state()
            research_snapshot_id = self._id("research")
            eligibility = PublicationEligibility(
                status="ELIGIBLE" if record.choice == "ALLOW_PUBLICATION" else "NOT_ELIGIBLE",
                approved_by=record.decided_by,
                decision_id=record.decision_id,
                scope="SNAPSHOT_ONLY",
                reviewed_research_state_id=research.state_id,
                recorded_research_state_id=research_snapshot_id,
            )
            resumed_publication = self.decisions.record_publication(
                publication,
                request,
                record,
                snapshot_id=self._id("publication"),
            )
            updated_research = research.model_copy(update={
                "state_id": research_snapshot_id,
                "publication_eligibility": eligibility,
                "prior_snapshot_id": research.state_id,
            })
            snapshot_path = self.store.snapshot("research", research_snapshot_id, updated_research)
            self.store.write_head("state/research/head.json", updated_research)
            self._register_snapshot(research_snapshot_id, snapshot_path)
            updated_publication = resumed_publication.model_copy(update={
                "state_id": self._id("publication"),
                "status": "SCAFFOLD",
                "pending_feedback_ids": [],
                "publication_eligibility": eligibility,
                "source_research_state_id": updated_research.state_id,
                "structure": None,
                "draft": None,
                "prior_snapshot_id": resumed_publication.state_id,
            })
            self.store.snapshot("publication", updated_publication.state_id, updated_publication)
            self.store.write_head("state/publication/head.json", updated_publication)
            return self.status()

    @staticmethod
    def _proposed_baselines(result: WorkerResult) -> list[ProposedQuestionBaseline]:
        """Normalize discovery output into typed Human Decision proposals.

        Interactive Question Formation carries rich candidate records in its
        observed output while the generic WorkerResult delta is intentionally
        small. Merge both representations and retain handoff-level
        uncertainty, scope, overlap, and Evidence Gap information.
        """
        observed = [item for item in result.observed if isinstance(item, dict) and item.get("question")]
        raw = [item for item in result.question_delta_candidate if isinstance(item, dict) and item.get("question")]
        if not raw:
            raw = observed
        identity_by_item: dict[str, dict] = {}
        for item in observed:
            identity = item.get("proposal_id") or item.get("candidate_id")
            if not identity:
                continue
            identity = str(identity)
            if identity in identity_by_item:
                raise OrchestratorError(f"Question Candidate identity is duplicated: {identity!r}")
            identity_by_item[identity] = item
        proposals: list[ProposedQuestionBaseline] = []
        seen_ids: set[str] = set()
        for item in raw:
            identity = item.get("proposal_id") or item.get("candidate_id")
            if not identity:
                raise OrchestratorError("Question Candidate is missing a stable proposal_id or candidate_id")
            identity = str(identity)
            if identity in seen_ids:
                raise OrchestratorError(f"Question Candidate identity is duplicated: {identity!r}")
            seen_ids.add(identity)
            merged = dict(item)
            observed_item = identity_by_item.get(identity)
            if observed_item is not None:
                for key, value in observed_item.items():
                    if key not in merged or merged[key] in (None, "", []):
                        merged[key] = value
            proposals.append(ProposedQuestionBaseline(
                proposal_id=identity,
                question=str(merged["question"]),
                rationale=str(merged.get("rationale") or merged.get("reason") or "Independent Question Candidate supplied by Work"),
                uncertainty=list(merged.get("uncertainty") or result.unknown),
                scope_limits=list(merged.get("scope_limits") or result.scope_limits),
                overlaps=list(merged.get("overlaps") or result.question_overlaps),
                evidence_gap_hypotheses=list(merged.get("evidence_gap_hypotheses") or result.evidence_gap_hypotheses),
            ))
        if not proposals:
            raise OrchestratorError("Question Decision has no proposed question candidates")
        return proposals

    def _method_decision(self, run_id: str) -> DecisionRequest:
        return DecisionRequest(
            decision_id=self._id("decision-method"), decision_kind=DecisionKind.METHOD_PROTOCOL,
            request="Approve or revise the Desktop Research protocol",
            status_scope="Desktop Research preparation is complete; no external research was performed",
            ai_recommendation="Approve the bounded protocol", evidence=["Prepared retrieval and source plan"],
            counterevidence=["Source coverage has not been executed"], unknowns=["Final database availability"],
            options=[{"id": "APPROVE", "label": "Approve protocol"}, {"id": "REVISE", "label": "Request revision"}],
            downstream_impact=["A later Research Run may begin"], becomes_fixed=["Desktop Research protocol"],
            human_questions=["Choice", "Conditions", "Rationale"],
            resume_plan={"by_choice": {
                "APPROVE": {"next_phase": "DESKTOP_RESEARCH", "next_task": "DESKTOP_RESEARCH"},
                "REVISE": {"next_phase": "RESEARCH_PLANNING", "next_task": "DESKTOP_RESEARCH_PREPARATION"},
            }}, references=[run_id],
        )

    def _commit_question_baseline(self, state: OrchestratorState, request: DecisionRequest, decision_id: str) -> OrchestratorState:
        research = self._research_state()
        snapshot_id = self._id("research")
        if not request.proposed_question_baselines:
            raise OrchestratorError("Question Decision has no typed proposed baselines")
        baselines = [QuestionRecord(
            question_id=item.proposal_id, text=item.question, status="BASELINE",
            uncertainty=item.uncertainty, scope_limits=item.scope_limits, overlaps=item.overlaps,
            evidence_gap_hypotheses=[gap.model_dump(mode="json") for gap in item.evidence_gap_hypotheses],
            delta_reasons=[item.rationale], decision_id=decision_id,
        ) for item in request.proposed_question_baselines]
        updated = research.model_copy(update={
            "state_id": snapshot_id,
            "questions": [*research.questions, *baselines],
            "prior_snapshot_id": research.state_id,
        })
        path = self.store.snapshot("research", snapshot_id, updated)
        self.store.write_head("state/research/head.json", updated)
        self._register_snapshot(snapshot_id, path)
        orchestrator_id = self._id("orchestrator")
        linked = state.model_copy(update={
            "state_id": orchestrator_id,
            "current_question_snapshot_id": snapshot_id,
            "prior_snapshot_id": state.state_id,
        })
        self.store.snapshot("orchestrator", orchestrator_id, linked)
        self.store.write_head("state/orchestrator/head.json", linked)
        return linked

    def _link_protocol_decision(self, state: OrchestratorState, decision_id: str) -> OrchestratorState:
        linked = state.model_copy(update={
            "state_id": self._id("orchestrator"), "approved_protocol_decision_id": decision_id,
            "prior_snapshot_id": state.state_id,
        })
        self.store.snapshot("orchestrator", linked.state_id, linked)
        self.store.write_head("state/orchestrator/head.json", linked)
        return linked

    @staticmethod
    def _ensure_active(state: OrchestratorState) -> None:
        if state.lifecycle_status == "ARCHIVED":
            raise OrchestratorError("workspace is archived; state-changing research operations are disabled")

    def _active_attention_artifact(self, state: OrchestratorState | None = None) -> ArtifactRecord | None:
        current = state or self.status()
        explicit_pointer = current.active_attention_map_id is not None
        active_id = current.active_attention_map_id or "attention-map"
        artifact = next(
            (item for item in self._registry().artifacts if item.artifact_id == active_id),
            None,
        )
        if artifact is None:
            if explicit_pointer:
                raise OrchestratorError("active Attention Map pointer references an unknown artifact")
            return None
        if artifact.status in {"INVALIDATED", "SUPERSEDED"}:
            raise OrchestratorError("active Attention Map is missing or superseded")
        return artifact

    def _drop_artifact_ids(self, drop_id: str) -> list[str]:
        prefix = f"{drop_id}-"
        return [item.artifact_id for item in self._registry().artifacts if item.artifact_id.startswith(prefix)]

    def _registry(self) -> ArtifactRegistry:
        return ArtifactRegistry.model_validate(self.store.read_json("registry/artifact_registry.json"))

    def _seed_registered(self) -> bool:
        return any(item.artifact_id == "rq-seed" and item.role == "PRIOR_SEED" for item in self._registry().artifacts)

    @contextmanager
    def _discovery_transition_lock(self) -> Iterator[None]:
        """Serialize the complete discovery transition, including nested calls."""
        with self._transition_lock("discovery-transition"):
            yield

    @contextmanager
    def _publication_transition_lock(self) -> Iterator[None]:
        """Serialize Publication snapshots independently of Research runs."""
        with self._transition_lock("publication-transition"):
            yield

    @contextmanager
    def _transition_lock(self, name: str) -> Iterator[None]:
        lock_path = (self.runtime / "locks" / f"{name}.lock").resolve()
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self._held_transition_locks_guard:
            held = self._held_transition_locks.get(lock_path)
            if held is not None:
                token, depth = held
                self._held_transition_locks[lock_path] = (token, depth + 1)
            else:
                token = uuid.uuid4().hex
                payload = json.dumps({
                    "lock_name": name,
                    "owner_token": token,
                    "pid": os.getpid(),
                    "acquired_at": datetime.now(UTC).isoformat(),
                }, sort_keys=True).encode("utf-8")
                try:
                    descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                    with os.fdopen(descriptor, "wb") as stream:
                        stream.write(payload)
                        stream.flush()
                        os.fsync(stream.fileno())
                except FileExistsError as exc:
                    owner = self._read_transition_lock(lock_path)
                    detail = f" owner_token={owner.get('owner_token')}" if owner else ""
                    raise OrchestratorError(
                        f"another {name} transition is in progress; inspect or explicitly release the lock.{detail}"
                    ) from exc
                self._held_transition_locks[lock_path] = (token, 1)
        try:
            yield
        finally:
            with self._held_transition_locks_guard:
                current = self._held_transition_locks.get(lock_path)
                if current is None or current[0] != token:
                    pass
                elif current[1] > 1:
                    self._held_transition_locks[lock_path] = (token, current[1] - 1)
                else:
                    self._held_transition_locks.pop(lock_path, None)
                    owner = self._read_transition_lock(lock_path)
                    if owner.get("owner_token") == token:
                        lock_path.unlink(missing_ok=True)

    def transition_lock_status(self) -> dict[str, object]:
        locks: dict[str, object] = {}
        for name in ("discovery-transition", "publication-transition"):
            path = (self.runtime / "locks" / f"{name}.lock").resolve()
            owner = self._read_transition_lock(path)
            if owner:
                locks[name] = {"status": "HELD", **owner}
            elif path.exists():
                locks[name] = {"status": "INVALID_LOCK", "path": str(path)}
            else:
                locks[name] = {"status": "FREE"}
        return {"locks": locks, "reclaim_policy": "EXPLICIT_OPERATOR_RELEASE_ONLY"}

    def release_transition_lock(
        self,
        name: str,
        *,
        actor: str,
        reason: str,
        owner_token: str | None = None,
    ) -> dict[str, object]:
        if name not in {"discovery-transition", "publication-transition"}:
            raise OrchestratorError(f"unknown transition lock: {name!r}")
        if not actor.strip() or not reason.strip():
            raise OrchestratorError("lock release requires a non-empty actor and reason")
        path = (self.runtime / "locks" / f"{name}.lock").resolve()
        with self._held_transition_locks_guard:
            if path in self._held_transition_locks:
                raise OrchestratorError("cannot release a lock held by this process")
            current = self._read_transition_lock(path)
            if not current:
                if path.exists():
                    raise OrchestratorError("transition lock metadata is invalid; preserve it for manual investigation")
                return {"status": "FREE", "lock_name": name}
            if owner_token is not None and current.get("owner_token") != owner_token:
                raise OrchestratorError("lock owner token does not match the current lock")
            release_id = self._id("lock-release")
            self.store.write_immutable(
                Path("locks") / "releases" / f"{release_id}.json",
                {
                    "release_id": release_id,
                    "lock_name": name,
                    "owner": current,
                    "released_by": actor,
                    "reason": reason,
                    "released_at": datetime.now(UTC).isoformat(),
                },
            )
            latest = self._read_transition_lock(path)
            if latest.get("owner_token") != current.get("owner_token"):
                raise OrchestratorError("transition lock changed during explicit release; no lock was removed")
            path.unlink(missing_ok=True)
            return {"status": "RELEASED", "lock_name": name, "release_id": release_id}

    @staticmethod
    def _read_transition_lock(path: Path) -> dict[str, object]:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _research_state(self) -> ResearchState:
        return ResearchState.model_validate(self.store.read_json("state/research/head.json"))

    def _register_snapshot(self, snapshot_id: str, path: Path) -> None:
        registry = self._registry()
        record = self._record(snapshot_id, path, "RESEARCH_STATE", Lane.RESEARCH)
        self.store.write_head("registry/artifact_registry.json", ArtifactRegistry(artifacts=[*registry.artifacts, record]))

    @staticmethod
    def _context_manifest(pack: Path):

        from misco_harness.models import ContextPackManifest
        return ContextPackManifest.model_validate_json((pack / "manifest.json").read_text(encoding="utf-8"))

    def _record(self, artifact_id: str, path: Path, role: str, lane: Lane) -> ArtifactRecord:
        if not path.is_absolute():
            path = self.workspace / path
        resolved = path.resolve()
        if not resolved.is_file():
            raise OrchestratorError(f"required input does not exist: {resolved}")
        return ArtifactRecord(
            artifact_id=artifact_id, path=str(resolved), sha256=sha256_file(resolved),
            role=role, authority="EXPLICITLY_REGISTERED", lane=lane,
            runtime_policy=self.builder.policy.runtime_policy_for_role(role),
        )

    @staticmethod
    def _id(prefix: str) -> str:
        return f"{prefix}-{uuid.uuid4().hex[:12]}"
