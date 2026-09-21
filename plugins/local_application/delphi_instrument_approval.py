"""Exact, Instrument-scoped human approval; never a Core research adoption.

Like Publication approval, this uses immutable request/receipt documents. The
existing Delphi transaction commits the receipt and its exact Instrument together.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping
from uuid import uuid4

from plugins.local_delphi_store import LocalDelphiStoreError, canonical_digest, registry_digest
from .facade import LocalApplicationError
from .survey_facade import _snapshot


def _request_digest(request):
    return canonical_digest(dict(request), omit=("registry_digest", "request_digest"))


def _basis(target, actor_id):
    logical = deepcopy(target)
    for field in ("created_at", "registry_digest", "content_digest"):
        logical.pop(field, None)
    instrument = logical["instrument"]
    for field in ("content_digest", "approval_status", "approval_decision_id", "material_revision_decision_id"):
        instrument.pop(field, None)
    return {"target": logical, "human_actor_id": actor_id}


def _validated_request(store, project_id, request_id):
    request = store.load(project_id, "approval_request", request_id)
    if request is None:
        raise LocalApplicationError("APPLICATION-DELPHI-AUTHORITY-001", "unknown Instrument approval request")
    if (request.get("request_digest") != _request_digest(request)
        or request.get("content_digest") != canonical_digest(request["request_basis"])
        or request["request_basis"] != _basis(request["target_document"], request["human_actor_id"])):
        raise LocalApplicationError("APPLICATION-DELPHI-AUTHORITY-001", "Instrument approval request binding is invalid")
    return request


def _verify_receipt(request, receipt):
    expected = request["target_document"]
    response = {key: receipt.get(key) for key in ("request_id", "request_digest", "actor", "choice")}
    digest = canonical_digest(response)
    if (receipt.get("choice") not in ("approve_exact", "decline")
        or receipt.get("status") != ("APPROVED" if receipt.get("choice") == "approve_exact" else "DECLINED")
        or receipt.get("request_id") != request["identity"]
        or receipt.get("request_digest") != request["request_digest"]
        or receipt.get("actor") != {"actor_id": request["human_actor_id"], "actor_type": "human"}
        or receipt.get("identity") != expected["instrument"]["approval_decision_id"]
        or receipt.get("project_id") != expected["project_id"]
        or receipt.get("panel_id") != expected["panel_id"]
        or receipt.get("round_sequence") != expected["round_sequence"]
        or receipt.get("target_digest") != expected["content_digest"]
        or receipt.get("response_digest") != digest or receipt.get("content_digest") != digest):
        raise LocalApplicationError("APPLICATION-DELPHI-AUTHORITY-001", "Instrument approval receipt does not match its exact request")


def verify_approval(store, target):
    """Check independent request/receipt bindings, not an Instrument's own label."""
    instrument = target["instrument"]
    receipt_id = instrument.get("approval_decision_id")
    receipt = store.load(target["project_id"], "approval_receipt", str(receipt_id))
    if receipt is None:
        raise LocalApplicationError("APPLICATION-DELPHI-AUTHORITY-001", "approved Instrument requires an exact local Human Decision receipt; ID-only legacy approval is insufficient")
    request = _validated_request(store, target["project_id"], receipt["request_id"])
    _verify_receipt(request, receipt)
    expected = request["target_document"]
    # Capture timestamp and observed Snapshot belong to the saved request, not a
    # new recapture. All semantic target fields and dependency pins still match.
    ignored = ("created_at", "captured_against", "registry_digest")
    if (receipt["choice"] != "approve_exact"
        or canonical_digest(target, omit=ignored) != canonical_digest(expected, omit=ignored)
        or (instrument.get("material_revision") is True and instrument.get("material_revision_decision_id") != receipt_id)):
        raise LocalApplicationError("APPLICATION-DELPHI-AUTHORITY-001", "Human Decision does not approve this exact Instrument/panel/project/version/content")
    return deepcopy(expected)


class DelphiInstrumentApproval:
    def __init__(self, facade):
        self.facade = facade
        self.store = facade._delphi_store()
        self.project_id = facade._project_id

    def request(self, value: Mapping[str, Any]):
        allowed = {"delphi_design_id", "delphi_design_version", "panel_id", "instrument", "derived_from", "human_actor_id"}
        if not isinstance(value, Mapping) or set(value) - allowed:
            raise LocalApplicationError("APPLICATION-DELPHI-INPUT-001", "Instrument approval request contains unknown fields")
        actor_id = value.get("human_actor_id")
        if not isinstance(actor_id, str) or not actor_id.strip():
            raise LocalApplicationError("APPLICATION-DELPHI-AUTHORITY-001", "human_actor_id must identify the intended approver")
        instrument = value.get("instrument")
        if not isinstance(instrument, Mapping):
            raise LocalApplicationError("APPLICATION-DELPHI-INPUT-001", "instrument proposal must be an object")
        # This is a proposal, not an approval. The fully bound, future approved
        # document is returned for human inspection BEFORE any receipt exists.
        proposal = {key: deepcopy(item) for key, item in value.items() if key != "human_actor_id"}
        instrument = proposal["instrument"]
        decision_id = "DLDEC-" + uuid4().hex
        instrument["approval_status"] = "approved"
        instrument["approval_decision_id"] = decision_id
        if instrument.get("material_revision") is True:
            instrument["material_revision_decision_id"] = decision_id
        else:
            instrument.pop("material_revision_decision_id", None)
        try:
            instrument["content_digest"] = canonical_digest(instrument, omit=("content_digest",))
        except (ValueError, TypeError) as exc:
            raise LocalApplicationError("APPLICATION-DELPHI-INPUT-001", "Instrument proposal must contain canonical JSON values") from exc
        state = self.facade._delphi_state()
        target = self.facade._delphi_instrument_document(proposal, state=state)
        target["registry_digest"] = registry_digest(target)
        basis = _basis(target, actor_id)
        request = {
            "schema_version": "0.1.0", "project_id": self.project_id,
            "document_kind": "approval_request", "identity": "DLAR-" + uuid4().hex,
            "version": "1", "panel_id": target["panel_id"], "round_sequence": target["round_sequence"],
            "content_digest": canonical_digest(basis), "created_at": target["created_at"],
            "request_basis": basis, "human_actor_id": actor_id, "target_document": target,
            "scope": "exact_instrument_and_declared_material_revision",
            "research_state_mutation_performed": False,
        }
        request["request_digest"] = _request_digest(request)
        request["registry_digest"] = registry_digest(request)
        try:
            stored, created = self.facade._capture(state, lambda: self.store.capture_approval_request(request))
        except LocalDelphiStoreError as exc:
            raise LocalApplicationError(exc.code, exc.message) from exc
        return {"status": "DECISION_REQUIRED", "idempotent_reuse": not created,
                "request_id": stored["identity"], "request_digest": stored["request_digest"], "request": stored}

    def show(self, request_id):
        if not isinstance(request_id, str) or not request_id:
            raise LocalApplicationError("APPLICATION-DELPHI-INPUT-001", "request_id is required")
        request = _validated_request(self.store, self.project_id, request_id)
        receipt = self.store.load(self.project_id, "approval_receipt", request["target_document"]["instrument"]["approval_decision_id"])
        if receipt is not None:
            _verify_receipt(request, receipt)
            if receipt["choice"] == "approve_exact":
                target = request["target_document"]
                stored = self.store.load(self.project_id, "instrument", target["identity"], target["version"])
                if stored != target:
                    raise LocalApplicationError("APPLICATION-DELPHI-AUTHORITY-001", "approved Instrument/receipt mismatch; restore an exact backup")
        return {"status": "PENDING" if receipt is None else receipt["status"], "request": request, "receipt": receipt}

    def resolve(self, value: Mapping[str, Any]):
        fields = {"request_id", "request_digest", "actor", "choice"}
        if not isinstance(value, Mapping) or set(value) != fields:
            raise LocalApplicationError("APPLICATION-DELPHI-INPUT-001", "approval response requires request_id, request_digest, actor, choice")
        request = _validated_request(self.store, self.project_id, str(value["request_id"]))
        if (value["request_digest"] != request["request_digest"]
            or value["actor"] != {"actor_id": request["human_actor_id"], "actor_type": "human"}
            or value["choice"] not in ("approve_exact", "decline")):
            raise LocalApplicationError("APPLICATION-DELPHI-AUTHORITY-001", "only the bound human may approve or decline this exact request")
        target = request["target_document"]
        receipt = {
            "schema_version": "0.1.0", "project_id": self.project_id,
            "document_kind": "approval_receipt", "identity": target["instrument"]["approval_decision_id"],
            "version": "1", "panel_id": target["panel_id"], "round_sequence": target["round_sequence"],
            "created_at": self.facade._application.clock.now(), "target_digest": target["content_digest"],
            "status": "APPROVED" if value["choice"] == "approve_exact" else "DECLINED",
            **deepcopy(dict(value)), "research_state_mutation_performed": False,
        }
        receipt["response_digest"] = canonical_digest(dict(value))
        receipt["content_digest"] = receipt["response_digest"]
        receipt["registry_digest"] = registry_digest(receipt)
        prior = self.store.load(self.project_id, "approval_receipt", receipt["identity"])
        if prior is not None:
            _verify_receipt(request, prior)
        state = self.facade._delphi_state()
        if prior is None and value["choice"] == "approve_exact":
            if _snapshot(state) != target["captured_against"]:
                raise LocalApplicationError("APPLICATION-DELPHI-STALE-001", "approval request Snapshot is stale; inspect and issue a new request")
            # Revalidate the exact dependency closure before the first effect.
            proposal = {"delphi_design_id": target["design_ref"]["delphi_design_id"],
                        "delphi_design_version": target["design_ref"]["version"], "panel_id": target["panel_id"],
                        "instrument": target["instrument"], "derived_from": target["derived_from"]}
            checked = self.facade._delphi_instrument_document(proposal, state=state, created_at=target["created_at"])
            checked["registry_digest"] = registry_digest(checked)
            if checked != target:
                raise LocalApplicationError("APPLICATION-DELPHI-AUTHORITY-001", "approval target dependencies no longer match")
        try:
            stored, created = self.facade._capture(state, lambda: self.store.resolve_approval(request, receipt))
        except LocalDelphiStoreError as exc:
            raise LocalApplicationError(exc.code, exc.message) from exc
        return {"status": stored["status"], "idempotent_reuse": not created, "receipt": stored,
                "instrument_id": target["identity"], "version": target["version"], "content_digest": target["content_digest"],
                "research_state_mutation_performed": False}
