from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from plugins.local_application import LocalApplicationError, LocalApplicationFacade, LocalResearchApplication
from plugins.local_application import external_submission as submission_module
import test_external_desktop_research_intake as intake
import test_issue92_external_submission_preflight as issue92
from runtime_fixtures import project, rq, seed_state


class Issue92ReviewRound3Tests(unittest.TestCase):
    def fixture(self):
        return issue92.Issue92ExternalSubmissionPreflightTests(
            methodName="test_d1_assembled_collect_uses_persisted_bindings_and_is_candidate_only"
        )

    def test_non_string_unknown_keys_fail_as_submission_errors(self):
        base = self.fixture()
        mutators = (
            lambda value: value["citation_details"][0].__setitem__(7, "bad"),
            lambda value: value["search_trace"].__setitem__(7, "bad"),
            lambda value: value["search_trace"]["entries"][0].__setitem__(7, "bad"),
        )
        for mutate in mutators:
            with self.subTest(mutate=mutate), tempfile.TemporaryDirectory() as temp:
                root = Path(temp); app, facade = base.make_facade(root)
                try:
                    run_id, valid, _ = base.prepared(root, facade)
                    broken = deepcopy(valid); mutate(broken)
                    with self.assertRaises(LocalApplicationError) as caught:
                        facade.preflight_external(run_id, {"research_result": broken})
                    self.assertEqual(caught.exception.code, "APPLICATION-EXTERNAL-SUBMISSION-001")
                    base.assert_running(app, run_id)
                finally:
                    facade.close()

    def test_capture_pair_resolution_scans_run_artifacts_once(self):
        base = self.fixture()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); app, facade = base.make_facade(root)
            try:
                run_id, _, _ = base.prepared(root, facade)
                raw = root / "captures/raw/source-b.html"; text = root / "captures/text/source-b.txt"
                raw.write_bytes(b"<html>source B</html>"); text.write_text("Source B text.", encoding="utf-8")
                facade.capture_external_source(run_id, {
                    "capture_id": "CAP-2", "source_category": "other",
                    "exact_locator": "https://example.test/source-b#section-1",
                    "acquired_at": "2026-08-31T00:00:01Z",
                    "original_file": "captures/raw/source-b.html", "original_media_type": "text/html",
                    "text_rendition_file": "captures/text/source-b.txt",
                })
                original = app.execution_store.artifacts_for
                with patch.object(app.execution_store, "artifacts_for", wraps=original) as artifacts_for:
                    captures, details, texts = submission_module._resolve_captures(app, run_id, ["CAP-1", "CAP-2"])
                self.assertEqual(artifacts_for.call_count, 1)
                self.assertEqual([item["capture_id"] for item in captures], ["CAP-1", "CAP-2"])
                self.assertEqual(len(details), 2); self.assertEqual(set(texts), {"CAP-1", "CAP-2"})
            finally:
                facade.close()

    def test_duplicate_resource_basis_is_verified_once(self):
        base = self.fixture()
        catalog = {
            "REF-SOURCE-1": {
                "reference_type": "source", "object_id": "SRC-1",
                "access_mode": "read", "evidentiary_use": "candidate_source",
            }
        }
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            seed = seed_state(objects=[project(), rq(state="approved")], mode="real", snapshot_id="SNP-R3-RESOURCE")
            app = LocalResearchApplication(
                root / ".research-loom", resolver=intake.NullResolver(),
                effective_profile_set_provider=intake.profile_provider, seed_state=seed,
                resource_catalog=catalog, resource_roles={"REF-SOURCE-1": "candidate_source"},
                resource_bytes={"REF-SOURCE-1": b"registered source resource bytes"},
            )
            facade = LocalApplicationFacade(app, "PRJ-1", workspace_root=root)
            try:
                run_id = facade.submit_action({
                    "action_type": "desktop_research.investigate",
                    "payload": {
                        "question_id": "RQ-1", "purpose": "duplicate resource validation",
                        "resource_reference_ids": ["REF-SOURCE-1"],
                    },
                })["run_id"]
                facade.start_external_retrieval_attempt(run_id, {
                    "attempt_id": "ATT-1", "strategy": "support search", "coverage_dimension_ids": ["COV-SUPPORT"]
                })
                base.write_capture_files(root)
                capture = facade.capture_external_source(run_id, {
                    "capture_id": "CAP-1", "source_category": "other",
                    "exact_locator": "https://example.test/source-a#section-1",
                    "acquired_at": "2026-08-31T00:00:00Z",
                    "original_file": "captures/raw/source-a.html", "original_media_type": "text/html",
                    "text_rendition_file": "captures/text/source-a.txt",
                })["capture"]
                facade.complete_external_retrieval_attempt(run_id, {
                    "attempt_id": "ATT-1", "outcome": "source_captured", "resulting_capture_id": "CAP-1"
                })
                facade.start_external_retrieval_attempt(run_id, {
                    "attempt_id": "ATT-2", "strategy": "counter search", "coverage_dimension_ids": ["COV-COUNTER"]
                })
                facade.complete_external_retrieval_attempt(run_id, {"attempt_id": "ATT-2", "outcome": "no_relevant_source"})
                handoff, extension = intake.golden_submission(app, run_id, capture)
                valid = base.research_result(handoff, extension)
                basis = {"basis_type": "resource_reference", "resource_reference_id": "REF-SOURCE-1"}
                valid["outputs"]["evidence_candidates"][0]["source_basis"] = deepcopy(basis)
                second = deepcopy(valid["outputs"]["evidence_candidates"][0])
                second["evidence_candidate_id"] = "EVC-2"
                second["source_basis"] = deepcopy(basis)
                valid["outputs"]["evidence_candidates"].append(second)
                with patch.object(
                    submission_module,
                    "verified_resource_basis_provenance",
                    wraps=submission_module.verified_resource_basis_provenance,
                ) as verified:
                    result = facade.preflight_external(run_id, {"research_result": valid})
                self.assertIn(result["status"], {"PREFLIGHT_OK", "PREFLIGHT_REJECTED"})
                self.assertEqual(verified.call_count, 1)
            finally:
                facade.close()


if __name__ == "__main__":
    unittest.main()
