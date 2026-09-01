from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
from typing import Any, Mapping

import rfc8785

from core.runtime.ports import StaleHeadError
from plugins.local_survey_store import LocalSurveyStore, LocalSurveyStoreError, registry_digest
from plugins.sqlite_state_store.exhibit_guard import guard_research_state_head
from .facade import LocalApplicationError
from .retention_facade import LocalApplicationFacade as _BaseLocalApplicationFacade
from .survey_exchange import exchange_projection, markdown_projection
from .survey_validation import (
    capture_origin,
    input_object,
    required_string,
    schema_validate,
    string_list,
    validate_digest,
    validate_questionnaire,
    validate_rqs,
)

_ROOT = Path(__file__).resolve().parents[2]
_DESIGN_SCHEMA = _ROOT / "core/packages/survey/survey-design.schema.json"
_CONTRACT_SCHEMA = _ROOT / "core/packages/survey/survey-contract.schema.json"
_EXCHANGE_SCHEMA = _ROOT / "core/packages/survey/survey-instrument-exchange.schema.json"
_STORE_NAME = "survey-registry.sqlite3"
_DESIGN_FIELDS = {"rq_ids", "design", "capture_origin"}
_INSTRUMENT_FIELDS = {
    "survey_design_id",
    "survey_design_version",
    "title",
    "description",
    "questionnaire",
    "capture_origin",
}


def _snapshot(state) -> dict[str, str]:
    return {
        "lineage_ref": str(state.active_lineage_ref),
        "snapshot_ref": str(state.current_snapshot["id"]),
        "snapshot_digest": str(state.current_snapshot["content_digest"]),
    }


class LocalApplicationFacade(_BaseLocalApplicationFacade):
    """Production Survey Design/Instrument registry and provider-neutral exchange."""

    def _survey_store(self) -> LocalSurveyStore:
        if self._workspace_root is None:
            root = getattr(self._application, "root", None)
            if root is None:
                raise LocalApplicationError(
                    "APPLICATION-SURVEY-STORE-001",
                    "Survey registry requires a local application root",
                )
            return LocalSurveyStore(Path(root) / _STORE_NAME)
        return LocalSurveyStore(
            self._workspace_root / ".research-loom" / _STORE_NAME
        )

    def _state(self):
        repository = self._application.state_repository
        lineage = repository.load_active_lineage_ref(self._project_id)
        return repository.load_state_view(self._project_id, lineage)

    def _capture(self, state, operation):
        try:
            with guard_research_state_head(
                self._application.state_repository,
                self._project_id,
                lineage_ref=str(state.active_lineage_ref),
                snapshot_ref=str(state.current_snapshot["id"]),
                snapshot_digest=str(state.current_snapshot["content_digest"]),
            ):
                return operation()
        except StaleHeadError as exc:
            raise LocalApplicationError(
                "APPLICATION-SURVEY-STATE-STALE-001",
                "Research State changed before Survey persistence",
            ) from exc

    @staticmethod
    def _record(
        state,
        project_id: str,
        rq_ids: list[str],
        origin: str,
    ) -> dict[str, Any]:
        return {
            "schema_version": "0.1.0",
            "project_id": project_id,
            "rq_ids": list(rq_ids),
            "captured_against": _snapshot(state),
            "project_config_digest": str(state.project_config_digest),
            "effective_profile_set_digest": str(
                state.effective_profile_set_digest
            ),
            "captured_at": "",
            "capture_origin": origin,
        }

    @staticmethod
    def _validate_design_current(design_record: Mapping[str, Any], state) -> None:
        binding = design_record["captured_against"]
        if str(design_record["project_id"]) != state.project_ref:
            raise LocalApplicationError(
                "APPLICATION-SURVEY-DESIGN-BINDING-001",
                "Survey Design belongs to a different project",
            )
        if str(binding["lineage_ref"]) != str(state.active_lineage_ref):
            raise LocalApplicationError(
                "APPLICATION-SURVEY-DESIGN-BINDING-001",
                "Survey Design belongs to a different Research lineage",
            )
        if (
            str(design_record["project_config_digest"])
            != str(state.project_config_digest)
            or str(design_record["effective_profile_set_digest"])
            != str(state.effective_profile_set_digest)
        ):
            raise LocalApplicationError(
                "APPLICATION-SURVEY-DESIGN-BINDING-001",
                "Survey Design provenance does not match the current project/profile binding",
            )

    def capture_survey_design(
        self, input_value: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        value = input_object(
            input_value, _DESIGN_FIELDS, "Survey Design capture"
        )
        rq_ids = string_list(value.get("rq_ids"), "rq_ids", required=True)
        design = value.get("design")
        if not isinstance(design, Mapping):
            raise LocalApplicationError(
                "APPLICATION-SURVEY-INPUT-001", "design must be an object"
            )
        design = deepcopy(dict(design))
        schema_validate(
            design,
            _DESIGN_SCHEMA,
            "APPLICATION-SURVEY-DESIGN-SCHEMA-001",
        )
        validate_digest(
            design,
            "content_digest",
            "APPLICATION-SURVEY-DESIGN-DIGEST-001",
        )
        state = self._state()
        validate_rqs(rq_ids, state)
        document = self._record(
            state,
            self._project_id,
            rq_ids,
            capture_origin(value),
        )
        document["captured_at"] = self._application.clock.now()
        document["design"] = design
        document["registry_digest"] = registry_digest(document)
        try:
            created = self._capture(
                state, lambda: self._survey_store().capture_design(document)
            )
        except LocalSurveyStoreError as exc:
            raise LocalApplicationError(exc.code, exc.message) from exc
        return {
            "status": "CAPTURED" if created else "ALREADY_CAPTURED",
            "project_id": self._project_id,
            "survey_design_id": str(design["survey_design_id"]),
            "version": str(design["version"]),
            "content_digest": str(design["content_digest"]),
            "rq_ids": rq_ids,
            "captured_against": deepcopy(document["captured_against"]),
        }

    def show_survey_design(
        self, survey_design_id: str, version: str
    ) -> Mapping[str, Any]:
        if not survey_design_id or not version:
            raise LocalApplicationError(
                "APPLICATION-SURVEY-INPUT-001",
                "survey_design_id and version are required",
            )
        try:
            record = self._survey_store().load_design(
                self._project_id, survey_design_id, version
            )
        except LocalSurveyStoreError as exc:
            raise LocalApplicationError(exc.code, exc.message) from exc
        if record is None:
            raise LocalApplicationError(
                "APPLICATION-SURVEY-DESIGN-001",
                "unknown Survey Design revision",
            )
        return {
            "status": "OK",
            "project_id": self._project_id,
            "survey_design": record,
        }

    def capture_survey_instrument(
        self, input_value: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        value = input_object(
            input_value, _INSTRUMENT_FIELDS, "Survey Instrument capture"
        )
        design_id = required_string(value, "survey_design_id")
        design_version = required_string(value, "survey_design_version")
        title = required_string(value, "title")
        description = value.get("description", "")
        if not isinstance(description, str):
            raise LocalApplicationError(
                "APPLICATION-SURVEY-INPUT-001",
                "description must be a string",
            )
        questionnaire = value.get("questionnaire")
        if not isinstance(questionnaire, Mapping):
            raise LocalApplicationError(
                "APPLICATION-SURVEY-INPUT-001",
                "questionnaire must be an object",
            )
        questionnaire = deepcopy(dict(questionnaire))
        schema_validate(
            questionnaire,
            _CONTRACT_SCHEMA,
            "APPLICATION-SURVEY-QUESTIONNAIRE-SCHEMA-001",
        )
        if questionnaire.get("object_type") != "survey_questionnaire":
            raise LocalApplicationError(
                "APPLICATION-SURVEY-QUESTIONNAIRE-SCHEMA-001",
                "instrument capture requires a canonical survey_questionnaire",
            )
        validate_digest(
            questionnaire,
            "content_digest",
            "APPLICATION-SURVEY-QUESTIONNAIRE-DIGEST-001",
        )
        store = self._survey_store()
        try:
            design_record = store.load_design(
                self._project_id, design_id, design_version
            )
        except LocalSurveyStoreError as exc:
            raise LocalApplicationError(exc.code, exc.message) from exc
        if design_record is None:
            raise LocalApplicationError(
                "APPLICATION-SURVEY-DESIGN-BINDING-001",
                "bound Survey Design revision does not exist",
            )

        state = self._state()
        self._validate_design_current(design_record, state)
        validate_rqs(list(design_record["rq_ids"]), state)
        validate_questionnaire(questionnaire, design_record, state)
        design = design_record["design"]
        document = self._record(
            state,
            self._project_id,
            list(design_record["rq_ids"]),
            capture_origin(value),
        )
        document.update(
            {
                "captured_at": self._application.clock.now(),
                "title": title,
                "description": description,
                "design_ref": {
                    "survey_design_id": str(design["survey_design_id"]),
                    "version": str(design["version"]),
                    "content_digest": str(design["content_digest"]),
                },
                "questionnaire": questionnaire,
            }
        )
        document["registry_digest"] = registry_digest(document)
        try:
            created = self._capture(
                state, lambda: store.capture_instrument(document)
            )
        except LocalSurveyStoreError as exc:
            raise LocalApplicationError(exc.code, exc.message) from exc
        return {
            "status": "CAPTURED" if created else "ALREADY_CAPTURED",
            "project_id": self._project_id,
            "instrument_id": str(questionnaire["questionnaire_id"]),
            "version": str(questionnaire["version"]),
            "content_digest": str(questionnaire["content_digest"]),
            "design_ref": deepcopy(document["design_ref"]),
            "rq_ids": list(document["rq_ids"]),
            "captured_against": deepcopy(document["captured_against"]),
        }

    def show_survey_instrument(
        self, instrument_id: str, version: str
    ) -> Mapping[str, Any]:
        if not instrument_id or not version:
            raise LocalApplicationError(
                "APPLICATION-SURVEY-INPUT-001",
                "instrument_id and version are required",
            )
        try:
            record = self._survey_store().load_instrument(
                self._project_id, instrument_id, version
            )
        except LocalSurveyStoreError as exc:
            raise LocalApplicationError(exc.code, exc.message) from exc
        if record is None:
            raise LocalApplicationError(
                "APPLICATION-SURVEY-INSTRUMENT-001",
                "unknown Survey Instrument revision",
            )
        return {
            "status": "OK",
            "project_id": self._project_id,
            "instrument": record,
        }

    def export_survey_instrument(
        self,
        instrument_id: str,
        version: str,
        *,
        format: str,
    ) -> Mapping[str, Any]:
        record = self.show_survey_instrument(instrument_id, version)[
            "instrument"
        ]
        ref = record["design_ref"]
        try:
            design_record = self._survey_store().load_design(
                self._project_id,
                str(ref["survey_design_id"]),
                str(ref["version"]),
            )
        except LocalSurveyStoreError as exc:
            raise LocalApplicationError(exc.code, exc.message) from exc
        if (
            design_record is None
            or design_record["design"]["content_digest"]
            != ref["content_digest"]
        ):
            raise LocalApplicationError(
                "APPLICATION-SURVEY-DESIGN-BINDING-001",
                "Survey Instrument Design binding no longer resolves exactly",
            )

        exchange = exchange_projection(record, design_record)
        schema_validate(
            exchange,
            _EXCHANGE_SCHEMA,
            "APPLICATION-SURVEY-EXCHANGE-SCHEMA-001",
        )
        if format == "json":
            content = rfc8785.dumps(exchange)
            media_type, extension = "application/json", ".json"
        elif format == "markdown":
            content = markdown_projection(exchange).encode("utf-8")
            media_type, extension = "text/markdown", ".md"
        else:
            raise LocalApplicationError(
                "APPLICATION-SURVEY-INPUT-001",
                "format must be json or markdown",
            )
        return {
            "status": "OK",
            "project_id": self._project_id,
            "instrument_id": instrument_id,
            "version": version,
            "format": format,
            "media_type": media_type,
            "file_extension": extension,
            "export_digest": "sha256:" + hashlib.sha256(content).hexdigest(),
            "content": content.decode("utf-8"),
        }
