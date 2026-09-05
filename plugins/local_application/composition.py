from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from types import MethodType
from typing import Any, Mapping

from core.execution import RunStatus
from core.conversation import ActionDefinition, ConversationRuntimeError, HarnessServiceResult
from plugins.local_execution_store import bind_controlled_import_root

from .facade import (
    LocalApplicationError,
    LocalApplicationFacade as _CoreFacade,
    _AUTHORITY_PAYLOAD_FIELDS,
    _INGRESS_FIELDS,
)
from .resume_facade import LocalApplicationFacade as _ResumeImplementation
from .external_desktop_facade import LocalApplicationFacade as _ExternalDesktopImplementation
from .run_inspection_facade import LocalApplicationFacade as _RunInspectionImplementation
from .exhibit_facade import LocalApplicationFacade as _ExhibitImplementation
from .material_inventory_facade import LocalApplicationFacade as _MaterialInventoryImplementation
from .retention_facade import LocalApplicationFacade as _RetentionImplementation
from .survey_facade import LocalApplicationFacade as _SurveyImplementation
from .survey_response_core import SurveyResponseCoreMixin
from .survey_response_capture import SurveyResponseCaptureMixin
from .survey_response_inspection import SurveyResponseInspectionMixin
from .survey_response_facade import (
    LocalApplicationFacade as _SurveyResponseImplementation,
    _SURVEY_RESPONSE_ACTIONS,
    _ACTION_VALIDATORS as _SURVEY_RESPONSE_VALIDATORS,
    _ACTION_REGISTRATION_LOCK as _SURVEY_RESPONSE_ACTION_REGISTRATION_LOCK,
    _nonempty_string as _survey_response_string,
)
from .virtual_runner_execute import VirtualRunnerExecuteMixin
from .virtual_runner_facade import LocalApplicationFacade as _VirtualRunnerImplementation
from .virtual_runner_inspection import VirtualRunnerInspectionMixin
from .survey_analysis_facade import (
    LocalApplicationFacade as _SurveyAnalysisImplementation,
    _SURVEY_ANALYSIS_ACTIONS,
    _ACTION_VALIDATORS as _SURVEY_ANALYSIS_VALIDATORS,
    _ACTION_REGISTRATION_LOCK as _SURVEY_ANALYSIS_ACTION_REGISTRATION_LOCK,
    _nonempty_string as _survey_analysis_string,
)
from .survey_virtual_pretest_inspection import SurveyVirtualPretestInspectionMixin
from .question_review_facade import (
    LocalApplicationFacade as _QuestionReviewImplementation,
    augment_question_review_resume,
)
from .project_input_facade import (
    LocalApplicationFacade as _ProjectInputImplementation,
    validate_question_review_project_inputs,
)
from .exhibit_guard_facade import _StateGuardedResearchExhibitStore
from .virtual_runner_input import _payload as _virtual_payload
from .virtual_runner_facade import _MAX_PRIOR_VIRTUAL_RUN_IDS


class _BoundFeatureService:
    """Bind implementation methods to one stable public Facade host.

    Historical feature Facade classes remain import-compatible, but the public
    runtime never instantiates them.  They are used only as method namespaces
    while behavior is delegated through explicit feature services.
    """

    def __init__(self, host: "LocalApplicationFacade", *owners: type) -> None:
        self._host = host
        self._owners = owners

    def method(self, name: str):
        for owner in self._owners:
            value = owner.__dict__.get(name)
            if isinstance(value, staticmethod):
                return value.__func__
            if isinstance(value, classmethod):
                return MethodType(value.__func__, owner)
            if callable(value):
                return MethodType(value, self._host)
        raise AttributeError(name)

    def call(self, name: str, *args: Any, **kwargs: Any) -> Any:
        return self.method(name)(*args, **kwargs)

    def has(self, name: str) -> bool:
        return any(callable(owner.__dict__.get(name)) for owner in self._owners)


class _ComposedSurveyActionHandler:
    """Route registered Survey actions back through the stable public facade."""

    def __init__(self, application, family: str, operation: str) -> None:
        self._application = application
        self._family = family
        self._operation = operation

    def execute(self, payload, *, state, actor, proposal):
        facade = LocalApplicationFacade(self._application, state.project_ref)
        if self._family == "response":
            if self._operation == "normalize":
                result = facade.normalize_survey_response(payload)
            elif self._operation == "capture":
                result = facade.capture_survey_response(payload)
            elif self._operation == "show_response":
                result = facade.show_survey_response(
                    _survey_response_string(payload, "response_id"),
                    identity_namespace=payload.get("identity_namespace"),
                )
            elif self._operation == "capture_dataset":
                result = facade.capture_survey_response_dataset(payload)
            elif self._operation == "show_dataset":
                result = facade.show_survey_response_dataset(
                    _survey_response_string(payload, "dataset_id"),
                    limit=payload.get("limit", 25),
                    offset=payload.get("offset", 0),
                )
            else:  # pragma: no cover - registration table is closed.
                raise ConversationRuntimeError("CONV-ROUTE-001", f"unknown Survey response operation: {self._operation}")
        else:
            if self._operation == "capture_spec":
                result = facade.capture_survey_analysis_spec(payload)
            elif self._operation == "show_spec":
                result = facade.show_survey_analysis_spec(
                    _survey_analysis_string(payload, "analysis_spec_id")
                )
            elif self._operation == "aggregate":
                result = facade.run_survey_aggregation(payload)
            elif self._operation == "show_result":
                result = facade.show_survey_aggregate_result(
                 _survey_analysis_string(payload, "aggregate_result_id"),
                    limit=payload.get("limit", 25),
                    offset=payload.get("offset", 0),
                )
            elif self._operation == "show_virtual_pretest":
                result = facade.show_survey_virtual_pretest(
                    _survey_analysis_string(payload, "run_id"),
                    aggregate_result_id=payload.get("aggregate_result_id"),
                )
            else:  # pragma: no cover - registration table is closed.
                raise ConversationRuntimeError("CONV-ROUTE-001", f"unknown Survey analysis operation: {self._operation}")

        result_reference = next(
            (result[field] for field in ("aggregate_result_id", "analysis_spec_id", "dataset_id", "response_id", "content_digest")
             if isinstance(result.get(field), str) and result[field]),
            None,
        )
        return HarnessServiceResult(
            result_reference=result_reference,
            data=deepcopy(dict(result)),
            research_state_mutation_performed=False,
        )


class _RunProjectionDelegate:
    """Base for composed inspection services that need a super().show_run()."""

    def __init__(self, host: "LocalApplicationFacade") -> None:
        self._host = host

    def __getattr__(self, name: str):
        return getattr(self._host, name)

    def show_run(self, run_id: str) -> Mapping[str, Any]:
        return self._host._features.run_inspection.call("show_run", run_id)


class _VirtualRunnerInspectionService(VirtualRunnerInspectionMixin, _RunProjectionDelegate):
    pass


class _PublicRunProjectionDelegate(_RunProjectionDelegate):
    def show_run(self, run_id: str) -> Mapping[str, Any]:
        return self._host.show_run(run_id)


class _VirtualPretestInspectionService(
    SurveyVirtualPretestInspectionMixin, _PublicRunProjectionDelegate
):
    pass


@dataclass(frozen=True)
class _FeatureServices:
    resume: _BoundFeatureService
    external: _BoundFeatureService
    run_inspection: _BoundFeatureService
    exhibits: _BoundFeatureService
    materials: _BoundFeatureService
    retention: _BoundFeatureService
    survey: _BoundFeatureService
    survey_response: _BoundFeatureService
    virtual_runner: _BoundFeatureService
    survey_analysis: _BoundFeatureService
    question_review: _BoundFeatureService
    project_input: _BoundFeatureService

    def all(self) -> tuple[_BoundFeatureService, ...]:
        return (
            self.resume,
            self.external,
            self.run_inspection,
            self.exhibits,
            self.materials,
            self.retention,
            self.survey,
            self.survey_response,
            self.virtual_runner,
            self.survey_analysis,
            self.question_review,
            self.project_input,
        )


class LocalApplicationFacade(_CoreFacade):
    """Stable public local Application Facade assembled by explicit composition."""

    def __init__(
        self,
        application,
        project_id: str,
        *,
        workspace_root: str | Path | None = None,
        owns_application: bool = False,
    ) -> None:
        super().__init__(
            application,
            project_id,
            workspace_root=workspace_root,
            owns_application=owns_application,
        )
        self._project_input_store = None
        self._features = _FeatureServices(
            resume=_BoundFeatureService(self, _ResumeImplementation),
            external=_BoundFeatureService(self, _ExternalDesktopImplementation),
            run_inspection=_BoundFeatureService(self, _RunInspectionImplementation),
            exhibits=_BoundFeatureService(self, _ExhibitImplementation),
            materials=_BoundFeatureService(self, _MaterialInventoryImplementation),
            retention=_BoundFeatureService(self, _RetentionImplementation),
            survey=_BoundFeatureService(self, _SurveyImplementation),
            survey_response=_BoundFeatureService(
                self,
                SurveyResponseInspectionMixin,
                SurveyResponseCaptureMixin,
                SurveyResponseCoreMixin,
                _SurveyResponseImplementation,
            ),
            virtual_runner=_BoundFeatureService(
                self, VirtualRunnerExecuteMixin, _VirtualRunnerImplementation
            ),
            survey_analysis=_BoundFeatureService(self, _SurveyAnalysisImplementation),
            question_review=_BoundFeatureService(self, _QuestionReviewImplementation),
            project_input=_BoundFeatureService(self, _ProjectInputImplementation),
        )
        self._virtual_run_inspection = _VirtualRunnerInspectionService(self)
        self._virtual_pretest_inspection = _VirtualPretestInspectionService(self)
        if self._workspace_root is not None:
            try:
                bind_controlled_import_root(
                    self._application.execution_store, self._workspace_root
                )
            except (OSError, PermissionError) as exc:
                raise LocalApplicationError(
                    "APPLICATION-EXTERNAL-FILE-001",
                    "workspace could not be bound as the controlled intake root",
                ) from exc
        if hasattr(self._application, "coordinator"):
            self._compose_action_services()

    def __getattr__(self, name: str):
        # Internal helper lookup only. Public methods are explicitly delegated below.
        if name.startswith("_") and "_features" in self.__dict__:
            for feature in self._features.all():
                if feature.has(name):
                    return feature.method(name)
        raise AttributeError(name)

    def _compose_action_services(self) -> None:
        # Registration happens once at composition time rather than as a side effect
        # of list_actions()/submit_action().
        self._features.question_review.call("_ensure_question_review_action")
        self._register_survey_actions(
            _SURVEY_ANALYSIS_ACTIONS,
            _SURVEY_ANALYSIS_VALIDATORS,
            family="analysis",
            conflict_code="APPLICATION-SURVEY-ANALYSIS-ROUTE-001",
        )
        self._register_survey_actions(
            _SURVEY_RESPONSE_ACTIONS,
            _SURVEY_RESPONSE_VALIDATORS,
            family="response",
            conflict_code="APPLICATION-SURVEY-RESPONSE-ROUTE-001",
        )

    def _register_survey_actions(self, actions, validators, *, family: str, conflict_code: str) -> None:
        coordinator = self._application.coordinator
        action_registry = coordinator._actions
        service_registry = coordinator._services
        with _SURVEY_RESPONSE_ACTION_REGISTRATION_LOCK, _SURVEY_ANALYSIS_ACTION_REGISTRATION_LOCK:
            existing = {
                definition.action_type: definition
                for definition in coordinator.action_definitions()
            }
            for action_type, payload_contract, operation in actions:
                definition = existing.get(action_type)
                if definition is None:
                    action_registry.register(
                        ActionDefinition(
                            action_type,
                            payload_contract,
                            "read_only",
                            "harness_service",
                            False,
                            human_decision_required=False,
                            service_id=action_type,
                            payload_validator=validators[action_type],
                        )
                    )
                    existing[action_type] = action_registry.get(action_type)
                elif (
                    definition.payload_contract != payload_contract
                    or definition.effect != "read_only"
                    or definition.route_kind != "harness_service"
                    or definition.confirmation_required
                    or definition.service_id != action_type
                ):
                    raise LocalApplicationError(
                        conflict_code,
                        f"registered action conflicts with Survey {family} route: {action_type}",
                    )
                try:
                    service_registry.resolve(action_type)
                except ConversationRuntimeError as exc:
                    if exc.code != "CONV-ROUTE-001":
                        raise
                    service_registry.register(
                        action_type,
                        _ComposedSurveyActionHandler(self._application, family, operation),
                    )

    def close(self) -> None:
        if self._project_input_store is not None:
            self._project_input_store.close()
            self._project_input_store = None
        super().close()

    # ---- Public conversation/application surface ---------------------------------
    def list_actions(self) -> Mapping[str, Any]:
        result = deepcopy(dict(super().list_actions()))
        result["actions"].append({
            "action_type": "virtual_runner.survey.execute",
            "payload_contract": "survey-virtual-runner-execution@0.1.0",
            "effect": "read_only",
            "confirmation_required": False,
            "route_category": "research_capability",
        })
        return result

    def submit_action(self, draft_input: Mapping[str, Any]) -> Mapping[str, Any]:
        validate_question_review_project_inputs(self, draft_input)
        if isinstance(draft_input, Mapping) and draft_input.get("action_type") == "virtual_runner.survey.execute":
            unknown = set(draft_input) - _INGRESS_FIELDS
            if unknown:
                raise LocalApplicationError(
                    "APPLICATION-INGRESS-001",
                    "typed action input contains caller-controlled authority or unknown fields: "
                    + ", ".join(sorted(map(str, unknown))),
                )
            payload = draft_input.get("payload")
            if not isinstance(payload, Mapping):
                raise LocalApplicationError("APPLICATION-INGRESS-001", "payload must be an object")
            forbidden = set(payload) & _AUTHORITY_PAYLOAD_FIELDS
            if forbidden:
                raise LocalApplicationError(
                    "APPLICATION-AUTHORITY-001",
                    "caller may not supply Harness authority metadata: "
                    + ", ".join(sorted(forbidden)),
                )
            normalized = _virtual_payload(payload)
            if len(normalized["prior_virtual_run_ids"]) > _MAX_PRIOR_VIRTUAL_RUN_IDS:
                raise LocalApplicationError(
                    "APPLICATION-VIRTUAL-PAYLOAD-001",
                    f"prior_virtual_run_ids may contain at most {_MAX_PRIOR_VIRTUAL_RUN_IDS} Run IDs",
                )
            return self.run_survey_virtual(normalized)
        return super().submit_action(draft_input)

    def resume_context(self, *, limits: Mapping[str, int] | None = None) -> Mapping[str, Any]:
        base = self._features.resume.call("resume_context", limits=limits)
        return augment_question_review_resume(self, base, limits=limits)

    # ---- Desktop Research ---------------------------------------------------------
    def replay_completed_desktop_research_run(self, run_id: str) -> Mapping[str, Any]:
        return self._features.external.call("replay_completed_desktop_research_run", run_id)

    def start_external_retrieval_attempt(self, run_id: str, submission: Mapping[str, Any]) -> Mapping[str, Any]:
        return self._features.external.call("start_external_retrieval_attempt", run_id, submission)

    def complete_external_retrieval_attempt(self, run_id: str, submission: Mapping[str, Any]) -> Mapping[str, Any]:
        return self._features.external.call("complete_external_retrieval_attempt", run_id, submission)

    def capture_external_source(self, run_id: str, submission: Mapping[str, Any]) -> Mapping[str, Any]:
        self._desktop_external_run(run_id)
        from .retention_facade import _LARGE_ORIGINAL_PREFIX
        from .external_desktop_facade import _ORIGINAL_ROLE

        if any(
            artifact.role == _ORIGINAL_ROLE
            and artifact.storage_locator.startswith(_LARGE_ORIGINAL_PREFIX)
            for artifact in self._application.execution_store.artifacts_for(run_id)
        ):
            return self._features.retention.call(
                "_capture_external_source_with_large_original", run_id, submission
            )
        try:
            return self._features.external.call("capture_external_source", run_id, submission)
        except LocalApplicationError as exc:
            if (
                exc.code != "APPLICATION-EXTERNAL-FILE-002"
                or "file exceeds configured intake size limit" not in exc.message
            ):
                raise
        return self._features.retention.call(
            "_capture_external_source_with_large_original", run_id, submission
        )

    def collect_external(self, run_id: str, submission: Mapping[str, Any]) -> Mapping[str, Any]:
        run, _context_extension = self._desktop_external_run(run_id)
        guard = getattr(self._application.execution_store, "require_run_status", None)
        if not callable(guard):
            raise LocalApplicationError(
                "APPLICATION-EXTERNAL-ATTEMPT-001",
                "external collect requires an atomic RUNNING-state guard",
            )
        try:
            with guard(run.run_id, RunStatus.RUNNING):
                try:
                    from . import external_attempt_lifecycle_facade as attempt_module

                    attempts = attempt_module.reconstruct_attempts(
                        self._application.operational_store, run.run_id
                    )
                except ValueError as exc:
                    raise LocalApplicationError(
                        "APPLICATION-EXTERNAL-ATTEMPT-001", str(exc)
                    ) from exc
                in_progress = sorted(
                    attempt_id
                    for attempt_id, attempt in attempts.items()
                    if attempt.get("completed_at") is None
                )
                if in_progress :
                    raise LocalApplicationError(
                        "APPLICATION-EXTERNAL-ATTEMPT-001",
                        "external collect requires every retrieval attempt to have a terminal outcome; "
                        "in-progress attempts: " + ", ".join(in_progress),
                    )
                return _CoreFacade.collect_external(self, run_id, submission)
        except LocalApplicationError:
            raise
        except ValueError as exc:
            raise LocalApplicationError(
                "APPLICATION-EXTERNAL-RUN-STATE-001", str(exc)
            ) from exc

    def show_run(self, run_id: str) -> Mapping[str, Any]:
        return self._virtual_run_inspection.show_run(run_id)

    def list_external_materials(self, *, limit: int = 100, cursor: str | None = None) -> Mapping[str, Any]:
        return self._features.materials.call(
            "list_external_materials", limit=limit, cursor=cursor
        )

    # ---- Research Exhibits --------------------------------------------------------
    def _exhibit_store(self):
        delegate = self._features.exhibits.call("_exhibit_store")
        return _StateGuardedResearchExhibitStore(
            delegate, self._application.state_repository
        )

    def capture_exhibit(self, value: Mapping[str, Any]) -> Mapping[str, Any]:
        return self._features.exhibits.call("capture_exhibit", value)

    def list_exhibits(self, *, rq_id: str | None = None) -> Mapping[str, Any]:
        return self._features.exhibits.call("list_exhibits", rq_id=rq_id)

    def show_exhibit(self, exhibit_id: str) -> Mapping[str, Any]:
        return self._features.exhibits.call("show_exhibit", exhibit_id)

    # ---- Survey ------------------------------------------------------------------
    def capture_survey_design(self, value: Mapping[str, Any]) -> Mapping[str, Any]:
        return self._features.survey.call("capture_survey_design", value)

    def show_survey_design(self, survey_design_id: str, version: str) -> Mapping[str, Any]:
        return self._features.survey.call("show_survey_design", survey_design_id, version)

    def capture_survey_instrument(self, value: Mapping[str, Any]) -> Mapping[str, Any]:
        return self._features.survey.call("capture_survey_instrument", value)

    def show_survey_instrument(self, instrument_id: str, version: str) -> Mapping[str, Any]:
        return self._features.survey.call("show_survey_instrument", instrument_id, version)

    def export_survey_instrument(self, instrument_id: str, version: str, *, format: str) -> Mapping[str, Any]:
        return self._features.survey.call(
            "export_survey_instrument", instrument_id, version, format=format
        )

    def normalize_survey_response(self, input_value: Mapping[str, Any]) -> Mapping[str, Any]:
        return self._features.survey_response.call("normalize_survey_response", input_value)

    def capture_survey_response(self, input_value: Mapping[str, Any]) -> Mapping[str, Any]:
        return self._features.survey_response.call("capture_survey_response", input_value)

    def capture_survey_response_dataset(self, input_value: Mapping[str, Any]) -> Mapping[str, Any]:
        return self._features.survey_response.call("capture_survey_response_dataset", input_value)

    def capture_virtual_run_response_dataset(self, run_id: str, *, instrument_ref: Mapping[str, Any]) -> Mapping[str, Any]:
        return self._features.survey_response.call(
            "capture_virtual_run_response_dataset", run_id, instrument_ref=instrument_ref
        )

    def show_survey_response(self, response_id: str, *, identity_namespace: str | None = None) -> Mapping[str, Any]:
        return self._features.survey_response.call(
            "show_survey_response", response_id, identity_namespace=identity_namespace
        )

    def show_survey_response_dataset(self, dataset_id: str, *, limit: int = 25, offset: int = 0) -> Mapping[str, Any]:
        return self._features.survey_response.call(
            "show_survey_response_dataset", dataset_id, limit=limit, offset=offset
        )

    def run_survey_virtual(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        return self._features.virtual_runner.call("run_survey_virtual", payload)

    def capture_survey_analysis_spec(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        return self._features.survey_analysis.call("capture_survey_analysis_spec", payload)

    def show_survey_analysis_spec(self, analysis_spec_id: str) -> Mapping[str, Any]:
        return self._features.survey_analysis.call("show_survey_analysis_spec", analysis_spec_id)

    def run_survey_aggregation(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        return self._features.survey_analysis.call("run_survey_aggregation", payload)

    def show_survey_aggregate_result(self, aggregate_result_id: str, *, limit: int = 25, offset: int = 0) -> Mapping[str, Any]:
        return self._features.survey_analysis.call(
            "show_survey_aggregate_result", aggregate_result_id, limit=limit, offset=offset
        )

    def show_survey_virtual_pretest(self, run_id: str, *, aggregate_result_id: str | None = None) -> Mapping[str, Any]:
        return self._virtual_pretest_inspection.show_survey_virtual_pretest(
            run_id, aggregate_result_id=aggregate_result_id
        )

    # ---- Project inputs -----------------------------------------------------------
    def register_project_input(self, value: Mapping[str, Any]) -> Mapping[str, Any]:
        return self._features.project_input.call("register_project_input", value)

    def list_project_inputs(self, *, limit: int = 100, cursor: str | None = None) -> Mapping[str, Any]:
        return self._features.project_input.call(
            "list_project_inputs", limit=limit, cursor=cursor
        )

    def show_project_input(self, input_id: str, *, format: str = "metadata") -> Mapping[str, Any]:
        return self._features.project_input.call(
            "show_project_input", input_id, format=format
        )