from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import unittest

from core.runtime import (
    Actor,
    CapabilityNormalizationBoundary,
    CanonicalResearchObjectSchemaValidator,
    LineageView,
    NormalizationRejected,
    ObjectRef,
    StateDeltaProposal,
    StateTransitionRejected,
    StateTransitionRequest,
    StateTransitionService,
    StateView,
    TransitionAction,
    TransitionKind,
    canonical_digest,
    reduce_state,
)
from core.runtime.testing import InMemoryResearchStateRepository
from core.runtime.transition_models import CommitReceipt, with_content_digest


ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((ROOT / "core/models/research-object.schema.json").read_text(encoding="utf-8"))
SCHEMA_VALIDATOR = CanonicalResearchObjectSchemaValidator(SCHEMA)


def project(project_id: str = "PRJ-1") -> dict:
    return {"schema_version":"0.1.0","id":project_id,"kind":"project","revision":0,"title":"Runtime fixture"}


def rq(*, project_id: str = "PRJ-1", revision: int = 0, state: str = "candidate", decision_ids=()) -> dict:
    value = {"schema_version":"0.1.0","id":"RQ-1","kind":"research_question","revision":revision,"project_id":project_id,"text":"What is supported?","adoption_state":state}
    if decision_ids:
        value["decision_ids"] = list(decision_ids)
    return value


def source(*, project_id: str = "PRJ-1") -> dict:
    return {"schema_version":"0.1.0","id":"SRC-1","kind":"source","revision":0,"project_id":project_id,"source_type":"report","canonical_locator":"fixture://source/1"}


def evidence(*, project_id: str = "PRJ-1", revision: int = 0, evidence_kind: str = "counterevidence", verification: str = "unverified", mode: str = "empirical", decision_ids=(), limitations=()) -> dict:
    value = {"schema_version":"0.1.0","id":"EVD-1","kind":"evidence","revision":revision,"project_id":project_id,"source_id":"SRC-1","locator":"p.1","statement":"Fixture evidence","evidence_kind":evidence_kind,"verification_status":verification,"evidence_mode":mode,"limitations":list(limitations)}
    if decision_ids:
        value["decision_ids"] = list(decision_ids)
    return value


def finding(*, project_id: str = "PRJ-1", revision: int = 0, statement: str = "Candidate finding", state: str = "candidate", question_id: str = "RQ-1", decision_ids=()) -> dict:
    value = {"schema_version":"0.1.0","id":"FND-1","kind":"finding","revision":revision,"project_id":project_id,"question_ids":[question_id],"statement":statement,"adoption_state":state,"limitations":["fixture scope"]}
    if decision_ids:
        value["decision_ids"] = list(decision_ids)
    return value


def decision(decision_id: str, decision_kind: str, choice: str, subject_kind: str, subject_id: str, *, project_id: str = "PRJ-1") -> dict:
    return {"schema_version":"0.1.0","id":decision_id,"kind":"decision","revision":0,"project_id":project_id,"decision_kind":decision_kind,"subjects":[{"kind":subject_kind,"id":subject_id}],"choice":choice,"actor_type":"human","decided_by":"fixture-human","decided_at":"2026-08-26T00:00:00Z"}


def snapshot(snapshot_id: str, objects: list[dict], *, project_id: str = "PRJ-1", mode: str = "real", prior: str | None = None) -> dict:
    value = {
        "schema_version":"0.1.0","id":snapshot_id,"kind":"snapshot","revision":0,"project_id":project_id,
        "snapshot_type":"research","created_at":"2026-08-25T00:00:00Z","mode":mode,
        "members":[{"kind":obj["kind"],"id":obj["id"],"revision":obj["revision"],"digest":canonical_digest(obj)} for obj in sorted(objects,key=lambda item:(item["kind"],item["id"]))]
    }
    if prior:
        value["prior_snapshot_id"] = prior
    return with_content_digest(value)


def seed_state(*, objects=None, decisions=(), mode="real", snapshot_id="SNP-0", project_id="PRJ-1", constraints=None, project_config=None, source_modes=None, non_reusable=()) -> StateView:
    objects = [project(project_id)] if objects is None else list(objects)
    snap = snapshot(snapshot_id, objects, project_id=project_id, mode=mode)
    cfg_digest = canonical_digest({"fixture":"config", "project":project_id})
    profile_digest = canonical_digest({"fixture":"profiles", "project":project_id})
    line = LineageView(
        lineage_id="LIN-1", lineage_kind="primary", head_snapshot_ref=snap["id"], head_snapshot_digest=snap["content_digest"],
        head_snapshot_revision=0, execution_mode=mode, project_config_ref="CFG-1", project_config_digest=cfg_digest,
        effective_profile_set_ref="EPS-1", effective_profile_set_digest=profile_digest,
    )
    all_objects = [*objects, snap, *decisions]
    return StateView(
        project_ref=project_id, lineage_ref="LIN-1", current_snapshot=snap, objects=tuple(all_objects), decisions=tuple(decisions),
        used_decision_ids=(), lineages=(line,), active_lineage_ref="LIN-1", project_config_ref="CFG-1", project_config_digest=cfg_digest,
        effective_profile_set_ref="EPS-1", effective_profile_set_digest=profile_digest, project_config=project_config or {},
        effective_constraints=constraints or {}, source_modes=source_modes or {}, non_reusable_refs=tuple(non_reusable),
    )


def make_request(state: StateView, actions, *, suffix="1", key=None, new_snapshot_id=None, source_refs=(), actor=None) -> StateTransitionRequest:
    req = StateTransitionRequest(
        transition_id=f"TR-{suffix}", project_ref=state.project_ref, lineage_ref=state.lineage_ref,
        expected_head_snapshot_ref=str(state.current_snapshot["id"]), expected_head_snapshot_digest=str(state.current_snapshot["content_digest"]),
        actor=actor or Actor("human-fixture","human"), actions=tuple(actions), project_config_ref=state.project_config_ref,
        project_config_digest=state.project_config_digest, effective_profile_set_ref=state.effective_profile_set_ref,
        effective_profile_set_digest=state.effective_profile_set_digest, authorization_evidence=(), idempotency_key=key or f"IDEMP-{suffix}",
        submitted_at=f"2026-08-26T00:00:{int(suffix) if suffix.isdigit() else 1:02d}Z", new_snapshot_id=new_snapshot_id or f"SNP-{suffix}",
        commit_id=f"COM-{suffix}", audit_event_id=f"AUD-{suffix}", source_refs=tuple(source_refs),
    )
    return req.with_calculated_digest()


def service(seed: StateView):
    repo = InMemoryResearchStateRepository(seed)
    return repo, StateTransitionService(repo, schema_validator=SCHEMA_VALIDATOR)


def codes(result) -> set[str]:
    return {item.error_code for item in result.issues}
