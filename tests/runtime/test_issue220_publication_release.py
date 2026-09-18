from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import patch
import zipfile

from plugins.local_application import LocalApplicationError
from research_package_acceptance_support import ResearchPackageAcceptanceSupport
from test_issue219_writer_round_trip import Issue219WriterRoundTripTests
import issue80_writer_composition_suite as writer_comp_support


class Issue220PublicationReleaseTests(ResearchPackageAcceptanceSupport):
    def _prepared(self, *, broken_token: bool = False):
        helper = Issue219WriterRoundTripTests()
        helper.root = self.root
        helper.workspace = self.workspace
        facade, case, composition, _exported, input_doc = helper._build_round_trip()
        scope = input_doc["sections"][0]["citation_scope"]
        self.assertTrue(scope)
        source_ref = scope[0]["source_ref"]
        locator = scope[0]["locators"][0]
        exhibit_ref = input_doc["sections"][0]["exhibit_refs"][0]
        token = "[[citation:MISSING-SOURCE]]" if broken_token else f"[[citation:{source_ref}]]"
        sections = [
            {
                "section_id": "SEC-FRAME",
                "content": f"Framing uses {token} and see [[exhibit:{exhibit_ref}]]. Continue at [[section:SEC-VALIDATE]].",
                "citations": [{"source_ref": source_ref, "locator_ref": locator}],
                "exhibit_refs": [exhibit_ref],
            },
            {
                "section_id": "SEC-VALIDATE",
                "content": "Validation remains bounded by the supplied unresolved material.",
                "citations": [],
                "exhibit_refs": [],
            },
        ]
        response = helper._response(input_doc, sections=sections)
        imported = facade.import_writer_response(response)
        return facade, case, composition, imported

    def test_deterministic_preview_docx_and_release_manifest(self):
        facade, case, composition, imported = self._prepared()
        try:
            state_repo = facade._application.state_repository
            before = state_repo.load_state_view(
                facade.project_id, state_repo.load_active_lineage_ref(facade.project_id)
            ).current_snapshot["content_digest"]
            with patch.object(
                facade._application.state_transition_service,
                "apply",
                side_effect=AssertionError("Publication must not mutate Research State"),
            ):
                first = facade.build_publication_preview(composition["composition_id"], imported["revision_id"])
                retry = facade.build_publication_preview(composition["composition_id"], imported["revision_id"])
            self.assertEqual(first["status"], "BUILT")
            self.assertEqual(retry["status"], "VERIFIED_REUSE")
            build = first["build"]
            self.assertEqual(build["verification"]["citation_resolution"], "passed")
            self.assertEqual(build["verification"]["exhibit_resolution"], "passed")
            self.assertEqual(build["verification"]["cross_reference_resolution"], "passed")
            self.assertEqual(build["verification"]["render_verification"], "passed")
            self.assertEqual(
                build["research_provenance"]["research_package_id"], case["package_id"]
            )
            self.assertEqual(
                build["source_manuscript"]["revision_digest"], imported["revision_digest"]
            )
            self.assertEqual(build["publication_profile"]["profile_id"], "fixture.publication")

            root = facade._publication_release_service()._build_path(build["build_id"])
            markdown = (root / "preview.md").read_text(encoding="utf-8")
            self.assertIn("[1]", markdown)
            self.assertIn("Table 1", markdown)
            self.assertIn('Section “Validation plan”', markdown)
            with zipfile.ZipFile(root / "formal.docx") as archive:
                self.assertIn("word/document.xml", archive.namelist())
                doc = archive.read("word/document.xml").decode("utf-8")
                self.assertIn("Table 1", doc)
                self.assertIn("References", doc)

            with self.assertRaises(LocalApplicationError) as error:
                facade.release_publication(build["build_id"], {})
            self.assertEqual(error.exception.code, "APPLICATION-PUBLICATION-RELEASE-DECISION-001")
            self.assertFalse((facade._publication_release_service().root / "releases").exists())

            decision = {
                "decision_id": "PUB-DEC-1",
                "actor_id": "HUMAN-RELEASE",
                "disposition": "approve_release",
                "build_id": build["build_id"],
                "build_digest": build["content_digest"],
            }
            with patch.object(
                facade._application.state_transition_service,
                "apply",
                side_effect=AssertionError("Publication release must not mutate Research State"),
            ):
                released = facade.release_publication(build["build_id"], decision)
                released_again = facade.release_publication(build["build_id"], deepcopy(decision))
            self.assertEqual(released["status"], "RELEASED")
            self.assertEqual(released_again["status"], "VERIFIED_REUSE")
            manifest = released["release"]
            self.assertEqual(manifest["human_release_decision"], decision)
            self.assertEqual(manifest["source_manuscript"]["revision_digest"], imported["revision_digest"])
            self.assertEqual(manifest["publication_profile"]["content_digest"], build["publication_profile"]["content_digest"])
            artifact = facade._publication_release_service().root / "releases" / manifest["release_id"] / "artifact.docx"
            self.assertEqual(manifest["output"]["size"], artifact.stat().st_size)
            self.assertEqual(manifest["output"]["digest"], next(x["digest"] for x in build["outputs"] if x["format"] == "docx"))

            after = state_repo.load_state_view(
                facade.project_id, state_repo.load_active_lineage_ref(facade.project_id)
            ).current_snapshot["content_digest"]
            self.assertEqual(after, before)
        finally:
            facade.close()

    def test_broken_reference_is_visible_in_preview_but_blocks_release(self):
        facade, _case, composition, imported = self._prepared(broken_token=True)
        try:
            built = facade.build_publication_preview(composition["composition_id"], imported["revision_id"])
            build = built["build"]
            self.assertEqual(build["verification"]["citation_resolution"], "failed")
            self.assertTrue(any(issue["code"] == "UNRESOLVED_CITATION" for issue in build["issues"]))
            root = facade._publication_release_service()._build_path(build["build_id"])
            # Ablation: rendering alone still produces an apparently valid document.
            self.assertTrue((root / "formal.docx").read_bytes().startswith(b"PK"))
            self.assertIn("[unresolved citation:MISSING-SOURCE]", (root / "preview.md").read_text(encoding="utf-8"))
            decision = {
                "decision_id": "PUB-DEC-BROKEN",
                "actor_id": "HUMAN-RELEASE",
                "disposition": "approve_release",
                "build_id": build["build_id"],
                "build_digest": build["content_digest"],
            }
            with self.assertRaises(LocalApplicationError) as error:
                facade.release_publication(build["build_id"], decision)
            self.assertEqual(error.exception.code, "APPLICATION-PUBLICATION-RELEASE-CHECK-001")
        finally:
            facade.close()
