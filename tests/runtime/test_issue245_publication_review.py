from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfWriter

import tests.runtime.test_issue220_publication_release as support
from plugins.local_application import LocalApplicationError, LocalApplicationFacade
from plugins.local_application.publication.publication_pdf import (
    FINAL_PDF_CHECKS,
    coverage_review,
    inspect_pdf,
)
from tests.runtime.research_package_acceptance_support import ResearchPackageAcceptanceSupport

CI_WINDOWS = True


class PublicationReviewTests(ResearchPackageAcceptanceSupport):
    def _ready(self):
        helper = support.Issue220PublicationReleaseTests()
        helper.root, helper.workspace = self.root, self.workspace
        facade, _, composition, imported, _ = helper._prepared()
        self.addCleanup(facade.close)
        build = facade.build_publication_preview(
            composition["composition_id"], imported["revision_id"]
        )["build"]
        return facade, build["build_id"]

    def test_pdf_inspection_accepts_more_than_256_pages_within_byte_bound(self):
        writer = PdfWriter()
        for _ in range(257):
            writer.add_blank_page(width=595.276, height=841.89)
        buffer = io.BytesIO()
        writer.write(buffer)

        result = inspect_pdf(buffer.getvalue())

        self.assertEqual(result["page_count"], 257)

    def test_pdf_review_accepts_complete_page_and_slide_evidence_above_256(self):
        page_count = 257
        pdf_digest = "sha256:" + "a" * 64
        review = {
            "pdf_digest": pdf_digest,
            "reviewer_id": "reviewer-1",
            "reviewed_at": "2026-10-20T12:00:00Z",
            "checks": [
                {"check_id": check_id, "status": "passed", "rationale": "Checked"}
                for check_id in FINAL_PDF_CHECKS
            ],
            "pages": [
                {"page": page, "status": "passed", "rationale": "Checked"}
                for page in range(1, page_count + 1)
            ],
            "presentation_review": {
                "artifact_digest": pdf_digest,
                "artifact_reference": "presentation.pptx",
                "software_version": "1.0",
                "slide_count": page_count,
                "slides": [
                    {
                        "slide": slide,
                        "status": "passed",
                        "citations_required": False,
                        "citations": [],
                        "rationale": "Checked",
                    }
                    for slide in range(1, page_count + 1)
                ],
            },
        }
        result = coverage_review(
            {"items": []},
            {
                "formal_report": {
                    "research_kind": "research_theme",
                    "presentation_required": True,
                },
                "review_conditions": {},
            },
            review,
            pdf_digest,
            page_count,
        )

        self.assertNotIn("all-page-review-incomplete", result["problems"])
        self.assertNotIn("presentation-review-binding", result["problems"])
        self.assertNotIn("presentation-per-slide-citations", result["problems"])

    def test_staging_initialization_errors_are_public_write_diagnostics_and_retryable(self):
        facade, build_id = self._ready()
        service = facade._publication_release_service()
        original_mkdir = Path.mkdir
        import tempfile

        original_mkstemp = tempfile.mkstemp
        operation_dir = service.root / "release-operations"

        def denied_mkdir(path, *args, **kwargs):
            if path == operation_dir:
                raise PermissionError("injected operation directory failure")
            return original_mkdir(path, *args, **kwargs)

        def denied_mkstemp(*args, **kwargs):
            if Path(kwargs.get("dir", ".")) == operation_dir:
                raise PermissionError("injected operation staging failure")
            return original_mkstemp(*args, **kwargs)

        for target, method, replacement in (
            (Path, "mkdir", denied_mkdir),
            (tempfile, "mkstemp", denied_mkstemp),
        ):
            with self.subTest(method=method):
                with patch.object(target, method, replacement):
                    with self.assertRaises(LocalApplicationError) as error:
                        facade.request_publication_release(build_id, method)
                self.assertEqual(error.exception.code, "APPLICATION-PUBLICATION-WRITE-001")
                request = facade.request_publication_release(build_id, method)["decision_request"]
                self.assertEqual(
                    facade.request_publication_release(build_id, method)["decision_request"],
                    request,
                )

    def test_operation_only_recovery_is_reported_without_changing_original_facts(self):
        facade, build_id = self._ready()
        request = facade.request_publication_release(build_id, "H")["decision_request"]
        response = support.Issue220PublicationReleaseTests._approval(request)
        manifest = facade.release_publication(build_id, response)["release"]
        service = facade._publication_release_service()
        operation = service._operation_path(request["request_id"])
        original = operation.read_bytes()
        operation.unlink()
        facade.close()
        with LocalApplicationFacade.open_workspace(self.workspace) as reopened:
            with patch.object(
                reopened._application.clock, "now", return_value="2099-01-01T00:00:00Z"
            ):
                result = reopened.release_publication(build_id, response)
            self.assertEqual(result["status"], "RESTORED")
            self.assertEqual(result["restored_components"], ["release-operation"])
            self.assertEqual(result["recovered_at"], "2099-01-01T00:00:00Z")
            self.assertEqual(result["release"], manifest)
            self.assertEqual(operation.read_bytes(), original)
            self.assertEqual(
                reopened.release_publication(build_id, response)["status"], "VERIFIED_REUSE"
            )

    def test_missing_operation_does_not_scan_unrelated_request_history(self):
        facade, build_id = self._ready()
        request = facade.request_publication_release(build_id, "H")["decision_request"]
        service = facade._publication_release_service()
        service._operation_path(request["request_id"]).unlink()
        # Both retained facts and total request loss use direct operation paths.
        with (
            patch.object(Path, "glob", side_effect=AssertionError("history scan")),
            patch.object(Path, "iterdir", side_effect=AssertionError("history scan")),
        ):
            with self.assertRaises(LocalApplicationError) as error:
                facade.request_publication_release(build_id, "H")
            self.assertEqual(error.exception.code, "APPLICATION-PUBLICATION-RECOVERY-REQUIRED-001")
            service._release_request_path(request["request_id"]).unlink()
            new = facade.request_publication_release(build_id, "H")["decision_request"]
        self.assertNotEqual(new["request_id"], request["request_id"])

    def test_exact_legacy_nonce_request_path_recovers_without_scanning_history(self):
        from plugins.local_application.publication.publication_release_support import (
            _digest,
            _json_bytes,
        )

        facade, build_id = self._ready()
        request = facade.request_publication_release(build_id, "H")["decision_request"]
        response = support.Issue220PublicationReleaseTests._approval(request)
        manifest = facade.release_publication(build_id, response)["release"]
        service = facade._publication_release_service()
        stable = service._release_request_path(request["request_id"])
        legacy = stable.with_name(request["request_id"] + ".json")
        stable.rename(legacy)
        service._operation_path(request["request_id"]).unlink()
        original = legacy.read_bytes()
        # Exact caller-supplied identity permits one bounded fallback, not a directory scan.
        forged = dict(request, request_id=request["request_id"] + "-other")
        forged["request_digest"] = _digest(forged, "request_digest")
        legacy.write_bytes(_json_bytes(forged))
        with self.assertRaises(LocalApplicationError) as error:
            facade.release_publication(build_id, response)
        self.assertEqual(error.exception.code, "APPLICATION-PUBLICATION-INTEGRITY-001")
        legacy.write_bytes(original)
        facade.close()
        with LocalApplicationFacade.open_workspace(self.workspace) as reopened:
            with (
                patch.object(Path, "glob", side_effect=AssertionError("history scan")),
                patch.object(Path, "iterdir", side_effect=AssertionError("history scan")),
                patch.object(
                    reopened._application.clock, "now", return_value="2099-01-01T00:00:00Z"
                ),
            ):
                restored = reopened.release_publication(build_id, response)
            self.assertEqual(restored["status"], "RESTORED")
            self.assertEqual(restored["release"], manifest)
            self.assertEqual(restored["recovered_at"], "2099-01-01T00:00:00Z")
            self.assertEqual(stable.read_bytes(), original)
            self.assertEqual(legacy.read_bytes(), original)
            self.assertEqual(
                reopened.release_publication(build_id, response)["status"], "VERIFIED_REUSE"
            )
