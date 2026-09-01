from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from plugins.local_survey_response_store import LocalSurveyResponseStore
from plugins.local_survey_store import LocalSurveyStoreError
from plugins.survey_response import normalize_response
from .facade import LocalApplicationError
from .survey_validation import input_object, required_string

_STORE_NAME = "survey-response-registry.sqlite3"
_RESPONSE_FIELDS = {
    "instrument_id", "instrument_version", "instrument_digest",
    "response_origin", "epistemic_status", "response",
    "source_run_id", "source_provenance", "capture_origin",
}
_DATASET_FIELDS = (_RESPONSE_FIELDS - {"response"}) | {"responses"}


def _status_value(value: Any) -> str:
    return str(getattr(value, "value", value))


class SurveyResponseCoreMixin:
    def _survey_response_store(self) -> LocalSurveyResponseStore:
        if self._workspace_root is None:
            root = getattr(self._application, "root", None)
            if root is None:
                raise LocalApplicationError(
                    "APPLICATION-SURVEY-RESPONSE-STORE-001",
                    "Survey response registry requires a local application root",
                )
            return LocalSurveyResponseStore(Path(root) / _STORE_NAME)
        return LocalSurveyResponseStore(
            self._workspace_root / ".research-loom" / _STORE_NAME
        )

    def _resolve_instrument(
        self,
        value: Mapping[str, Any],
    ) -> tuple[dict[str, Any], dict[str, str]]:
        instrument_id = required_string(value, "instrument_id")
        instrument_version = required_string(value, "instrument_version")
        instrument_digest = required_string(value, "instrument_digest")
        if not instrument_digest.startswith("sha256:"):
            raise LocalApplicationError(
                "APPLICATION-SURVEY-RESPONSE-INSTRUMENT-001",
                "instrument_digest must be a sha256 digest",
            )
        try:
            record = self._survey_store().load_instrument(
                self._project_id,
                instrument_id,
                instrument_version,
            )
        except LocalSurveyStoreError as exc:
            raise LocalApplicationError(exc.code, exc.message) from exc
        if record is None:
            raise LocalApplicationError(
                "APPLICATION-SURVEY-RESPONSE-INSTRUMENT-001",
                "exact Survey Instrument revision was not found",
            )
        questionnaire = deepcopy(dict(record["questionnaire"]))
        if questionnaire.get("content_digest") != instrument_digest:
            raise LocalApplicationError(
                "APPLICATION-SURVEY-RESPONSE-INSTRUMENT-001",
                "Survey response Instrument digest does not match the exact stored revision",
            )
        return questionnaire, {
            "id": instrument_id,
            "version": instrument_version,
            "content_digest": instrument_digest,
        }

    @staticmethod
    def _origin(value: Mapping[str, Any]) -> tuple[str, str]:
        origin = required_string(value, "response_origin")
        epistemic = required_string(value, "epistemic_status")
        if origin not in {"synthetic", "real"}:
            raise LocalApplicationError(
                "SURVEY_RESPONSE_ORIGIN_MISMATCH",
                "response_origin must be synthetic or real",
            )
        expected = "SYNTHETIC_TEST_ONLY" if origin == "synthetic" else "EMPIRICAL"
        if epistemic != expected:
            raise LocalApplicationError(
                "SURVEY_RESPONSE_ORIGIN_MISMATCH",
                f"{origin} response origin requires explicit epistemic_status={expected}",
            )
        return origin, epistemic

    @staticmethod
    def _source_provenance(value: Mapping[str, Any]) -> dict[str, Any]:
        provenance = value.get("source_provenance", {})
        if not isinstance(provenance, Mapping):
            raise LocalApplicationError(
                "APPLICATION-SURVEY-INPUT-001",
                "source_provenance must be an object",
            )
        return deepcopy(dict(provenance))

    def _source_run(self, value: Mapping[str, Any], *, origin: str) -> str | None:
        raw = value.get("source_run_id")
        if raw is None:
            return None
        if not isinstance(raw, str) or not raw.strip():
            raise LocalApplicationError(
                "APPLICATION-SURVEY-INPUT-001",
                "source_run_id must be a non-empty string when supplied",
            )
        run = self._application.execution_store.load_run(raw)
        if run is None or str(run.project_ref) != self._project_id:
            raise LocalApplicationError(
                "APPLICATION-SURVEY-RESPONSE-RUN-001",
                "source_run_id does not resolve in this project",
            )
        if _status_value(run.status) != "COMPLETED":
            raise LocalApplicationError(
                "APPLICATION-SURVEY-RESPONSE-RUN-001",
                "source_run_id must reference a completed Run",
            )
        if origin == "synthetic" and _status_value(run.execution_mode) != "virtual":
            raise LocalApplicationError(
                "SURVEY_RESPONSE_ORIGIN_MISMATCH",
                "synthetic response provenance may only bind a virtual source Run",
            )
        return raw

    def normalize_survey_response(
        self,
        input_value: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        value = input_object(input_value, _RESPONSE_FIELDS, "Survey response normalize")
        questionnaire, instrument_ref = self._resolve_instrument(value)
        origin, epistemic = self._origin(value)
        source_run_id = self._source_run(value, origin=origin)
        raw = value.get("response")
        outcome = normalize_response(
            questionnaire,
            raw,
            project_id=self._project_id,
            instrument_ref=instrument_ref,
            response_origin=origin,
            epistemic_status=epistemic,
            ingested_at=self._application.clock.now(),
            source_run_id=source_run_id,
            source_provenance=self._source_provenance(value),
        )
        return {
            "status": "OK",
            "project_id": self._project_id,
            "instrument_ref": instrument_ref,
            "response_origin": origin,
            "epistemic_status": epistemic,
            "normalization": outcome,
            "research_state_mutation_performed": False,
        }
