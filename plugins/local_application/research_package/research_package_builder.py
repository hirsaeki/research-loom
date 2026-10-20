from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

import rfc8785

from core.execution import RunStatus
from core.runtime import canonical_digest as core_canonical_digest
from plugins._infra.clock import utc_now
from plugins.application_errors import LocalApplicationError
from plugins.desktop_research.normalization import source_id_for_capture

from ..workspace.workspace import workspace_document_path
from .generated_explanation import validate_explanation
from .research_chart import validate_chart_exhibit
from .research_package_contents import (
    _collect_exhibit_modes,
    _package_visual_target,
    _research_inventories,
    _validate_selected_reference_closure,
    append_package_attachment,
)
from .research_package_format import (
    ALLOWED,
    MAX_ITEM_BYTES,
    MAX_TEXT_BYTES,
    NARRATIVE,
    SCHEMA_VERSION,
    TOOL_VERSION,
    brief,
    digest_bytes,
    digest_json,
    narrative_refs,
    profile_pins,
    profile_resources,
    project_must_not_claim,
    require_resolved_narrative,
    safe_component,
    str_list,
    validate_schema,
)
from .visual_origin import verify_visual_origin
from .visual_package_bindings import validate_visual_package_bindings


def build_package(service, value: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) - ALLOWED:
        raise LocalApplicationError(
            "APPLICATION-RESEARCH-PACKAGE-INPUT-001", "build input contains unknown fields"
        )
    sid, rqid = value.get("snapshot_id"), value.get("rq_id")
    if not isinstance(sid, str) or not sid or not isinstance(rqid, str) or not rqid:
        raise LocalApplicationError(
            "APPLICATION-RESEARCH-PACKAGE-INPUT-001", "snapshot_id and rq_id are required"
        )
    state = service._state()
    snapshot = service._snapshot(sid, state)
    for field, actual in (
        ("snapshot_digest", snapshot.get("content_digest")),
        ("lineage_ref", state.active_lineage_ref),
        ("project_config_digest", state.project_config_digest),
        ("effective_profile_set_digest", state.effective_profile_set_digest),
    ):
        if value.get(field) is not None and value.get(field) != actual:
            raise LocalApplicationError(
                "APPLICATION-RESEARCH-PACKAGE-BINDING-001",
                f"explicit {field} contradicts persisted binding",
            )
    requested_object_ids = str_list(value.get("object_ids"), "object_ids")
    objects = service._objects(snapshot, {rqid, *requested_object_ids})
    rq = objects.get(rqid)
    if rq is None or rq.get("kind") != "research_question":
        raise LocalApplicationError(
            "APPLICATION-RESEARCH-PACKAGE-INPUT-001",
            "selected RQ does not exist in selected Snapshot",
        )
    selected = [deepcopy(dict(rq))]
    for oid in requested_object_ids:
        if oid == rqid:
            continue
        if oid not in objects:
            raise LocalApplicationError(
                "APPLICATION-RESEARCH-PACKAGE-INPUT-001", f"unknown selected object: {oid}"
            )
        selected.append(deepcopy(dict(objects[oid])))
    _validate_selected_reference_closure(selected)

    run_ids = str_list(value.get("run_ids"), "run_ids")
    runs = []
    gaps = []
    modes = set()
    for rid in run_ids:
        run = service.app.execution_store.load_run(rid)
        if run is None:
            raise LocalApplicationError(
                "APPLICATION-RESEARCH-PACKAGE-INPUT-001", f"unknown selected Run: {rid}"
            )
        if run.project_ref != service.project_id or run.lineage_ref != state.active_lineage_ref:
            raise LocalApplicationError(
                "APPLICATION-RESEARCH-PACKAGE-BINDING-001",
                f"selected Run belongs to another project/lineage: {rid}",
            )
        if run.status is not RunStatus.COMPLETED:
            raise LocalApplicationError(
                "APPLICATION-RESEARCH-PACKAGE-INPUT-001", f"selected Run is not completed: {rid}"
            )
        h = service._handoff(run)
        if h is None:
            raise LocalApplicationError(
                "APPLICATION-RESEARCH-PACKAGE-INTEGRITY-001",
                f"completed Run has no persisted Handoff: {rid}",
            )
        modes.add("virtual" if str(run.execution_mode) in {"virtual", "synthetic_test"} else "real")
        outputs = deepcopy(dict(h.get("outputs", {})))
        for gap in (
            outputs.get("evidence_gaps", [])
            if isinstance(outputs.get("evidence_gaps", []), list)
            else []
        ):
            if isinstance(gap, Mapping) and isinstance(gap.get("gap_id"), str):
                gaps.append({"source_run_id": rid, **deepcopy(dict(gap))})
        runs.append(
            {
                "run_id": rid,
                "execution_mode": str(run.execution_mode),
                "historical_binding": {
                    "lineage_ref": str(run.lineage_ref),
                    "snapshot_id": str(run.snapshot_ref),
                    "snapshot_digest": str(run.snapshot_digest),
                },
                "handoff": deepcopy(dict(h)) if isinstance(h, Mapping) else None,
                "candidate_only": True,
            }
        )
    if len(modes) > 1:
        raise LocalApplicationError(
            "APPLICATION-RESEARCH-PACKAGE-EPISTEMIC-001",
            "REAL and VIRTUAL Run material may not be mixed",
        )

    exhs = []
    inputs = []
    attachments = []
    attachment_bytes = 0
    exhibit_provenance_seen = set()
    visual_attachment_paths = {}
    for eid in str_list(value.get("exhibit_ids"), "exhibit_ids"):
        ex = service.facade.show_exhibit(eid).get("exhibit")
        if not isinstance(ex, Mapping):
            raise LocalApplicationError(
                "APPLICATION-RESEARCH-PACKAGE-INTEGRITY-001",
                f"Research Exhibit did not resolve: {eid}",
            )
        cap = ex.get("captured_against", {})
        if (
            cap.get("project_id", service.project_id) != service.project_id
            or cap.get("lineage_ref") != state.active_lineage_ref
        ):
            raise LocalApplicationError(
                "APPLICATION-RESEARCH-PACKAGE-BINDING-001",
                f"Research Exhibit belongs to another project/lineage: {eid}",
            )
        content = ex.get("content", {})
        rep = str(content.get("representation", "text"))
        raw = content.get("value")
        if rep == "json":
            data = rfc8785.dumps(raw)
            ext = "json"
            media = "application/json"
        else:
            data = str(raw).encode()
            ext = "md" if rep == "markdown" else "txt"
            media = "text/markdown" if rep == "markdown" else "text/plain"
        if len(data) > MAX_ITEM_BYTES:
            raise LocalApplicationError(
                "APPLICATION-RESEARCH-PACKAGE-BOUND-001",
                f"Research Exhibit exceeds per-item bound: {eid}",
            )
        modes.update(_collect_exhibit_modes(service, ex, state, exhibit_provenance_seen))
        path = f"attachments/exhibits/{safe_component(eid, 'exhibit_id')}.{ext}"
        attachment_bytes = append_package_attachment(
            attachments, attachment_bytes, (path, data, media, f"research_exhibit:{eid}")
        )
        packaged_exhibit, attachment_bytes = _package_visual_target(
            service, ex, attachments, visual_attachment_paths, attachment_bytes
        )
        exhs.append(packaged_exhibit)
    try:
        validate_visual_package_bindings(exhs, selected)
    except (TypeError, ValueError) as exc:
        raise LocalApplicationError("APPLICATION-RESEARCH-PACKAGE-REFERENCE-001", str(exc)) from exc
    visual_origins = {}
    for exhibit in exhs:
        png = validate_chart_exhibit(exhibit, selected)
        if png is None:
            png = validate_explanation(exhibit)
        if png is not None:
            origin_id = exhibit["content"]["value"]["package_binding"]["package_id"]
            if origin_id not in visual_origins:
                visual_origins[origin_id] = service._load(origin_id)
            origin = visual_origins[origin_id]
            try:
                verify_visual_origin(exhibit, origin)
            except (KeyError, TypeError, ValueError) as exc:
                raise LocalApplicationError(
                    "APPLICATION-RESEARCH-PACKAGE-REFERENCE-001", str(exc)
                ) from exc
            origin_bytes = rfc8785.dumps(origin)
            if len(origin_bytes) > MAX_ITEM_BYTES:
                raise LocalApplicationError(
                    "APPLICATION-RESEARCH-PACKAGE-BOUND-001",
                    "visual generation Package document exceeds attachment bound",
                )
            origin_path = f"attachments/visual-origin/{safe_component(origin['package_id'], 'package_id')}.json"
            if not any(a[0] == origin_path for a in attachments):
                attachment_bytes = append_package_attachment(
                    attachments,
                    attachment_bytes,
                    (origin_path, origin_bytes, "application/json", "visual_generation_context"),
                )
            path = f"attachments/visuals/{safe_component(exhibit['exhibit_id'], 'exhibit_id')}.png"
            attachment_bytes = append_package_attachment(
                attachments,
                attachment_bytes,
                (path, png, "image/png", f"generated_visual:{exhibit['exhibit_id']}"),
            )
            exhibit["generated_visual"] = {
                "visual_class": exhibit["visual_semantics"]["visual_class"],
                "attachment_path": path,
                "media_type": "image/png",
                "byte_length": len(png),
                "digest": digest_bytes(png),
                "generation_context": {
                    "attachment_path": origin_path,
                    "byte_length": len(origin_bytes),
                    "content_digest": digest_bytes(origin_bytes),
                },
            }
    for iid in str_list(value.get("project_input_ids"), "project_input_ids"):
        shown = service.facade.show_project_input(iid, format="text")
        item = shown.get("project_input", {})
        content = shown.get("content", {})
        if (
            item.get("project_id") != service.project_id
            or item.get("lineage_ref") != state.active_lineage_ref
        ):
            raise LocalApplicationError(
                "APPLICATION-RESEARCH-PACKAGE-BINDING-001",
                f"Project Input belongs to another project/lineage: {iid}",
            )
        data = str(content.get("value", "")).encode()
        if len(data) != int(content.get("byte_length", -1)) or digest_bytes(data) != content.get(
            "content_digest"
        ):
            raise LocalApplicationError(
                "APPLICATION-RESEARCH-PACKAGE-INTEGRITY-001",
                f"Project Input content mismatch: {iid}",
            )
        if len(data) > MAX_ITEM_BYTES:
            raise LocalApplicationError(
                "APPLICATION-RESEARCH-PACKAGE-BOUND-001",
                f"Project Input exceeds per-item bound: {iid}",
            )
        path = f"attachments/inputs/{safe_component(iid, 'input_id')}.txt"
        attachment_bytes = append_package_attachment(
            attachments,
            attachment_bytes,
            (path, data, str(content.get("media_type", "text/plain")), f"project_input:{iid}"),
        )
        packaged_content = deepcopy(dict(content))
        packaged_content["attachment_path"] = path
        inputs.append({"metadata": deepcopy(dict(item)), "content": packaged_content})

    materials = []
    rawm = value.get("materials") or []
    if not isinstance(rawm, list):
        raise LocalApplicationError(
            "APPLICATION-RESEARCH-PACKAGE-INPUT-001", "materials must be an array"
        )
    for idx, m in enumerate(rawm):
        if not isinstance(m, Mapping) or set(m) != {"run_id", "capture_id"}:
            raise LocalApplicationError(
                "APPLICATION-RESEARCH-PACKAGE-INPUT-001",
                f"materials[{idx}] must contain run_id and capture_id",
            )
        rid, cid = m.get("run_id"), m.get("capture_id")
        shown = service.facade.show_external_material(rid, cid, max_text_bytes=MAX_ITEM_BYTES)
        run = service.app.execution_store.load_run(rid)
        if (
            run is None
            or run.project_ref != service.project_id
            or run.lineage_ref != state.active_lineage_ref
        ):
            raise LocalApplicationError(
                "APPLICATION-RESEARCH-PACKAGE-BINDING-001",
                f"selected material Run belongs to another project/lineage: {rid}",
            )
        modes.add("virtual" if str(run.execution_mode) in {"virtual", "synthetic_test"} else "real")
        view = shown.get("text_rendition_view", {})
        if view.get("truncated"):
            raise LocalApplicationError(
                "APPLICATION-RESEARCH-PACKAGE-BOUND-001",
                f"material rendition exceeds per-item bound: {cid}",
            )
        data = str(view.get("content", "")).encode()
        capture = shown.get("capture", {})
        rend = (capture.get("renditions") or [{}])[0]
        if rend.get("digest") and digest_bytes(data) != rend.get("digest"):
            raise LocalApplicationError(
                "APPLICATION-RESEARCH-PACKAGE-INTEGRITY-001",
                f"material rendition digest mismatch: {cid}",
            )
        source_matches = [
            str(obj["id"])
            for obj in selected
            if obj.get("kind") == "source"
            and str(obj.get("canonical_locator", "")) == str(capture.get("source_locator", ""))
            and str(obj.get("content_digest", ""))
            == str(capture.get("original", {}).get("digest", ""))
        ]
        capture_source_id = source_id_for_capture(str(rid), str(cid))
        if capture_source_id in source_matches:
            source_matches = [capture_source_id]
        elif any(obj.get("id") == capture_source_id for obj in selected):
            raise LocalApplicationError(
                "APPLICATION-RESEARCH-PACKAGE-REFERENCE-001",
                f"selected capture Source does not match verified material: {rid}:{cid}",
            )
        if len(source_matches) > 1:
            raise LocalApplicationError(
                "APPLICATION-RESEARCH-PACKAGE-REFERENCE-001",
                f"selected material ambiguously resolves multiple Sources: {rid}:{cid}",
            )
        if (
            source_matches
            and capture_source_id not in source_matches
            and service._objects(snapshot, {capture_source_id}).get(capture_source_id) is not None
        ):
            raise LocalApplicationError(
                "APPLICATION-RESEARCH-PACKAGE-REFERENCE-001",
                f"selected material does not resolve to its capture Source: {rid}:{cid}",
            )
        path = f"attachments/materials/{safe_component(str(rid), 'run_id')}/{safe_component(str(cid), 'capture_id')}.txt"
        attachment_bytes = append_package_attachment(
            attachments,
            attachment_bytes,
            (path, data, "text/plain", f"external_material:{rid}:{cid}"),
        )
        material_row = {
            "run_id": rid,
            "historical_binding": {
                "lineage_ref": str(run.lineage_ref),
                "snapshot_id": str(run.snapshot_ref),
                "snapshot_digest": str(run.snapshot_digest),
            },
            "capture": deepcopy(dict(capture)),
            "text_rendition": {
                "encoding": "UTF-8",
                "byte_length": len(data),
                "content_digest": digest_bytes(data),
                "attachment_path": path,
            },
        }
        if source_matches:
            material_row["source_id"] = source_matches[0]
        materials.append(material_row)
    if len(modes) > 1:
        raise LocalApplicationError(
            "APPLICATION-RESEARCH-PACKAGE-EPISTEMIC-001",
            "REAL and VIRTUAL material may not be mixed",
        )
    selected_material_pairs = {
        (str(m.get("run_id")), str(m.get("capture_id"))) for m in rawm if isinstance(m, Mapping)
    }
    missing_visual_materials = []
    for exhibit in exhs:
        visual = exhibit.get("visual_target") if isinstance(exhibit, Mapping) else None
        if isinstance(visual, Mapping):
            pair = (str(visual.get("source_run_id")), str(visual.get("capture_id")))
            if pair not in selected_material_pairs:
                missing_visual_materials.append(f"{pair[0]}:{pair[1]}")
    if missing_visual_materials:
        raise LocalApplicationError(
            "APPLICATION-RESEARCH-PACKAGE-REFERENCE-001",
            "visual targets require bundled source materials: "
            + ", ".join(sorted(set(missing_visual_materials))),
        )
    missing_run_materials = []
    for row in runs:
        outputs = (
            row.get("handoff", {}).get("outputs", {})
            if isinstance(row.get("handoff"), Mapping)
            else {}
        )
        for capture in (
            outputs.get("source_captures", [])
            if isinstance(outputs.get("source_captures", []), list)
            else []
        ):
            cid = capture.get("capture_id") if isinstance(capture, Mapping) else None
            if isinstance(cid, str) and (str(row["run_id"]), cid) not in selected_material_pairs:
                missing_run_materials.append(f"{row['run_id']}:{cid}")
    if missing_run_materials:
        raise LocalApplicationError(
            "APPLICATION-RESEARCH-PACKAGE-REFERENCE-001",
            "selected Run candidate has unresolved source captures: "
            + ", ".join(sorted(missing_run_materials)),
        )
    selected_source_ids = {str(obj["id"]) for obj in selected if obj.get("kind") == "source"}
    material_source_ids = {
        str(row.get("source_id")) for row in materials if isinstance(row.get("source_id"), str)
    }
    missing_source_materials = sorted(selected_source_ids - material_source_ids)
    if missing_source_materials:
        raise LocalApplicationError(
            "APPLICATION-RESEARCH-PACKAGE-REFERENCE-001",
            "selected Sources have no bundled verified material: "
            + ", ".join(missing_source_materials),
        )
    requested = str_list(value.get("gap_ids"), "gap_ids")
    if requested:
        by = {str(x["gap_id"]): x for x in gaps}
        missing = [x for x in requested if x not in by]
        if missing:
            raise LocalApplicationError(
                "APPLICATION-RESEARCH-PACKAGE-INPUT-001",
                "selected gap IDs do not resolve: " + ", ".join(missing),
            )
        gaps = [by[x] for x in requested]

    config = deepcopy(dict(state.project_config))
    binding_path = service.workspace / ".research-loom" / "workspace-binding.json"
    eps_path = (
        workspace_document_path(service.workspace, "effective_profile_set")
        if binding_path.is_file()
        else service.workspace / "effective-profile-set.json"
    )
    try:
        eps = json.loads(eps_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise LocalApplicationError(
            "APPLICATION-RESEARCH-PACKAGE-INTEGRITY-001",
            "persisted Effective Profile Set is unreadable",
        ) from exc
    if core_canonical_digest(eps) != str(state.effective_profile_set_digest):
        raise LocalApplicationError(
            "APPLICATION-RESEARCH-PACKAGE-INTEGRITY-001",
            "persisted Effective Profile Set no longer matches fixed Research State digest",
        )
    constraints = [deepcopy(dict(x)) for x in eps.get("effective_constraints", [])]
    require_resolved_narrative(constraints)
    sem = NARRATIVE.read_bytes()
    attachment_bytes = append_package_attachment(
        attachments,
        attachment_bytes,
        (
            "attachments/profile/narrative-semantics.yaml",
            sem,
            "application/yaml",
            "canonical_narrative_semantics",
        ),
    )
    source_mode = next(
        iter(modes), "virtual" if str(snapshot.get("mode", "real")) == "virtual" else "real"
    )
    virt = source_mode == "virtual"
    source_refs = [
        {
            "source_id": str(o["id"]),
            "citation_capable": bool(o.get("canonical_locator")),
            "citation_namespace": "supplied_source",
            "locator_refs": [],
            "metadata_origin": "supplied",
        }
        for o in selected
        if o.get("kind") == "source"
    ]
    package = {
        "schema_version": SCHEMA_VERSION,
        "object_type": "research_package",
        "package_id": "RP-" + uuid.uuid4().hex,
        "package_mode": "preview" if virt else "real",
        "source_epistemic_status": "SYNTHETIC_TEST_ONLY" if virt else "EMPIRICAL_RESEARCH_STATE",
        "preview_only": True,
        "authoritative_research_freeze": False,
        "release_eligible": False,
        "project": {
            "project_id": service.project_id,
            "title": str(config.get("project", {}).get("title") or service.project_id),
        },
        "project_config_digest": str(state.project_config_digest),
        "effective_profile_set": {
            "effective_profile_set_ref": str(state.effective_profile_set_ref),
            "content_digest": str(state.effective_profile_set_digest),
            "profile_pins": profile_pins(eps),
            **(
                {"effective_resources": profile_resources(eps)}
                if eps.get("effective_resources")
                else {}
            ),
        },
        "source_research_snapshot": {
            "snapshot_id": str(snapshot["id"]),
            "revision": int(snapshot.get("revision", 0)),
            "content_digest": str(snapshot["content_digest"]),
            "execution_mode": "virtual"
            if str(snapshot.get("mode", "real")) == "virtual"
            else "real",
            "lineage_ref": str(state.active_lineage_ref),
        },
        "communication_brief": brief(config, None),
        "content": {
            "research_question_refs": [rqid],
            "finding_refs": [str(o["id"]) for o in selected if o.get("kind") == "finding"],
            "argument_refs": [str(o["id"]) for o in selected if o.get("kind") == "argument"],
            "contribution_refs": [
                str(o["id"]) for o in selected if o.get("kind") == "contribution"
            ],
            "evidence_refs": [str(o["id"]) for o in selected if o.get("kind") == "evidence"],
            "source_refs": source_refs,
            "counter_review_refs": [
                str(o["id"]) for o in selected if o.get("kind") == "counter_review"
            ],
            "qualifier_refs": [],
            "limitations": [],
            "unresolved_evidence_gap_refs": [str(g["gap_id"]) for g in gaps],
            "research_attention_refs": [],
        },
        "narrative_constraints": narrative_refs(constraints),
        "project_constraints": {"must_not_claim": project_must_not_claim(config)},
        "publication_requirements": {"requirement_refs": []},
        "provenance": {
            "generated_at": utc_now(),
            "generator_id": "research-loom.research-package",
            "tool_version": TOOL_VERSION,
            "input_digests": list(
                dict.fromkeys(
                    [
                        str(snapshot["content_digest"]),
                        str(state.project_config_digest),
                        str(state.effective_profile_set_digest),
                    ]
                    + [
                        str(o.get("content_digest"))
                        for o in selected
                        if isinstance(o.get("content_digest"), str)
                    ]
                    + [
                        str(r["handoff"].get("handoff_digest"))
                        for r in runs
                        if isinstance(r.get("handoff"), Mapping)
                        and isinstance(r["handoff"].get("handoff_digest"), str)
                    ]
                )
            ),
        },
        "resolved_profiles": {
            "effective_constraints": constraints,
            "narrative_semantics": {
                "contract_path": "attachments/profile/narrative-semantics.yaml",
                "content_digest": digest_bytes(sem),
                "byte_length": len(sem),
            },
        },
        "resolved_content": {
            "research_objects": selected,
            "working_material": {
                "run_candidates": runs,
                "research_exhibits": exhs,
                "project_inputs": inputs,
            },
            "materials": materials,
            "unresolved_gaps": gaps,
        },
        "inventories": _research_inventories(selected, exhs, materials),
        "attachments": [],
        "projections": {},
    }
    package["content"]["research_question_refs"] = [
        str(obj["id"]) for obj in selected if obj.get("kind") == "research_question"
    ]
    for path, data, media, source in attachments:
        package["attachments"].append(
            {
                "path": path,
                "media_type": media,
                "byte_length": len(data),
                "content_digest": digest_bytes(data),
                "source": source,
            }
        )
    if attachment_bytes > MAX_TEXT_BYTES:
        raise LocalApplicationError(
            "APPLICATION-RESEARCH-PACKAGE-BOUND-001",
            "Research Package attachments exceed the 64 MiB per-operation budget; "
            "split the selected content across multiple Packages and retry",
        )
    md = service._markdown(package).encode()
    package["projections"] = {
        "markdown": {
            "path": "research-package.md",
            "byte_length": len(md),
            "content_digest": digest_bytes(md),
        }
    }
    package["package_digest"] = digest_json(package)
    validate_schema(package)
    service._persist(package, md, attachments)
    return {
        "status": "BUILT",
        "package": service._summary(package),
        "research_state_mutation_performed": False,
    }
