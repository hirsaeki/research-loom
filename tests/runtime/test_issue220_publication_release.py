from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import threading
from unittest.mock import patch
import zipfile

from jsonschema import Draft202012Validator, FormatChecker

from plugins.local_application import LocalApplicationError
from plugins.local_application.publication_release_service import PublicationReleaseService
from research_package_acceptance_support import ResearchPackageAcceptanceSupport
from test_issue219_writer_round_trip import Issue219WriterRoundTripTests
import issue80_writer_composition_suite as writer_comp_support


ROOT = Path(__file__).resolve().parents[2]
PREVIEW_SCHEMA = ROOT / "core/packages/writer-publication/publication-preview.schema.json"


class Issue220PublicationReleaseTests(ResearchPackageAcceptanceSupport):
    def _prepared(
        self,
        *,
        broken_token: bool = False,
        structured_citation: bool = True,
        frame_content: str | None = None,
    ):
        helper = Issue219WriterRoundTripTests()
        helper.root = self.root
        helper.workspace = self.workspace
        facade, case, composition, _exported, input_doc = helper._build_round_trip()
        scope = input_doc["sections"][0]["citation_scope"]
        self.assertTrue(scope)
        source_ref = scope[0]["source_ref"]
        locator = scope[0]["locators"][0]
        exhibit_ref = input_doc["sections"][0]["exhibit_refs"][0]
        token = (
            "[[citation:MISSING-SOURCE]]"
            if broken_token
            else f"[[citation:{source_ref}]]"
        )
        content = frame_content or (
            f"Framing uses {token} and see [[exhibit:{exhibit_ref}]]. "
            "Continue at [[section:SEC-VALIDATE]]."
        )
        sections = [
            {
                "section_id": "SEC-FRAME",
                "content": content,
                "citations": (
                    [{"source_ref": source_ref, "locator_ref": locator}]
                    if structured_citation
                    else []
                ),
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
        return facade, case, composition, imported, source_ref

    @staticmethod
    def _approval(request):
        return {
            "request_id": request["request_id"],
            "request_digest": request["request_digest"],
            "disposition": "approve_release",
            "actor_id": request["human_actor_id"],
        }

    def test_deterministic_preview_docx_and_bound_release_decision(self):
        facade, case, composition, imported, _source_ref = self._prepared()
        try:
            state_repo = facade._application.state_repository
            before = state_repo.load_state_view(
                facade.project_id,
                state_repo.load_active_lineage_ref(facade.project_id),
            ).current_snapshot["content_digest"]
            with patch.object(
                facade._application.state_transition_service,
                "apply",
                side_effect=AssertionError("Publication must not mutate Research State"),
            ):
                first = facade.build_publication_preview(
                    composition["composition_id"], imported["revision_id"]
                )
                retry = facade.build_publication_preview(
                    composition["composition_id"], imported["revision_id"]
                )
            self.assertEqual(first["status"], "BUILT")
            self.assertEqual(retry["status"], "VERIFIED_REUSE")
            build = first["build"]
            preview_manifest = first["preview_manifest"]
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
            self.assertEqual(preview_manifest["object_type"], "preview_artifact_manifest")
            self.assertEqual(preview_manifest["preview_id"], build["build_id"])
            schema = json.loads(PREVIEW_SCHEMA.read_text(encoding="utf-8"))
            Draft202012Validator(
                schema, format_checker=FormatChecker()
            ).validate(preview_manifest)

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

            # Ablation: caller-provided identifiers are not a release decision.
            with self.assertRaises(LocalApplicationError) as error:
                facade.release_publication(
                    build["build_id"],
                    {
                        "request_id": "PUBRELREQ-FORGED",
                        "request_digest": "sha256:" + "0" * 64,
                        "disposition": "approve_release",
                        "actor_id": "HUMAN-RELEASE",
                    },
                )
            self.assertEqual(
                error.exception.code, "APPLICATION-PUBLICATION-RELEASE-DECISION-001"
            )
            self.assertFalse(
                (facade._publication_release_service().root / "releases").exists()
            )

            request_result = facade.request_publication_release(
                build["build_id"], "HUMAN-RELEASE"
            )
            request = request_result["decision_request"]
            self.assertEqual(request_result["status"], "PENDING")
            self.assertEqual(request["project_ref"], facade.project_id)
            self.assertEqual(
                request["source_preview"]["preview_digest"],
                preview_manifest["content_digest"],
            )
            approval = self._approval(request)
            with patch.object(
                facade._application.state_transition_service,
                "apply",
                side_effect=AssertionError("Publication release must not mutate Research State"),
            ):
                released = facade.release_publication(build["build_id"], approval)
                released_again = facade.release_publication(
                    build["build_id"], deepcopy(approval)
                )
            self.assertEqual(released["status"], "RELEASED")
            self.assertEqual(released_again["status"], "VERIFIED_REUSE")
            manifest = released["release"]
            self.assertEqual(
                manifest["human_release_decision"]["request_id"], request["request_id"]
            )
            self.assertEqual(
                manifest["source_manuscript"]["revision_digest"], imported["revision_digest"]
            )
            self.assertEqual(
                manifest["publication_profile"]["content_digest"],
                build["publication_profile"]["content_digest"],
            )
            artifact = (
                facade._publication_release_service().root
                / "releases"
                / manifest["release_id"]
                / "artifact.docx"
            )
            self.assertEqual(manifest["output"]["size"], artifact.stat().st_size)
            self.assertEqual(
                manifest["output"]["digest"],
                next(x["digest"] for x in build["outputs"] if x["format"] == "docx"),
            )

            after = state_repo.load_state_view(
                facade.project_id,
                state_repo.load_active_lineage_ref(facade.project_id),
            ).current_snapshot["content_digest"]
            self.assertEqual(after, before)
        finally:
            facade.close()

    def test_broken_reference_is_visible_in_preview_but_blocks_release_request(self):
        facade, _case, composition, imported, _source_ref = self._prepared(
            broken_token=True
        )
        try:
            built = facade.build_publication_preview(
                composition["composition_id"], imported["revision_id"]
            )
            build = built["build"]
            self.assertEqual(build["verification"]["citation_resolution"], "failed")
            self.assertTrue(
                any(issue["code"] == "UNRESOLVED_CITATION" for issue in build["issues"])
            )
            root = facade._publication_release_service()._build_path(build["build_id"])
            # Ablation: rendering alone still produces an apparently valid document.
            self.assertTrue((root / "formal.docx").read_bytes().startswith(b"PK"))
            self.assertIn(
                "[unresolved citation:MISSING-SOURCE]",
                (root / "preview.md").read_text(encoding="utf-8"),
            )
            with self.assertRaises(LocalApplicationError) as error:
                facade.request_publication_release(build["build_id"], "HUMAN-RELEASE")
            self.assertEqual(
                error.exception.code, "APPLICATION-PUBLICATION-RELEASE-CHECK-001"
            )
        finally:
            facade.close()

    def test_synthetic_preview_cannot_request_or_complete_release(self):
        facade, _case, composition, imported, _source_ref = self._prepared()
        try:
            built = facade.build_publication_preview(
                composition["composition_id"], imported["revision_id"]
            )
            synthetic_preview = deepcopy(built["preview_manifest"])
            synthetic_preview["source_epistemic_status"] = "SYNTHETIC_TEST_ONLY"
            shown = {
                "build": deepcopy(built["build"]),
                "preview_manifest": synthetic_preview,
            }
            service = facade._publication_release_service()
            with patch.object(service, "show_preview", return_value=shown):
                with self.assertRaises(LocalApplicationError) as request_error:
                    service.request_release(built["build"]["build_id"], "HUMAN-RELEASE")
            self.assertEqual(
                request_error.exception.code,
                "APPLICATION-PUBLICATION-RELEASE-CHECK-001",
            )

            request = {
                "request_id": "PUBRELREQ-SYNTHETIC",
                "request_digest": "sha256:" + "1" * 64,
                "human_actor_id": "HUMAN-RELEASE",
                "allowed_dispositions": ["approve_release"],
            }
            response = {
                "request_id": request["request_id"],
                "request_digest": request["request_digest"],
                "disposition": "approve_release",
                "actor_id": request["human_actor_id"],
            }
            with (
                patch.object(service, "_load_release_request", return_value=request),
                patch.object(service, "show_preview", return_value=shown),
            ):
                with self.assertRaises(LocalApplicationError) as release_error:
                    service.release(built["build"]["build_id"], response)
            self.assertEqual(
                release_error.exception.code,
                "APPLICATION-PUBLICATION-RELEASE-CHECK-001",
            )
        finally:
            facade.close()

    def test_token_only_citation_resolves_from_pinned_package(self):
        facade, _case, composition, imported, source_ref = self._prepared(
            structured_citation=False
        )
        try:
            built = facade.build_publication_preview(
                composition["composition_id"], imported["revision_id"]
            )
            self.assertEqual(built["build"]["verification"]["citation_resolution"], "passed")
            markdown = facade.show_publication_preview(built["build"]["build_id"])[
                "preview_markdown"
            ]
            self.assertIn("[1]", markdown)
            self.assertIn(source_ref, markdown)
        finally:
            facade.close()

    def test_cross_reference_to_composition_section_absent_from_revision_is_unresolved(self):
        facade, case = writer_comp_support.Issue80WriterCompositionTests._build_complete_support_package(
            self
        )
        try:
            proposal = writer_comp_support.Issue80WriterCompositionTests._proposal(self, case)
            proposal["sections"][1]["narrative_stage_refs"] = ["framing"]
            proposal["sections"][1]["semantic_purpose_refs"] = ["frame_problem"]
            composition = facade.capture_writer_composition(case["package_id"], proposal)[
                "composition"
            ]
            facade.select_writer_composition(
                composition["composition_id"], 1, composition["composition_digest"]
            )
            output = self.root / "writer-round-trip-single"
            facade.export_writer_round_trip_input(
                composition["composition_id"], ["SEC-FRAME"], output
            )
            input_doc = json.loads((output / "writer-input.json").read_text(encoding="utf-8"))
            helper = Issue219WriterRoundTripTests()
            response = helper._response(
                input_doc,
                sections=[
                    {
                        "section_id": "SEC-FRAME",
                        "content": "Missing target [[section:SEC-VALIDATE]].",
                        "citations": [],
                        "exhibit_refs": list(input_doc["sections"][0]["exhibit_refs"]),
                    }
                ],
                feedback=[],
            )
            imported = facade.import_writer_response(response)
            built = facade.build_publication_preview(
                composition["composition_id"], imported["revision_id"]
            )
            self.assertEqual(
                built["build"]["verification"]["cross_reference_resolution"], "failed"
            )
            self.assertIn(
                "[unresolved section:SEC-VALIDATE]",
                facade.show_publication_preview(built["build"]["build_id"])[
                    "preview_markdown"
                ],
            )
        finally:
            facade.close()

    def test_tampered_docx_after_release_request_is_rejected(self):
        facade, _case, composition, imported, _source_ref = self._prepared()
        try:
            built = facade.build_publication_preview(
                composition["composition_id"], imported["revision_id"]
            )
            build = built["build"]
            request = facade.request_publication_release(
                build["build_id"], "HUMAN-RELEASE"
            )["decision_request"]
            root = facade._publication_release_service()._build_path(build["build_id"])
            (root / "formal.docx").write_bytes(b"PK-tampered")
            with self.assertRaises(LocalApplicationError) as error:
                facade.release_publication(build["build_id"], self._approval(request))
            self.assertEqual(error.exception.code, "APPLICATION-PUBLICATION-INTEGRITY-001")
        finally:
            facade.close()

    def test_xml_incompatible_writer_text_is_rejected_before_docx_persistence(self):
        facade, _case, composition, imported, _source_ref = self._prepared(
            frame_content="Invalid control \x01 in Writer text."
        )
        try:
            with self.assertRaises(LocalApplicationError) as error:
                facade.build_publication_preview(
                    composition["composition_id"], imported["revision_id"]
                )
            self.assertEqual(error.exception.code, "APPLICATION-PUBLICATION-RENDER-001")
        finally:
            facade.close()

    def test_concurrent_identical_preview_serializes_to_verified_reuse(self):
        facade, _case, composition, imported, _source_ref = self._prepared()
        inspection = facade.inspect_writer_round_trip(
            composition["composition_id"], imported["revision_id"]
        )
        receipt = inspection["writer_input"]
        package = facade._writer_composition_service()._package(
            str(receipt["source"]["research_package_id"])
        )

        class PackageReader:
            @staticmethod
            def _package(_package_id):
                return deepcopy(package)

        class PublicationFacade:
            _workspace_root = self.workspace
            project_id = facade.project_id

            @staticmethod
            def inspect_writer_round_trip(_composition_id, _revision_id):
                return deepcopy(inspection)

            @staticmethod
            def _writer_composition_service():
                return PackageReader()

        service = PublicationReleaseService(PublicationFacade())
        entered = threading.Event()
        release = threading.Event()
        second_started = threading.Event()
        original = PublicationReleaseService._render
        call_count = 0
        count_lock = threading.Lock()

        def slow_render(instance, render_inspection):
            nonlocal call_count
            with count_lock:
                call_count += 1
                first = call_count == 1
            if first:
                entered.set()
                self.assertTrue(release.wait(5))
            return original(instance, render_inspection)

        results = []
        errors = []

        def run_preview(*, is_second: bool = False):
            try:
                if is_second:
                    second_started.set()
                results.append(
                    service.build_preview(
                        composition["composition_id"], imported["revision_id"]
                    )
                )
            except Exception as exc:  # pragma: no cover - assertion captures details
                errors.append(exc)

        try:
            with patch.object(PublicationReleaseService, "_render", slow_render):
                first = threading.Thread(target=run_preview)
                second = threading.Thread(target=run_preview, kwargs={"is_second": True})
                first.start()
                self.assertTrue(entered.wait(5))
                second.start()
                self.assertTrue(second_started.wait(5))
                self.assertTrue(second.is_alive())
                release.set()
                first.join(5)
                second.join(5)
            self.assertFalse(errors)
            self.assertEqual(
                {row["status"] for row in results}, {"BUILT", "VERIFIED_REUSE"}
            )
            self.assertEqual(call_count, 1)
        finally:
            facade.close()
