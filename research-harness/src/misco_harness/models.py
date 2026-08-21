from __future__ import annotations

from datetime import UTC, datetime
import re
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = "0.1"
SAFE_IDENTIFIER_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"


def utc_now() -> datetime:
    return datetime.now(UTC)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = SCHEMA_VERSION


class Lane(StrEnum):
    CONTROL_PLANE = "CONTROL_PLANE"
    RESEARCH = "RESEARCH"
    PUBLICATION = "PUBLICATION"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    IMPLEMENTATION = "IMPLEMENTATION"


class DecisionKind(StrEnum):
    QUESTION_BASELINE = "QUESTION_BASELINE"
    METHOD_PROTOCOL = "METHOD_PROTOCOL"
    RESEARCH_ACTION = "RESEARCH_ACTION"
    PUBLICATION_ELIGIBILITY = "PUBLICATION_ELIGIBILITY"
    CONTRACT_MIGRATION = "CONTRACT_MIGRATION"
    ATTENTION_MAP_ADOPTION = "ATTENTION_MAP_ADOPTION"
    RECOVERY = "RECOVERY"
    GENERIC = "GENERIC"
    LEGACY_UNCLASSIFIED = "LEGACY_UNCLASSIFIED"


class RuntimePolicyValue(StrEnum):
    INCLUDE = "INCLUDE"
    RETRIEVE = "RETRIEVE"
    DENY = "DENY"
    HUMAN_ONLY = "HUMAN_ONLY"
    EXPLICIT_INCLUDE = "EXPLICIT_INCLUDE"


class ArtifactRecord(StrictModel):
    artifact_id: str
    path: str
    sha256: str | None = None
    role: str
    authority: str
    lane: Lane
    runtime_policy: dict[str, RuntimePolicyValue] = Field(default_factory=dict)
    evidence_eligible: bool = False
    may_shape_questions: bool = False
    may_determine_method: bool = False
    may_determine_answer: bool = False
    status: str = "ACTIVE"
    supersedes: list[str] = Field(default_factory=list)
    superseded_by: str | None = None
    mode: Literal["REAL", "VIRTUAL"] | None = None


class ArtifactRegistry(StrictModel):
    artifacts: list[ArtifactRecord] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_ids(self) -> ArtifactRegistry:
        ids = [item.artifact_id for item in self.artifacts]
        if len(ids) != len(set(ids)):
            raise ValueError("artifact_id values must be unique")
        return self


class RuntimeAccessDecision(StrictModel):
    artifact_id: str
    event: str
    decision: RuntimePolicyValue
    reason: str


class QuestionRecord(StrictModel):
    question_id: str
    text: str
    status: Literal["CANDIDATE", "PROPOSED", "BASELINE", "REVISED", "REJECTED"] = "CANDIDATE"
    uncertainty: list[Any] = Field(default_factory=list)
    scope_limits: list[Any] = Field(default_factory=list)
    overlaps: list[Any] = Field(default_factory=list)
    evidence_gap_hypotheses: list[Any] = Field(default_factory=list)
    delta_reasons: list[str] = Field(default_factory=list)
    decision_id: str | None = None

    @model_validator(mode="after")
    def semantic_status_requires_decision(self) -> QuestionRecord:
        if self.status in {"BASELINE", "REVISED", "REJECTED"} and not self.decision_id:
            raise ValueError(f"Question status {self.status} requires a Human Decision ID")
        return self


class PublicationEligibility(StrictModel):
    status: Literal["ELIGIBLE", "NOT_ELIGIBLE"]
    approved_by: str | None = None
    decision_id: str | None = None
    scope: str | None = None
    # ``reviewed_research_state_id`` is the immutable snapshot the Human
    # reviewed. ``recorded_research_state_id`` is the immutable Research
    # snapshot that carries this decision after recording. Keeping both is
    # required because recording the decision creates a new Research snapshot.
    reviewed_research_state_id: str | None = Field(default=None, pattern=SAFE_IDENTIFIER_PATTERN)
    recorded_research_state_id: str | None = Field(default=None, pattern=SAFE_IDENTIFIER_PATTERN)

    @model_validator(mode="after")
    def eligible_requires_approval(self) -> PublicationEligibility:
        if self.status == "ELIGIBLE" and (not self.approved_by or not self.decision_id):
            raise ValueError("Publication Eligibility requires Human approval and Decision ID")
        if self.status == "ELIGIBLE" and not self.is_snapshot_bound:
            raise ValueError(
                "Publication Eligibility requires reviewed and recorded Research State IDs"
            )
        return self

    @property
    def is_snapshot_bound(self) -> bool:
        return bool(self.reviewed_research_state_id and self.recorded_research_state_id)


class ResearchState(StrictModel):
    # 0.2 remains the default for legacy snapshots; migrated v0.3 snapshots
    # set this explicitly while preserving the immutable prior state.
    schema_version: str = "0.2"
    state_id: str
    questions: list[QuestionRecord] = Field(default_factory=list)
    candidate_outputs: list[dict[str, Any]] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    source_captures: list[dict[str, Any]] = Field(default_factory=list)
    evidence_citations: list[dict[str, Any]] = Field(default_factory=list)
    findings: list[dict[str, Any]] = Field(default_factory=list)
    counterevidence: list[Any] = Field(default_factory=list)
    unknowns: list[Any] = Field(default_factory=list)
    scope_limits: list[Any] = Field(default_factory=list)
    question_overlaps: list[Any] = Field(default_factory=list)
    evidence_gap_hypotheses: list[Any] = Field(default_factory=list)
    evidence_gaps: list[Any] = Field(default_factory=list)
    mode: Literal["REAL", "VIRTUAL"] | None = None
    publication_eligibility: PublicationEligibility | None = None
    prior_snapshot_id: str | None = None
    recovery_id: str | None = None
    recovery_baseline_state_id: str | None = None
    invalidated_lineage_ids: list[str] = Field(default_factory=list)
    recovery_uncertainty: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def mark_v03_evidence_state(self) -> ResearchState:
        if self.source_captures or self.evidence_citations:
            self.schema_version = "0.3"
        return self


class PublicationStructureNode(StrictModel):
    node_id: str = Field(min_length=1)
    kind: Literal["CHAPTER", "SECTION"]
    title: str = Field(min_length=1)
    parent_id: str | None = None
    position: int = Field(ge=0)
    attention_refs: list[str] = Field(default_factory=list)


class PublicationStructureChange(StrictModel):
    action: Literal["ADD", "REMOVE", "MERGE", "SPLIT", "MOVE", "RENAME"]
    node_ids: list[str] = Field(default_factory=list)
    node: PublicationStructureNode | None = None
    new_nodes: list[PublicationStructureNode] = Field(default_factory=list)
    target_node_id: str | None = None
    new_title: str | None = None
    new_parent_id: str | None = None

    @model_validator(mode="after")
    def validate_change_shape(self) -> PublicationStructureChange:
        if self.action == "ADD" and self.node is None:
            raise ValueError("ADD requires a node")
        if self.action in {"REMOVE", "MERGE", "SPLIT", "MOVE", "RENAME"} and not self.node_ids:
            raise ValueError(f"{self.action} requires node_ids")
        if self.action == "RENAME" and not self.new_title:
            raise ValueError("RENAME requires new_title")
        if self.action == "MERGE" and not self.target_node_id:
            raise ValueError("MERGE requires target_node_id")
        if self.action == "SPLIT" and not self.new_nodes:
            raise ValueError("SPLIT requires new_nodes")
        return self


class PublicationStructure(StrictModel):
    schema_version: str = "0.2"
    structure_id: str
    source_research_state_id: str
    source_attention_map_id: str | None = None
    authority: Literal["PROVISIONAL_READER_ORIENTED"] = "PROVISIONAL_READER_ORIENTED"
    revision: int = Field(default=0, ge=0)
    nodes: list[PublicationStructureNode] = Field(default_factory=list)
    changes: list[PublicationStructureChange] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_tree(self) -> PublicationStructure:
        by_id = {node.node_id: node for node in self.nodes}
        if len(by_id) != len(self.nodes):
            raise ValueError("Publication Structure node_id values must be unique")
        for node in self.nodes:
            if node.parent_id is not None and node.parent_id not in by_id:
                raise ValueError(f"Publication Structure parent {node.parent_id!r} is missing")
            if node.kind == "CHAPTER" and node.parent_id is not None:
                raise ValueError("CHAPTER nodes cannot have a parent")
            if node.kind == "SECTION" and node.parent_id is None:
                raise ValueError("SECTION nodes require a parent")
        for node in self.nodes:
            seen: set[str] = set()
            parent_id = node.parent_id
            while parent_id is not None:
                if parent_id in seen:
                    raise ValueError("Publication Structure cannot contain cycles")
                seen.add(parent_id)
                parent_id = by_id[parent_id].parent_id
        return self


class PublicationDraft(StrictModel):
    schema_version: str = "0.2"
    draft_id: str
    source_research_state_id: str
    structure_id: str
    status: Literal["PROVISIONAL", "REVISED", "INTEGRATED"] = "PROVISIONAL"
    sections: dict[str, str] = Field(default_factory=dict)
    evidence_eligible: Literal[False] = False
    research_state_mutation: Literal[False] = False


class PublicationState(StrictModel):
    schema_version: str = "0.2"
    state_id: str
    status: Literal[
        "SCAFFOLD", "PROVISIONAL", "REVISED", "INTEGRATED", "STABLE", "FINAL",
        "STALE", "REVIEW_REQUIRED", "REVOKED_PENDING_REVIEW",
    ] = "SCAFFOLD"
    pending_decision_ids: list[str] = Field(default_factory=list)
    pending_feedback_ids: list[str] = Field(default_factory=list)
    stable_decision_id: str | None = None
    final_decision_id: str | None = None
    source_research_state_id: str | None = None
    source_attention_map_id: str | None = None
    publication_eligibility: PublicationEligibility | None = None
    structure: PublicationStructure | None = None
    draft: PublicationDraft | None = None
    prior_snapshot_id: str | None = None

    @model_validator(mode="after")
    def release_status_requires_decision(self) -> PublicationState:
        if self.status in {"STABLE", "FINAL"} and not self.stable_decision_id:
            raise ValueError(f"Publication status {self.status} requires a Human STABLE decision")
        if self.status == "FINAL" and not self.final_decision_id:
            raise ValueError("Publication FINAL requires a Human FINAL decision")
        if self.structure is not None:
            if self.source_research_state_id and self.structure.source_research_state_id != self.source_research_state_id:
                raise ValueError("Publication Structure must reference the Publication State Research snapshot")
            if self.source_attention_map_id and self.structure.source_attention_map_id != self.source_attention_map_id:
                raise ValueError("Publication Structure must reference the Publication State Attention Map")
        if self.draft is not None:
            if self.structure is None or self.draft.structure_id != self.structure.structure_id:
                raise ValueError("Publication Draft must reference the current Publication Structure")
            if self.source_research_state_id and self.draft.source_research_state_id != self.source_research_state_id:
                raise ValueError("Publication Draft must reference the Publication State Research snapshot")
        return self


class DropFileRecord(StrictModel):
    relative_path: str
    stored_path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)


class DropBatchManifest(StrictModel):
    drop_id: str = Field(pattern=SAFE_IDENTIFIER_PATTERN)
    source_path: str
    registered_by: str = Field(min_length=1)
    files: list[DropFileRecord] = Field(default_factory=list)
    ignored_paths: list[str] = Field(default_factory=list)
    tree_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    registered_at: datetime = Field(default_factory=utc_now)


class AttentionMapCandidateItem(StrictModel):
    attention_id: str = Field(pattern=SAFE_IDENTIFIER_PATTERN)
    title: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    operation: Literal["ADD", "UPDATE", "KEEP", "MERGE", "REMOVE_CANDIDATE"]
    source_refs: list[str] = Field(default_factory=list)
    uncertainty: list[str] = Field(default_factory=list)
    proposed_publication_location: str | None = None


class AttentionDistillationHandoff(StrictModel):
    run_id: str = Field(pattern=SAFE_IDENTIFIER_PATTERN)
    drop_id: str = Field(pattern=SAFE_IDENTIFIER_PATTERN)
    basis_attention_map_id: str | None = None
    used_artifact_ids: list[str] = Field(default_factory=list)
    excluded_artifact_ids: list[str] = Field(default_factory=list)
    exclusion_reasons: dict[str, str] = Field(default_factory=dict)
    items: list[AttentionMapCandidateItem] = Field(default_factory=list)
    candidate_map_markdown: str = Field(min_length=1)
    candidate_map_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    conflicts: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    back_references: list[str] = Field(default_factory=list)
    evidence_eligible: Literal[False] = False
    may_determine_method: Literal[False] = False
    may_determine_answer: Literal[False] = False


class ArchiveManifest(StrictModel):
    archive_id: str = Field(pattern=SAFE_IDENTIFIER_PATTERN)
    source_workspace: str
    destination: str
    created_by: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    status: Literal["COMPLETE", "INCOMPLETE"]
    basis_orchestrator_state_id: str
    basis_orchestrator_state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    payload_tree_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_ids: list[str] = Field(default_factory=list)
    artifact_files: list[dict[str, str]] = Field(default_factory=list)
    run_count: int = Field(ge=0)
    context_pack_count: int = Field(ge=0)
    pending_work_run_id: str | None = None
    pending_decision_ids: list[str] = Field(default_factory=list)
    pending_attention_drop_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)


class WorkExecutionRequest(StrictModel):
    run_id: str = Field(pattern=SAFE_IDENTIFIER_PATTERN)
    status: Literal["WORK_EXECUTION_REQUIRED"] = "WORK_EXECUTION_REQUIRED"
    context_pack: str
    manifest: str
    context_pack_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    exchange_directory: str
    task_file: str
    expected_output_schema: Literal[
        "IndependentQuestionFormationHandoff",
        "SeedComparisonHandoff",
        "DesktopResearchHandoff",
        "ProvenanceAuditHandoff",
        "AttentionDistillationHandoff",
        "WorkerResult",
    ]
    expected_output_schema_file: str
    expected_output_file: str


class InteractiveWorkNextAction(StrictModel):
    """Control-plane response consumed by an Interactive Work coordinator.

    This model deliberately contains pointers and operational metadata only.
    It does not contain research conclusions or instructions that could grant
    Work authority over a semantic decision.
    """

    state: Literal[
        "WORK_EXECUTION_REQUIRED",
        "DECISION_REQUIRED",
        "COMPLETE",
        "ERROR",
        "BLOCKED",
    ]
    observed_state_id: str
    phase: str
    worker_backend: Literal["mock", "interactive-work"] | None = None
    message: str = ""
    run_id: str | None = None
    task_type: str | None = None
    context_pack: str | None = None
    task_file: str | None = None
    result_schema: str | None = None
    result_schema_file: str | None = None
    result_destination: str | None = None
    decision_id: str | None = None
    decision_packet: str | None = None
    decision_request: str | None = None
    decision_options: list[dict[str, Any]] = Field(default_factory=list)
    resume_instruction: str | None = None
    recovery: str | None = None


# Short aliases keep the client-facing interface discoverable without creating
# parallel models or state machines.
CoordinatorAction = InteractiveWorkNextAction
NextAction = InteractiveWorkNextAction


class CoordinatorTrace(StrictModel):
    """Operational trace for one coordinator observation or submission."""

    trace_id: str
    observed_state_id: str
    action_state: Literal[
        "WORK_EXECUTION_REQUIRED",
        "DECISION_REQUIRED",
        "COMPLETE",
        "ERROR",
        "BLOCKED",
    ]
    phase: str
    run_id: str | None = None
    task_file: str | None = None
    context_pack: str | None = None
    submitted_result: str | None = None
    submitted_run_id: str | None = None
    decision_id: str | None = None
    message: str = ""
    recorded_at: datetime = Field(default_factory=utc_now)


class OrchestratorState(StrictModel):
    state_id: str
    phase: str = "QUESTION_FORMATION"
    completed_steps: list[str] = Field(default_factory=list)
    pending_decision_ids: list[str] = Field(default_factory=list)
    run_refs: list[str] = Field(default_factory=list)
    total_run_count: int = 0
    current_question_snapshot_id: str | None = None
    terminal: bool = False
    worker_backend: Literal["mock", "interactive-work"] = "mock"
    execution_state: Literal["READY", "WORK_EXECUTION_REQUIRED"] = "READY"
    pending_work: WorkExecutionRequest | None = None
    approved_protocol_decision_id: str | None = None
    provenance_audit_plan_path: str | None = None
    provenance_audit_run_ids: list[str] = Field(default_factory=list)
    prior_snapshot_id: str | None = None
    lifecycle_status: Literal["ACTIVE", "ARCHIVED"] = "ACTIVE"
    active_attention_map_id: str | None = None
    pending_attention_drop_ids: list[str] = Field(default_factory=list)
    attention_map_run_ids: list[str] = Field(default_factory=list)


class ArtifactRef(StrictModel):
    artifact_id: str
    path: str
    sha256: str
    approval_state: str | None = None


class SourceType(StrEnum):
    PEER_REVIEWED_RESEARCH = "PEER_REVIEWED_RESEARCH"
    GOVERNMENT_PRIMARY = "GOVERNMENT_PRIMARY"
    STANDARDS_BODY = "STANDARDS_BODY"
    COMPANY_PRIMARY = "COMPANY_PRIMARY"
    INDEPENDENT_ANALYSIS = "INDEPENDENT_ANALYSIS"
    NEWS_REPORTING = "NEWS_REPORTING"
    WORKING_PAPER = "WORKING_PAPER"
    PREPRINT = "PREPRINT"
    INDUSTRY_REPORT = "INDUSTRY_REPORT"
    CORPORATE_PUBLICATION = "CORPORATE_PUBLICATION"
    SOCIAL_MEDIA = "SOCIAL_MEDIA"
    ONLINE_FORUM = "ONLINE_FORUM"
    OTHER = "OTHER"


class SourceQuality(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    LOW_TRUST = "LOW_TRUST"


class EvidenceStatus(StrEnum):
    VERIFIED = "VERIFIED"
    LEAD_ONLY = "LEAD_ONLY"
    UNVERIFIED = "UNVERIFIED"
    CLAIM_NOT_SUPPORTED = "CLAIM_NOT_SUPPORTED"
    CAPTURE_UNAVAILABLE = "CAPTURE_UNAVAILABLE"


class WriterUseMode(StrEnum):
    DIRECT_QUOTE = "DIRECT_QUOTE"
    ATTRIBUTED_PARAPHRASE = "ATTRIBUTED_PARAPHRASE"
    AGGREGATE_SYNTHESIS = "AGGREGATE_SYNTHESIS"
    LEAD_ONLY = "LEAD_ONLY"
    BLOCKED = "BLOCKED"


class VerbatimUseStatus(StrEnum):
    QUOTABLE = "QUOTABLE"
    LICENSED = "LICENSED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    PROHIBITED = "PROHIBITED"


class StudyRole(StrEnum):
    PRIMARY_RESEARCH = "PRIMARY_RESEARCH"
    SYSTEMATIC_REVIEW = "SYSTEMATIC_REVIEW"
    META_ANALYSIS = "META_ANALYSIS"
    SCOPING_REVIEW = "SCOPING_REVIEW"
    NARRATIVE_REVIEW = "NARRATIVE_REVIEW"
    UMBRELLA_REVIEW = "UMBRELLA_REVIEW"
    GUIDELINE_OR_CONSENSUS = "GUIDELINE_OR_CONSENSUS"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ClaimType(StrEnum):
    DEFINITIONAL = "DEFINITIONAL"
    DESCRIPTIVE_TREND = "DESCRIPTIVE_TREND"
    PREVALENCE = "PREVALENCE"
    ASSOCIATION = "ASSOCIATION"
    INDEPENDENT_EFFECT = "INDEPENDENT_EFFECT"
    CAUSAL_EFFECT = "CAUSAL_EFFECT"
    GOVERNANCE_REQUIREMENT = "GOVERNANCE_REQUIREMENT"
    LEGAL_OR_POLICY_DESCRIPTION = "LEGAL_OR_POLICY_DESCRIPTION"
    FUTURE_SCENARIO = "FUTURE_SCENARIO"


class BibliographicStatus(StrEnum):
    VERIFIED = "VERIFIED"
    UNAVAILABLE = "UNAVAILABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class EvidenceKind(StrEnum):
    SUPPORTING = "SUPPORTING"
    COUNTEREVIDENCE = "COUNTEREVIDENCE"
    CONFLICT = "CONFLICT"
    NULL = "NULL"
    LIMITATION = "LIMITATION"
    UNKNOWN = "UNKNOWN"


class SupportScope(StrEnum):
    COMPANY_CLAIM = "COMPANY_CLAIM"
    DESCRIPTIVE_CONTEXT = "DESCRIPTIVE_CONTEXT"
    LEAD_ONLY = "LEAD_ONLY"
    INDEPENDENT_EFFECTIVENESS = "INDEPENDENT_EFFECTIVENESS"
    CAUSAL_EFFECT = "CAUSAL_EFFECT"


class RemainingInformationValue(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class QuestionInput(StrictModel):
    question_id: str
    text: str
    status: Literal["CANDIDATE", "PROPOSED", "BASELINE", "REVISED"]
    authoritative: bool = False
    decision_id: str | None = None

    @model_validator(mode="after")
    def authority_requires_human_decision(self) -> QuestionInput:
        if self.authoritative and (self.status not in {"BASELINE", "REVISED"} or not self.decision_id):
            raise ValueError("a provisional Question Candidate is not authoritative without a Human Decision")
        return self


class DesktopResearchContextSpec(StrictModel):
    question: QuestionInput | None = None
    questions: list[QuestionInput] = Field(default_factory=list)
    allowed_source_types: list[SourceType]
    retrieval_scope: list[str]
    forbidden_roles: list[str]
    coverage_dimensions: list[str]
    max_context_artifacts: int = Field(default=50, ge=1)
    work_execution_mode: Literal["HUMAN_INTERACTIVE", "VERIFIED_ADAPTER"] = "HUMAN_INTERACTIVE"
    research_brief: ResearchBrief | None = None

    @model_validator(mode="after")
    def retain_mandatory_firewall_roles(self) -> DesktopResearchContextSpec:
        mandatory = {
            "PUBLICATION_DRAFT",
            "PUBLICATION_FEEDBACK",
            "CLEAN_PUBLICATION_SOURCE",
            "FORMAL_PUBLICATION_SPEC",
            "SUPERSEDED_CANONICAL_PROVENANCE",
            "HISTORICAL_CALIBRATION_SOURCE",
            "SIMULATION_PROVENANCE",
        }
        self.forbidden_roles = sorted(set(self.forbidden_roles).union(mandatory))
        if self.question is None and not self.questions:
            raise ValueError("Desktop Research requires at least one approved Question")
        if self.question is not None and not self.questions:
            self.questions = [self.question]
        return self


class EvidenceExcerpt(StrictModel):
    excerpt: str = Field(min_length=1)
    locator: str = Field(min_length=1)


class DesktopResearchEvidence(StrictModel):
    schema_version: str = "0.2"
    evidence_id: str
    source_id: str
    source_type: SourceType
    source_quality: SourceQuality
    locator: str = Field(min_length=1)
    captured_statement: str = Field(min_length=1)
    acquired_at: datetime
    text_snapshot: str = Field(min_length=1)
    snapshot_path: str = Field(min_length=1)
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    excerpt_locator_pairs: list[EvidenceExcerpt] = Field(min_length=1)
    evidence_kind: EvidenceKind
    support_scope: SupportScope
    material: bool = True
    independent_support_source_ids: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)

    @field_validator("acquired_at")
    @classmethod
    def acquired_at_must_be_timezone_aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("acquired_at must be timezone-aware UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def excerpts_resolve_to_snapshot(self) -> DesktopResearchEvidence:
        missing = [
            pair.excerpt
            for pair in self.excerpt_locator_pairs
            if pair.excerpt not in self.text_snapshot
        ]
        if missing:
            raise ValueError("every excerpt must be present in text_snapshot")
        if self.locator not in {pair.locator for pair in self.excerpt_locator_pairs}:
            raise ValueError("primary locator must be represented in excerpt_locator_pairs")
        return self

    @model_validator(mode="after")
    def company_claim_support_boundary(self) -> DesktopResearchEvidence:
        allowed_scopes = {
            SourceType.PEER_REVIEWED_RESEARCH: {
                SupportScope.DESCRIPTIVE_CONTEXT,
                SupportScope.INDEPENDENT_EFFECTIVENESS,
                SupportScope.CAUSAL_EFFECT,
            },
            SourceType.GOVERNMENT_PRIMARY: {
                SupportScope.DESCRIPTIVE_CONTEXT,
                SupportScope.INDEPENDENT_EFFECTIVENESS,
            },
            SourceType.STANDARDS_BODY: {SupportScope.DESCRIPTIVE_CONTEXT},
            SourceType.COMPANY_PRIMARY: {SupportScope.COMPANY_CLAIM, SupportScope.DESCRIPTIVE_CONTEXT},
            SourceType.INDEPENDENT_ANALYSIS: {
                SupportScope.DESCRIPTIVE_CONTEXT,
                SupportScope.INDEPENDENT_EFFECTIVENESS,
            },
            SourceType.NEWS_REPORTING: {SupportScope.DESCRIPTIVE_CONTEXT},
            SourceType.WORKING_PAPER: {SupportScope.DESCRIPTIVE_CONTEXT, SupportScope.LEAD_ONLY},
            SourceType.PREPRINT: {SupportScope.DESCRIPTIVE_CONTEXT, SupportScope.LEAD_ONLY},
            SourceType.INDUSTRY_REPORT: {SupportScope.DESCRIPTIVE_CONTEXT, SupportScope.LEAD_ONLY},
            SourceType.CORPORATE_PUBLICATION: {SupportScope.DESCRIPTIVE_CONTEXT, SupportScope.LEAD_ONLY},
            SourceType.SOCIAL_MEDIA: {SupportScope.DESCRIPTIVE_CONTEXT, SupportScope.LEAD_ONLY},
            SourceType.ONLINE_FORUM: {SupportScope.DESCRIPTIVE_CONTEXT, SupportScope.LEAD_ONLY},
            SourceType.OTHER: {SupportScope.DESCRIPTIVE_CONTEXT, SupportScope.LEAD_ONLY},
        }
        independent_scopes = {SupportScope.INDEPENDENT_EFFECTIVENESS, SupportScope.CAUSAL_EFFECT}
        low_confidence_types = {
            SourceType.WORKING_PAPER,
            SourceType.PREPRINT,
            SourceType.INDUSTRY_REPORT,
            SourceType.CORPORATE_PUBLICATION,
        }
        low_trust_types = {SourceType.SOCIAL_MEDIA, SourceType.ONLINE_FORUM}
        if self.source_type in low_confidence_types and self.source_quality is not SourceQuality.LOW_CONFIDENCE:
            raise ValueError(f"{self.source_type.value} sources must be flagged LOW_CONFIDENCE")
        if self.source_type in low_trust_types and self.source_quality is not SourceQuality.LOW_TRUST:
            raise ValueError(f"{self.source_type.value} sources must be flagged LOW_TRUST")
        if self.source_quality is SourceQuality.LOW_TRUST and self.support_scope not in {
            SupportScope.DESCRIPTIVE_CONTEXT,
            SupportScope.LEAD_ONLY,
        }:
            raise ValueError("LOW_TRUST sources may support only DESCRIPTIVE_CONTEXT or LEAD_ONLY")
        if self.source_quality is SourceQuality.LOW_CONFIDENCE and self.support_scope in independent_scopes:
            raise ValueError("LOW_CONFIDENCE sources may not support INDEPENDENT_EFFECTIVENESS or CAUSAL_EFFECT")
        if self.source_type is SourceType.COMPANY_PRIMARY and self.support_scope in independent_scopes:
            raise ValueError("COMPANY_PRIMARY sources remain COMPANY_CLAIM or DESCRIPTIVE_CONTEXT evidence")
        if self.support_scope not in allowed_scopes[self.source_type]:
            raise ValueError(f"source type {self.source_type.value} may not support {self.support_scope.value}")
        return self


class SourceCapture(StrictModel):
    """Immutable source material shared by one or more Evidence Citations."""

    schema_version: Literal["0.3"] = "0.3"
    capture_id: str
    source_id: str
    canonical_locator: str = Field(min_length=1)
    acquired_at: datetime
    original_path: str = Field(min_length=1)
    original_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    original_media_type: str = Field(min_length=1)
    text_snapshot_path: str = Field(min_length=1)
    text_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    extractor_name: str | None = None
    extractor_version: str | None = None
    source_title: str | None = None
    source_title_status: BibliographicStatus = BibliographicStatus.UNAVAILABLE
    publisher_or_author: str | None = None
    publisher_or_author_status: BibliographicStatus = BibliographicStatus.UNAVAILABLE
    publication_or_update_date: str | None = None
    publication_or_update_date_status: BibliographicStatus = BibliographicStatus.UNAVAILABLE
    version_or_revision: str | None = None
    version_or_revision_status: BibliographicStatus = BibliographicStatus.UNAVAILABLE
    bibliography_notes: list[str] = Field(default_factory=list)

    @property
    def identity_key(self) -> tuple[str, str]:
        """Stable deduplication identity for one acquired source version."""
        return (self.canonical_locator, self.original_sha256)

    @field_validator("acquired_at")
    @classmethod
    def capture_time_must_be_timezone_aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("SourceCapture acquired_at must be timezone-aware UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def bibliography_status_matches_value(self) -> SourceCapture:
        pairs = (
            (self.source_title, self.source_title_status, "source_title"),
            (self.publisher_or_author, self.publisher_or_author_status, "publisher_or_author"),
            (self.publication_or_update_date, self.publication_or_update_date_status, "publication_or_update_date"),
            (self.version_or_revision, self.version_or_revision_status, "version_or_revision"),
        )
        for value, status, field_name in pairs:
            if status is BibliographicStatus.VERIFIED and not value:
                raise ValueError(f"{field_name} is required when its status is VERIFIED")
            if status is not BibliographicStatus.VERIFIED and value:
                raise ValueError(f"{field_name} must be null unless its status is VERIFIED")
        return self


class EvidenceCitation(StrictModel):
    """A research claim tied to a verbatim excerpt in a SourceCapture."""

    schema_version: Literal["0.3"] = "0.3"
    evidence_id: str
    capture_id: str
    captured_statement: str = Field(min_length=1)
    excerpt: str = Field(min_length=1)
    excerpt_locator: str = Field(min_length=1)
    evidence_status: EvidenceStatus = EvidenceStatus.VERIFIED
    evidence_kind: EvidenceKind
    support_scope: SupportScope
    claim_types: list[ClaimType] = Field(default_factory=list)
    source_type: SourceType
    source_quality: SourceQuality
    study_role: StudyRole = StudyRole.NOT_APPLICABLE
    study_design: str | None = None
    population_or_context: str | None = None
    intervention_or_exposure: str | None = None
    comparator: str | None = None
    outcome: str | None = None
    study_period: str | None = None
    synthesis_scope: str | None = None
    search_cutoff_date: str | None = None
    inclusion_exclusion_scope: str | None = None
    included_source_ids: list[str] = Field(default_factory=list)
    overlap_group_id: str | None = None
    heterogeneity_limitations: list[str] = Field(default_factory=list)
    material: bool = True
    independent_support_source_ids: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    writer_use_mode: WriterUseMode = WriterUseMode.ATTRIBUTED_PARAPHRASE
    verbatim_use_status: VerbatimUseStatus = VerbatimUseStatus.REVIEW_REQUIRED
    attribution: str | None = None
    verbatim_checklist: dict[str, bool] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_citation_shape(self) -> EvidenceCitation:
        if self.evidence_status in {EvidenceStatus.CLAIM_NOT_SUPPORTED, EvidenceStatus.CAPTURE_UNAVAILABLE}:
            if self.writer_use_mode is not WriterUseMode.BLOCKED:
                raise ValueError("unsupported or unavailable EvidenceCitation must be BLOCKED for Writer use")
        elif self.evidence_status is not EvidenceStatus.VERIFIED and self.writer_use_mode not in {
            WriterUseMode.LEAD_ONLY, WriterUseMode.BLOCKED,
        }:
            raise ValueError("non-verified EvidenceCitation must use LEAD_ONLY or BLOCKED writer mode")
        if self.evidence_status is EvidenceStatus.LEAD_ONLY and self.support_scope in {
            SupportScope.INDEPENDENT_EFFECTIVENESS, SupportScope.CAUSAL_EFFECT,
        }:
            raise ValueError("LEAD_ONLY EvidenceCitation cannot support independent or causal effects")
        if self.writer_use_mode is WriterUseMode.DIRECT_QUOTE and self.verbatim_use_status not in {
            VerbatimUseStatus.QUOTABLE, VerbatimUseStatus.LICENSED,
        }:
            raise ValueError("DIRECT_QUOTE requires QUOTABLE or LICENSED verbatim use")
        if self.writer_use_mode is WriterUseMode.AGGREGATE_SYNTHESIS and not self.included_source_ids:
            raise ValueError("AGGREGATE_SYNTHESIS requires included_source_ids traceability")
        if self.verbatim_use_status is VerbatimUseStatus.QUOTABLE:
            required_checks = {
                "published", "purpose", "necessity", "clear_distinction",
                "relationship", "minimal", "attribution",
            }
            if not required_checks.issubset({key for key, value in self.verbatim_checklist.items() if value}):
                raise ValueError("QUOTABLE EvidenceCitation requires the complete quotation checklist")
        if self.study_role in {StudyRole.SYSTEMATIC_REVIEW, StudyRole.META_ANALYSIS, StudyRole.SCOPING_REVIEW,
                               StudyRole.NARRATIVE_REVIEW, StudyRole.UMBRELLA_REVIEW} and not self.synthesis_scope:
            raise ValueError("review EvidenceCitation requires synthesis_scope")
        if self.study_role is StudyRole.PRIMARY_RESEARCH and not self.study_design:
            raise ValueError("primary research EvidenceCitation requires study_design")
        if self.study_role in {StudyRole.SYSTEMATIC_REVIEW, StudyRole.META_ANALYSIS, StudyRole.UMBRELLA_REVIEW} \
                and not self.search_cutoff_date:
            raise ValueError("systematic synthesis EvidenceCitation requires search_cutoff_date")
        if self.study_role in {StudyRole.NARRATIVE_REVIEW, StudyRole.SCOPING_REVIEW} \
            and self.support_scope in {SupportScope.INDEPENDENT_EFFECTIVENESS, SupportScope.CAUSAL_EFFECT}:
            raise ValueError("narrative or scoping reviews cannot directly support an effect conclusion")
        if self.study_role is StudyRole.GUIDELINE_OR_CONSENSUS and self.support_scope in {
            SupportScope.INDEPENDENT_EFFECTIVENESS, SupportScope.CAUSAL_EFFECT,
        }:
            raise ValueError("guideline or consensus evidence cannot be represented as empirical effect evidence")
        if self.source_quality is SourceQuality.LOW_TRUST and self.support_scope not in {
            SupportScope.DESCRIPTIVE_CONTEXT, SupportScope.LEAD_ONLY,
        }:
            raise ValueError("LOW_TRUST citations may support only DESCRIPTIVE_CONTEXT or LEAD_ONLY")
        if self.source_type in {
            SourceType.WORKING_PAPER, SourceType.PREPRINT,
            SourceType.INDUSTRY_REPORT, SourceType.CORPORATE_PUBLICATION,
        } and self.source_quality is not SourceQuality.LOW_CONFIDENCE:
            raise ValueError(f"{self.source_type.value} citations must be flagged LOW_CONFIDENCE")
        if self.source_type in {SourceType.SOCIAL_MEDIA, SourceType.ONLINE_FORUM} and self.source_quality is not SourceQuality.LOW_TRUST:
            raise ValueError(f"{self.source_type.value} citations must be flagged LOW_TRUST")
        if self.source_quality is SourceQuality.LOW_CONFIDENCE and self.support_scope in {
            SupportScope.INDEPENDENT_EFFECTIVENESS, SupportScope.CAUSAL_EFFECT,
        }:
            raise ValueError("LOW_CONFIDENCE citations may not support independent or causal effects")
        if self.source_type is SourceType.COMPANY_PRIMARY and self.support_scope in {
            SupportScope.INDEPENDENT_EFFECTIVENESS, SupportScope.CAUSAL_EFFECT,
        }:
            raise ValueError("COMPANY_PRIMARY citations cannot establish independent or causal effects")
        return self


class ResearchBrief(StrictModel):
    """Human-approved research quality contract rendered into Work instructions."""

    schema_version: Literal["0.3"] = "0.3"
    research_objective: str = Field(min_length=1)
    approved_questions: list[str] = Field(min_length=1)
    claim_types_to_test: list[ClaimType] = Field(min_length=1)
    study_role_requirements: dict[str, list[StudyRole]] = Field(default_factory=dict)
    source_role_requirements: dict[str, list[SourceType]] = Field(default_factory=dict)
    inclusion_criteria: list[str] = Field(default_factory=list)
    exclusion_criteria: list[str] = Field(default_factory=list)
    freshness_requirements: list[str] = Field(default_factory=list)
    counterevidence_requirements: list[str] = Field(default_factory=list)
    capture_requirements: list[str] = Field(default_factory=list)
    coverage_requirements: list[str] = Field(default_factory=list)
    stopping_conditions: list[str] = Field(default_factory=list)
    prohibited_inferences: list[str] = Field(default_factory=list)

class ProvenanceAuditBaseline(StrictModel):
    state_id: str
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ProvenanceAuditSelection(StrictModel):
    predicate: str
    expected_count: int = Field(ge=1)
    actual_count: int = Field(ge=0)
    legacy_schema_version: Literal["0.1"]
    missing_capture_fields: list[str] = Field(default_factory=list)
    selection_is_closed_world: bool

    @model_validator(mode="after")
    def selection_count_is_closed(self) -> ProvenanceAuditSelection:
        if self.expected_count != self.actual_count:
            raise ValueError("PROVENANCE_AUDIT selection expected_count must equal actual_count")
        if not self.selection_is_closed_world:
            raise ValueError("PROVENANCE_AUDIT selection must be closed-world")
        return self


class ProvenanceAuditTarget(StrictModel):
    evidence_id: str
    source_id: str
    source_type: SourceType
    support_scope: SupportScope
    locator: str = Field(min_length=1)


class ProvenanceAuditPlan(StrictModel):
    manifest_kind: Literal["PROVENANCE_REPAIR_RUN_PLAN"]
    schema_version: Literal["0.1"]
    status: Literal["PLANNED"]
    created_at: datetime
    proposed_run_id: str = Field(pattern=SAFE_IDENTIFIER_PATTERN)
    proposed_context_pack_id: str = Field(pattern=SAFE_IDENTIFIER_PATTERN)
    event: Literal["PROVENANCE_AUDIT"]
    lane: Literal["IMPLEMENTATION"]
    objective: str = Field(min_length=1)
    execution_boundary: str = Field(min_length=1)
    baseline_snapshot: ProvenanceAuditBaseline
    selection: ProvenanceAuditSelection
    target_evidence: list[ProvenanceAuditTarget] = Field(min_length=1)
    allowed_context: dict[str, Any] = Field(default_factory=dict)
    forbidden_context: list[str] = Field(default_factory=list)
    retrieval_rules: list[str] = Field(default_factory=list)
    required_outputs: dict[str, Any] = Field(default_factory=dict)
    invariants: list[str] = Field(default_factory=list)
    human_decision_triggers: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def target_set_matches_selection(self) -> ProvenanceAuditPlan:
        ids = [item.evidence_id for item in self.target_evidence]
        if len(ids) != len(set(ids)):
            raise ValueError("PROVENANCE_AUDIT target evidence IDs must be unique")
        if len(ids) != self.selection.actual_count:
            raise ValueError("PROVENANCE_AUDIT target evidence count does not match selection")
        return self


class ProvenanceAuditRecord(DesktopResearchEvidence):
    schema_version: Literal["0.2"] = "0.2"
    source_title: str = Field(min_length=1)
    publisher_or_author: str = Field(min_length=1)
    publication_or_update_date: str = Field(min_length=1)
    version_or_revision: str = Field(min_length=1)
    verification_status: Literal["VERIFIED"] = "VERIFIED"
    metadata_confidence: Literal["HIGH", "MEDIUM", "LOW"]


class ProvenanceAuditUnresolved(StrictModel):
    evidence_id: str
    status: Literal["UNRESOLVED_GAP"] = "UNRESOLVED_GAP"
    reason: str = Field(min_length=1)
    attempted_locator: str | None = None


class ProvenanceAuditHandoff(StrictModel):
    schema_version: str = "0.2"
    run_id: str
    source_manifest_id: str
    baseline_state_id: str
    target_evidence_ids: list[str] = Field(min_length=1)
    evidence: list[ProvenanceAuditRecord] = Field(default_factory=list)
    unresolved: list[ProvenanceAuditUnresolved] = Field(default_factory=list)
    # v0.3 capture/citation phases; legacy resolved records remain immutable.
    source_captures: list[SourceCapture] = Field(default_factory=list)
    evidence_citations: list[EvidenceCitation] = Field(default_factory=list)
    back_references: list[str] = Field(min_length=1)
    audit_notes: list[str] = Field(default_factory=list)
    selected_method: None = None

    @model_validator(mode="before")
    @classmethod
    def infer_v03_schema_for_capture_handoff(cls, value: Any) -> Any:
        if isinstance(value, dict) and (value.get("source_captures") or value.get("evidence_citations")):
            value = dict(value)
            value.setdefault("schema_version", "0.3")
        return value

    @model_validator(mode="after")
    def target_partition_is_unique(self) -> ProvenanceAuditHandoff:
        if len(self.target_evidence_ids) != len(set(self.target_evidence_ids)):
            raise ValueError("PROVENANCE_AUDIT target evidence IDs must be unique")
        resolved = [item.evidence_id for item in self.evidence]
        unresolved = [item.evidence_id for item in self.unresolved]
        if len(resolved) != len(set(resolved)) or len(unresolved) != len(set(unresolved)):
            raise ValueError("PROVENANCE_AUDIT evidence IDs must be unique")
        if self.source_captures or self.evidence_citations:
            captures = {item.capture_id for item in self.source_captures}
            citations = {item.evidence_id for item in self.evidence_citations}
            if len(captures) != len(self.source_captures) or len(citations) != len(self.evidence_citations):
                raise ValueError("PROVENANCE_AUDIT v0.3 capture/citation IDs must be unique")
            if len({item.identity_key for item in self.source_captures}) != len(self.source_captures):
                raise ValueError("PROVENANCE_AUDIT identical source versions must share one SourceCapture")
            if not citations.issubset(set(self.target_evidence_ids)):
                raise ValueError("PROVENANCE_AUDIT v0.3 citations must be within target_evidence_ids")
            if not {item.capture_id for item in self.evidence_citations}.issubset(captures):
                raise ValueError("PROVENANCE_AUDIT v0.3 citations reference missing captures")
            return self
        if set(resolved).intersection(unresolved):
            raise ValueError("PROVENANCE_AUDIT evidence cannot be both resolved and unresolved")
        if set(resolved).union(unresolved) != set(self.target_evidence_ids):
            raise ValueError("PROVENANCE_AUDIT results must cover the target evidence set exactly")
        return self


class ContractRegistryRefresh(StrictModel):
    """Immutable receipt for refreshing a live Registry from current contracts."""

    schema_version: Literal["0.1"] = "0.1"
    run_id: str
    context_pack_id: str
    event: Literal["CONTRACT_MIGRATION_REVIEW"] = "CONTRACT_MIGRATION_REVIEW"
    lane: Literal["IMPLEMENTATION"] = "IMPLEMENTATION"
    status: Literal["COMPLETED"] = "COMPLETED"
    registry_before_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    registry_after_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    research_state_id: str
    research_state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    refreshed_artifact_ids: list[str] = Field(default_factory=list)
    added_artifact_ids: list[str] = Field(default_factory=list)
    changed_policy_artifact_ids: list[str] = Field(default_factory=list)
    unchanged_artifact_ids: list[str] = Field(default_factory=list)
    canonical_artifact_ids: list[str] = Field(min_length=1)
    pending_decision_ids: list[str] = Field(default_factory=list)


class EvidenceModelMigrationReceipt(StrictModel):
    """Immutable receipt for the destructive v0.2 -> v0.3 evidence split."""

    schema_version: Literal["0.3"] = "0.3"
    event: Literal["EVIDENCE_MODEL_MIGRATION"] = "EVIDENCE_MODEL_MIGRATION"
    run_id: str
    prior_state_id: str
    new_state_id: str
    prior_state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    new_state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    capture_count: int = Field(ge=0)
    citation_count: int = Field(ge=0)
    shared_capture_count: int = Field(ge=0)
    lead_only_count: int = Field(ge=0)
    gap_count: int = Field(ge=0)
    conversion_reasons: list[str] = Field(default_factory=list)
    immutable_history_refs: list[str] = Field(default_factory=list)


class CoverageDimension(StrictModel):
    dimension: str
    status: Literal["COVERED", "PARTIAL", "GAP", "NOT_APPLICABLE"]
    rationale: str


class CoverageStoppingAssessment(StrictModel):
    dimensions: list[CoverageDimension]
    saturation: Literal["LOW", "PARTIAL", "SATURATED"]
    unresolved_material_evidence_gap_ids: list[str]
    remaining_information_value: RemainingInformationValue
    stop_recommended: bool
    stopping_rationale: str
    stopping_basis: list[Literal["COVERAGE", "SATURATION", "REMAINING_INFORMATION_VALUE"]]
    fixed_source_count_reached: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def stopping_requires_coverage_not_count(self) -> CoverageStoppingAssessment:
        if self.stop_recommended and self.unresolved_material_evidence_gap_ids:
            raise ValueError("cannot stop with unresolved material Evidence Gaps")
        if self.stop_recommended and self.remaining_information_value is RemainingInformationValue.HIGH:
            raise ValueError("cannot stop while remaining information value is HIGH")
        if self.stop_recommended and not self.stopping_basis:
            raise ValueError("stopping requires coverage, saturation, or remaining information value basis")
        return self


class QuestionImpact(StrictModel):
    status: Literal["NO_CHANGE", "REFINE_CANDIDATE", "SPLIT_CANDIDATE", "CLOSE_CANDIDATE", "HUMAN_DECISION_REQUIRED"]
    rationale: str


class FindingRecord(StrictModel):
    finding_id: str
    statement: str
    evidence_ids: list[str]
    material: bool = False
    status: Literal["CANDIDATE", "PROVISIONAL", "HUMAN_APPROVED"] = "CANDIDATE"
    decision_id: str | None = None

    @model_validator(mode="after")
    def adopted_finding_requires_decision(self) -> FindingRecord:
        if self.status == "HUMAN_APPROVED" and not self.decision_id:
            raise ValueError("Human-approved Finding requires a Decision ID")
        return self


class EvidenceGap(StrictModel):
    gap_id: str
    description: str
    material: bool
    resolved_by_evidence_ids: list[str] = Field(default_factory=list)


class NextMethodOption(StrictModel):
    option_id: str
    method: str
    rationale: str
    addresses_gap_ids: list[str]
    selected: Literal[False] = False


class RunManifest(StrictModel):
    run_id: str = Field(pattern=SAFE_IDENTIFIER_PATTERN)
    task_id: str = Field(pattern=SAFE_IDENTIFIER_PATTERN)
    task_type: str
    objective: str
    event: str
    lane: Lane
    context_pack_id: str | None = Field(default=None, pattern=SAFE_IDENTIFIER_PATTERN)
    active_questions: list[str] = Field(default_factory=list)
    canonical_versions: dict[str, str] = Field(default_factory=dict)
    input_refs: list[ArtifactRef] = Field(default_factory=list)
    forbidden_context: list[str] = Field(default_factory=list)
    retrieval_policy: list[str] = Field(default_factory=list)
    output_schema: str = "WorkerResult"
    stop_conditions: list[str] = Field(default_factory=list)
    worker_backend: str = "mock"
    audit_policy: list[str] = Field(default_factory=list)
    decision_context: list[str] = Field(default_factory=list)
    status: str = "PLANNED"
    attempt: int = 1
    created_at: datetime = Field(default_factory=utc_now)


class ContextPackManifest(StrictModel):
    pack_id: str = Field(pattern=SAFE_IDENTIFIER_PATTERN)
    run_id: str = Field(pattern=SAFE_IDENTIFIER_PATTERN)
    event: str
    lane: Lane
    must_include: list[ArtifactRef] = Field(default_factory=list)
    retrieve_on_demand: list[ArtifactRef] = Field(default_factory=list)
    forbidden_context: list[str] = Field(default_factory=list)
    access_decisions: list[RuntimeAccessDecision] = Field(default_factory=list)
    desktop_research_spec: DesktopResearchContextSpec | None = None
    created_at: datetime = Field(default_factory=utc_now)


class WorkerResult(StrictModel):
    run_id: str
    observed: list[Any] = Field(default_factory=list)
    derived: list[Any] = Field(default_factory=list)
    interpreted: list[Any] = Field(default_factory=list)
    counterevidence: list[Any] = Field(default_factory=list)
    unknown: list[Any] = Field(default_factory=list)
    scope_limits: list[Any] = Field(default_factory=list)
    question_overlaps: list[Any] = Field(default_factory=list)
    evidence_gap_hypotheses: list[Any] = Field(default_factory=list)
    question_delta_candidate: list[Any] = Field(default_factory=list)
    next_evidence_request: list[Any] = Field(default_factory=list)
    back_references: list[str] = Field(default_factory=list)
    issues: list[Any] = Field(default_factory=list)
    selected_method: None = None


class QuestionCandidate(StrictModel):
    candidate_id: str
    question: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    uncertainty: list[Any]
    scope_limits: list[Any]


class EvidenceGapHypothesis(StrictModel):
    gap_id: str
    hypothesis: str = Field(min_length=1)
    why_material: str = Field(min_length=1)


class ProposedQuestionBaseline(StrictModel):
    proposal_id: str
    question: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    uncertainty: list[Any]
    scope_limits: list[Any]
    overlaps: list[Any]
    evidence_gap_hypotheses: list[EvidenceGapHypothesis]


class IndependentQuestionFormationHandoff(StrictModel):
    run_id: str
    candidates: list[QuestionCandidate] = Field(min_length=1)
    counterevidence: list[Any]
    uncertainty: list[Any]
    scope_limits: list[Any]
    question_overlaps: list[Any]
    evidence_gap_hypotheses: list[EvidenceGapHypothesis]
    back_references: list[str]
    attention_map_authority: Literal["GUIDANCE_ONLY", "NONE"]
    selected_method: None = None


class SeedComparisonHandoff(StrictModel):
    run_id: str
    matches: list[Any]
    mismatches: list[Any]
    missing: list[Any]
    over_scoped: list[Any]
    proposed_baselines: list[ProposedQuestionBaseline] = Field(min_length=1)
    counterevidence: list[Any]
    uncertainty: list[Any]
    scope_limits: list[Any]
    question_overlaps: list[Any]
    evidence_gap_hypotheses: list[EvidenceGapHypothesis]
    back_references: list[str]
    attention_map_authority: Literal["GUIDANCE_ONLY", "NONE"] = "GUIDANCE_ONLY"
    selected_method: None = None


class AuditIssue(StrictModel):
    code: str
    severity: Literal["BLOCKER", "MAJOR", "MINOR"]
    message: str


class AuditResult(StrictModel):
    run_id: str
    passed: bool
    issues: list[AuditIssue] = Field(default_factory=list)
    metrics: dict[str, int] = Field(default_factory=dict)


class StateDeltaProposal(StrictModel):
    run_id: str
    operational_changes: dict[str, Any] = Field(default_factory=dict)
    semantic_changes: dict[str, Any] = Field(default_factory=dict)
    requires_human_decision: bool = False
    preserved_counterevidence: list[Any] = Field(default_factory=list)
    preserved_unknowns: list[Any] = Field(default_factory=list)
    preserved_scope_limits: list[Any] = Field(default_factory=list)
    preserved_evidence_gaps: list[Any] = Field(default_factory=list)
    preserved_question_overlaps: list[Any] = Field(default_factory=list)

    @model_validator(mode="after")
    def semantic_changes_require_decision(self) -> StateDeltaProposal:
        if self.semantic_changes and not self.requires_human_decision:
            raise ValueError("semantic changes require a Human Decision")
        return self


class ResearchHandoff(StrictModel):
    run_id: str
    current_answer: list[Any] = Field(default_factory=list)
    counterevidence: list[Any] = Field(default_factory=list)
    unknowns: list[Any] = Field(default_factory=list)
    scope_limits: list[Any] = Field(default_factory=list)
    question_overlaps: list[Any] = Field(default_factory=list)
    evidence_gap_hypotheses: list[Any] = Field(default_factory=list)
    minority_warnings: list[Any] = Field(default_factory=list)
    question_change_reasons: list[Any] = Field(default_factory=list)
    back_references: list[str] = Field(default_factory=list)


class DesktopResearchHandoff(StrictModel):
    # Keep the legacy default for old Work exchanges. A v0.3 handoff is
    # selected by supplying SourceCapture/EvidenceCitation records.
    schema_version: str = "0.2"
    run_id: str
    question_impact: QuestionImpact
    findings: list[FindingRecord] = Field(default_factory=list)
    evidence: list[DesktopResearchEvidence] = Field(default_factory=list)
    source_captures: list[SourceCapture] = Field(default_factory=list)
    evidence_citations: list[EvidenceCitation] = Field(default_factory=list)
    research_brief: ResearchBrief | None = None
    counterevidence: list[Any] = Field(default_factory=list)
    counterevidence_search_summary: str = ""
    unknowns: list[Any] = Field(default_factory=list)
    evidence_gaps: list[EvidenceGap] = Field(default_factory=list)
    candidate_next_method_options: list[NextMethodOption] = Field(default_factory=list)
    coverage: CoverageStoppingAssessment | None = None
    back_references: list[str] = Field(default_factory=list)
    publication_eligibility: PublicationEligibility | None = None

    @model_validator(mode="before")
    @classmethod
    def infer_v03_schema_for_capture_handoff(cls, value: Any) -> Any:
        if isinstance(value, dict):
            value = dict(value)
            is_v03 = bool(value.get("source_captures") or value.get("evidence_citations") or value.get("schema_version") == "0.3")
            if is_v03:
                value.setdefault("schema_version", "0.3")
            else:
                required_legacy = {
                    "findings", "evidence", "counterevidence", "counterevidence_search_summary",
                    "unknowns", "evidence_gaps", "candidate_next_method_options", "coverage",
                    "back_references", "publication_eligibility",
                }
                missing = sorted(required_legacy.difference(value))
                if missing:
                    raise ValueError(f"legacy Desktop Research Handoff requires fields: {missing}")
        return value

    @model_validator(mode="after")
    def findings_resolve_to_source_locators(self) -> DesktopResearchHandoff:
        if any(item.status == "HUMAN_APPROVED" for item in self.findings):
            raise ValueError("Desktop Research workers cannot Human-approve Findings")
        if self.publication_eligibility is not None and self.publication_eligibility.status == "ELIGIBLE":
            raise ValueError("Desktop Research workers cannot grant Publication Eligibility")
        if self.source_captures or self.evidence_citations:
            capture_by_id = {item.capture_id: item for item in self.source_captures}
            citation_by_id = {item.evidence_id: item for item in self.evidence_citations}
            if len(capture_by_id) != len(self.source_captures):
                raise ValueError("SourceCapture capture_id values must be unique")
            if len(citation_by_id) != len(self.evidence_citations):
                raise ValueError("EvidenceCitation evidence_id values must be unique")
            identities = [item.identity_key for item in self.source_captures]
            if len(identities) != len(set(identities)):
                raise ValueError("identical canonical_locator + original_sha256 must share one SourceCapture")
            missing_captures = sorted({item.capture_id for item in self.evidence_citations}.difference(capture_by_id))
            if missing_captures:
                raise ValueError(f"Evidence Citations reference missing Source Captures: {missing_captures}")
            missing_evidence = sorted({evidence_id for finding in self.findings for evidence_id in finding.evidence_ids}
                                      .difference(citation_by_id))
            if missing_evidence:
                raise ValueError(f"Findings reference missing Evidence Citations: {missing_evidence}")
            unresolved_material_gaps = (
                set(self.coverage.unresolved_material_evidence_gap_ids)
                if self.coverage is not None else set()
            )
            for gap in self.evidence_gaps:
                resolved_ids = set(gap.resolved_by_evidence_ids)
                if not resolved_ids.issubset(citation_by_id):
                    raise ValueError("Evidence Gap resolution references missing Evidence Citations")
                if any(citation_by_id[item].evidence_status is not EvidenceStatus.VERIFIED for item in resolved_ids):
                    raise ValueError("only VERIFIED Evidence Citations may resolve an Evidence Gap")
                if gap.material and gap.gap_id not in unresolved_material_gaps and not resolved_ids:
                    raise ValueError("a material Evidence Gap must remain unresolved or cite explicit resolution evidence")
            return self
        if self.publication_eligibility is None:
            raise ValueError("legacy Desktop Research Handoff requires publication_eligibility")
        if self.coverage is None:
            raise ValueError("legacy Desktop Research Handoff requires coverage")
        evidence_by_id = {item.evidence_id: item for item in self.evidence}
        if len(evidence_by_id) != len(self.evidence):
            raise ValueError("Desktop Research evidence_id values must be unique")
        missing_evidence = sorted({
            evidence_id
            for finding in self.findings
            for evidence_id in finding.evidence_ids
            if evidence_id not in evidence_by_id
        })
        if missing_evidence:
            raise ValueError(f"Findings reference missing Evidence Captures: {missing_evidence}")
        missing_sources = sorted({item.source_id for item in self.evidence}.difference(self.back_references))
        if missing_sources:
            raise ValueError(f"Evidence Captures reference sources absent from back_references: {missing_sources}")
        low_trust_evidence_ids = {
            item.evidence_id
            for item in self.evidence
            if item.source_quality is SourceQuality.LOW_TRUST
            or item.source_type in {SourceType.SOCIAL_MEDIA, SourceType.ONLINE_FORUM}
        }
        for finding in self.findings:
            if finding.material and not any(item not in low_trust_evidence_ids for item in finding.evidence_ids):
                raise ValueError("a material Finding cannot rely solely on LOW_TRUST evidence")
        evidence_ids = set(evidence_by_id)
        unresolved_material_gaps = set(self.coverage.unresolved_material_evidence_gap_ids)
        for gap in self.evidence_gaps:
            resolved_ids = set(gap.resolved_by_evidence_ids)
            if not resolved_ids.issubset(evidence_ids):
                raise ValueError(f"Evidence Gap resolution references missing Evidence Captures: {sorted(resolved_ids - evidence_ids)}")
            if resolved_ids.intersection(low_trust_evidence_ids) or any(
                item.source_quality is SourceQuality.LOW_CONFIDENCE
                for item in self.evidence
                if item.evidence_id in resolved_ids
            ):
                raise ValueError("LOW_TRUST or LOW_CONFIDENCE evidence cannot resolve an Evidence Gap")
            if gap.material and gap.gap_id not in unresolved_material_gaps and not resolved_ids:
                raise ValueError("a material Evidence Gap must remain unresolved or cite explicit resolution evidence")
        return self


class PublicationFeedback(StrictModel):
    schema_version: str = "0.2"
    feedback_id: str
    type: str
    problem: str
    location: str | None = None
    missing_or_conflicting_state: str | None = None
    suggested_destination: str | None = None
    blocking: bool = False
    source_publication_state_id: str | None = None
    source_research_state_id: str | None = None
    evidence_eligible: Literal[False] = False
    research_state_mutation: Literal[False] = False


class PublicationWriterOutput(StrictModel):
    schema_version: str = "0.2"
    output_id: str
    publication_state: PublicationState
    feedback: list[PublicationFeedback] = Field(default_factory=list)

    @model_validator(mode="after")
    def feedback_is_publication_only(self) -> PublicationWriterOutput:
        if any(item.evidence_eligible or item.research_state_mutation for item in self.feedback):
            raise ValueError("Publication Feedback cannot become Research Evidence or mutate Research State")
        return self


class DecisionRequest(StrictModel):
    decision_id: str = Field(pattern=SAFE_IDENTIFIER_PATTERN)
    decision_kind: DecisionKind = DecisionKind.LEGACY_UNCLASSIFIED
    request: str
    status_scope: str
    ai_recommendation: str
    evidence: list[Any] = Field(default_factory=list)
    counterevidence: list[Any] = Field(default_factory=list)
    unknowns: list[Any] = Field(default_factory=list)
    options: list[dict[str, Any]] = Field(default_factory=list)
    downstream_impact: list[str] = Field(default_factory=list)
    becomes_fixed: list[str] = Field(default_factory=list)
    human_questions: list[str] = Field(default_factory=list)
    resume_plan: dict[str, Any] = Field(default_factory=dict)
    references: list[str] = Field(default_factory=list)
    proposed_question_baselines: list[ProposedQuestionBaseline] = Field(default_factory=list)
    status: Literal["PENDING", "RECORDED"] = "PENDING"


class DecisionRecord(StrictModel):
    decision_id: str = Field(pattern=SAFE_IDENTIFIER_PATTERN)
    decision_kind: DecisionKind = DecisionKind.LEGACY_UNCLASSIFIED
    choice: str
    conditions: list[str] = Field(default_factory=list)
    rationale: str | None = None
    decided_by: str
    decided_at: datetime = Field(default_factory=utc_now)


class PublicationBundleManifest(StrictModel):
    schema_version: str = "0.3"
    bundle_id: str
    research_snapshot_id: str
    publication_state_id: str
    eligibility: PublicationEligibility
    input_refs: list[ArtifactRef] = Field(default_factory=list)
    primary_exposition_map: dict[str, str] = Field(default_factory=dict)
    publication_structure_id: str | None = None
    provisional_draft_id: str | None = None
    output_status_ceiling: Literal["INTEGRATED"] = "INTEGRATED"


class ChatInputClassification(StrEnum):
    QUERY = "QUERY"
    PROPOSAL = "PROPOSAL"
    COMMITTABLE_ACTION = "COMMITTABLE_ACTION"
    CONFIRMATION = "CONFIRMATION"
    CANCEL = "CANCEL"


class ConversationActionType(StrEnum):
    SHOW_STATUS = "SHOW_STATUS"
    SHOW_DECISION = "SHOW_DECISION"
    PROPOSE_DECISION = "PROPOSE_DECISION"
    RECORD_DECISION = "RECORD_DECISION"
    SUBMIT_WORK_RESULT = "SUBMIT_WORK_RESULT"
    STOP_AT_BOUNDARY = "STOP_AT_BOUNDARY"
    ABORT_PENDING_RUN = "ABORT_PENDING_RUN"
    REQUEST_RECOVERY = "REQUEST_RECOVERY"
    CONFIRM_RECOVERY = "CONFIRM_RECOVERY"
    CANCEL_PENDING_ACTION = "CANCEL_PENDING_ACTION"
    REGISTER_ATTENTION_DROP = "REGISTER_ATTENTION_DROP"
    ARCHIVE_RESEARCH = "ARCHIVE_RESEARCH"


class ChatTurnInput(StrictModel):
    turn_id: str
    actor: str = Field(min_length=1)
    text: str = ""
    classification: ChatInputClassification | None = None
    action: ConversationActionType | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    expected_state_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class ProposedAction(StrictModel):
    action_id: str
    turn_id: str
    actor: str
    action: ConversationActionType
    parameters: dict[str, Any] = Field(default_factory=dict)
    effect: str
    becomes_fixed: list[str] = Field(default_factory=list)
    does_not_happen_automatically: list[str] = Field(default_factory=list)
    requires_confirmation: bool = True
    expected_state_id: str
    expected_state_sha256: str | None = None
    status: Literal["PROPOSED", "CONFIRMED", "CANCELLED", "REJECTED"] = "PROPOSED"
    created_at: datetime = Field(default_factory=utc_now)


class ConfirmationRequest(StrictModel):
    confirmation_id: str
    action_id: str
    actor: str
    action: ConversationActionType
    exact_effect: str
    becomes_fixed: list[str] = Field(default_factory=list)
    does_not_happen_automatically: list[str] = Field(default_factory=list)
    expected_state_id: str
    expected_state_sha256: str | None = None
    token_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expires_at: datetime
    single_use: Literal[True] = True
    status: Literal["PENDING", "USED", "EXPIRED", "CANCELLED"] = "PENDING"


class ConfirmedAction(StrictModel):
    confirmation_id: str
    action_id: str
    actor: str
    action: ConversationActionType
    confirmed_at: datetime = Field(default_factory=utc_now)


class ActionReceipt(StrictModel):
    receipt_id: str
    action: str
    actor: str
    status: Literal["ACCEPTED", "REJECTED"]
    reason: str
    confirmation_id: str | None = None
    state_before_id: str
    state_before_sha256: str | None = None
    state_after_id: str | None = None
    state_after_sha256: str | None = None
    trace_references: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)


class HumanAttentionRequired(StrictModel):
    reason: str
    references: list[str] = Field(default_factory=list)
    allowed_actions: list[ConversationActionType] = Field(default_factory=list)


class ChatStatusView(StrictModel):
    lane: str
    phase: str
    execution_state: str
    lifecycle_status: str = "ACTIVE"
    state_id: str
    state_sha256: str | None = None
    pending_work_run_id: str | None = None
    pending_decision_ids: list[str] = Field(default_factory=list)
    active_attention_map_id: str | None = None
    pending_attention_drop_ids: list[str] = Field(default_factory=list)
    evidence_summary: dict[str, int] = Field(default_factory=dict)
    allowed_actions: list[ProposedAction] = Field(default_factory=list)
    human_attention: list[HumanAttentionRequired] = Field(default_factory=list)
    recovery_available: bool = True
    trace_references: list[str] = Field(default_factory=list)


class ConversationTurnResult(StrictModel):
    classification: ChatInputClassification
    status_view: ChatStatusView
    proposal: ProposedAction | None = None
    confirmation_request: ConfirmationRequest | None = None
    confirmed_action: ConfirmedAction | None = None
    receipt: ActionReceipt | None = None
    attention: list[HumanAttentionRequired] = Field(default_factory=list)


class RecoveryReasonCode(StrEnum):
    HARNESS_DEFECT = "HARNESS_DEFECT"
    CONTRACT_DEFECT = "CONTRACT_DEFECT"
    SCHEMA_DEFECT = "SCHEMA_DEFECT"
    REDUCER_DEFECT = "REDUCER_DEFECT"
    CONTEXT_CONTAMINATION = "CONTEXT_CONTAMINATION"
    ARTIFACT_ACCESS_DEFECT = "ARTIFACT_ACCESS_DEFECT"
    EVIDENCE_INTEGRITY_FAILURE = "EVIDENCE_INTEGRITY_FAILURE"
    OPERATOR_ERROR = "OPERATOR_ERROR"


class DecisionImpactTreatment(StrEnum):
    PRESERVE = "PRESERVE"
    RECONFIRM = "RECONFIRM"
    INVALIDATE = "INVALIDATE"


class RecoveryStatus(StrEnum):
    REQUESTED = "REQUESTED"
    IMPACT_ASSESSED = "IMPACT_ASSESSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REPLAY_PLANNED = "REPLAY_PLANNED"
    REPLAYED = "REPLAYED"
    INTERRUPTED = "INTERRUPTED"


class RunAbortRecord(StrictModel):
    record_id: str
    run_id: str
    status: Literal["ABORT_REQUESTED", "ABORTED", "REJECTED_INPUT", "SUPERSEDED"]
    reason: str
    actor: str
    confirmation_id: str | None = None
    decision_id: str | None = None
    harness_version: str
    context_pack_sha256: str | None = None
    superseding_run_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class DecisionImpactProposal(StrictModel):
    decision_id: str
    proposed_treatment: DecisionImpactTreatment
    rationale: str
    basis_references: list[str] = Field(default_factory=list)


class RecoveryRequest(StrictModel):
    recovery_id: str = Field(pattern=SAFE_IDENTIFIER_PATTERN)
    requested_by: str = Field(min_length=1)
    reason_code: RecoveryReasonCode
    affected_run_ids: list[str] = Field(min_length=1)
    affected_state_ids: list[str] = Field(min_length=1)
    known_good_baseline_state_id: str
    known_good_baseline_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    defect_summary: str = Field(min_length=1)
    versions_before: dict[str, str] = Field(default_factory=dict)
    versions_after: dict[str, str] = Field(default_factory=dict)
    proposed_replay_phase: str
    downstream_consumers: list[str] = Field(default_factory=list)
    current_head_state_id: str
    current_head_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("affected_run_ids", "affected_state_ids")
    @classmethod
    def identifiers_are_safe(cls, values: list[str]) -> list[str]:
        invalid = [value for value in values if re.fullmatch(SAFE_IDENTIFIER_PATTERN, value) is None]
        if invalid:
            raise ValueError(f"unsafe Recovery identifier(s): {invalid!r}")
        return values


class RecoveryImpactAssessment(StrictModel):
    recovery_id: str
    affected_run_ids: list[str]
    affected_state_ids: list[str]
    affected_artifact_ids: list[str] = Field(default_factory=list)
    decision_impacts: list[DecisionImpactProposal] = Field(default_factory=list)
    publication_impacts: list[dict[str, Any]] = Field(default_factory=list)
    invalidated_context_exclusions: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    bounded: Literal[True] = True
    assessed_at: datetime = Field(default_factory=utc_now)


class RecoveryDecision(StrictModel):
    recovery_id: str
    decision_id: str
    status: Literal["PENDING", "APPROVED", "REJECTED"] = "PENDING"
    decided_by: str
    decision_treatments: dict[str, DecisionImpactTreatment] = Field(default_factory=dict)
    rationale: str | None = None
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    assessment_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    decided_at: datetime = Field(default_factory=utc_now)


class InvalidatedLineage(StrictModel):
    lineage_id: str
    recovery_id: str
    run_id: str | None = None
    state_id: str | None = None
    artifact_ids: list[str] = Field(default_factory=list)
    original_sha256: str | None = None
    status: Literal["INVALIDATED", "SUPERSEDED"]
    reason_code: RecoveryReasonCode
    created_at: datetime = Field(default_factory=utc_now)


class ReplayPlan(StrictModel):
    plan_id: str
    recovery_id: str
    approved_decision_id: str
    known_good_baseline_state_id: str
    known_good_baseline_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    recovery_state_id: str
    recovery_state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    replay_phase: str
    new_run_ids: list[str] = Field(default_factory=list)
    forbidden_actions: list[str] = Field(default_factory=lambda: ["DIRECT_HEAD_REWIND", "OVERWRITE_PRIOR_RUN"])
    status: Literal["APPROVED", "EXECUTED"] = "APPROVED"
    created_at: datetime = Field(default_factory=utc_now)


class ReplayExecution(StrictModel):
    execution_id: str
    recovery_id: str
    plan_id: str
    status: Literal["REPLAYED", "INTERRUPTED"]
    new_run_ids: list[str] = Field(default_factory=list)
    resulting_state_id: str | None = None
    uncertainty: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)


class RecoveryRecord(StrictModel):
    record_id: str
    recovery_id: str
    status: RecoveryStatus
    request_ref: str
    assessment_ref: str | None = None
    decision_ref: str | None = None
    replay_plan_ref: str | None = None
    invalidated_lineage_refs: list[str] = Field(default_factory=list)
    prior_head_state_id: str
    new_head_state_id: str | None = None
    uncertainty: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)


# ResearchBrief is declared after the legacy model block so older snapshots can
# still be imported without changing their serialized shape.
DesktopResearchContextSpec.model_rebuild()
