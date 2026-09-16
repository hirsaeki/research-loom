from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import errno
import hashlib
import os
from threading import RLock
import time
from typing import Any, Mapping

from core.execution import RunStatus
from plugins.desktop_research import DesktopResearchAttemptRecorder, DesktopResearchCaptureService
from plugins.desktop_research.attempts import reconstruct_attempts

from .facade import LocalApplicationError
from .material_content_facade import _artifact_pair_for_capture
from .material_reacquisition_public_facade import LocalApplicationFacade as _BaseLocalApplicationFacade
from . import new_material_continuation_admission as admission

_CONTINUATION_LOCK = RLock()


@contextmanager
def _target_lock(workspace_root, reacquisition_run_id: str):
    """Serialize one continuation target across local processes.

    The lock is operational only: its presence is never persisted as authority or
    used to rewrite an earlier execution fact.
    """
    if workspace_root is None:
        raise LocalApplicationError(
            "APPLICATION-NEW-MATERIAL-CONTINUATION-EXECUTION-001",
            "new-material continuation requires a workspace-bound facade",
        )
    lock_root = workspace_root / ".research-loom" / "new-material-continuation-locks"
    lock_root.mkdir(parents=True, exist_ok=True)
    token = hashlib.sha256(reacquisition_run_id.encode("utf-8")).hexdigest()
    lock_path = lock_root / f"{token}.lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | getattr(os, "O_BINARY", 0), 0o600)
    locked = False
    try:
        if os.name == "nt":
            import msvcrt

            if os.fstat(fd).st_size == 0:
                os.write(fd, b"\0")
                os.fsync(fd)
            os.lseek(fd, 0, os.SEEK_SET)
            while True:
                try:
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    locked = True
                    break
                except OSError as exc:
                    if exc.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                        raise
                    time.sleep(0.05)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX)
            locked = True
        yield
    finally:
        if locked:
            if os.name == "nt":
                import msvcrt

                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)

def _remap_outputs(
    handoff: Mapping[str, Any],
    *,
    reacquisition_run_id: str,
    capture_map: Mapping[str, str],
) -> tuple[dict[str, Any], dict[str, str]]:
    outputs = deepcopy(dict(handoff["outputs"]))
    outputs.pop("source_captures", None)
    id_map: dict[str, str] = {}
    id_fields = {
        "observations": "observation_id",
        "evidence_candidates": "evidence_candidate_id",
        "candidate_findings": "candidate_finding_id",
        "counterevidence": "counterevidence_id",
        "conflicts": "conflict_id",
        "unknowns": "unknown_id",
        "evidence_gaps": "gap_id",
        "candidate_next_actions": "proposal_id",
        "candidate_next_methods": "proposal_id",
    }
    for collection, field in id_fields.items():
        for item in outputs.get(collection, []):
            old = str(item[field])
            item[field] = id_map.setdefault(old, admission._new_id(old, reacquisition_run_id))

    def remap_ids(values):
        return [id_map.get(str(value), str(value)) for value in values]

    for item in outputs.get("observations", []):
        if "evidence_candidate_ids" in item:
            item["evidence_candidate_ids"] = remap_ids(item["evidence_candidate_ids"])
    for collection in ("evidence_candidates", "counterevidence"):
        for item in outputs.get(collection, []):
            basis = item.get("source_basis", {})
            if basis.get("basis_type") == "source_capture":
                basis["capture_id"] = capture_map[str(basis["capture_id"])]
    for item in outputs.get("candidate_findings", []):
        item["supporting_evidence_candidate_ids"] = remap_ids(
            item.get("supporting_evidence_candidate_ids", [])
        )
        item["counterevidence_candidate_ids"] = remap_ids(
            item.get("counterevidence_candidate_ids", [])
        )
    for item in outputs.get("conflicts", []):
        item["related_output_ids"] = remap_ids(item.get("related_output_ids", []))
    return outputs, id_map


def _research_result_for_new_run(
    handoff: Mapping[str, Any],
    extension: Mapping[str, Any],
    *,
    reacquisition_run_id: str,
    capture_map: Mapping[str, str],
    attempt_map: Mapping[str, str],
) -> dict[str, Any]:
    outputs, id_map = _remap_outputs(
        handoff,
        reacquisition_run_id=reacquisition_run_id,
        capture_map=capture_map,
    )

    citations = []
    for item in extension.get("citation_details", []):
        old_capture = str(item["capture_id"])
        citations.append(
            {
                "citation_id": admission._new_id(str(item["citation_id"]), reacquisition_run_id),
                "handoff_output_kind": item["handoff_output_kind"],
                "handoff_output_id": id_map.get(
                    str(item["handoff_output_id"]), str(item["handoff_output_id"])
                ),
                "capture_id": capture_map[old_capture],
                "excerpt": item["excerpt"],
                "excerpt_locator": item["excerpt_locator"],
            }
        )

    search_entries = []
    for item in extension.get("search_trace", {}).get("entries", []):
        old_attempt = str(item["trace_entry_id"])
        entry = {
            "attempt_id": attempt_map[old_attempt],
            "related_handoff_output_ids": [
                id_map.get(str(value), str(value))
                for value in item.get("related_handoff_output_ids", [])
            ],
        }
        if item.get("notes") is not None:
            entry["notes"] = item["notes"]
        search_entries.append(entry)

    null_results = deepcopy(list(extension.get("null_results", [])))
    for item in null_results:
        item["null_id"] = admission._new_id(str(item["null_id"]), reacquisition_run_id)
        projection = item.get("handoff_projection")
        if isinstance(projection, Mapping):
            projection["output_id"] = id_map.get(
                str(projection["output_id"]), str(projection["output_id"])
            )

    gap_assessments = deepcopy(list(extension.get("evidence_gap_assessments", [])))
    for item in gap_assessments:
        item["gap_id"] = id_map.get(str(item["gap_id"]), str(item["gap_id"]))

    coverage = deepcopy(dict(extension.get("coverage_assessment", {})))
    for dimension in coverage.get("dimensions", []):
        dimension["trace_entry_ids"] = [
            attempt_map[str(value)] for value in dimension.get("trace_entry_ids", [])
        ]

    return {
        "validation": deepcopy(dict(handoff["validation"])),
        "outputs": outputs,
        "capture_ids": [capture_map[key] for key in capture_map],
        "citation_details": citations,
        "search_trace": {"entries": search_entries},
        "null_results": null_results,
        "evidence_gap_assessments": gap_assessments,
        "coverage_assessment": coverage,
        "candidate_next_method_ids": [
            id_map.get(str(value), str(value))
            for value in extension.get("candidate_next_method_ids", [])
        ],
    }


class NewMaterialContinuationService:
    def __init__(self, application, project_id: str, workspace_root) -> None:
        self._application = application
        self._project_id = project_id
        self._workspace_root = workspace_root

    def continue_new_version(self, reacquisition_run_id: str) -> Mapping[str, Any]:
        with _CONTINUATION_LOCK, _target_lock(self._workspace_root, reacquisition_run_id):
            _reacq, result, new_artifact, historical, _original, _capture = (
                admission._find_reacquisition_result(
                    self._application, self._project_id, reacquisition_run_id
                )
            )
            store = self._application.execution_store
            historical_handoff, historical_extension = admission._historical_canonical_result(
                self._application, historical.run_id
            )
            historical_payload = admission._historical_action_payload(
                self._application, historical.run_id
            )
            prior_run = None
            binding = admission._continuation_binding(store, reacquisition_run_id)
            if binding is not None:
                # Validate immutable identity first. Mirror/capture closure is
                # operational state: it decides reuse vs recovery, never whether
                # different material may be admitted.
                bound = admission._validate_continuation_binding(
                    self._application,
                    self._project_id,
                    binding,
                    result,
                    historical,
                    require_mirror=False,
                    require_completed_capture=False,
                )
                mirror_complete = admission._continuation_mirror_complete(store, binding)

                if mirror_complete and bound.status is RunStatus.COMPLETED:
                    # A COMPLETED Run without the exact bound capture is not an
                    # incomplete continuation result; it is an incompatible or
                    # forged binding and remains fail-closed. Canonical Handoff /
                    # proposal closure may still be retried when the capture is intact.
                    admission._validate_continuation_binding(
                        self._application,
                        self._project_id,
                        binding,
                        result,
                        historical,
                    )
                    if admission._completed_continuation_is_reusable(
                        self._application,
                        self._project_id,
                        binding,
                        result,
                        historical,
                    ):
                        return {
                            "status": "COMPLETED",
                            "reacquisition_run_id": reacquisition_run_id,
                            "historical_run_id": historical.run_id,
                            "new_run_id": bound.run_id,
                            "new_handoff_id": bound.handoff_ref,
                            "new_handoff_digest": bound.handoff_digest,
                            "candidate_only": True,
                            "idempotent_reuse": True,
                            "research_state_mutation_performed": False,
                        }
                    prior_run = bound
                elif mirror_complete and bound.status in {RunStatus.PREPARED, RunStatus.RUNNING}:
                    return {
                        "status": bound.status.value,
                        "reacquisition_run_id": reacquisition_run_id,
                        "historical_run_id": historical.run_id,
                        "new_run_id": bound.run_id,
                        "new_handoff_id": bound.handoff_ref,
                        "new_handoff_digest": bound.handoff_digest,
                        "candidate_only": True,
                        "idempotent_reuse": True,
                        "in_progress": True,
                        "research_state_mutation_performed": False,
                    }
                else:
                    if bound.status in {RunStatus.PREPARED, RunStatus.RUNNING}:
                        # The target-scoped process lock proves no continuation
                        # request still owns this interrupted partial mirror. Close
                        # only that unusable execution attempt; its history remains.
                        bound = self._application.capability_execution_service.abort(
                            bound.run_id,
                            reason="interrupted new-material continuation binding",
                        )
                    prior_run = bound

            interrupted = admission._latest_correlated_continuation_attempt(
                self._application,
                self._project_id,
                reacquisition_run_id,
                historical_payload,
                current_bound_run_id=(
                    str(binding["new_run_id"]) if binding is not None else None
                ),
            )
            if interrupted is not None:
                if interrupted.status in {RunStatus.PREPARED, RunStatus.RUNNING}:
                    interrupted = self._application.capability_execution_service.abort(
                        interrupted.run_id,
                        reason="interrupted new-material continuation before binding",
                    )
                if interrupted.status is RunStatus.COMPLETED:
                    recovered_binding = {
                        "relation": "new_material_version_continuation",
                        "reacquisition_run_id": reacquisition_run_id,
                        "historical_run_id": historical.run_id,
                        "historical_capture_id": str(result["historical_capture_id"]),
                        "new_material_artifact_id": new_artifact.reference_id,
                        "new_run_id": interrupted.run_id,
                    }
                    admission._validate_continuation_binding(
                        self._application,
                        self._project_id,
                        recovered_binding,
                        result,
                        historical,
                        require_mirror=False,
                    )
                    store.store_diagnostic(
                        reacquisition_run_id,
                        admission._CONTINUATION_BINDING_DIAGNOSTIC,
                        recovered_binding,
                    )
                    store.store_diagnostic(
                        interrupted.run_id,
                        admission._CONTINUATION_BINDING_DIAGNOSTIC,
                        recovered_binding,
                    )
                    if admission._completed_continuation_is_reusable(
                        self._application,
                        self._project_id,
                        recovered_binding,
                        result,
                        historical,
                    ):
                        return {
                            "status": "COMPLETED",
                            "reacquisition_run_id": reacquisition_run_id,
                            "historical_run_id": historical.run_id,
                            "new_run_id": interrupted.run_id,
                            "new_handoff_id": interrupted.handoff_ref,
                            "new_handoff_digest": interrupted.handoff_digest,
                            "candidate_only": True,
                            "idempotent_reuse": True,
                            "research_state_mutation_performed": False,
                        }
                if interrupted.status not in {
                    RunStatus.COMPLETED,
                    RunStatus.FAILED,
                    RunStatus.ABORTED,
                }:
                    raise LocalApplicationError(
                        "APPLICATION-NEW-MATERIAL-CONTINUATION-IDEMPOTENCY-001",
                        "correlated prior continuation attempt is still active",
                    )
                prior_run = interrupted

            claim = {
                "relation": "new_material_version_continuation_claim",
                "reacquisition_run_id": reacquisition_run_id,
                "historical_run_id": historical.run_id,
                "historical_capture_id": str(result["historical_capture_id"]),
                "new_material_artifact_id": new_artifact.reference_id,
            }
            try:
                claimed = store.claim_diagnostic_once(
                    reacquisition_run_id,
                    admission._CONTINUATION_CLAIM_DIAGNOSTIC,
                    claim,
                )
            except Exception as exc:
                raise LocalApplicationError(
                    "APPLICATION-NEW-MATERIAL-CONTINUATION-IDEMPOTENCY-001",
                    "new-material continuation claim is conflicting or corrupt",
                ) from exc
            if not claimed:
                existing_claim = admission._continuation_claim(store, reacquisition_run_id)
                if existing_claim != claim:
                    raise LocalApplicationError(
                        "APPLICATION-NEW-MATERIAL-CONTINUATION-IDEMPOTENCY-001",
                        "prior new-material continuation claim does not match the admitted material",
                    )

            if prior_run is None:
                historical_payload.pop("parent_run_id", None)
            else:
                if prior_run.status not in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.ABORTED}:
                    raise LocalApplicationError(
                        "APPLICATION-NEW-MATERIAL-CONTINUATION-IDEMPOTENCY-001",
                        "prior continuation attempt is still active",
                    )
                historical_payload["parent_run_id"] = prior_run.run_id

            facade = _BaseLocalApplicationFacade(
                self._application,
                self._project_id,
                workspace_root=self._workspace_root,
                owns_application=False,
            )
            prepared = facade.submit_action(
                {
                    "action_type": "desktop_research.investigate",
                    "payload": historical_payload,
                    "rationale": (
                        "Continue persisted NEW_MATERIAL_VERSION from "
                        f"{reacquisition_run_id}."
                    ),
                    "conversation_id": admission._continuation_conversation_id(
                        reacquisition_run_id
                    ),
                }
            )
            new_run_id = str(prepared.get("run_id") or "")
            if not new_run_id:
                raise LocalApplicationError(
                    "APPLICATION-NEW-MATERIAL-CONTINUATION-EXECUTION-001",
                    "new Desktop Research execution could not be prepared",
                )
            new_run, _context_extension = facade._desktop_external_run(new_run_id)
            binding = {
                "relation": "new_material_version_continuation",
                "reacquisition_run_id": reacquisition_run_id,
                "historical_run_id": historical.run_id,
                "historical_capture_id": str(result["historical_capture_id"]),
                "new_material_artifact_id": new_artifact.reference_id,
                "new_run_id": new_run_id,
            }
            collect_attempted = False
            try:
                # Each attempt is immutable. The reacquisition Run keeps an
                # append-only attempt index; the child Run carries its own exact
                # mirror. The newest exact binding is the current attempt.
                store.store_diagnostic(
                    reacquisition_run_id,
                    admission._CONTINUATION_BINDING_DIAGNOSTIC,
                    binding,
                )
                store.store_diagnostic(
                    new_run_id, admission._CONTINUATION_BINDING_DIAGNOSTIC, binding
                )
                capture_map = self._capture_new_material_version(
                    new_run,
                    historical,
                    historical_extension,
                    result,
                    new_artifact,
                    reacquisition_run_id,
                )
                attempt_map = self._replay_attempts(
                    new_run,
                    historical,
                    capture_map,
                    reacquisition_run_id,
                )
                research_result = _research_result_for_new_run(
                    historical_handoff,
                    historical_extension,
                    reacquisition_run_id=reacquisition_run_id,
                    capture_map=capture_map,
                    attempt_map=attempt_map,
                )
                collect_attempted = True
                collected = facade.collect_external(
                    new_run_id, {"research_result": research_result}
                )
                execution = collected.get("execution_result") or {}
                run_wire = execution.get("run") if isinstance(execution, Mapping) else None
                proposal = execution.get("state_delta_proposal") if isinstance(execution, Mapping) else None
                if (
                    not isinstance(run_wire, Mapping)
                    or run_wire.get("status") != "COMPLETED"
                    or not isinstance(proposal, Mapping)
                ):
                    issues = execution.get("issues") if isinstance(execution, Mapping) else None
                    raise LocalApplicationError(
                        "APPLICATION-NEW-MATERIAL-CONTINUATION-RESULT-001",
                        "new canonical Desktop Research result did not complete"
                        + (f": {issues}" if issues else ""),
                    )
                completed = store.load_run(new_run_id)
                if (
                    completed is None
                    or not completed.handoff_ref
                    or not completed.handoff_digest
                    or not admission._completed_continuation_is_reusable(
                        self._application,
                        self._project_id,
                        binding,
                        result,
                        historical,
                    )
                ):
                    raise LocalApplicationError(
                        "APPLICATION-NEW-MATERIAL-CONTINUATION-RESULT-001",
                        "completed continuation is missing canonical reusable result closure",
                    )
                return {
                    "status": "COMPLETED",
                    "reacquisition_run_id": reacquisition_run_id,
                    "historical_run_id": historical.run_id,
                    "historical_capture_id": str(result["historical_capture_id"]),
                    "new_material_artifact_id": new_artifact.reference_id,
                    "new_run_id": new_run_id,
                    "new_handoff_id": completed.handoff_ref,
                    "new_handoff_digest": completed.handoff_digest,
                    "new_capture_ids": list(capture_map.values()),
                    "state_delta_proposal_id": proposal.get("proposal_id"),
                    "state_delta_proposal_digest": proposal.get("proposal_digest"),
                    "candidate_only": True,
                    "idempotent_reuse": False,
                    "research_state_mutation_performed": False,
                }
            except Exception:
                # Failures before external collection leave no public correction
                # seam, so close only that execution attempt. Once collect has
                # been attempted, preserve RUNNING so the ordinary public
                # preflight/collect correction path remains usable.
                if not collect_attempted:
                    try:
                        current = store.load_run(new_run_id)
                        if current is not None and current.status is RunStatus.RUNNING:
                            self._application.capability_execution_service.abort(
                                new_run_id, reason="new material continuation setup failed"
                            )
                    except Exception:
                        pass
                raise

    def _capture_new_material_version(
        self,
        new_run,
        historical,
        historical_extension: Mapping[str, Any],
        result: Mapping[str, Any],
        new_artifact,
        reacquisition_run_id: str,
    ) -> dict[str, str]:
        store = self._application.execution_store
        capture_map: dict[str, str] = {}
        target_capture_id = str(result["historical_capture_id"])
        target_count = 0
        service = DesktopResearchCaptureService(store)

        for detail in historical_extension.get("source_capture_details", []):
            old_capture_id = str(detail["capture_id"])
            _run, old_original, old_text, old_capture = _artifact_pair_for_capture(
                store, self._project_id, historical.run_id, old_capture_id
            )
            try:
                original_current = store.load_artifact_verified_once(old_original.artifact_id)
                if old_capture_id == target_capture_id:
                    target_count += 1
                    text_content = new_artifact.content
                    acquired_at = str(result["reacquired_at"])
                else:
                    text_content = store.load_artifact_verified_once(old_text.artifact_id).content
                    acquired_at = str(old_capture["acquired_at"])
            except Exception as exc:
                raise LocalApplicationError(
                    "APPLICATION-NEW-MATERIAL-CONTINUATION-PAIR-001",
                    f"required paired capture material is unavailable: {old_capture_id}",
                ) from exc

            new_capture_id = admission._new_id(old_capture_id, reacquisition_run_id)
            provenance = {
                "relation": "new_material_version_continuation",
                "historical_run_id": historical.run_id,
                "historical_capture_id": old_capture_id,
                "historical_acquired_at": str(old_capture["acquired_at"]),
                "reacquisition_run_id": reacquisition_run_id,
                "verified_original_artifact_id": old_original.artifact_id,
            }
            if old_capture_id == target_capture_id:
                provenance.update(
                    {
                        "reacquired_artifact_id": new_artifact.reference_id,
                        "reacquired_at": str(result["reacquired_at"]),
                    }
                )
            service.capture(
                new_run,
                capture_id=new_capture_id,
                source_category=str(old_capture["source_category"]),
                exact_locator=str(old_capture["source_locator"]),
                acquired_at=acquired_at,
                original_bytes=original_current.content,
                original_media_type=old_original.media_type,
                text_rendition=text_content,
                provenance=provenance,
                artifact_write_options={"expected_status": RunStatus.RUNNING},
            )
            capture_map[old_capture_id] = new_capture_id

        if target_count != 1:
            raise LocalApplicationError(
                "APPLICATION-NEW-MATERIAL-CONTINUATION-PROVENANCE-001",
                "historical canonical result does not reference the reacquired capture exactly once",
            )
        return capture_map

    def _replay_attempts(
        self,
        new_run,
        historical,
        capture_map: Mapping[str, str],
        reacquisition_run_id: str,
    ) -> dict[str, str]:
        old_attempts = reconstruct_attempts(
            self._application.operational_store, historical.run_id
        )
        recorder = DesktopResearchAttemptRecorder(
            new_run,
            self._application.execution_store,
            self._application.operational_store,
            self._application.clock,
        )
        attempt_map: dict[str, str] = {}
        for attempt in old_attempts.values():
            old_attempt_id = str(attempt["attempt_id"])
            new_attempt_id = admission._new_id(old_attempt_id, reacquisition_run_id)
            attempt_map[old_attempt_id] = new_attempt_id
            provenance = deepcopy(dict(attempt.get("provenance") or {}))
            provenance.update(
                {
                    "relation": "new_material_version_continuation",
                    "historical_run_id": historical.run_id,
                    "historical_attempt_id": old_attempt_id,
                    "reacquisition_run_id": reacquisition_run_id,
                }
            )
            recorder.start_attempt(
                new_attempt_id,
                strategy=str(attempt["strategy"]),
                coverage_dimension_ids=tuple(attempt["coverage_dimension_ids"]),
                query_or_target=attempt.get("query_or_target"),
                provider_or_tool=attempt.get("provider_or_tool"),
                target_locator=attempt.get("target_locator"),
                provenance=provenance,
            )
            old_resulting = attempt.get("resulting_capture_id")
            recorder.complete_attempt(
                new_attempt_id,
                outcome=str(attempt["outcome"]),
                failure_or_blocking_reason=attempt.get("failure_or_blocking_reason"),
                target_locator=attempt.get("target_locator"),
                resulting_capture_id=(
                    capture_map[str(old_resulting)]
                    if old_resulting in capture_map
                    else None
                ),
                provenance=provenance,
            )
        return attempt_map
