from copy import deepcopy
import base64
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.runtime import canonical_digest
from plugins.local_application import LocalApplicationFacade, LocalApplicationError, LocalResearchApplication
from plugins.local_application.research_chart import quantitative_input, validate_chart_spec, validate_chart_exhibit
from plugins.local_application.research_chart_png import render_chart
from plugins.local_application.publication_exhibits import png_size
from plugins.research_visual_semantics import validate_visual_package_bindings
from runtime_fixtures import project, rq, source, evidence, seed_state
from test_research_exhibits import NullResolver, profile_provider, state_signature


def chart_evidence(numeric_x=False):
    obj = evidence(verification="verified", evidence_kind="supporting")
    obj["excerpt"] = json.dumps({"columns": ["category", "cases"], "rows": [[1 if numeric_x else "東京", 30], [2 if numeric_x else "大阪", 20], [3 if numeric_x else "名古屋", 50]], "units": {"category": None, "cases": "件"}, "denominator": None, "period": "2026"}, ensure_ascii=False)
    return obj


def chart_spec(obj, kind="bar"):
    data = quantitative_input(obj)
    return {"schema": "research-chart/v1", "chart_type": kind, "input_evidence_id": obj["id"], "input_digest": canonical_digest(obj), "x_column": "category", "y_column": "cases", "row_order": [0,1,2], "title": "比較", "caption": "検証済み資料の比較", "units": data["units"], "denominator": data["denominator"], "period": data["period"]}


class ChartValidationTests(unittest.TestCase):
    def test_bar_line_scatter_are_deterministic_real_pngs(self):
        for kind in ("bar", "line", "scatter"):
            obj = chart_evidence(kind != "bar")
            validated = validate_chart_spec(chart_spec(obj, kind), obj)
            png = render_chart(validated)
            self.assertEqual(png_size(png), (800,480))
            self.assertEqual(png, render_chart(validated))
            changed = chart_spec(obj, kind)
            changed["caption"] += " (別版)"
            self.assertNotEqual(canonical_digest(changed), canonical_digest(chart_spec(obj, kind)))

    def test_modified_value_digest_unit_category_and_aggregation_fail_closed(self):
        obj, spec = chart_evidence(), chart_spec(chart_evidence())
        changed = deepcopy(obj)
        data = json.loads(changed["excerpt"]); data["rows"][0][1] += 1
        changed["excerpt"] = json.dumps(data)
        with self.assertRaises(ValueError): validate_chart_spec(spec, changed)
        for mutate in (
            lambda s: s.update(values=[31,20,50]),
            lambda s: s.update(aggregation="mean"),
            lambda s: s.update(x_column="invented"),
            lambda s: s.update(row_order=[0,1,1]),
            lambda s: s.update(row_order=[0,1]),
            lambda s: s.update(period=None),
            lambda s: s.update(units={"category": None, "cases": "割合"}),
        ):
            bad = deepcopy(spec); mutate(bad)
            with self.assertRaises(ValueError): validate_chart_spec(bad, obj)
        unverified = deepcopy(obj); unverified["verification_status"] = "unverified"
        with self.assertRaises(ValueError): validate_chart_spec(chart_spec(obj), unverified)

    def test_nan_bool_nonmonotonic_line_and_unsupported_chart_fail_closed(self):
        obj = chart_evidence(True)
        spec = chart_spec(obj, "line"); spec["row_order"] = [2,1,0]
        with self.assertRaises(ValueError): validate_chart_spec(spec, obj)
        spec = chart_spec(obj, "pie")
        with self.assertRaises(ValueError): validate_chart_spec(spec, obj)
        for number in (True, float("nan"), float("inf")):
            changed = deepcopy(obj); data = json.loads(changed["excerpt"])
            data["rows"][0][1] = number; changed["excerpt"] = json.dumps(data)
            with self.assertRaises(ValueError): quantitative_input(changed)


class ChartCaptureTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.evidence = chart_evidence()
        seed = seed_state(objects=[project(), rq(state="approved"), source(), self.evidence])
        self.app = LocalResearchApplication(Path(temp.name), resolver=NullResolver(), effective_profile_set_provider=profile_provider, seed_state=seed)
        self.addCleanup(self.app.close)
        self.facade = LocalApplicationFacade(self.app, "PRJ-1")
        self.package = {"package_id": "RP-CHART-FIXTURE", "package_digest": "sha256:"+"1"*64, "content": {"research_question_refs": ["RQ-1"]}, "resolved_content": {"research_objects": [rq(state="approved"), source(), self.evidence]}}

    def capture(self, proposer="operator"):
        # Inject an already loaded package at the read boundary; this is unit
        # evidence, not a production Host/UAT or an authority gate substitute.
        with patch.object(self.facade, "show_research_package", return_value={"package": self.package}):
            result = self.facade.capture_chart_exhibit({"package_id": self.package["package_id"], "chart_spec": chart_spec(self.evidence), "generator_identity": proposer})
        return self.facade.show_exhibit(result["exhibit"]["exhibit_id"])["exhibit"]

    def test_operator_and_model_specs_have_same_validation_and_no_authority(self):
        before = state_signature(self.app)
        manual, model = self.capture(), self.capture("GPT")
        self.assertEqual(before, state_signature(self.app))
        self.assertNotEqual(manual["exhibit_id"], model["exhibit_id"])
        self.assertEqual(manual["content"]["value"]["output"], model["content"]["value"]["output"])
        self.assertEqual(model["visual_semantics"]["semantic_status"], "review_required")
        validate_visual_package_bindings([model], self.package["resolved_content"]["research_objects"])
        png = validate_chart_exhibit(model, [self.evidence])
        self.assertEqual(png_size(png), (800,480))

    def test_output_tampering_cannot_gain_validated_chart_semantics(self):
        baseline = self.capture()
        changed = deepcopy(baseline)
        output = changed["content"]["value"]["output"]
        png = base64.b64decode(output["bytes_base64"]) + b"tampered"
        output["bytes_base64"] = base64.b64encode(png).decode()
        output["digest"] = "sha256:" + hashlib.sha256(png).hexdigest()
        with self.assertRaises(ValueError): validate_chart_exhibit(changed, [self.evidence])
        with self.assertRaises(ValueError): validate_chart_exhibit(baseline, [])
        changed = deepcopy(baseline); changed["content"]["value"]["legend"]["rows"][0][1] = "別分類"
        with self.assertRaises(ValueError): validate_chart_exhibit(changed, [self.evidence])

    def test_without_renderer_source_and_spec_provenance_remain(self):
        with patch("plugins.local_application.visual_facade.render_chart", side_effect=ValueError("renderer unavailable")), patch.object(self.facade, "show_research_package", return_value={"package": self.package}):
            with self.assertRaises(LocalApplicationError):
                self.facade.capture_chart_exhibit({"package_id": self.package["package_id"], "chart_spec": chart_spec(self.evidence)})
        self.assertEqual(validate_chart_spec(chart_spec(self.evidence), self.evidence)["points"][0], ["東京",30])
        self.assertEqual(self.facade.list_exhibits()["exhibits"], [])


if __name__ == "__main__": unittest.main()
