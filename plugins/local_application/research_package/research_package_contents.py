"""Research Package reference closure, inventories and exhibit/visual selection helpers (#494)."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from plugins.application_errors import LocalApplicationError

from .research_package_format import (
    MAX_ITEM_BYTES,
    MAX_RUNS,
    MAX_TEXT_BYTES,
    digest_bytes,
    safe_component,
)


def required_object_refs(obj: Mapping[str, Any]) -> list[tuple[str, str]]:
    kind = str(obj.get("kind", ""))
    refs: list[tuple[str, str]] = []

    def add(kind_name: str, values: Any) -> None:
        if isinstance(values, str) and values:
            refs.append((kind_name, values))
        elif isinstance(values, list):
            refs.extend(
                (kind_name, str(value)) for value in values if isinstance(value, str) and value
            )

    if kind == "claim":
        add("evidence", obj.get("supporting_evidence_ids"))
        add("evidence", obj.get("challenging_evidence_ids"))
    elif kind == "evidence":
        add("source", obj.get("source_id"))
    elif kind == "analysis":
        add("evidence", obj.get("evidence_ids"))
    elif kind == "finding":
        add("evidence", obj.get("evidence_ids"))
        add("analysis", obj.get("analysis_ids"))
        add("evidence", obj.get("counter_evidence_ids"))
    elif kind == "counter_review":
        target = obj.get("target")
        if (
            isinstance(target, Mapping)
            and target.get("kind") not in {None, "research_question"}
            and isinstance(target.get("id"), str)
        ):
            refs.append((str(target["kind"]), str(target["id"])))
        add("evidence", obj.get("evidence_ids"))
    elif kind == "argument":
        add("claim", obj.get("conclusion_claim_id"))
        add("claim", obj.get("premise_claim_ids"))
        add("finding", obj.get("finding_ids"))
        add("evidence", obj.get("evidence_ids"))
        add("counter_review", obj.get("counter_review_ids"))
    elif kind in {"contribution", "recommendation"}:
        add("finding", obj.get("finding_ids"))
    return refs


def _validate_selected_reference_closure(selected: list[Mapping[str, Any]]) -> None:
    by_id = {str(obj.get("id")): obj for obj in selected if isinstance(obj.get("id"), str)}
    missing = []
    for obj in selected:
        for expected_kind, ref_id in required_object_refs(obj):
            target = by_id.get(ref_id)
            if target is None or str(target.get("kind")) != expected_kind:
                missing.append(f"{obj.get('id')}->{expected_kind}:{ref_id}")
    if missing:
        raise LocalApplicationError(
            "APPLICATION-RESEARCH-PACKAGE-REFERENCE-001",
            "selected research content has unresolved required references: "
            + ", ".join(sorted(set(missing))),
        )


def bibliography_readiness(source: Mapping[str, Any]) -> tuple[bool, list[str]]:
    def supplied(field):
        return isinstance(source.get(field), str) and bool(source[field].strip())

    exceptions = source.get("bibliography_exceptions", {})

    def accounted(field):
        return (
            supplied(field)
            or isinstance(exceptions.get(field), str)
            and bool(exceptions[field].strip())
        )

    missing = [
        field
        for field in ("title", "publication_or_update_date")
        if not (supplied(field) if field == "title" else accounted(field))
    ]
    if not supplied("publisher_or_author") and not (accounted("author") and accounted("publisher")):
        missing.insert(1 if "title" in missing else 0, "publisher_or_author")
    return (not missing, [f"bibliography_missing:{field}" for field in missing])


def _research_inventories(
    selected: list[Mapping[str, Any]],
    exhibits: list[Mapping[str, Any]],
    materials: list[Mapping[str, Any]],
) -> Mapping[str, Any]:
    objects = {str(obj.get("id")): obj for obj in selected if isinstance(obj.get("id"), str)}
    citation_inventory = []
    for evidence in selected:
        if evidence.get("kind") != "evidence":
            continue
        source_id = str(evidence.get("source_id", ""))
        source = objects.get(source_id)
        unresolved = []
        locator = (
            evidence.get("locator")
            if isinstance(evidence.get("locator"), str) and evidence.get("locator")
            else None
        )
        if locator is None:
            unresolved.append("locator_missing")
        bibliography_ready = False
        if source is None or source.get("kind") != "source":
            unresolved.append("source_unresolved")
        else:
            bibliography_ready, missing = bibliography_readiness(source)
            unresolved.extend(missing)
        verification_status = str(evidence.get("verification_status") or "unspecified")
        if verification_status != "verified":
            unresolved.append("evidence_unverified")
        citation_inventory.append(
            {
                "evidence_id": str(evidence["id"]),
                "source_id": source_id,
                "locator": locator,
                "bibliography_ready": bibliography_ready,
                "evidence_role": str(evidence.get("evidence_kind") or "unspecified"),
                "verification_status": verification_status,
                "citation_ready": not unresolved,
                "unresolved_reasons": unresolved,
            }
        )
    source_exhibit_inventory = []
    for exhibit in exhibits:
        visual = exhibit.get("visual_target")
        semantics = exhibit.get("visual_semantics")
        if not isinstance(visual, Mapping) or visual.get("target_type") != "source_visual":
            continue
        source_ids = [
            str(ref)
            for ref in exhibit.get("source_object_ids", [])
            if isinstance(ref, str) and objects.get(ref, {}).get("kind") == "source"
        ]
        if not source_ids:
            capture_locators = set()
            for material in materials:
                capture = material.get("capture") if isinstance(material, Mapping) else None
                if (
                    isinstance(capture, Mapping)
                    and material.get("run_id") == visual.get("source_run_id")
                    and capture.get("capture_id") == visual.get("capture_id")
                ):
                    for key in ("source_locator", "exact_locator"):
                        if isinstance(capture.get(key), str):
                            capture_locators.add(str(capture[key]))
            source_ids = sorted(
                str(obj["id"])
                for obj in selected
                if obj.get("kind") == "source"
                and obj.get("content_digest") == visual.get("source_digest")
                and (not capture_locators or obj.get("canonical_locator") in capture_locators)
            )
        unresolved = []
        if not source_ids:
            unresolved.append("source_unresolved")
        # Rights are deliberately not inferred in Research. Publication policy resolves them.
        rights_status = "unresolved"
        unresolved.append("rights_unresolved")
        source_exhibit_inventory.append(
            {
                "exhibit_id": str(exhibit["exhibit_id"]),
                "source_ids": source_ids,
                "source_run_id": str(visual.get("source_run_id", "")),
                "capture_id": str(visual.get("capture_id", "")),
                "locator": deepcopy(dict(visual.get("locator", {}))),
                "retained_artifact_ref": str(
                    (visual.get("derived_artifact") or {}).get("artifact_ref")
                    or visual.get("source_artifact_ref", "")
                ),
                "retained_digest": str(
                    (visual.get("derived_artifact") or {}).get("digest")
                    or visual.get("source_digest", "")
                ),
                "rights_status": rights_status,
                "research_ready": bool(visual.get("source_run_id"))
                and bool(visual.get("capture_id"))
                and bool(visual.get("source_digest"))
                and bool(visual.get("source_artifact_ref"))
                and isinstance(visual.get("locator"), Mapping)
                and not (
                    isinstance(semantics, Mapping)
                    and semantics.get("semantic_status") == "research_required"
                ),
                "semantic_status": str(semantics.get("semantic_status"))
                if isinstance(semantics, Mapping)
                else "unspecified",
                "unresolved_reasons": unresolved,
            }
        )
    return {
        "citation_inventory": citation_inventory,
        "source_exhibit_inventory": source_exhibit_inventory,
    }


def _visual_extension(media_type: str) -> str:
    return {
        "application/pdf": "pdf",
        "image/png": "png",
        "image/jpeg": "jpg",
        "image/webp": "webp",
        "image/gif": "gif",
        "application/json": "json",
        "text/csv": "csv",
    }.get(media_type, "bin")


def _package_visual_target(
    service,
    exhibit: Mapping[str, Any],
    attachments: list,
    attachment_paths: dict[tuple[str, str], str],
) -> Mapping[str, Any]:
    target = exhibit.get("visual_target")
    if target is None:
        return deepcopy(dict(exhibit))
    if not isinstance(target, Mapping) or target.get("target_type") != "source_visual":
        raise LocalApplicationError(
            "APPLICATION-RESEARCH-PACKAGE-INTEGRITY-001",
            f"invalid Research Exhibit visual target: {exhibit.get('exhibit_id')}",
        )
    run_id = str(target.get("source_run_id", ""))
    artifact_ref = str(target.get("source_artifact_ref", ""))
    capture_id = str(target.get("capture_id", ""))
    if run_id not in (exhibit.get("source_run_ids") or []) or artifact_ref not in (
        exhibit.get("source_artifact_refs") or []
    ):
        raise LocalApplicationError(
            "APPLICATION-RESEARCH-PACKAGE-REFERENCE-001",
            f"visual target is not declared by Research Exhibit provenance: {exhibit.get('exhibit_id')}",
        )
    metadata = {
        str(item.artifact_id): item for item in service.app.execution_store.artifacts_for(run_id)
    }
    source = metadata.get(artifact_ref)
    if (
        source is None
        or str(source.role) != "desktop_research.original_capture"
        or str(source.provenance.get("capture_id", "")) != capture_id
        or str(source.digest) != str(target.get("source_digest"))
        or int(source.size) != int(target.get("source_byte_length", -1))
        or str(source.media_type) != str(target.get("source_media_type"))
    ):
        raise LocalApplicationError(
            "APPLICATION-RESEARCH-PACKAGE-INTEGRITY-001",
            f"visual target source binding changed: {exhibit.get('exhibit_id')}",
        )
    exhibit_id = safe_component(str(exhibit["exhibit_id"]), "exhibit_id")
    source_key = (artifact_ref, str(target["source_digest"]))
    source_path = attachment_paths.get(source_key)
    if source_path is None:
        source_size = int(target["source_byte_length"])
        if source_size > MAX_ITEM_BYTES:
            raise LocalApplicationError(
                "APPLICATION-RESEARCH-PACKAGE-BOUND-001",
                f"visual source exceeds per-item bound: {exhibit.get('exhibit_id')}",
            )
        if sum(len(item[1]) for item in attachments) + source_size > MAX_TEXT_BYTES:
            raise LocalApplicationError(
                "APPLICATION-RESEARCH-PACKAGE-BOUND-001",
                f"visual source exceeds detached package output bound: {exhibit.get('exhibit_id')}",
            )
        source_payload = service.app.execution_store.load_artifact_verified_once(artifact_ref)
        source_bytes = bytes(source_payload.content)
        if (
            len(source_bytes) != source_size
            or digest_bytes(source_bytes) != str(target["source_digest"])
            or str(source_payload.media_type) != str(target["source_media_type"])
        ):
            raise LocalApplicationError(
                "APPLICATION-RESEARCH-PACKAGE-INTEGRITY-001",
                f"visual target source bytes changed: {exhibit.get('exhibit_id')}",
            )
        source_path = (
            f"attachments/visual/{exhibit_id}/source."
            f"{_visual_extension(str(target['source_media_type']))}"
        )
        attachments.append(
            (
                source_path,
                source_bytes,
                str(target["source_media_type"]),
                f"visual_source:{artifact_ref}",
            )
        )
        attachment_paths[source_key] = source_path
    packaged = deepcopy(dict(exhibit))
    packaged_target = deepcopy(dict(target))
    packaged_target["source_attachment_path"] = source_path

    derived = target.get("derived_artifact")
    if derived is not None:
        if not isinstance(derived, Mapping):
            raise LocalApplicationError(
                "APPLICATION-RESEARCH-PACKAGE-INTEGRITY-001",
                f"invalid derived visual artifact: {exhibit.get('exhibit_id')}",
            )
        derived_ref = str(derived.get("artifact_ref", ""))
        derived_meta = metadata.get(derived_ref)
        if (
            derived_meta is None
            or artifact_ref not in tuple(derived_meta.provenance.get("parent_artifact_refs", ()))
            or str(derived_meta.provenance.get("derivation_type", ""))
            != str(derived.get("derivation_type"))
            or str(derived.get("derived_from_artifact_ref")) != artifact_ref
            or str(derived_meta.digest) != str(derived.get("digest"))
            or int(derived_meta.size) != int(derived.get("byte_length", -1))
            or str(derived_meta.media_type) != str(derived.get("media_type"))
        ):
            raise LocalApplicationError(
                "APPLICATION-RESEARCH-PACKAGE-INTEGRITY-001",
                f"derived visual artifact binding changed: {exhibit.get('exhibit_id')}",
            )
        derived_key = (derived_ref, str(derived["digest"]))
        derived_path = attachment_paths.get(derived_key)
        if derived_path is None:
            derived_size = int(derived["byte_length"])
            if derived_size > MAX_ITEM_BYTES:
                raise LocalApplicationError(
                    "APPLICATION-RESEARCH-PACKAGE-BOUND-001",
                    f"derived visual artifact exceeds per-item bound: {exhibit.get('exhibit_id')}",
                )
            if sum(len(item[1]) for item in attachments) + derived_size > MAX_TEXT_BYTES:
                raise LocalApplicationError(
                    "APPLICATION-RESEARCH-PACKAGE-BOUND-001",
                    f"derived visual artifact exceeds detached package output bound: {exhibit.get('exhibit_id')}",
                )
            derived_payload = service.app.execution_store.load_artifact_verified_once(derived_ref)
            derived_bytes = bytes(derived_payload.content)
            if (
                len(derived_bytes) != derived_size
                or digest_bytes(derived_bytes) != str(derived["digest"])
                or str(derived_payload.media_type) != str(derived["media_type"])
            ):
                raise LocalApplicationError(
                    "APPLICATION-RESEARCH-PACKAGE-INTEGRITY-001",
                    f"derived visual artifact bytes changed: {exhibit.get('exhibit_id')}",
                )
            derived_path = (
                f"attachments/visual/{exhibit_id}/derived."
                f"{_visual_extension(str(derived['media_type']))}"
            )
            attachments.append(
                (
                    derived_path,
                    derived_bytes,
                    str(derived["media_type"]),
                    f"visual_derived:{derived_ref}",
                )
            )
            attachment_paths[derived_key] = derived_path
        packaged_target["derived_artifact"] = deepcopy(dict(derived))
        packaged_target["derived_artifact"]["attachment_path"] = derived_path
    packaged["visual_target"] = packaged_target
    return packaged


def _collect_exhibit_modes(
    service, exhibit: Mapping[str, Any], state, visited: set[str]
) -> set[str]:
    modes: set[str] = set()
    stack = [exhibit]
    while stack:
        current = stack.pop()
        exhibit_id = str(current.get("exhibit_id", ""))
        if exhibit_id in visited:
            continue
        visited.add(exhibit_id)
        captured = current.get("captured_against", {})
        if (
            str(current.get("project_id", service.project_id)) != service.project_id
            or captured.get("lineage_ref") != state.active_lineage_ref
        ):
            raise LocalApplicationError(
                "APPLICATION-RESEARCH-PACKAGE-BINDING-001",
                f"Research Exhibit provenance belongs to another project/lineage: {exhibit_id}",
            )
        source_run_ids = current.get("source_run_ids", []) or []
        if not isinstance(source_run_ids, list) or len(source_run_ids) > MAX_RUNS:
            raise LocalApplicationError(
                "APPLICATION-RESEARCH-PACKAGE-BOUND-001",
                "Research Exhibit source Run provenance exceeds supported bound",
            )
        for source_run_id in source_run_ids:
            run = service.app.execution_store.load_run(str(source_run_id))
            if (
                run is None
                or run.project_ref != service.project_id
                or run.lineage_ref != state.active_lineage_ref
            ):
                raise LocalApplicationError(
                    "APPLICATION-RESEARCH-PACKAGE-BINDING-001",
                    f"Research Exhibit source Run belongs to another project/lineage: {source_run_id}",
                )
            modes.add(
                "virtual" if str(run.execution_mode) in {"virtual", "synthetic_test"} else "real"
            )
        for parent_id in current.get("derived_from_exhibit_ids", []) or []:
            parent = service.facade.show_exhibit(str(parent_id)).get("exhibit")
            if not isinstance(parent, Mapping):
                raise LocalApplicationError(
                    "APPLICATION-RESEARCH-PACKAGE-INTEGRITY-001",
                    f"derived-from Research Exhibit did not resolve: {parent_id}",
                )
            stack.append(parent)
    return modes
