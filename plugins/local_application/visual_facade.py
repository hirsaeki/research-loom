from __future__ import annotations

import base64
import hashlib
import json
from typing import Mapping

from core.runtime import canonical_digest
from .facade import LocalApplicationError
from .research_quality_facade import LocalApplicationFacade as _BaseLocalApplicationFacade
from .research_chart import validate_chart_exhibit, validate_chart_spec
from .research_chart_png import RENDERER_ID, render_chart
from .generated_explanation import EXPLANATION_SCHEMA, REVIEW_SCHEMA, matching_review, validate_explanation, validate_request
from plugins.research_visual_semantics import digest
from .exhibit_facade import _string_list
from .visual_origin import verify_visual_origin


class LocalApplicationFacade(_BaseLocalApplicationFacade):
    """Research-backed chart capture, using the existing Exhibit registry."""

    def _visual_semantics(self, value, document, state, store):
        semantics = super()._visual_semantics(value, document, state, store)
        candidate = {**document, **({"visual_semantics": semantics} if semantics is not None else {})}
        try:
            png = validate_chart_exhibit(candidate, list(state.effective_objects()))
            if png is None:
                png = validate_explanation(candidate)
            if png is not None:
                binding = candidate["content"]["value"]["package_binding"]
                origin = self.show_research_package(binding["package_id"])["package"]
                verify_visual_origin(candidate, origin)
        except (TypeError, ValueError, OverflowError) as exc:
            raise LocalApplicationError("APPLICATION-VISUAL-VALIDATION-001", str(exc)) from exc
        return semantics

    def capture_exhibit(self, value):
        content = value.get("content", {}).get("value") if isinstance(value, Mapping) and isinstance(value.get("content"), Mapping) else None
        if isinstance(content, Mapping) and content.get("schema") == REVIEW_SCHEMA:
            raise LocalApplicationError("APPLICATION-VISUAL-REVIEW-001", "use the explicit visual review operation; generation/capture cannot self-approve")
        return super().capture_exhibit(value)

    def capture_explanation_exhibit(self, value):
        fields = {"package_id", "object_ids", "exhibit_ids", "request", "generator", "output_base64", "semantic_changes"}
        if not isinstance(value, Mapping) or set(value) != fields:
            raise LocalApplicationError("APPLICATION-EXPLANATION-INPUT-001", "explanation request shape is invalid")
        package = self.show_research_package(value["package_id"])["package"]
        objects = _string_list(value["object_ids"], "object_ids")
        exhibits = _string_list(value["exhibit_ids"], "exhibit_ids")
        selected_objects = {o["id"]: o for o in package["resolved_content"]["research_objects"]}
        selected_exhibits = {e["exhibit_id"]: e for e in package["resolved_content"]["working_material"]["research_exhibits"]}
        current = {o["id"]: o for o in self._current_state().effective_objects()}
        refs = []
        for oid in objects:
            if oid not in selected_objects or oid not in current or canonical_digest(selected_objects[oid]) != canonical_digest(current[oid]):
                raise LocalApplicationError("APPLICATION-EXPLANATION-BINDING-001", "explanation object is not exact current selected research: " + oid)
            refs.append({"kind": "research_object", "id": oid, "digest": canonical_digest(current[oid])})
        for eid in exhibits:
            if eid not in selected_exhibits:
                raise LocalApplicationError("APPLICATION-EXPLANATION-BINDING-001", "explanation Exhibit is not selected: " + eid)
            refs.append({"kind": "exhibit", "id": eid, "digest": selected_exhibits[eid]["content_digest"]})
        try:
            validate_request(value["request"])
            generator = dict(value["generator"])
            if set(generator) != {"identity", "version", "instruction"}:
                raise ValueError("generator must retain identity, version and instruction")
            normalized_generator = {**generator, "instruction_digest": digest(generator["instruction"])}
            if not isinstance(value["output_base64"], str) or len(value["output_base64"]) > 1048576:
                raise ValueError("output_base64 must be bounded PNG bytes")
            png = base64.b64decode(value["output_base64"], validate=True)
            content = {
                "schema": EXPLANATION_SCHEMA, "request": dict(value["request"]),
                "generation_input_digest": digest({"request": value["request"], "semantic_refs": refs, "generator": normalized_generator}),
                "package_binding": {"package_id": package["package_id"], "package_digest": package["package_digest"]},
                "output": {"media_type": "image/png", "bytes_base64": value["output_base64"], "digest": "sha256:" + hashlib.sha256(png).hexdigest()},
            }
            return self.capture_exhibit({
                "kind": "graph", "title": value["request"]["purpose"], "purpose": value["request"]["purpose"],
                "rq_ids": list(package["content"]["research_question_refs"]),
                "source_object_ids": objects, "derived_from_exhibit_ids": exhibits,
                "content": {"representation": "json", "value": content}, "capture_origin": "host_generated_explanation",
                "visual_semantics": {"visual_class": "explanatory_visual", "semantic_changes": value["semantic_changes"], "generator": generator},
            })
        except (TypeError, ValueError) as exc:
            raise LocalApplicationError("APPLICATION-EXPLANATION-VALIDATION-001", str(exc)) from exc

    def capture_visual_review(self, value):
        if not isinstance(value, Mapping) or set(value) != {"candidate_id", "disposition", "semantic_changes", "reviewer", "rationale"}:
            raise LocalApplicationError("APPLICATION-VISUAL-REVIEW-001", "visual review packet shape is invalid")
        candidate = self.show_exhibit(value["candidate_id"])["exhibit"]
        try:
            if validate_explanation(candidate) is None:
                raise ValueError("visual review requires an exact explanatory candidate")
            content = {
                "schema": REVIEW_SCHEMA, "candidate_id": candidate["exhibit_id"],
                "candidate_content_digest": candidate["content_digest"],
                "candidate_semantics_digest": digest(candidate["visual_semantics"]),
                "disposition": value["disposition"], "semantic_changes": value["semantic_changes"],
                "reviewer": value["reviewer"], "rationale": value["rationale"],
                "reviewed_at": self._application.clock.now(),
            }
            matching_review(candidate, [{"derived_from_exhibit_ids": [candidate["exhibit_id"]], "content": {"value": content}}])
            return super().capture_exhibit({
                "kind": "note", "title": "Visual semantic review", "purpose": value["rationale"],
                "rq_ids": list(candidate["rq_ids"]), "derived_from_exhibit_ids": [candidate["exhibit_id"]],
                "content": {"representation": "json", "value": content}, "capture_origin": "explicit_host_human_visual_review",
            })
        except (TypeError, ValueError) as exc:
            raise LocalApplicationError("APPLICATION-VISUAL-REVIEW-001", str(exc)) from exc

    def capture_chart_exhibit(self, value: Mapping) -> Mapping:
        if not isinstance(value, Mapping) or set(value) - {"package_id", "chart_spec", "generator_identity", "generator_version"}:
            raise LocalApplicationError("APPLICATION-CHART-INPUT-001", "chart request shape is invalid")
        package = self.show_research_package(value.get("package_id"))["package"]
        spec = value.get("chart_spec")
        if not isinstance(spec, Mapping):
            raise LocalApplicationError("APPLICATION-CHART-INPUT-001", "chart_spec is required")
        objects = package["resolved_content"]["research_objects"]
        evidence = next((o for o in objects if o.get("id") == spec.get("input_evidence_id")), None)
        current = next((o for o in self._current_state().effective_objects() if o.get("id") == spec.get("input_evidence_id")), None)
        if evidence is None or current is None or canonical_digest(current) != canonical_digest(evidence):
            raise LocalApplicationError("APPLICATION-CHART-BINDING-001", "chart requires exact current Evidence selected in the Research Package")
        try:
            validated = validate_chart_spec(spec, evidence)
            png = render_chart(validated)
        except (TypeError, ValueError, OverflowError) as exc:
            raise LocalApplicationError("APPLICATION-CHART-VALIDATION-001", str(exc)) from exc
        legend_rows = [[str(i), str(x), str(y)] for i, (x, y) in enumerate(validated["points"], start=1)]
        content = {
            "schema": "research-generated-chart/v1", "chart_spec": dict(spec),
            "package_binding": {"package_id": package["package_id"], "package_digest": package["package_digest"]},
            "renderer": RENDERER_ID,
            "output": {"media_type": "image/png", "bytes_base64": base64.b64encode(png).decode("ascii"), "digest": "sha256:" + hashlib.sha256(png).hexdigest()},
            "legend": {"columns": ["ordinal", spec["x_column"], spec["y_column"]], "rows": legend_rows},
        }
        result = self.capture_exhibit({
            "kind": "graph", "title": spec["title"], "purpose": spec["caption"],
            "rq_ids": list(package["content"]["research_question_refs"]),
            "source_object_ids": [str(evidence["id"])],
            "content": {"representation": "json", "value": content},
            "capture_origin": "validated_chart_renderer",
            "visual_semantics": {
                "visual_class": "data_visualization", "semantic_changes": [],
                "generator": {"identity": value.get("generator_identity", "operator"), "version": value.get("generator_version", "not exposed"), "instruction": json.dumps(spec, ensure_ascii=False, sort_keys=True, separators=(",", ":"))},
            },
        })
        return {**result, "data_validation": "passed", "renderer": RENDERER_ID, "research_state_mutation_performed": False}
