from __future__ import annotations

from contextlib import ExitStack
from copy import deepcopy
import hashlib
from typing import Any, Mapping

from core.execution import RunStatus
from plugins.desktop_research import DesktopResearchAttemptRecorder, DesktopResearchCaptureService
from plugins.desktop_research.attempts import reconstruct_attempts

from .facade import LocalApplicationError
from .material_content_facade import _artifact_pair_for_capture
from .new_material_continuation_service import (
    NewMaterialContinuationService,
    _BaseLocalApplicationFacade,
    _CONTINUATION_LOCK,
    _research_result_for_new_run,
    _render_reacquired_html_rendition,
    _target_lock,
)
from . import new_material_continuation_admission as admission

_GROUP_LIMIT = 16
_GROUP_RELATION = "new_material_version_group_continuation"


def _group_token(reacquisition_run_ids: tuple[str, ...]) -> str:
    digest = hashlib.sha256(
        ("new-material-continuation-group\0" + "\0".join(reacquisition_run_ids)).encode(
            "utf-8"
        )
    ).hexdigest()[:24]
    return f"NMVG-{digest}"


def _group_conversation_id(reacquisition_run_ids: tuple[str, ...]) -> str:
    return f"CONV-{_group_token(reacquisition_run_ids)}"


def _latest_correlated_attempt(
    application,
    project_id: str,
    conversation_id: str,
    historical_payload: Mapping[str, Any],
):
    query = getattr(application.conversation_store, "run_correlations_for_conversation", None)
    if query is None:
        return None
    expected_payload = deepcopy(dict(historical_payload))
    expected_payload.pop("parent_run_id", None)
    for correlation in query(conversation_id, limit=_GROUP_LIMIT):
        run_id = str(correlation.get("run_id") or "")
        if not run_id:
            continue
        proposal = application.conversation_store.load_proposal(
            str(correlation.get("proposal_id") or "")
        )
        action = proposal.get("action") if isinstance(proposal, Mapping) else None
        payload = action.get("payload") if isinstance(action, Mapping) else None
        if (
            not isinstance(proposal, Mapping)
            or proposal.get("project_id") != project_id
            or proposal.get("conversation_id") != conversation_id
            or not isinstance(action, Mapping)
            or action.get("action_type") != "desktop_research.investigate"
            or not isinstance(payload, Mapping)
        ):
            continue
        actual = deepcopy(dict(payload))
        parent_run_id = actual.pop("parent_run_id", None)
        if actual != expected_payload:
            continue
        run = application.execution_store.load_run(run_id)
        if (
            run is None
            or run.project_ref != project_id
            or run.capability_id != "desktop-research"
            or run.function_id != "investigate"
            or run.execution_mode != "real"
            or run.parent_run_id != parent_run_id
        ):
            raise LocalApplicationError(
                "APPLICATION-NEW-MATERIAL-CONTINUATION-IDEMPOTENCY-001",
                "correlated paired continuation attempt has incompatible execution identity",
            )
        return run
    return None


class PairedNewMaterialContinuationService(NewMaterialContinuationService):
    """Continue one canonical result with an explicit set of new material versions."""

    def continue_new_versions(self, reacquisition_run_ids: tuple[str, ...]) -> Mapping[str, Any]:
        run_ids = tuple(sorted(reacquisition_run_ids))
        if (
            len(run_ids) < 2
            or len(run_ids) > _GROUP_LIMIT
            or len(set(run_ids)) != len(run_ids)
        ):
            raise LocalApplicationError(
                "APPLICATION-NEW-MATERIAL-CONTINUATION-BINDING-001",
                "paired continuation requires 2-16 unique reacquisition Runs",
            )

        with _CONTINUATION_LOCK, ExitStack() as locks:
            for run_id in run_ids:
                locks.enter_context(_target_lock(self._workspace_root, run_id))
            historical, replacements = self._resolve_replacements(run_ids)
            return self._continue_group(run_ids, historical, replacements)

    def _resolve_replacements(self, run_ids: tuple[str, ...]):
        historical = None
        replacements: dict[str, dict[str, Any]] = {}
        for run_id in run_ids:
            _run, result, artifact, candidate_historical, _original, _capture = (
                admission._find_reacquisition_result(
                    self._application, self._project_id, run_id
                )
            )
            if historical is None:
                historical = candidate_historical
            elif candidate_historical.run_id != historical.run_id:
                raise LocalApplicationError(
                    "APPLICATION-NEW-MATERIAL-CONTINUATION-BINDING-001",
                    "paired reacquisitions must resolve to one historical Run",
                )
            capture_id = str(result["historical_capture_id"])
            if capture_id in replacements:
                raise LocalApplicationError(
                    "APPLICATION-NEW-MATERIAL-CONTINUATION-BINDING-001",
                    "paired reacquisitions must bind distinct historical captures",
                )
            replacements[capture_id] = {
                "reacquisition_run_id": run_id,
                "result": result,
                "artifact": artifact,
            }
        assert historical is not None
        return historical, replacements

    @staticmethod
    def _replacement_entries(
        replacements: Mapping[str, Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        return [
            {
                "reacquisition_run_id": str(replacement["reacquisition_run_id"]),
                "historical_capture_id": capture_id,
                "new_material_artifact_id": str(replacement["result"]["new_artifact_id"]),
                "new_material_kind": str(
                    replacement["result"].get("new_material_kind")
                    or replacement["result"].get("kind")
                    or ""
                ),
                "new_material_digest": str(replacement["result"]["actual_digest"]),
                "new_material_size": int(replacement["result"]["actual_size"]),
            }
            for capture_id, replacement in sorted(replacements.items())
        ]

    def _completed_group_is_reusable(
        self,
        run,
        run_ids: tuple[str, ...],
        replacements: Mapping[str, Mapping[str, Any]],
    ) -> bool:
        if run.status is not RunStatus.COMPLETED:
            return False
        artifacts = self._application.execution_store.artifacts_for(run.run_id)
        for entry in self._replacement_entries(replacements):
            role = (
                "desktop_research.original_capture"
                if entry["new_material_kind"] == "original"
                else "desktop_research.text_rendition"
            )
            matches = [
                item
                for item in artifacts
                if item.role == role
                and item.provenance.get("relation") == _GROUP_RELATION
                and item.provenance.get("continuation_group_id") == _group_token(run_ids)
                and item.provenance.get("reacquisition_run_id")
                == entry["reacquisition_run_id"]
                and item.provenance.get("historical_capture_id")
                == entry["historical_capture_id"]
                and item.provenance.get("reacquired_artifact_id")
                == entry["new_material_artifact_id"]
                and item.digest == entry["new_material_digest"]
                and item.size == entry["new_material_size"]
            ]
            if len(matches) != 1:
                raise LocalApplicationError(
                      "APPLLICATION-NEW-MATERIAL-CONTINUATION-IDEMPOTENCY-001",
                    "completed paired continuation does not contain the admitted material set",
                )
        return admission._canonical_result_closure_is_complete(self._application, run)

    def _result(
        self,
        run,
        run_ids: tuple[str, ...],
        historical,
        replacements: Mapping[str, Mapping[str, Any]],
        *,
        idempotent_reuse: bool,
        capture_ids: list[str] | None = None,
        proposal: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = {
            "status": "COMPLETED",
            "group_token": _group_token(run_ids),
            "reacquisition_run_ids": list(run_ids),
            "historical_run_id": historical.run_id,
            "replacements": self._replacement_entries(replacements),
            "new_run_id": run.run_id,
            "new_handoff_id": run.handoff_ref,
            "new_handoff_digest": run.handoff_digest,
            "candidate_only": True,
            "idempotent_reuse": idempotent_reuse,
            "research_state_mutation_performed": False,
        }
        if capture_ids is not None:
            result["new_capture_ids"] = capture_ids
        if proposal is not None:
            result["state_delta_proposal_id"] = proposal.get("proposal_id")
            result["state_delta_proposal_digest"] = proposal.get("proposal_digest")
        return result

    def _continue_group(self, run_ids, historical, replacements):
        historical_handoff, historical_extension = admission._historical_canonical_result(
            self._application, historical.run_id
        )
        historical_payload = admission._historical_action_payload(
            self._application, historical.run_id
        )
        conversation_id = _group_conversation_id(run_ids)
        prior_run = _latest_correlated_attempt(
            self._application,
            self._project_id,
            conversation_id,
            historical_payload,
        )
        if prior_run is not None:
            if self._completed_group_is_reusable(prior_run, run_ids, replacements):
                return self._result(
                    prior_run,
                    run_ids,
                    historical,
                    replacements,
                    idempotent_reuse=True,
                )
            if prior_run.status in {RunStatus.PREPARED, RunStatus.RUNNING}:
                prior_run = self._application.capability_execution_service.abort(
                    prior_run.run_id,
                    reason="interrupted paired new-material continuation",
                )

        if prior_run is None:
            historical_payload.pop("parent_run_id", None)
        else:
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
                "rationale": "Continue explicit paired NEW_MATERIAL_VERSION captures.",
                "conversation_id": conversation_id,
            }
        )
        new_run_id = str(prepared.get("run_id") or "")
        if not new_run_id:
            raise LocalApplicationError(
                "APPLICATION-NEW-MATERIAL-CONTINUATION-EXECUTION-001",
                "paired Desktop Research continuation could not be prepared",
            )
        new_run, _context_extension = facade._desktop_external_run(new_run_id)

        try:
            capture_map = self._capture_group(
                new_run,
                historical,
                historical_extension,
                replacements,
                _group_token(run_ids),
                run_ids,
            )
            attempt_map = self._replay_group_attempts(
                new_run, historical, capture_map, _group_token(run_ids), run_ids
            )
            research_result = _research_result_for_new_run(
                historical_handoff,
                historical_extension,
                reacquisition_run_id=_group_token(run_ids),
                capture_map=capture_map,
                attempt_map=attempt_map,
            )
            collected = facade.collect_external(
                new_run_id, {"research_result": research_result}
            )
            execution = collected.get("execution_result") or {}
            run_wire = execution.get("run") if isinstance(execution, Mapping) else None
            proposal = (
                execution.get("state_delta_proposal")
                if isinstance(execution, Mapping)
                else None
            )
            if (
                not isinstance(run_wire, Mapping)
                or run_wire.get("status") != "COMPLETED"
                or not isinstance(proposal, Mapping)
            ):
                issues = execution.get("issues") if isinstance(execution, Mapping) else None
                raise LocalApplicationError(
                    "APPLICATION-NEW-MATERIAL-CONTINUATION-RESULT-001",
                    "paired canonical Desktop Research result did not complete"
                    + (f": {issues}" if issues else ""),
                )
            completed = self._application.execution_store.load_run(new_run_id)
            if completed is None or not self._completed_group_is_reusable(
                completed, run_ids, replacements
            ):
                raise LocalApplicationError(
                    "APPLICATION-NEW-MATERIAL-CONTINUATION-RESULT-001",
                    "paired continuation is missing canonical reusable result closure",
                )
            return self._result(
                completed,
                run_ids,
                historical,
                replacements,
                idempotent_reuse=False,
                capture_ids=list(capture_map.values()),
                proposal=proposal,
            )
        except Exception:
            current = self._application.execution_store.load_run(new_run_id)
            if current is not None and current.status is RunStatus.RUNNING:
                try:
                    self._application.capability_execution_service.abort(
                        new_run_id,
                        reason="paired new-material continuation failed",
                    )
                except Exception:
                    pass
            raise

    def _capture_limits(self, new_run) -> tuple[int, int]:
        extension = self._application.context_extension_store.load(
            new_run.capability_id,
            new_run.capability_version,
            new_run.function_id,
            new_run.context_pack_id,
        )
        budget = extension.get("budget") if isinstance(extension, Mapping) else None
        if not isinstance(budget, Mapping):
            raise LocalApplicationError(
                "APPLICATION-NEW-MATERIAL-CONTINUATION-MATERIAL-001",
                "new Desktop Research Run has no valid capture budget binding",
            )
        try:
            store_limit = int(self._application.execution_store.config.max_artifact_bytes)
            original_declared = budget.get("max_original_capture_bytes")
            original_limit = (
                store_limit
                if original_declared is None
                else min(store_limit, int(original_declared))
            )
            text_limit = min(store_limit, int(budget["max_text_rendition_bytes"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise LocalApplicationError(
                "APPLICATION-NEW-MATERIAL-CONTINUATION-MATERIAL-001",
                "new Desktop Research Run capture budget is malformed",
            ) from exc
        if min(original_limit, text_limit) < 0:
            raise LocalApplicationError(
                "APPLICATION-NEW-MATERIAL-CONTINUATION-MATERIAL-001",
                "new Desktop Research Run capture budget is malformed",
            )
        return original_limit, text_limit

    def _capture_group(
        self,
        new_run,
        historical,
        historical_extension: Mapping[str, Any],
        replacements: Mapping[str, Mapping[str, Any]],
        group_token: str,
        run_ids: tuple[str, ...],
    ) -> dict[str, str]:
        store = self._application.execution_store
        original_limit, text_limit = self._capture_limits(new_run)
        capture_map: dict[str, str] = {}
        matched: set[str] = set()
        service = DesktopResearchCaptureService(store)
        for detail in historical_extension.get("source_capture_details", []):
            old_capture_id = str(detail["capture_id"])
            _run, old_original, old_text, old_capture = _artifact_pair_for_capture(
                store, self._project_id, historical.run_id, old_capture_id
            )
            replacement = replacements.get(old_capture_id)
            try:
                if replacement is None:
                    original_content = store.load_artifact_verified_once(
                        old_original.artifact_id
                    ).content
                    original_media_type = old_original.media_type
                    text_content = store.load_artifact_verified_once(
                        old_text.artifact_id
                    ).content
                    acquired_at = str(old_capture["acquired_at"])
                else:
                    matched.add(old_capture_id)
                    result = replacement["result"]
                    artifact = replacement["artifact"]
                    kind = str(
                        result.get("new_material_kind") or result.get("kind") or ""
                    )
                    if kind == "original":
                        if len(artifact.content) > original_limit:
                            raise LocalApplicationError(
                                "APPLICATION-NEW-MATERIAL-CONTINUATION-MATERIAL-001",
                                "reacquired original exceeds the pinned capture budget",
                            )
                        original_content = artifact.content
                        original_media_type = str(
                            artifact.media_type or old_original.media_type
                        )
                        text_content = _render_reacquired_html_rendition(
                            artifact.content,
                            artifact.media_type,
                            max_bytes=text_limit,
                        )
                    else:
                        original_content = store.load_artifact_verified_once(
                            old_original.artifact_id
                        ).content
                        original_media_type = old_original.media_type
                        if len(artifact.content) > text_limit:
                            raise LocalApplicationError(
                                "APPLICATION-NEW-MATERIAL-CONTINUATION-MATERIAL-001",
                                "reacquired rendition exceeds the pinned capture budget",
                            )
                        text_content = artifact.content
                    acquired_at = str(result["reacquired_at"])
            except Exception as exc:
                if isinstance(exc, LocalApplicationError):
                    raise
                raise LocalApplicationError(
                    "APPLICATION-NEW-MATERIAL-CONTINUATION-PAIR-001",
                    f"required paired capture material is unavailable: {old_capture_id}",
                ) from exc

            new_capture_id = admission._new_id(old_capture_id, group_token)
            provenance: dict[str, Any] = {
                "relation": _GROUP_RELATION,
                "continuation_group_id": group_token,
                "reacquisition_run_ids": list(run_ids),
                "historical_run_id": historical.run_id,
                "historical_capture_id": old_capture_id,
                "historical_acquired_at": str(old_capture["acquired_at"]),
            }
            if replacement is None:
                provenance["verified_original_artifact_id"] = old_original.artifact_id
            else:
                result = replacement["result"]
                artifact = replacement["artifact"]
                kind = str(
                    result.get("new_material_kind") or result.get("kind") or ""
                )
                provenance.update(
                    {
                        "reacquisition_run_id": str(
                            replacement["reacquisition_run_id"]
                        ),
                        "reacquired_artifact_id": artifact.reference_id,
                        "reacquired_at": str(result["reacquired_at"]),
                    }
                )
                if kind == "original":
                    provenance["reacquired_original_artifact_id"] = artifact.reference_id
                    provenance["text_rendition_provider"] = (
                        "python-htmlparser/g1-normalized-text@0.1.0;newline=crlf"
                    )
                else:
                    provenance["verified_original_artifact_id"] = old_original.artifact_id
            service.capture(
                new_run,
                capture_id=new_capture_id,
                source_category=str(old_capture["source_category"]),
                exact_locator=str(old_capture["source_locator"]),
                acquired_at=acquired_at,
                original_bytes=original_content,
                original_media_type=original_media_type,
                text_rendition=text_content,
                provenance=provenance,
                artifact_write_options={"expected_status": RunStatus.RUNNING},
            )
            capture_map[old_capture_id] = new_capture_id

        if matched != set(replacements):
            raise LocalApplicationError(
                "APPLICATION-NEW-MATERIAL-CONTINUATION-PROVENANCE-001",
                "historical canonical result does not reference every paired replacement",
            )
        return capture_map

    def _replay_group_attempts(
        self,
        new_run,
        historical,
        capture_map: Mapping[str, str],
        group_token: str,
        run_ids: tuple[str, ...],
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
            new_attempt_id = admission._new_id(old_attempt_id, group_token)
            attempt_map[old_attempt_id] = new_attempt_id
            provenance = deepcopy(dict(attempt.get("provenance") or {}))
            provenance.update(
                {
                    "relation": _GROUP_RELATION,
                    "continuation_group_id": group_token,
                    "historical_run_id": historical.run_id,
                    "historical_attempt_id": old_attempt_id,
                    "reacquisition_run_ids": list(run_ids),
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
