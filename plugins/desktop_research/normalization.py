from __future__ import annotations

import hashlib
import re
from typing import Any, Mapping

from core.runtime.transition_models import (
    ObjectRef,
    StateDeltaProposal,
    TransitionAction,
    TransitionKind,
)

from .result_validation import DesktopResearchResultValidator


_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _id(prefix: str, basis: str) -> str:
    candidate = f"{prefix}-{basis}"
    if len(candidate) <= 128 and _SAFE_ID.match(candidate):
        return candidate
    digest = hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}-{digest}"


class DesktopResearchNormalizer:
    """PR20 CapabilityResultNormalizer for canonical Desktop Research."""

    def __init__(
        self,
        trace_store,
        context_extension_store,
        artifact_store,
        operational_store,
    ) -> None:
        self._traces = trace_store
        self._contexts = context_extension_store
        self._artifacts = artifact_store
        self._validator = DesktopResearchResultValidator(
            artifact_store,
            operational_store,
            diagnostic_store=trace_store,
        )

    def supports(
        self,
        capability_contract_id: str,
        function_id: str,
        contract_version: str,
    ) -> bool:
        return (capability_contract_id, function_id, contract_version) == (
            "desktop-research", "investigate", "0.1.0"
        )

    def _load_inputs(self, handoff: Mapping[str, Any]):
        run_id = str(handoff["run_id"])
        run = self._traces.load_run(run_id)
        if run is None:
            raise ValueError("Desktop Run is missing from execution trace")
        context_pack = self._traces.load_context_pack(run.context_pack_id)
        if context_pack is None:
            raise ValueError("Desktop Context Pack is missing from execution trace")
        context_extension = self._contexts.load(
            run.capability_id,
            run.capability_version,
            run.function_id,
            run.context_pack_id,
        )
        if context_extension is None:
            raise ValueError("Desktop Context extension is missing from immutable input store")
        return run, context_pack, context_extension

    def validate_extension(
        self,
        handoff: Mapping[str, Any],
        extension: Mapping[str, Any] | None,
        context: Mapping[str, Any],
    ) -> tuple[str, ...]:
        del context
        try:
            run, context_pack, context_extension = self._load_inputs(handoff)
            return self._validator.validate(
                handoff,
                extension,
                context_pack,
                context_extension,
                run_id=run.run_id,
            )
        except Exception as exc:
            return (f"DR-RESULT-BINDING-001: {exc}",)

    def normalize(
        self,
        handoff: Mapping[str, Any],
        extension: Mapping[str, Any] | None,
        context: Mapping[str, Any],
    ) -> StateDeltaProposal:
        if extension is None:
            raise ValueError("Desktop result extension is required")
        run, context_pack, _context_extension = self._load_inputs(handoff)
        project_ref = str(context["project_ref"])
        actions: list[TransitionAction] = []
        affected: list[ObjectRef] = []
        object_ids: set[tuple[str, str]] = set()

        def propose(obj: Mapping[str, Any]) -> None:
            key = (str(obj["kind"]), str(obj["id"]))
            if key in object_ids:
                return
            object_ids.add(key)
            actions.append(
                TransitionAction(
                    TransitionKind.CREATE_OBJECT,
                    {"object": dict(obj)},
                    source_refs=(str(handoff["handoff_id"]),),
                )
            )
            affected.append(ObjectRef(*key))

        artifact_index = {
            item.artifact_id: item for item in self._artifacts.artifacts_for(run.run_id)
        }
        for detail in extension["source_capture_details"]:
            for role_key, role_name in (
                ("original_capture", "desktop_research_original_capture"),
                ("text_rendition", "desktop_research_text_rendition"),
            ):
                ref = str(detail[role_key]["content_reference"])
                meta = artifact_index.get(ref)
                if meta is None:
                    continue
                propose({
                    "schema_version": "0.1.0",
                    "id": _id("ART", f"{run.run_id}:{ref}"),
                    "kind": "artifact",
                    "revision": 0,
                    "project_id": project_ref,
                    "role": role_name,
                    "lane": "research",
                    "artifact_class": "process",
                    "locator": meta.storage_locator,
                    "content_digest": meta.digest,
                    "evidence_eligible": False,
                })

        source_ids: dict[str, str] = {}
        evidence_ids: dict[str, str] = {}
        counter_ids: dict[str, str] = {}

        if str(handoff["execution_mode"]) == "real":
            details = {
                str(item["capture_id"]): item
                for item in extension["source_capture_details"]
            }
            for capture in handoff["outputs"]["source_captures"]:
                capture_id = str(capture["capture_id"])
                detail = details[capture_id]
                source_id = _id("SRC", f"{run.run_id}:{capture_id}")
                source_ids[capture_id] = source_id
                propose({
                    "schema_version": "0.1.0",
                    "id": source_id,
                    "kind": "source",
                    "revision": 0,
                    "project_id": project_ref,
                    "source_type": str(detail["source_category"]),
                    "canonical_locator": str(detail["exact_locator"]),
                    "acquired_at": str(detail["acquired_at"]),
                    "content_digest": str(detail["original_capture"]["content_digest"]),
                    "media_type": str(detail["original_capture"]["media_type"]),
                })

            resources = {
                str(item["reference_id"]): item for item in context_pack["resources"]
            }

            def source_for_basis(basis: Mapping[str, Any]) -> str | None:
                if basis["basis_type"] == "source_capture":
                    return source_ids.get(str(basis["capture_id"]))
                resource = resources.get(str(basis["resource_reference_id"]))
                if resource and resource.get("reference_type") == "source":
                    object_id = resource.get("object_id")
                    return str(object_id) if object_id is not None else None
                return None

            for item in handoff["outputs"]["evidence_candidates"]:
                source_id = source_for_basis(item["source_basis"])
                if source_id is None:
                    continue
                output_id = str(item["evidence_candidate_id"])
                eid = _id("EVD", f"{run.run_id}:{output_id}")
                evidence_ids[output_id] = eid
                propose({
                    "schema_version": "0.1.0", "id": eid, "kind": "evidence",
                    "revision": 0, "project_id": project_ref, "source_id": source_id,
                    "locator": str(item["locator"]), "statement": str(item["statement"]),
                    "evidence_kind": "supporting", "verification_status": "unverified",
                    "evidence_mode": "empirical", "limitations": list(item.get("limitations", ())),
                })

            for item in handoff["outputs"]["counterevidence"]:
                source_id = source_for_basis(item["source_basis"])
                if source_id is None:
                    continue
                output_id = str(item["counterevidence_id"])
                eid = _id("EVD", f"{run.run_id}:{output_id}")
                counter_ids[output_id] = eid
                propose({
                    "schema_version": "0.1.0", "id": eid, "kind": "evidence",
                    "revision": 0, "project_id": project_ref, "source_id": source_id,
                    "locator": str(item["locator"]), "statement": str(item["statement"]),
                    "evidence_kind": "counterevidence", "verification_status": "unverified",
                    "evidence_mode": "empirical", "limitations": [],
                })

            for item in handoff["outputs"]["candidate_findings"]:
                support = [evidence_ids.get(str(ref)) for ref in item["supporting_evidence_candidate_ids"]]
                counter = [counter_ids.get(str(ref)) for ref in item["counterevidence_candidate_ids"]]
                if any(ref is None for ref in (*support, *counter)):
                    continue
                fid = _id("FND", f"{run.run_id}:{item['candidate_finding_id']}")
                propose({
                    "schema_version": "0.1.0", "id": fid, "kind": "finding",
                    "revision": 0, "project_id": project_ref,
                    "question_ids": list(item["question_ids"]), "statement": str(item["statement"]),
                    "evidence_ids": [str(ref) for ref in support],
                    "counter_evidence_ids": [str(ref) for ref in counter],
                    "boundary_conditions": list(item["boundary_conditions"]),
                    "limitations": list(item["limitations"]), "adoption_state": "candidate",
                })

        provenance = {
            "run_id": run.run_id,
            "implementation_id": run.implementation_id,
            "implementation_version": run.implementation_version,
            "execution_mode": run.execution_mode,
            "desktop_research": {
                "search_trace": extension["search_trace"],
                "coverage_assessment": extension["coverage_assessment"],
                "evidence_gap_assessments": extension["evidence_gap_assessments"],
                "null_results": extension["null_results"],
                "candidate_next_method_ids": extension["candidate_next_method_ids"],
                "handoff_outputs": handoff["outputs"],
            },
        }
        proposal = StateDeltaProposal(
            proposal_id=_id("SDP", f"desktop-research:{run.run_id}"),
            project_ref=project_ref,
            lineage_ref=str(context["lineage_ref"]),
            source_refs=(str(handoff["handoff_id"]),),
            proposed_actions=tuple(actions),
            affected_refs=tuple(affected),
            rationale=(
                "Candidate-only Desktop Research normalization; no Source/Evidence/Finding "
                "verification or adoption is performed by the capability runtime."
            ),
            required_human_decision_kinds=("research_adoption",),
            current_snapshot_ref=str(context["current_snapshot_ref"]),
            current_snapshot_digest=str(context["current_snapshot_digest"]),
            provenance=provenance,
            candidate_only=True,
        )
        return proposal.with_calculated_digest()
