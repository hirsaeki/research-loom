from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from plugins.local_application import LocalApplicationError, LocalApplicationFacade
from plugins.local_research_exhibit_store import LocalResearchExhibitStore, LocalResearchExhibitStoreError
from plugins.research_visual_semantics import validate_visual_package_bindings
from test_research_exhibits import make_app, exhibit_payload, state_signature
from research_package_acceptance_support import ResearchPackageAcceptanceSupport


def visual_payload(**changes):
    payload = exhibit_payload(
        kind="graph", source_object_ids=["RQ-1"], representation="json",
        value={"labels": ["existing question"], "relations": []},
        visual_semantics={
            "visual_class": "explanatory_visual", "semantic_changes": [],
            "generator": {"identity": "host", "version": "not exposed", "instruction": "Represent the existing question without adding conclusions."},
        },
    )
    payload.update(changes)
    return payload


class VisualSemanticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = make_app(Path(self.temp.name))
        self.addCleanup(self.app.close)
        self.facade = LocalApplicationFacade(self.app, "PRJ-1")

    def capture(self, payload=None):
        result = self.facade.capture_exhibit(payload or visual_payload())
        return self.facade.show_exhibit(result["exhibit"]["exhibit_id"])["exhibit"]

    def test_capture_is_exact_candidate_and_does_not_mutate_research(self):
        before = state_signature(self.app)
        first = self.capture()
        second = self.capture()
        self.assertEqual(before, state_signature(self.app))
        self.assertNotEqual(first["exhibit_id"], second["exhibit_id"])
        semantics = first["visual_semantics"]
        self.assertEqual(semantics["semantic_status"], "review_required")
        self.assertEqual(semantics["spec_digest"], first["content_digest"])
        self.assertEqual(semantics["semantic_refs"][0]["id"], "RQ-1")
        self.assertEqual(self.facade.show_exhibit(first["exhibit_id"])["exhibit"], first)

    def test_bounded_ablation_missing_refs_and_bytes_only_do_not_gain_semantics(self):
        first = self.capture()
        with self.assertRaises(LocalApplicationError):
            self.capture(visual_payload(source_object_ids=[]))
        with self.assertRaises(LocalApplicationError):
            self.capture(visual_payload(source_object_ids=["missing"]))
        legacy = visual_payload(source_object_ids=[])
        legacy.pop("visual_semantics")
        bytes_only = self.capture(legacy)
        self.assertNotIn("visual_semantics", bytes_only)
        self.assertEqual(first["content_digest"], bytes_only["content_digest"])

    def test_new_meaning_requires_research_even_when_generator_claims_conformance(self):
        payload = visual_payload()
        payload["visual_semantics"]["semantic_changes"] = ["causality"]
        payload["visual_semantics"]["generator"]["instruction"] = "No new meaning (model self-report)"
        self.assertEqual(self.capture(payload)["visual_semantics"]["semantic_status"], "research_required")
        payload["visual_semantics"]["semantic_status"] = "approved"
        with self.assertRaises(LocalApplicationError):
            self.capture(payload)

    def test_source_class_cannot_disguise_generated_content(self):
        payload = visual_payload()
        payload["visual_semantics"]["visual_class"] = "source_visual"
        with self.assertRaises(LocalApplicationError):
            self.capture(payload)

    def test_persisted_missing_refs_and_stale_spec_are_rejected(self):
        baseline = self.capture()
        store = LocalResearchExhibitStore(Path(self.temp.name) / "other.sqlite3")
        for mutate in (
            lambda e: e["visual_semantics"]["semantic_refs"].clear(),
            lambda e: e["visual_semantics"].update(spec_digest="sha256:" + "0" * 64),
            lambda e: e["visual_semantics"].update(semantic_status="approved"),
        ):
            candidate = deepcopy(baseline)
            mutate(candidate)
            with self.assertRaises(LocalResearchExhibitStoreError):
                store.capture(candidate)

    def test_package_binding_rejects_omitted_or_changed_objects(self):
        exhibit = self.capture()
        objects = list(self.facade._current_state().effective_objects())
        validate_visual_package_bindings([exhibit], objects)
        with self.assertRaises(ValueError):
            validate_visual_package_bindings([exhibit], [])
        modified = deepcopy(objects)
        next(o for o in modified if o["id"] == "RQ-1")["text"] = "Changed question"
        with self.assertRaises(ValueError):
            validate_visual_package_bindings([exhibit], modified)


class VisualPackageRoundTripTests(ResearchPackageAcceptanceSupport):
    def test_exact_visual_semantics_survive_package_build_export_verify(self):
        facade, case = self._prepare_case()
        try:
            payload = visual_payload(rq_ids=[case["rq_id"]], source_object_ids=[case["rq_id"]])
            eid = facade.capture_exhibit(payload)["exhibit"]["exhibit_id"]
            original = facade.show_exhibit(eid)["exhibit"]
            case["build_input"]["exhibit_ids"].append(eid)
            built = facade.build_research_package(case["build_input"])
            package_id = built["package"]["package_id"]
            output = self.root / "visual-package"
            facade.export_research_package(package_id, output)
            from plugins.local_application.research_package_format import verify_export_root
            import json
            self.assertEqual(verify_export_root(output)["status"], "VERIFIED")
            package = json.loads((output / "research-package.json").read_text())
            saved = next(e for e in package["resolved_content"]["working_material"]["research_exhibits"] if e["exhibit_id"] == eid)
            self.assertEqual(saved["visual_semantics"], original["visual_semantics"])
        finally:
            facade.close()


if __name__ == "__main__":
    unittest.main()
