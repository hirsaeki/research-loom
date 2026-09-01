from __future__ import annotations

from copy import deepcopy
from typing import Mapping

from plugins.local_application.facade import LocalApplicationError
from .virtual_runner_profile import _approved_decision_for, _profile_set_pin


def resolve_virtual_inputs(facade, state, record, design_record, payload):
    questionnaire = deepcopy(dict(record["questionnaire"]))
    rq_ids = [str(item) for item in record["rq_ids"]]
    effective_objects = list(state.effective_objects())
    rq_objects = []
    for rq_id in rq_ids:
        rq = next((item for item in effective_objects if item.get("kind") == "research_question" and item.get("id") == rq_id and item.get("adoption_state") in {"approved", "revised"}), None)
        if rq is None:
            raise LocalApplicationError("APPLICATION-VIRTUAL-RQ-001", f"Instrument RQ is not current authoritative Research State: {rq_id}")
        rq_objects.append(rq)

    method = state.exact_object("method", str(payload["core_method_id"]), int(payload["core_method_revision"]))
    if method is None or method.get("adoption_state") != "approved":
        raise LocalApplicationError("VR-METHOD-BINDING-001", "exact approved Core Method does not resolve in Research State")
    if not set(rq_ids).issubset(set(map(str, method.get("question_ids", ())))):
        raise LocalApplicationError("VR-METHOD-BINDING-001", "approved Core Method does not cover all Instrument RQs")
    method_decisions = [str(item) for item in method.get("decision_ids", ()) if _approved_decision_for(state, str(item), subject_kind="method", subject_id=str(method["id"]))]
    if not method_decisions:
        raise LocalApplicationError("VR-HUMAN-DECISION-001", "approved Core Method lacks a verifiable Human Decision binding")

    protocol = deepcopy(dict(payload["protocol"]))
    method_protocol_ref = method.get("protocol_ref")
    if method_protocol_ref is not None and str(method_protocol_ref) != str(protocol["protocol_id"]):
        raise LocalApplicationError("VR-METHOD-BINDING-001", "approved Core Method protocol_ref does not match the exact Protocol pin")
    material_decisions: list[str] = []
    if protocol["material_revision"]:
        material_decisions.append(str(protocol["material_revision_decision_id"]))

    if questionnaire.get("approval_status") != "approved" or not questionnaire.get("approval_decision_id"):
        raise LocalApplicationError("VR-HUMAN-DECISION-001", "Virtual Runner requires the PR40 canonical Instrument to be approved with its decision binding")
    if questionnaire.get("material_revision") and not questionnaire.get("material_revision_decision_id"):
        raise LocalApplicationError("VR-HUMAN-DECISION-001", "material Instrument revision lacks material_revision_decision_id")

    captured = record["captured_against"]
    snapshot = state.current_snapshot
    if (captured["lineage_ref"] != state.lineage_ref or captured["snapshot_ref"] != snapshot["id"] or captured["snapshot_digest"] != snapshot["content_digest"] or record["project_config_digest"] != state.project_config_digest or record["effective_profile_set_digest"] != state.effective_profile_set_digest):
        raise LocalApplicationError("APPLICATION-VIRTUAL-PIN-001", "Instrument provenance is stale relative to the current Research Snapshot/Profile/Project Config")
    if design_record["captured_against"] != captured or design_record["design"]["content_digest"] != record["design_ref"]["content_digest"]:
        raise LocalApplicationError("APPLICATION-VIRTUAL-PIN-001", "Survey Design binding is stale or inconsistent")

    effective = _profile_set_pin(facade._effective_profile_set(state), state.effective_profile_set_digest)
    attention = deepcopy(list(facade._application.effective_attention(state)))
    guards = state.project_config.get("guards", state.project_config.get("project_guards", {}))
    if not isinstance(guards, Mapping):
        guards = {}
    project_constraints = {
        "requirements": deepcopy(list(guards.get("requirements", ()))),
        "prohibitions": deepcopy(list(guards.get("prohibitions", ()))),
        "must_not_claim": deepcopy(list(state.project_config.get("must_not_claim", guards.get("must_not_claim", ())))),
    }
    raw_constraints = state.effective_constraints
    if isinstance(raw_constraints, Mapping):
        effective_constraints = [deepcopy(dict(item)) for item in raw_constraints.values() if isinstance(item, Mapping)]
    else:
        effective_constraints = [deepcopy(dict(item)) for item in raw_constraints if isinstance(item, Mapping)]
    return questionnaire, rq_ids, rq_objects, method, method_decisions, protocol, material_decisions, snapshot, effective, attention, project_constraints, effective_constraints
