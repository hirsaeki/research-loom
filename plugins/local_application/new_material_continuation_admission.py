from __future__ import annotations

from copy import deepcopy
import hashlib
from typing import Any, Mapping

from core.execution import RunStatus
from plugins.local_conversation_store import find_state_delta_proposals_by_provenance_run_id
from plugins.local_execution_store import (
    canonical_handoff_for,
    diagnostics_for,
    latest_diagnostic_for,
    result_extensions_for_run,
)

from .facade import LocalApplicationError
from .material_content_facade import _artifact_pair_for_capture
from .material_reacquisition_facade import (
    _CAPABILITY_ID as _MRA_CAPABILITY_ID,
    _NEW_MATERIAL_ROLES,
    _RESULT_DIAGNOSTIC as _MRA_RESULT_DIAGNOSTIC,
)

_CONTINUATION_BINDING_DIAGNOSTIC = "desktop_research.new_material_continuation.binding"
_CONTINUATION_CLAIM_DIAGNOSTIC = "desktop_research.new_material_continuation.claim"

def _new_id(old: str, reacquisition_run_id: str) -> str:
    digest = hashlib.sha256(f"{reacquisition_run_id}\0{old}".encode("utf-8")).hexdigest()[:24]
    return f"NMV-{digest}"


def _require_new_material_artifact_class(
    metadata,
    result: Mapping[str, Any],
    reacquisition_run_id: str,
) -> None:
    """Admission guard for the exact persisted NEW_MATERIAL_VERSION artifact."""
    if (
        metadata.run_id != reacquisition_run_id
        or metadata.role != _NEW_MATERIAL_ROLES["rendition"]
        or metadata.digest != result.get("actual_digest")
        or metadata.size != result.get("actual_size")
    ):
        raise LocalApplicationError(
            "APPLICATION-NEW-MATERIAL-CONTINUATION-MATERIAL-001",
            "persisted new material does not match the reacquisition result",
        )


def _find_reacquisition_result(application, project_id: str, reacquisition_run_id: str):
    store = application.execution_store
    run = store.load_run(reacquisition_run_id)
    if run is None or run.project_ref != project_id:
        raise LocalApplicationError(
            "APPLICATION-NEW-MATERIAL-CONTINUATION-BINDING-001",
            "reacquisition Run does not resolve in this project",
        )
    if (
        run.capability_id != _MRA_CAPABILITY_ID
        or run.function_id != "reacquire"
        or run.execution_mode != "real"
        or run.status is not RunStatus.COMPLETED
    ):
        raise LocalApplicationError(
            "APPLICATION-NEW-MATERIAL-CONTINUATION-CLASS-001",
            "continuation requires a terminal successful material reacquisition Run",
        )

    records = [
        item["payload"]
        for item in diagnostics_for(
            store, reacquisition_run_id, limit=2, kind=_MRA_RESULT_DIAGNOSTIC
        )
    ]
    if len(records) != 1:
        raise LocalApplicationError(
            "APPLICATION-NEW-MATERIAL-CONTINUATION-CLASS-001",
            "reacquisition result is missing or ambiguous",
        )
    result = records[0]
    if (
        result.get("status") != "NEW_MATERIAL_VERSION"
        or result.get("requires_new_canonical_research_result") is not True
    ):
        raise LocalApplicationError(
            "APPLICATION-NEW-MATERIAL-CONTINUATION-CLASS-001",
            "reacquisition result is not an actionable NEW_MATERIAL_VERSION",
        )

    # #171's live branch is a divergent rendition. It can be paired with the
    # exact verified historical original. A divergent original cannot safely be
    # paired with a historical rendition derived from different bytes, so keep
    # that future branch closed rather than inventing a generic promotion path.
    kind = str(result.get("new_material_kind") or result.get("kind") or "")
    if kind != "rendition":
        raise LocalApplicationError(
            "APPLICATION-NEW-MATERIAL-CONTINUATION-PAIR-001",
            "current continuation requires a divergent rendition with a verified historical original",
        )

    artifact_id = str(result.get("new_artifact_id") or "")
    metadata = next(
        (
            item
            for item in store.artifacts_for(reacquisition_run_id)
            if item.artifact_id == artifact_id
        ),
        None,
    )
    if not artifact_id or metadata is None:
        raise LocalApplicationError(
            "APPLICATION-NEW-MATERIAL-CONTINUATION-MATERIAL-001",
            "persisted new material metadata does not resolve in the reacquisition Run",
        )
    try:
        artifact = store.load_artifact_verified_once(artifact_id)
    except Exception as exc:
        raise LocalApplicationError(
            "APPLICATION-NEW-MATERIAL-CONTINUATION-MATERIAL-001",
            "persisted new material cannot be verified by digest and size",
        ) from exc
    _require_new_material_artifact_class(metadata, result, reacquisition_run_id)

    historical_run_id = str(result.get("historical_run_id") or "")
    capture_id = str(result.get("historical_capture_id") or "")
    historical_artifact_id = str(result.get("historical_artifact_id") or "")
    if (
        run.parent_run_id != historical_run_id
        or metadata.provenance.get("historical_run_id") != historical_run_id
        or metadata.provenance.get("historical_capture_id") != capture_id
        or metadata.provenance.get("historical_artifact_id") != historical_artifact_id
        or metadata.provenance.get("relation")
        != "regenerated_version_of_historical_rendition"
    ):
        raise LocalApplicationError(
            "APPLICATION-NEW-MATERIAL-CONTINUATION-PROVENANCE-001",
            "new material provenance does not resolve intact to its historical target",
        )

    historical, original, historical_rendition, capture = _artifact_pair_for_capture(
        store, project_id, historical_run_id, capture_id
    )
    derivation = result.get("derivation_source")
    if (
        historical.status is not RunStatus.COMPLETED
        or historical_rendition.artifact_id != historical_artifact_id
        or not isinstance(derivation, Mapping)
        or derivation.get("artifact_id") != original.artifact_id
        or derivation.get("digest") != original.digest
        or derivation.get("size") != original.size
        or metadata.provenance.get("derivation_source") != derivation
        or metadata.provenance.get("exact_locator")
        != result.get("requested_exact_locator")
        or metadata.provenance.get("acquired_at") != result.get("reacquired_at")
        or metadata.provenance.get("provider") != result.get("provider")
    ):
        raise LocalApplicationError(
            "APPLICATION-NEW-MATERIAL-CONTINUATION-PROVENANCE-001",
            "reacquisition provenance or paired historical material is inconsistent",
        )
    try:
        store.load_artifact_verified_once(original.artifact_id)
    except Exception as exc:
        raise LocalApplicationError(
            "APPLICATION-NEW-MATERIAL-CONTINUATION-PAIR-001",
            "verified historical original required for the new rendition is unavailable",
        ) from exc
    return run, result, artifact, historical, original, capture


def _continuation_claim(store, reacquisition_run_id: str) -> dict[str, Any] | None:
    records = [
        item.get("payload")
        for item in diagnostics_for(
            store, reacquisition_run_id, limit=2, kind=_CONTINUATION_CLAIM_DIAGNOSTIC
        )
    ]
    if not records:
        return None
    if len(records) != 1 or not isinstance(records[0], Mapping):
        raise LocalApplicationError(
            "APPLICATION-NEW-MATERIAL-CONTINUATION-IDEMPOTENCY-001",
            "new-material continuation claim is ambiguous or corrupt",
        )
    claim = deepcopy(dict(records[0]))
    if (
        claim.get("relation") != "new_material_version_continuation_claim"
        or claim.get("reacquisition_run_id") != reacquisition_run_id
        or not isinstance(claim.get("historical_run_id"), str)
        or not isinstance(claim.get("historical_capture_id"), str)
        or not isinstance(claim.get("new_material_artifact_id"), str)
    ):
        raise LocalApplicationError(
            "APPLICATION-NEW-MATERIAL-CONTINUATION-IDEMPOTENCY-001",
            "new-material continuation claim is invalid",
        )
    return claim


def _continuation_binding(store, reacquisition_run_id: str) -> dict[str, Any] | None:
    latest = latest_diagnostic_for(
        store,
        reacquisition_run_id,
        kind=_CONTINUATION_BINDING_DIAGNOSTIC,
    )
    if latest is None:
        return None
    record = latest.get("payload")
    if not isinstance(record, Mapping):
        raise LocalApplicationError(
            "APPLICATION-NEW-MATERIAL-CONTINUATION-IDEMPOTENCY-001",
            "new-material continuation binding is ambiguous or corrupt",
        )
    binding = deepcopy(dict(record))
    if (
        binding.get("relation") != "new_material_version_continuation"
        or binding.get("reacquisition_run_id") != reacquisition_run_id
        or not isinstance(binding.get("new_run_id"), str)
        or not binding["new_run_id"]
    ):
        raise LocalApplicationError(
            "APPLICATION-NEW-MATERIAL-CONTINUATION-IDEMPOTENCY-001",
            "new-material continuation binding is invalid",
        )
    return binding


def _validate_continuation_binding(
    application,
    project_id: str,
    binding: Mapping[str, Any],
    result: Mapping[str, Any],
    historical,
    *,
    require_mirror: bool = True,
    require_completed_capture: bool = True,
) -> Any:
    store = application.execution_store
    new_run_id = str(binding.get("new_run_id") or "")
    new_run = store.load_run(new_run_id)
    expected = {
        "relation": "new_material_version_continuation",
        "reacquisition_run_id": str(binding.get("reacquisition_run_id") or ""),
        "historical_run_id": historical.run_id,
        "historical_capture_id": str(result["historical_capture_id"]),
        "new_material_artifact_id": str(result["new_artifact_id"]),
        "new_run_id": new_run_id,
    }
    if any(binding.get(key) != value for key, value in expected.items()):
        raise LocalApplicationError(
            "APPLICATION-NEW-MATERIAL-CONTINUATION-IDEMPOTENCY-001",
            "new-material continuation binding no longer matches its admitted material",
        )
    if (
        new_run is None
        or new_run.project_ref != project_id
        or new_run.capability_id != "desktop-research"
        or new_run.function_id != "investigate"
        or new_run.execution_mode != "real"
    ):
        raise LocalApplicationError(
            "APPLICATION-NEW-MATERIAL-CONTINUATION-IDEMPOTENCY-001",
            "bound continuation Run is missing or has incompatible execution identity",
        )
    if new_run.parent_run_id is not None:
        parent = store.load_run(new_run.parent_run_id)
        if (
            parent is None
            or parent.project_ref != project_id
            or parent.capability_id != "desktop-research"
            or parent.function_id != "investigate"
            or parent.execution_mode != "real"
            or parent.status not in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.ABORTED}
        ):
            raise LocalApplicationError(
                "APPLICATION-NEW-MATERIAL-CONTINUATION-IDEMPOTENCY-001",
                "continuation retry parent has incompatible execution identity",
            )
    own = [
        item.get("payload")
        for item in diagnostics_for(
            store, new_run_id, limit=2, kind=_CONTINUATION_BINDING_DIAGNOSTIC
        )
    ]
    if not own and not require_mirror:
        own = []
    elif len(own) != 1 or own[0] != dict(binding):
        raise LocalApplicationError(
            "APPLICATION-NEW-MATERIAL-CONTINUATION-IDEMPOTENCY-001",
            "continuation Run does not carry the same immutable reacquisition binding",
        )
    if new_run.status is RunStatus.COMPLETED and require_completed_capture:
        target = [
            item
            for item in store.artifacts_for(new_run_id)
            if item.role == "desktop_research.text_rendition"
            and item.provenance.get("relation") == "new_material_version_continuation"
            and item.provenance.get("reacquisition_run_id") == binding["reacquisition_run_id"]
            and item.provenance.get("historical_capture_id") == result["historical_capture_id"]
            and item.provenance.get("reacquired_artifact_id") == result["new_artifact_id"]
        ]
        if len(target) != 1:
            raise LocalApplicationError(
                "APPLICATION-NEW-MATERIAL-CONTINUATION-IDEMPOTENCY-001",
                "completed continuation Run does not contain the bound new material capture",
            )
    return new_run


def _continuation_mirror_complete(store, binding: Mapping[str, Any]) -> bool:
    """Return whether the child Run carries the exact immutable binding mirror."""
    new_run_id = str(binding.get("new_run_id") or "")
    own = [
        item.get("payload")
        for item in diagnostics_for(
            store, new_run_id, limit=2, kind=_CONTINUATION_BINDING_DIAGNOSTIC
        )
    ]
    if not own:
        return False
    if len(own) != 1 or own[0] != dict(binding):
        raise LocalApplicationError(
            "APPLICATION-NEW-MATERIAL-CONTINUATION-IDEMPOTENCY-001",
            "continuation Run does not carry the same immutable reacquisition binding",
        )
    return True


def _completed_continuation_is_reusable(
    application,
    project_id: str,
    binding: Mapping[str, Any],
    result: Mapping[str, Any],
    historical,
) -> bool:
    """Require canonical result closure before treating COMPLETED as reusable success."""
    try:
        run = _validate_continuation_binding(
            application,
            project_id,
            binding,
            result,
            historical,
        )
    except LocalApplicationError:
        # Callers first validate the immutable identity with relaxed operational
        # closure. A failure here therefore means required result closure is
        # incomplete, not that the old Run may be rewritten or trusted.
        return False
    if run.status is not RunStatus.COMPLETED or not run.handoff_ref or not run.handoff_digest:
        return False
    handoff = canonical_handoff_for(application.execution_store, run.handoff_ref)
    if (
        handoff is None
        or handoff.get("run_id") != run.run_id
        or handoff.get("handoff_digest") != run.handoff_digest
    ):
        return False
    extensions = result_extensions_for_run(application.execution_store, run.run_id, limit=2)
    if len(extensions) != 1:
        return False
    extension_binding = extensions[0].get("handoff_binding")
    if not isinstance(extension_binding, Mapping) or (
        extension_binding.get("handoff_id") != run.handoff_ref
        or extension_binding.get("handoff_digest") != run.handoff_digest
        or extension_binding.get("run_id") != run.run_id
    ):
        return False
    proposals = find_state_delta_proposals_by_provenance_run_id(
        application.conversation_store,
        run.run_id,
        limit=2,
    )
    return len(proposals) == 1


def _historical_canonical_result(application, historical_run_id: str):
    store = application.execution_store
    historical = store.load_run(historical_run_id)
    if historical is None or not historical.handoff_ref:
        raise LocalApplicationError(
            "APPLICATION-NEW-MATERIAL-CONTINUATION-RESULT-001",
            "historical canonical Desktop Research result is unavailable",
        )
    handoff = canonical_handoff_for(store, historical.handoff_ref)
    extensions = result_extensions_for_run(store, historical_run_id, limit=3)
    if handoff is None or len(extensions) != 1:
        raise LocalApplicationError(
            "APPLICATION-NEW-MATERIAL-CONTINUATION-RESULT-001",
            "historical canonical Desktop Research result is incomplete or ambiguous",
        )
    return deepcopy(dict(handoff)), deepcopy(dict(extensions[0]))


def _historical_action_payload(application, historical_run_id: str) -> dict[str, Any]:
    correlation = application.conversation_store.load_run_correlation(historical_run_id)
    if correlation is None:
        raise LocalApplicationError(
            "APPLICATION-NEW-MATERIAL-CONTINUATION-PROVENANCE-001",
            "historical Run is not correlated to a public Desktop Research action",
        )
    proposal = application.conversation_store.load_proposal(str(correlation["proposal_id"]))
    action = proposal.get("action") if isinstance(proposal, Mapping) else None
    if (
        not isinstance(action, Mapping)
        or action.get("action_type") != "desktop_research.investigate"
        or not isinstance(action.get("payload"), Mapping)
    ):
        raise LocalApplicationError(
            "APPLICATION-NEW-MATERIAL-CONTINUATION-PROVENANCE-001",
            "historical Desktop Research action is unavailable or unsupported",
        )
    return deepcopy(dict(action["payload"]))
