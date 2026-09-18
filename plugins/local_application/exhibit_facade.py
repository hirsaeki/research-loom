from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from plugins.local_research_exhibit_store import (
    LocalResearchExhibitStore,
    LocalResearchExhibitStoreError,
    SUPPORTED_EXHIBIT_KINDS,
    content_digest,
    normalized_content,
)

from .run_inspection_facade import LocalApplicationFacade as _BaseLocalApplicationFacade
from .facade import LocalApplicationError


_EXHIBIT_STORE_NAME = "research-exhibits.sqlite3"
_EXHIBIT_LIST_LIMIT = 100
_CAPTURE_FIELDS = {
    "kind",
    "title",
    "purpose",
    "rq_ids",
    "source_run_ids",
    "source_artifact_refs",
    "source_object_ids",
    "derived_from_exhibit_ids",
    "content",
    "visual_target",
    "capture_origin",
}
_HARNESS_OWNED_FIELDS = {
    "exhibit_id",
    "project_id",
    "captured_against",
    "content_digest",
    "captured_at",
}


def _string_list(value: Any, field: str, *, required: bool = False) -> list[str]:
    if value is None:
        if required:
            raise LocalApplicationError(
                "APPLICATION-EXHIBIT-INPUT-001", f"{field} is required"
            )
        return []
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise LocalApplicationError(
            "APPLICATION-EXHIBIT-INPUT-001",
            f"{field} must be an array of non-empty strings",
        )
    if len(value) != len(set(value)):
        raise LocalApplicationError(
            "APPLICATION-EXHIBIT-INPUT-001", f"{field} must not contain duplicates"
        )
    if required and not value:
        raise LocalApplicationError(
            "APPLICATION-EXHIBIT-INPUT-001", f"{field} requires at least one item"
        )
    return [str(item) for item in value]


def _metadata_projection(document: Mapping[str, Any]) -> Mapping[str, Any]:
    return {
        "exhibit_id": str(document["exhibit_id"]),
        "kind": str(document["kind"]),
        "title": str(document["title"]),
        "purpose": str(document["purpose"]),
        "rq_ids": list(document["rq_ids"]),
        "source_run_ids": list(document["source_run_ids"]),
        "source_artifact_refs": list(document["source_artifact_refs"]),
        "source_object_ids": list(document["source_object_ids"]),
        "derived_from_exhibit_ids": list(document["derived_from_exhibit_ids"]),
        "content_representation": str(document["content"]["representation"]),
        "content_digest": str(document["content_digest"]),
        "captured_against": deepcopy(dict(document["captured_against"])),
        "captured_at": str(document["provenance"]["captured_at"]),
        "capture_origin": str(document["provenance"]["capture_origin"]),
    }


def _stored_metadata_projection(metadata: Mapping[str, Any]) -> Mapping[str, Any]:
    return {
        "exhibit_id": str(metadata["exhibit_id"]),
        "kind": str(metadata["kind"]),
        "title": str(metadata["title"]),
        "purpose": str(metadata["purpose"]),
        "rq_ids": list(metadata["rq_ids"]),
        "source_run_ids": list(metadata["source_run_ids"]),
        "source_artifact_refs": list(metadata["source_artifact_refs"]),
        "source_object_ids": list(metadata["source_object_ids"]),
        "derived_from_exhibit_ids": list(metadata["derived_from_exhibit_ids"]),
        "content_representation": str(metadata["content_representation"]),
        "content_digest": str(metadata["content_digest"]),
        "captured_against": deepcopy(dict(metadata["captured_against"])),
        "captured_at": str(metadata["captured_at"]),
        "capture_origin": str(metadata["capture_origin"]),
    }


def _state_binding(state) -> tuple[str, str, str]:
    snapshot = state.current_snapshot
    return (
        str(state.active_lineage_ref),
        str(snapshot["id"]),
        str(snapshot["content_digest"]),
    )


class LocalApplicationFacade(_BaseLocalApplicationFacade):
    """Production facade extended with immutable Research Exhibit persistence."""

    def _exhibit_store(self) -> LocalResearchExhibitStore:
        return LocalResearchExhibitStore(self._application.root / _EXHIBIT_STORE_NAME)

    def _current_state(self):
        repository = self._application.state_repository
        lineage = repository.load_active_lineage_ref(self._project_id)
        return repository.load_state_view(self._project_id, lineage)

    @staticmethod
    def _authoritative_rqs(state) -> dict[str, Mapping[str, Any]]:
        return {
            str(item["id"]): item
            for item in state.effective_objects()
            if item.get("kind") == "research_question"
            and str(item.get("project_id", state.project_ref)) == state.project_ref
            and item.get("adoption_state") == "approved"
        }

    def _validate_rqs(self, rq_ids: list[str], state) -> None:
        known = self._authoritative_rqs(state)
        unknown = [rq_id for rq_id in rq_ids if rq_id not in known]
        if unknown:
            raise LocalApplicationError(
                "APPLICATION-EXHIBIT-RQ-001",
                "Research Exhibit RQ bindings must resolve to current authoritative approved Research Questions: "
                + ", ".join(unknown),
            )

    def _validate_source_runs(
        self,
        source_run_ids: list[str],
        source_artifact_refs: list[str],
    ) -> dict[str, Any]:
        artifact_to_run: dict[str, str] = {}
        artifact_index: dict[str, Any] = {}
        for run_id in source_run_ids:
            run = self._application.execution_store.load_run(run_id)
            if run is None:
                raise LocalApplicationError(
                    "APPLICATION-EXHIBIT-RUN-001", f"unknown source Run: {run_id}"
                )
            if run.project_ref != self._project_id:
                raise LocalApplicationError(
                    "APPLICATION-EXHIBIT-RUN-BINDING-001",
                    f"source Run belongs to another project: {run_id}",
                )
            for artifact in self._application.execution_store.artifacts_for(run_id):
                artifact_to_run[str(artifact.artifact_id)] = run_id
                artifact_index[str(artifact.artifact_id)] = artifact

        if source_artifact_refs and not source_run_ids:
            raise LocalApplicationError(
                "APPLICATION-EXHIBIT-ARTIFACT-001",
                "source_artifact_refs require declared source_run_ids",
            )
        missing = [
            artifact_id
            for artifact_id in source_artifact_refs
            if artifact_id not in artifact_to_run
        ]
        if missing:
            raise LocalApplicationError(
                "APPLICATION-EXHIBIT-ARTIFACT-001",
                "source artifacts must exist on one of the declared current-project source Runs: "
                + ", ".join(missing),
            )
        return artifact_index

    @staticmethod
    def _normalize_visual_locator(value: Any) -> dict[str, Any]:
        allowed = {"kind", "page", "label", "region"}
        if not isinstance(value, Mapping) or set(value) - allowed:
            raise LocalApplicationError(
                "APPLICATION-EXHIBIT-VISUAL-001", "visual_target.locator is invalid"
            )
        kind = value.get("kind")
        if kind not in {"figure", "table", "diagram", "region"}:
            raise LocalApplicationError(
                "APPLICATION-EXHIBIT-VISUAL-001", "visual_target.locator.kind is invalid"
            )
        page = value.get("page")
        if page is not None and (isinstance(page, bool) or not isinstance(page, int) or page < 1):
            raise LocalApplicationError(
                "APPLICATION-EXHIBIT-VISUAL-001", "visual_target.locator.page is invalid"
            )
        label = value.get("label")
        if label is not None and (not isinstance(label, str) or not label.strip()):
            raise LocalApplicationError(
                "APPLICATION-EXHIBIT-VISUAL-001", "visual_target.locator.label is invalid"
            )
        region = value.get("region")
        normalized_region = None
        if region is not None:
            if not isinstance(region, Mapping) or set(region) != {"x", "y", "width", "height", "unit"} or region.get("unit") != "normalized":
                raise LocalApplicationError(
                    "APPLICATION-EXHIBIT-VISUAL-001", "visual_target.locator.region is invalid"
                )
            normalized_region = {"unit": "normalized"}
            for field in ("x", "y", "width", "height"):
                item = region.get(field)
                if isinstance(item, bool) or not isinstance(item, (int, float)) or item < 0 or item > 1:
                    raise LocalApplicationError(
                        "APPLICATION-EXHIBIT-VISUAL-001",
                        f"visual_target.locator.region.{field} is invalid",
                    )
                normalized_region[field] = item
            if (
                normalized_region["width"] <= 0
                or normalized_region["height"] <= 0
                or normalized_region["x"] + normalized_region["width"] > 1
                or normalized_region["y"] + normalized_region["height"] > 1
            ):
                raise LocalApplicationError(
                    "APPLICATION-EXHIBIT-VISUAL-001",
                    "visual_target.locator.region exceeds normalized page bounds",
                )
        if page is None and label is None and normalized_region is None:
            raise LocalApplicationError(
                "APPLICATION-EXHIBIT-VISUAL-001",
                "visual_target.locator requires page, label, or region",
            )
        result = {"kind": str(kind)}
        if page is not None:
            result["page"] = page
        if label is not None:
            result["label"] = label
        if normalized_region is not None:
            result["region"] = normalized_region
        return result

    def _normalize_visual_target(
        self,
        value: Any,
        *,
        source_run_ids: list[str],
        source_artifact_refs: list[str],
        artifact_index: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        if value is None:
            return None
        allowed = {
            "source_run_id", "capture_id", "source_artifact_ref", "locator",
            "derived_artifact_ref", "derivation_type",
        }
        if not isinstance(value, Mapping) or set(value) - allowed:
            raise LocalApplicationError(
                "APPLICATION-EXHIBIT-VISUAL-001", "visual_target shape is invalid"
            )
        for field in ("source_run_id", "capture_id", "source_artifact_ref"):
            item = value.get(field)
            if not isinstance(item, str) or not item.strip():
                raise LocalApplicationError(
                    "APPLICATION-EXHIBIT-VISUAL-001", f"visual_target.{field} is required"
                )
        source_run_id = str(value["source_run_id"])
        capture_id = str(value["capture_id"])
        source_artifact_ref = str(value["source_artifact_ref"])
        if source_run_id not in source_run_ids or source_artifact_ref not in source_artifact_refs:
            raise LocalApplicationError(
                "APPLICATION-EXHIBIT-VISUAL-001",
                "visual_target must use declared source_run_ids/source_artifact_refs",
            )
        source = artifact_index.get(source_artifact_ref)
        if source is None or str(source.role) != "desktop_research.original_capture":
            raise LocalApplicationError(
                "APPLICATION-EXHIBIT-VISUAL-001",
                "visual_target source artifact must be a stored Desktop Research original capture",
            )
        if str(source.provenance.get("capture_id", "")) != capture_id:
            raise LocalApplicationError(
                "APPLICATION-EXHIBIT-VISUAL-001",
                "visual_target capture_id does not match the source artifact provenance",
            )
        media_type = str(source.media_type)
        if not (media_type.startswith("image/") or media_type == "application/pdf"):
            raise LocalApplicationError(
                "APPLICATION-EXHIBIT-VISUAL-001",
                "visual_target source must be a stored PDF or image",
            )
        normalized = {
            "target_type": "source_visual",
            "source_run_id": source_run_id,
            "capture_id": capture_id,
            "source_artifact_ref": source_artifact_ref,
            "locator": self._normalize_visual_locator(value.get("locator")),
            "source_media_type": media_type,
            "source_byte_length": int(source.size),
            "source_digest": str(source.digest),
            "derived_artifact": None,
        }
        derived_ref = value.get("derived_artifact_ref")
        derivation_type = value.get("derivation_type")
        if derived_ref is None and derivation_type is None:
            return normalized
        if (
            not isinstance(derived_ref, str)
            or not derived_ref.strip()
            or derived_ref not in source_artifact_refs
            or derivation_type not in {"crop", "table_extraction"}
        ):
            raise LocalApplicationError(
                "APPLICATION-EXHIBIT-VISUAL-001",
                "derived visual artifacts require declared artifact ref and derivation_type",
            )
        derived = artifact_index.get(derived_ref)
        if derived is None or source_artifact_ref not in tuple(derived.provenance.get("parent_artifact_refs", ())):
            raise LocalApplicationError(
                "APPLICATION-EXHIBIT-VISUAL-001",
                "derived visual artifact must declare the source original as its parent",
            )
        normalized["derived_artifact"] = {
            "artifact_ref": str(derived.artifact_id),
            "derived_from_artifact_ref": source_artifact_ref,
            "derivation_type": str(derivation_type),
            "media_type": str(derived.media_type),
            "byte_length": int(derived.size),
            "digest": str(derived.digest),
        }
        return normalized

    def _validate_source_objects(self, source_object_ids: list[str], state) -> None:
        effective = {
            str(item.get("id")): item
            for item in state.effective_objects()
            if item.get("id")
        }
        for object_id in source_object_ids:
            item = effective.get(object_id)
            if item is None:
                continue
            project_id = item.get("project_id")
            if project_id is not None and str(project_id) != self._project_id:
                raise LocalApplicationError(
                    "APPLICATION-EXHIBIT-OBJECT-BINDING-001",
                    f"source object belongs to another project: {object_id}",
                )

    def _validate_derived_exhibits(
        self,
        derived_from: list[str],
        store: LocalResearchExhibitStore,
    ) -> None:
        for exhibit_id in derived_from:
            try:
                prior = store.load(exhibit_id)
            except LocalResearchExhibitStoreError as exc:
                raise LocalApplicationError(exc.code, exc.message) from exc
            if prior is None:
                raise LocalApplicationError(
                    "APPLICATION-EXHIBIT-DERIVED-001",
                    f"unknown derived-from Research Exhibit: {exhibit_id}",
                )
            if str(prior["project_id"]) != self._project_id:
                raise LocalApplicationError(
                    "APPLICATION-EXHIBIT-DERIVED-001",
                    f"derived-from Research Exhibit belongs to another project: {exhibit_id}",
                )

    def capture_exhibit(self, input_value: Mapping[str, Any]) -> Mapping[str, Any]:
        if not isinstance(input_value, Mapping):
            raise LocalApplicationError(
                "APPLICATION-EXHIBIT-INPUT-001", "Research Exhibit input must be an object"
            )
        unknown = set(input_value) - _CAPTURE_FIELDS
        if unknown:
            owned = sorted(str(item) for item in unknown if item in _HARNESS_OWNED_FIELDS)
            if owned:
                raise LocalApplicationError(
                    "APPLICATION-EXHIBIT-AUTHORITY-001",
                    "caller may not supply Harness-owned Research Exhibit fields: "
                    + ", ".join(owned),
                )
            raise LocalApplicationError(
                "APPLICATION-EXHIBIT-INPUT-001",
                "Research Exhibit input contains unknown fields: "
                + ", ".join(sorted(str(item) for item in unknown)),
            )

        kind = input_value.get("kind")
        if kind not in SUPPORTED_EXHIBIT_KINDS:
            raise LocalApplicationError(
                "APPLICATION-EXHIBIT-INPUT-001", "unsupported Research Exhibit kind"
            )
        title = input_value.get("title")
        purpose = input_value.get("purpose")
        if not isinstance(title, str) or not title.strip():
            raise LocalApplicationError(
                "APPLICATION-EXHIBIT-INPUT-001", "title must be a non-empty string"
            )
        if not isinstance(purpose, str) or not purpose.strip():
            raise LocalApplicationError(
                "APPLICATION-EXHIBIT-INPUT-001", "purpose must be a non-empty string"
            )

        rq_ids = _string_list(input_value.get("rq_ids"), "rq_ids", required=True)
        source_run_ids = _string_list(input_value.get("source_run_ids"), "source_run_ids")
        source_artifact_refs = _string_list(
            input_value.get("source_artifact_refs"), "source_artifact_refs"
        )
        source_object_ids = _string_list(
            input_value.get("source_object_ids"), "source_object_ids"
        )
        derived_from = _string_list(
            input_value.get("derived_from_exhibit_ids"), "derived_from_exhibit_ids"
        )
        capture_origin = input_value.get("capture_origin", "operator_conversation")
        if not isinstance(capture_origin, str) or not capture_origin.strip():
            raise LocalApplicationError(
                "APPLICATION-EXHIBIT-INPUT-001",
                "capture_origin must be a non-empty string",
            )

        raw_content = input_value.get("content")
        try:
            content = normalized_content(raw_content)
        except LocalResearchExhibitStoreError as exc:
            raise LocalApplicationError(exc.code, exc.message) from exc

        state = self._current_state()
        self._validate_rqs(rq_ids, state)
        artifact_index = self._validate_source_runs(source_run_ids, source_artifact_refs)
        visual_target = self._normalize_visual_target(
            input_value.get("visual_target"),
            source_run_ids=source_run_ids,
            source_artifact_refs=source_artifact_refs,
            artifact_index=artifact_index,
        )
        self._validate_source_objects(source_object_ids, state)
        store = self._exhibit_store()
        self._validate_derived_exhibits(derived_from, store)

        latest = self._current_state()
        if _state_binding(latest) != _state_binding(state):
            raise LocalApplicationError(
                "APPLICATION-EXHIBIT-STATE-STALE-001",
                "Research State changed while validating the Research Exhibit",
            )
        state = latest

        captured_at = self._application.clock.now()
        snapshot = state.current_snapshot
        document: dict[str, Any] = {
            "schema_version": "0.1.0",
            "exhibit_id": self._application.ids.new("EXH-"),
            "project_id": self._project_id,
            "kind": str(kind),
            "title": title,
            "purpose": purpose,
            "rq_ids": rq_ids,
            "source_run_ids": source_run_ids,
            "source_artifact_refs": source_artifact_refs,
            "source_object_ids": source_object_ids,
            "derived_from_exhibit_ids": derived_from,
            "captured_against": {
                "lineage_ref": str(state.active_lineage_ref),
                "snapshot_ref": str(snapshot["id"]),
                "snapshot_digest": str(snapshot["content_digest"]),
            },
            "content": content,
            "content_digest": content_digest(content),
            "provenance": {
                "captured_at": captured_at,
                "capture_origin": str(capture_origin),
            },
        }
        if visual_target is not None:
            document["visual_target"] = visual_target
        try:
            store.capture(document)
        except LocalResearchExhibitStoreError as exc:
            raise LocalApplicationError(exc.code, exc.message) from exc
        return {
            "status": "CAPTURED",
            "project_id": self._project_id,
            "exhibit": _metadata_projection(document),
        }

    def list_exhibits(self, *, rq_id: str | None = None) -> Mapping[str, Any]:
        if rq_id is not None and (not isinstance(rq_id, str) or not rq_id.strip()):
            raise LocalApplicationError(
                "APPLICATION-EXHIBIT-INPUT-001", "rq_id must be a non-empty string"
            )
        if rq_id is not None:
            state = self._current_state()
            self._validate_rqs([rq_id], state)

        store = self._exhibit_store()
        try:
            probe = store.list_for_project(
                self._project_id,
                rq_id=rq_id,
                limit=_EXHIBIT_LIST_LIMIT + 1,
            )
        except LocalResearchExhibitStoreError as exc:
            raise LocalApplicationError(exc.code, exc.message) from exc
        truncated = len(probe) > _EXHIBIT_LIST_LIMIT
        return {
            "status": "OK",
            "project_id": self._project_id,
            "rq_id": rq_id,
            "exhibits": [
                _stored_metadata_projection(item)
                for item in probe[:_EXHIBIT_LIST_LIMIT]
            ],
            "truncated": truncated,
        }

    def show_exhibit(self, exhibit_id: str) -> Mapping[str, Any]:
        if not isinstance(exhibit_id, str) or not exhibit_id.strip():
            raise LocalApplicationError(
                "APPLICATION-EXHIBIT-INPUT-001", "exhibit_id is required"
            )
        store = self._exhibit_store()
        try:
            document = store.load(exhibit_id)
        except LocalResearchExhibitStoreError as exc:
            raise LocalApplicationError(exc.code, exc.message) from exc
        if document is None:
            raise LocalApplicationError(
                "APPLICATION-EXHIBIT-001", "unknown Research Exhibit"
            )
        if str(document["project_id"]) != self._project_id:
            raise LocalApplicationError(
                "APPLICATION-EXHIBIT-BINDING-001",
                "Research Exhibit belongs to another project",
            )
        return {
            "status": "OK",
            "project_id": self._project_id,
            "exhibit": deepcopy(dict(document)),
        }
