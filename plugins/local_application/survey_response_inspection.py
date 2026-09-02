from __future__ import annotations

from typing import Any, Mapping

from plugins.local_survey_response_store import LocalSurveyResponseStoreError
from .facade import LocalApplicationError

_MAX_DATASET_SHOW = 100


class SurveyResponseInspectionMixin:
    def show_survey_response(
        self,
        response_id: str,
        *,
        identity_namespace: str | None = None,
    ) -> Mapping[str, Any]:
        if not response_id:
            raise LocalApplicationError(
                "APPLICATION-SURVEY-INPUT-001",
                "response_id is required",
            )
        try:
            record = self._survey_response_store().load_response(
                self._project_id,
                response_id,
                identity_namespace=identity_namespace,
            )
        except LocalSurveyResponseStoreError as exc:
            raise LocalApplicationError(exc.code, exc.message) from exc
        if record is None:
            raise LocalApplicationError(
                "APPLICATION-SURVEY-RESPONSE-001",
                "unknown SurveyResponse",
            )
        return {
            "status": "OK",
            "project_id": self._project_id,
            "response": record["response"],
            "raw_input": record["raw_input"],
        }

    def show_survey_response_dataset(
        self,
        dataset_id: str,
        *,
        limit: int = 25,
        offset: int = 0,
    ) -> Mapping[str, Any]:
        if not dataset_id:
            raise LocalApplicationError(
                "APPLICATION-SURVEY-INPUT-001",
                "dataset_id is required",
            )
        if not isinstance(limit, int) or limit < 1 or limit > _MAX_DATASET_SHOW:
            raise LocalApplicationError(
                "APPLICATION-SURVEY-INPUT-001",
                f"limit must be between 1 and {_MAX_DATASET_SHOW}",
            )
        if not isinstance(offset, int) or offset < 0:
            raise LocalApplicationError(
                "APPLICATION-SURVEY-INPUT-001",
                "offset must be zero or greater",
            )
        try:
            page = self._survey_response_store().load_dataset_entries(
                self._project_id,
                dataset_id,
                limit=limit,
                offset=offset,
            )
        except LocalSurveyResponseStoreError as exc:
            raise LocalApplicationError(exc.code, exc.message) from exc
        if page is None:
            raise LocalApplicationError(
                "APPLICATION-SURVEY-RESPONSE-DATASET-001",
                "unknown SurveyResponseDataset",
            )

        entries = page["entries"]
        total = int(page["total"])
        return {
            "status": "OK",
            "project_id": self._project_id,
            "dataset": page["dataset"],
            "entries": entries,
            "pagination": {
                "offset": offset,
                "limit": limit,
                "returned": len(entries),
                "total": total,
                "has_more": offset + len(entries) < total,
            },
        }
