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
from .visual_origin import verify_visual_origin


class LocalApplicationFacade(_BaseLocalApplicationFacade):
    """Research-backed chart capture, using the existing Exhibit registry."""

    def _visual_semantics(self, value, document, state, store):
        semantics = super()._visual_semantics(value, document, state, store)
        candidate = {**document, **({"visual_semantics": semantics} if semantics is not None else {})}
        try:
            png = validate_chart_exhibit(candidate, list(state.effective_objects()))
            if png is not None:
                binding = candidate["content"]["value"]["package_binding"]
                origin = self.show_research_package(binding["package_id"])["package"]
                verify_visual_origin(candidate, origin)
        except (TypeError, ValueError, OverflowError) as exc:
            raise LocalApplicationError("APPLICATION-CHART-VALIDATION-001", str(exc)) from exc
        return semantics

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
