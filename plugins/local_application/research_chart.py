"""Small quantitative chart contract; values come only from verified Evidence."""
from __future__ import annotations

from copy import deepcopy
import base64
import hashlib
import json
import math
from typing import Any, Mapping

from core.runtime import canonical_digest

MAX_POINTS = 128
CHART_TYPES = frozenset({"bar", "line", "scatter"})
HOST_CHART_SCHEMA = "research-generated-chart/v2"


def is_host_chart(exhibit: Mapping) -> bool:
    value = exhibit.get("content", {}).get("value")
    return isinstance(value, Mapping) and value.get("schema") == HOST_CHART_SCHEMA


def quantitative_input(evidence: Mapping[str, Any]) -> dict:
    if evidence.get("kind") != "evidence" or evidence.get("verification_status") != "verified":
        raise ValueError("chart input must be an existing verified Evidence")
    excerpt = evidence.get("excerpt")
    if not isinstance(excerpt, str):
        raise ValueError("verified Evidence needs an exact structured quantitative excerpt")
    try:
        value = json.loads(excerpt)
    except (ValueError, TypeError) as exc:
        raise ValueError("quantitative excerpt must be explicit JSON; no inferred extraction") from exc
    if not isinstance(value, dict) or set(value) != {"columns", "rows", "units", "denominator", "period"}:
        raise ValueError("quantitative excerpt needs columns, rows, units, denominator and period")
    columns, rows = value["columns"], value["rows"]
    if not isinstance(columns, list) or not 2 <= len(columns) <= 8 or any(not isinstance(c, str) or not c.strip() or len(c) > 128 for c in columns) or len(columns) != len(set(columns)):
        raise ValueError("quantitative columns must be bounded unique labels")
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_POINTS:
        raise ValueError("quantitative row count exceeds the bounded chart contract")
    for row in rows:
        if not isinstance(row, list) or len(row) != len(columns):
            raise ValueError("quantitative rows must be rectangular")
        for cell in row:
            if isinstance(cell, str):
                if not cell.strip() or len(cell) > 256:
                    raise ValueError("quantitative category must be a bounded literal string")
            else:
                number(cell)
    units = value["units"]
    if not isinstance(units, dict) or set(units) != set(columns) or any(v is not None and (not isinstance(v, str) or not v.strip() or len(v) > 128) for v in units.values()):
        raise ValueError("units must explicitly bind every input column (null means not applicable)")
    for field in ("denominator", "period"):
        item = value[field]
        if item is not None and (not isinstance(item, str) or not item.strip() or len(item) > 256):
            raise ValueError(field + " must be explicit or null")
    return deepcopy(value)


def number(value: Any) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or abs(value) > 1e12 or not math.isfinite(value):
        raise ValueError("chart values must be finite bounded numbers, without parsing or aggregation")
    return value


def validate_chart_spec(spec: Any, evidence: Mapping[str, Any]) -> dict:
    fields = {"schema", "chart_type", "input_evidence_id", "input_digest", "x_column", "y_column", "row_order", "title", "caption", "units", "denominator", "period"}
    if not isinstance(spec, Mapping) or set(spec) != fields or spec.get("schema") != "research-chart/v1":
        raise ValueError("unsupported chart spec; literal values/expressions/aggregation are not accepted")
    if not isinstance(spec["chart_type"], str) or spec["chart_type"] not in CHART_TYPES:
        raise ValueError("only bar, line and scatter are supported")
    if spec["input_evidence_id"] != evidence.get("id") or spec["input_digest"] != canonical_digest(evidence):
        raise ValueError("chart input Evidence identity/digest mismatch")
    data = quantitative_input(evidence)
    for field in ("title", "caption"):
        if not isinstance(spec[field], str) or not spec[field].strip() or len(spec[field]) > 2048:
            raise ValueError("chart " + field + " must be a bounded non-empty string")
    x, y = spec["x_column"], spec["y_column"]
    if x not in data["columns"] or y not in data["columns"] or x == y:
        raise ValueError("chart mappings must select distinct existing columns")
    if any(spec[f] != data[f] for f in ("units", "denominator", "period")):
        raise ValueError("chart cannot change or drop unit, denominator or period semantics")
    order = spec["row_order"]
    if not isinstance(order, list) or any(isinstance(i, bool) or not isinstance(i, int) for i in order) or sorted(order) != list(range(len(data["rows"]))):
        raise ValueError("row_order must explicitly retain every input row once")
    xi, yi = data["columns"].index(x), data["columns"].index(y)
    points = [[data["rows"][i][xi], number(data["rows"][i][yi])] for i in order]
    if spec["chart_type"] == "bar":
        if any(not isinstance(p[0], str) for p in points) or len({p[0] for p in points}) != len(points):
            raise ValueError("bar categories must be existing unique literal labels")
    else:
        for point in points:
            number(point[0])
        if spec["chart_type"] == "line" and any(points[i][0] >= points[i+1][0] for i in range(len(points)-1)):
            raise ValueError("line row_order must explicitly preserve strictly increasing x values")
    return {"spec": deepcopy(dict(spec)), "input": data, "points": points}


def validate_chart_exhibit(exhibit: Mapping, objects: list) -> bytes | None:
    value = exhibit.get("content", {}).get("value")
    if not isinstance(value, Mapping) or value.get("schema") not in ("research-generated-chart/v1", HOST_CHART_SCHEMA):
        return None
    from .research_chart_png import RENDERER_ID, render_chart
    host = is_host_chart(exhibit)
    fields = {"schema", "chart_spec", "package_binding", "renderer", "output", "legend"}
    if set(value) != (fields | {"chart_spec_digest"} if host else fields) or (not host and value["renderer"] != RENDERER_ID):
        raise ValueError("unsupported generated chart contract/renderer")
    semantics = exhibit.get("visual_semantics")
    if not isinstance(semantics, Mapping) or semantics.get("visual_class") != "data_visualization" or semantics.get("semantic_changes") != []:
        raise ValueError("generated chart requires representation-only data semantics")
    spec = value["chart_spec"]
    if not isinstance(spec, Mapping):
        raise ValueError("chart spec is missing")
    evidence = next((o for o in objects if o.get("id") == spec.get("input_evidence_id")), None)
    if evidence is None or exhibit.get("source_object_ids") != [evidence["id"]]:
        raise ValueError("chart requires exact selected Evidence provenance")
    validated = validate_chart_spec(spec, evidence)
    if host:
        from plugins.research_visual_semantics import digest
        renderer = value["renderer"]
        if not isinstance(renderer, Mapping) or set(renderer) != {"identity", "version", "instruction", "instruction_digest"}:
            raise ValueError("host chart must retain renderer identity/version/instruction")
        if any(not isinstance(renderer[f], str) or not renderer[f].strip() for f in ("identity", "version", "instruction")) or len(renderer["identity"]) > 256 or len(renderer["version"]) > 256 or len(renderer["instruction"].encode("utf-8")) > 65536:
            raise ValueError("host chart renderer provenance is invalid")
        if renderer["identity"] == RENDERER_ID or renderer != semantics.get("generator") or renderer["instruction_digest"] != digest(renderer["instruction"]) or value["chart_spec_digest"] != canonical_digest(spec):
            raise ValueError("host chart provenance/spec digest mismatch")
    binding = value["package_binding"]
    if not isinstance(binding, Mapping) or set(binding) != {"package_id", "package_digest"} or not isinstance(binding["package_id"], str) or not binding["package_id"].strip() or not isinstance(binding["package_digest"], str) or len(binding["package_digest"]) != 71 or not binding["package_digest"].startswith("sha256:"):
        raise ValueError("chart generation Package binding is incomplete")
    output = value["output"]
    if not isinstance(output, Mapping) or set(output) != {"media_type", "bytes_base64", "digest"} or output["media_type"] != "image/png" or not isinstance(output["bytes_base64"], str) or len(output["bytes_base64"]) > 1048576:
        raise ValueError("generated chart output is invalid")
    try:
        png = base64.b64decode(output["bytes_base64"], validate=True)
    except (TypeError, ValueError) as exc:
        raise ValueError("generated chart bytes are invalid") from exc
    if output["digest"] != "sha256:" + hashlib.sha256(png).hexdigest() or (not host and png != render_chart(validated)):
        raise ValueError("generated chart digest or deterministic rendering differs from bound data/spec")
    if host:
        from .publication_exhibits import png_size
        png_size(png)
    legend = {"columns": ["ordinal", spec["x_column"], spec["y_column"]], "rows": [[str(i), str(x), str(y)] for i, (x, y) in enumerate(validated["points"], start=1)]}
    if value["legend"] != legend:
        raise ValueError("chart category/value legend must correspond exactly to bound data")
    return png
