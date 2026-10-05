from copy import deepcopy
import base64
import tempfile
import unittest
from unittest.mock import patch

from plugins.local_application import LocalApplicationFacade, LocalApplicationError
from plugins.local_application.generated_explanation import matching_review, validate_explanation
from plugins.research_visual_semantics import digest, validate_visual_package_bindings
from test_research_exhibits import make_app, state_signature
from test_issue256_native_publication import fixture_png
from research_package_acceptance_support import ResearchPackageAcceptanceSupport


class GeneratedExplanationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.app = make_app(temp.name); self.addCleanup(self.app.close)
        self.facade = LocalApplicationFacade(self.app, "PRJ-1")
        self.objects = list(self.facade._current_state().effective_objects())
        self.package = {"package_id": "RP-EXPLANATION-UNIT", "package_digest": "sha256:"+"1"*64, "content": {"research_question_refs": ["RQ-1"]}, "resolved_content": {"research_objects": self.objects, "working_material": {"research_exhibits": []}}}
        self.package.pop("package_digest")
        self.package["package_digest"] = digest(self.package)

    def request(self):
        return {"package_id": self.package["package_id"], "object_ids": ["RQ-1"], "exhibit_ids": [], "request": {"purpose": "Explain the question", "allowed_labels": ["existing question"], "allowed_relations": [], "must_not_add": ["new causal or quantitative claims"]}, "generator": {"identity": "host image model", "version": "not exposed", "instruction": "Draw only the selected research meaning."}, "output_base64": base64.b64encode(fixture_png(2,2)).decode(), "semantic_changes": []}

    def capture(self, request=None):
        with patch.object(self.facade, "show_research_package", return_value={"package": self.package}):
            captured = self.facade.capture_explanation_exhibit(request or self.request())
        return self.facade.show_exhibit(captured["exhibit"]["exhibit_id"])["exhibit"]

    def review(self, candidate, disposition="existing_meaning_only", changes=None):
        result = self.facade.capture_visual_review({"candidate_id": candidate["exhibit_id"], "disposition": disposition, "semantic_changes": changes or [], "reviewer": {"actor_id": "UNIT-HOST-REVIEWER", "actor_type": "host"}, "rationale": "Synthetic unit review attestation; not live visual QA."})
        return self.facade.show_exhibit(result["exhibit"]["exhibit_id"])["exhibit"]

    def test_generation_is_pending_exact_and_research_state_is_unchanged(self):
        before = state_signature(self.app)
        candidate = self.capture()
        self.assertEqual(validate_explanation(candidate), fixture_png(2,2))
        self.assertEqual(candidate["visual_semantics"]["semantic_status"], "review_required")
        self.assertIsNone(matching_review(candidate, []))
        self.assertEqual(before, state_signature(self.app))
        review = self.review(candidate)
        self.assertEqual(matching_review(candidate, [review]), "existing_meaning_only")
        self.assertEqual(self.facade.show_exhibit(candidate["exhibit_id"])["exhibit"], candidate)
        self.assertEqual(before, state_signature(self.app))
        validate_visual_package_bindings([candidate, review], self.objects)

    def test_prompt_generator_and_output_ablation_create_new_candidates(self):
        baseline = self.capture()
        for change in ("prompt", "generator", "bytes"):
            request = self.request()
            if change == "prompt": request["generator"]["instruction"] += " (alternative)"
            elif change == "generator": request["generator"]["identity"] = "another host generator"
            else: request["output_base64"] = base64.b64encode(fixture_png(3,2)).decode()
            candidate = self.capture(request)
            self.assertNotEqual(candidate["exhibit_id"], baseline["exhibit_id"])
            self.assertNotEqual(candidate["content_digest"], baseline["content_digest"])
        self.assertEqual(self.facade.show_exhibit(baseline["exhibit_id"])["exhibit"], baseline)

    def test_orphan_refs_invalid_bytes_and_generation_self_review_are_rejected(self):
        for mutate in (
            lambda r: r.update(object_ids=[]),
            lambda r: r.update(object_ids=["unknown"]),
            lambda r: r.update(output_base64=base64.b64encode(b"not png").decode()),
        ):
            request = self.request(); mutate(request)
            with self.assertRaises(LocalApplicationError): self.capture(request)
        candidate = self.capture(); review = self.review(candidate)
        with self.assertRaises(ValueError): validate_visual_package_bindings([review], self.objects)
        with self.assertRaises(LocalApplicationError):
            self.facade.capture_exhibit({"kind": "note", "title": "self review", "purpose": "claim approval", "rq_ids": ["RQ-1"], "content": {"representation": "json", "value": review["content"]["value"]}})

    def test_new_meaning_and_conflicting_review_require_research(self):
        request = self.request(); request["semantic_changes"] = ["causality"]
        candidate = self.capture(request)
        self.assertEqual(candidate["visual_semantics"]["semantic_status"], "research_required")
        with self.assertRaises(LocalApplicationError): self.review(candidate)
        review = self.review(candidate, "research_required", ["causality"])
        self.assertEqual(matching_review(candidate, [review]), "research_required")
        ordinary = self.capture()
        accepted = self.review(ordinary)
        rejected = self.review(ordinary, "research_required", ["classification"])
        self.assertEqual(matching_review(ordinary, [accepted,rejected]), "research_required")


class GeneratedExplanationPackageTests(ResearchPackageAcceptanceSupport):
    def test_actual_package_retains_candidate_review_and_exact_generation_context(self):
        facade, case = self._build()
        try:
            original = facade.show_research_package(case["package_id"])["package"]
            captured = facade.capture_explanation_exhibit({
                "package_id": case["package_id"], "object_ids": [case["rq_id"]], "exhibit_ids": [],
                "request": {"purpose": "Question overview", "allowed_labels": ["existing question"], "allowed_relations": [], "must_not_add": ["new facts"]},
                "generator": {"identity": "unit generator", "version": "1", "instruction": "Represent the existing question only."},
                "output_base64": base64.b64encode(fixture_png(2,2)).decode(), "semantic_changes": [],
            })
            eid = captured["exhibit"]["exhibit_id"]
            reviewed = facade.capture_visual_review({"candidate_id": eid, "disposition": "existing_meaning_only", "semantic_changes": [], "reviewer": {"actor_type": "host", "actor_id": "UNIT-REVIEWER"}, "rationale": "Synthetic review fixture, not live visual QA."})
            case["build_input"]["exhibit_ids"] += [eid, reviewed["exhibit"]["exhibit_id"]]
            newer = facade.build_research_package(case["build_input"])
            self.assertNotEqual(newer["package"]["package_id"], original["package_id"])
            export = self.root / "generated-explanation-package"
            facade.export_research_package(newer["package"]["package_id"], export)
            from plugins.local_application.research_package_format import verify_export_root
            self.assertEqual(verify_export_root(export)["status"], "VERIFIED")
            self.assertEqual(facade.show_research_package(original["package_id"])["package"], original)
            import json
            package = json.loads((export / "research-package.json").read_text())
            exhibit = next(e for e in package["resolved_content"]["working_material"]["research_exhibits"] if e["exhibit_id"] == eid)
            context = exhibit["generated_visual"]["generation_context"]
            retained = json.loads((export / context["attachment_path"]).read_text())
            self.assertEqual(retained, original)
            self.assertEqual((export / exhibit["generated_visual"]["attachment_path"]).read_bytes(), fixture_png(2,2))
            # Missing provenance is never a tolerated missing-image diagnostic.
            (export / context["attachment_path"]).unlink()
            with self.assertRaises(LocalApplicationError): verify_export_root(export, _visual_diagnostics=[])
        finally:
            facade.close()


if __name__ == "__main__": unittest.main()
