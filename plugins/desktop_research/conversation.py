from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from core.conversation.models import CapabilityMaterialization, ConversationRuntimeError
from core.conversation.validation import canonical_digest

from .submission import with_context_extension_digest


class DesktopResearchConversationMaterializer:
    """PR25 adapter from a typed Desktop action to PR9 + PR11 bounded context.

    Resource access is ID-based: conversational text/payload cannot introduce an
    arbitrary path or URL. Only resources pre-registered in the injected catalog
    can enter the Context Pack, and each receives an explicit Desktop role.
    """

    materializer_id = "desktop_research.investigate@0.1.0"

    def __init__(
        self,
        *,
        effective_profile_set_provider,
        resource_catalog: Mapping[str, Mapping[str, Any]] | None = None,
        resource_roles: Mapping[str, str] | None = None,
    ) -> None:
        self._profiles = effective_profile_set_provider
        self._resources = dict(resource_catalog or {})
        self._roles = dict(resource_roles or {})

    def materialize(self, proposal_payload, state, descriptor, *, context_pack_id):
        question_id = str(proposal_payload.get("question_id", ""))
        if not question_id:
            raise ConversationRuntimeError("CONV-PIN-001", "Desktop action requires question_id")
        rq = next(
            (obj for obj in state.effective_objects()
             if obj.get("kind") == "research_question" and str(obj.get("id")) == question_id),
            None,
        )
        if rq is None:
            raise ConversationRuntimeError("CONV-PIN-001", "Desktop target RQ is not in current Snapshot")

        requested = tuple(str(item) for item in proposal_payload.get("resource_reference_ids", ()))
        unknown = [item for item in requested if item not in self._resources]
        if unknown:
            raise ConversationRuntimeError(
                "CONV-PIN-001",
                "unregistered resource references cannot enter Context Pack: " + ", ".join(unknown),
            )
        resources = [deepcopy(dict(self._resources[item])) for item in requested]
        role_bindings = []
        for item in requested:
            role = self._roles.get(item)
            if role not in {"research_context", "candidate_source", "research_artifact"}:
                raise ConversationRuntimeError(
                    "CONV-PIN-001", f"resource has no authorized Desktop role: {item}"
                )
            role_bindings.append({"reference_id": item, "role": role})

        effective = deepcopy(dict(self._profiles(state.project_ref, state.effective_profile_set_digest)))
        if effective.get("content_digest") != state.effective_profile_set_digest:
            raise ConversationRuntimeError("CONV-PIN-001", "Effective Profile Set provider returned wrong pin")
        snapshot = state.current_snapshot
        project = state.project_config
        attention = deepcopy(list(project.get("research_attention", ())))
        guards = project.get("guards", project.get("project_guards", {}))
        if not isinstance(guards, Mapping):
            guards = {}
        project_constraints = {
            "requirements": deepcopy(list(guards.get("requirements", ()))),
            "prohibitions": deepcopy(list(guards.get("prohibitions", ()))),
            "must_not_claim": deepcopy(list(project.get("must_not_claim", guards.get("must_not_claim", ())))),
        }
        raw_constraints = state.effective_constraints
        if isinstance(raw_constraints, Mapping):
            effective_constraints = [deepcopy(dict(item)) for item in raw_constraints.values() if isinstance(item, Mapping)]
        else:
            effective_constraints = [deepcopy(dict(item)) for item in raw_constraints]
        context = {
            "schema_version": "0.1.0",
            "context_pack_id": context_pack_id,
            "project_id": state.project_ref,
            "purpose": str(proposal_payload.get("purpose") or f"Bounded Desktop Research for {question_id}."),
            "pins": {
                "project_config": {"configuration_digest": state.project_config_digest},
                "effective_profile_set": effective,
                "research_snapshot": {
                    "snapshot_id": str(snapshot["id"]),
                    "revision": int(snapshot.get("revision", 0)),
                    "content_digest": str(snapshot["content_digest"]),
                },
            },
            "question_ids": [question_id],
            "research_object_references": [{
                "kind": "research_question",
                "id": question_id,
                "revision": int(rq.get("revision", 0)),
            }],
            "resources": resources,
            "research_attention": attention,
            "project_constraints": project_constraints,
            "effective_constraints": effective_constraints,
        }
        context["bounds"] = {
            "max_questions": len(context["question_ids"]),
            "max_research_object_references": len(context["research_object_references"]),
            "max_resources": len(resources),
            "max_attention_items": len(attention),
            "max_project_guards": sum(len(value) for value in project_constraints.values()),
            "max_effective_constraints": len(context["effective_constraints"]),
        }
        context["context_pack_digest"] = canonical_digest(context)

        dimensions = deepcopy(list(proposal_payload.get("coverage_dimensions", ()))) or [
            {"dimension_id": "COV-SUPPORT", "label": "Supporting material", "required": True},
            {"dimension_id": "COV-COUNTER", "label": "Counterevidence and limitations", "required": True},
        ]
        policy = proposal_payload.get("desktop_policy", {})
        extension = with_context_extension_digest({
            "schema_version": "0.1.0",
            "extension_type": "desktop_research_context",
            "context_binding": {
                "context_pack_id": context_pack_id,
                "context_pack_digest": context["context_pack_digest"],
                "project_id": state.project_ref,
            },
            "target": {"target_type": "research_question", "question_id": question_id},
            "retrieval_scope": {
                "scope_statement": str(policy.get("scope_statement") or f"Investigate bounded external information relevant to {question_id}."),
                "in_scope": list(policy.get("in_scope", ["authorized external source retrieval"])),
                "out_of_scope": list(policy.get("out_of_scope", ["Writer/Publication material as research evidence"])),
            },
            "allowed_source_categories": list(policy.get("allowed_source_categories", ["other"])),
            "resource_role_bindings": role_bindings,
            "forbidden_resource_roles": [
                "writer_material", "publication_material", "publication_feedback", "archive_provenance"
            ],
            "coverage_dimensions": dimensions,
            "budget": {
                "max_total_resources": len(resources),
                "max_candidate_source_resources": sum(item["role"] == "candidate_source" for item in role_bindings),
                "max_artifact_resources": sum(item["role"] == "research_artifact" for item in role_bindings),
                "max_acquired_source_captures": int(policy.get("max_acquired_source_captures", 20)),
                "max_search_trace_entries": int(policy.get("max_search_trace_entries", 50)),
                "max_text_rendition_bytes": int(policy.get("max_text_rendition_bytes", 2_000_000)),
                "max_original_capture_bytes": int(policy.get("max_original_capture_bytes", 10_000_000)),
                "max_capture_artifacts": int(policy.get("max_capture_artifacts", 40)),
            },
        })
        return CapabilityMaterialization(
            descriptor=deepcopy(dict(descriptor)),
            context_pack=context,
            context_extension=extension,
            lineage_ref=state.lineage_ref,
            execution_mode="real",
        )
