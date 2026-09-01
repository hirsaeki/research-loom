from __future__ import annotations

from copy import deepcopy
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
            dataset = self._survey_response_store().load_dataset(
                self._project_id,
                dataset_id,
            )
        except LocalSurveyResponseStoreError as exc:
            raise LocalApplicationError(exc.code, exc.message) from exc
        if dataset is None:
            raise LocalApplicationError(
                "APPLICATION-SURVEY-RESPONSE-DATASET-001",
                "unknown SurveyResponseDataset",
            )

        entries: list[dict[str, Any]] = []
        for ref in dataset["accepted_response_refs"]:
            entries.append({"kind": "accepted_response", "response_ref": deepcopy(ref)})
        rejected_by_ref = {
            (
                (item.get("canonical_response_ref") or {}).get("identity_namespace"),
                (item.get("canonical_response_ref") or {}).get("response_id"),
            ): item
            for item in dataset["rejected_inputs"]
            if item.get("canonical_response_ref")
        }
        for ref in dataset["rejected_response_refs"]:
            entries.append(
                {
                    "kind": "rejected_response",
                    "response_ref": deepcopy(ref),
                    "issues": deepcopy(
                        rejected_by_ref.get(
                            (ref["identity_namespace"], ref["response_id"]), {}
                        ).get("issues", [])
                    ),
                }
            )
        for rejected in dataset["rejected_inputs"]:
            if rejected.get("canonical_response_ref"):
                continue
            entries.append(
                {
                    "kind": "rejected_raw_input",
                    "raw_input_digest": rejected["raw_input_digest"],
                    "raw_input": deepcopy(rejected["raw_input"]),
                    "issues": deepcopy(rejected["issues"]),
                }
            )
        entries.sort(
            key=lambda item: (
                item["kind"],
                str((item.get("response_ref") or {}).get("identity_namespace", "")),
                str((item.get("response_ref") or {}).get("response_id", "")),
                str(item.get("raw_input_digest", "")),
            )
        )
        selected = entries[offset : offset + limit]
        metadata = deepcopy(dict(dataset))
        for field in (
            "accepted_response_refs",
            "rejected_response_refs",
            "rejected_inputs",
        ):
            metadata.pop(field, None)
        return {
            "status": "OK",
            "project_id": self._project_id,
            "dataset": metadata,
            "entries": selected,
            "pagination": {
                "offset": offset,
                "limit": limit,
                "returned": len(selected),
                "total": len(entries),
                "has_more": offset + len(selected) < len(entries),
            },
        }
