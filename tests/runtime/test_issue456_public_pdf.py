import hashlib
import io
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import rfc8785
from pypdf import PdfWriter

import tests.runtime.test_external_desktop_research_intake as intake
import tests.runtime.test_misco_writer_profile_application as writer_tests
from plugins.local_application import LocalApplicationError, LocalApplicationFacade, LocalWorkspace
from plugins.local_application.workspace.profile_resolution import resolve_effective_profile_set
from tests.runtime.research_package_acceptance_support import ResearchPackageAcceptanceSupport
from tests.runtime.test_issue456_formal_document import representative_report

ROOT = Path(__file__).resolve().parents[2]


class PublicPdfTests(ResearchPackageAcceptanceSupport):
    _build_round_trip = writer_tests.MiscoWriterProfileApplicationTests._build_round_trip
    _review = staticmethod(writer_tests.MiscoWriterProfileApplicationTests._review)
    _response = classmethod(writer_tests.MiscoWriterProfileApplicationTests._response.__func__)

    def _write_structured_workspace_inputs(self):
        config = intake.bootstrap_config()
        config["profile_requests"] = {
            "research": [],
            "organization": [],
            "narrative": [
                {"profile_id": "misco.writer", "profile_type": "narrative", "version": "1.1.0"}
            ],
            "publication": [
                {
                    "profile_id": "misco.publication",
                    "profile_type": "publication",
                    "version": "1.4.0",
                }
            ],
        }
        config["publication_metadata"] = {"research_group_type": "G"}
        config.pop("configuration_digest", None)
        config["configuration_digest"] = (
            "sha256:" + hashlib.sha256(rfc8785.dumps(config)).hexdigest()
        )
        effective = resolve_effective_profile_set(
            config,
            [writer_tests.WRITER_MANIFEST, ROOT / "profiles/publication/misco/1.4.0/profile.json"],
        )
        cfg, eps = self.root / "config.json", self.root / "profiles.json"
        cfg.write_text(json.dumps(config), encoding="utf-8")
        eps.write_text(json.dumps(effective), encoding="utf-8")
        return cfg, eps

    def draft(self):
        facade, case, composition, input_doc, output = self._build_round_trip()
        response = self._response(input_doc, response_id="WR-456")
        for section in response["sections"]:
            section["exhibit_refs"] = []
        imported = facade.import_writer_response(response)
        report = representative_report()
        report["structure"] = [
            {"section_id": "SEC-FRAME", "level": 1},
            {"section_id": "SEC-VALIDATE", "level": 2},
        ]
        report["footnotes"] = []
        built = facade.build_publication_preview(
            composition["composition_id"],
            imported["revision_id"],
            {"schema_version": "0.1.0", "document_mode": "formal_report", "formal_report": report},
        )
        return facade, built

    def finalization_input(self, build):
        stream = io.BytesIO()
        pdf = PdfWriter()
        pdf.add_blank_page(width=595.276, height=841.89)
        pdf.write(stream)
        payload = stream.getvalue()
        (self.workspace / "test.pdf").write_bytes(payload)
        digest = "sha256:" + hashlib.sha256(payload).hexdigest()
        docx = next(row for row in build["outputs"] if row["format"] == "docx")["digest"]
        review = {
            "pdf_digest": digest,
            "reviewer_id": "synthetic-reviewer",
            "reviewed_at": "2026-10-13T00:00:00Z",
            "checks": [],
            "pages": [{"page": 1, "status": "passed", "rationale": "Synthetic page fixture only."}],
        }
        for id_ in [item["id"] for item in build["publication_policy"]["coverage"]["items"]] + [
            "misco-editorial-qa",
            "final-pdf-all-pages",
            "final-pdf-toc",
            "final-pdf-footnotes",
            "final-pdf-parity",
            "final-pdf-cover",
        ]:
            review["checks"].append(
                {
                    "check_id": id_,
                    "status": "passed",
                    "rationale": "Synthetic exact-binding acceptance only.",
                }
            )
        next(row for row in review["checks"] if row["check_id"] == "misco-body-length").update(
            status="warning",
            rationale="Short synthetic persistence fixture, not a substantive research report.",
        )
        return {
            "pdf_path": "test.pdf",
            "pdf_digest": digest,
            "source_docx_digest": docx,
            "project_config_digest": build["publication_policy"]["project_config_pin"][
                "configuration_digest"
            ],
            "host_receipt": {
                "source_docx_digest": docx,
                "pdf_digest": digest,
                "software": "Microsoft Word",
                "software_version": "16.0",
                "fields_updated": True,
                "page_ranges": {"abstract": [1, 1], "body": [1, 1], "appendix": [1, 1]},
            },
            "review": review,
        }

    def test_exact_pdf_binding_review_release_and_retry(self):
        facade, draft = self.draft()
        try:
            build = draft["build"]
            self.assertEqual(build["verification"]["formal_specification"], "warning")
            with self.assertRaises(LocalApplicationError):
                facade.request_publication_release(build["build_id"], "reviewer")
            input_ = self.finalization_input(build)
            failed = facade.finalize_publication_pdf(build["build_id"], input_)
            self.assertEqual(failed["build"]["verification"]["final_pdf_machine"], "failed")
            with self.assertRaises(LocalApplicationError):
                facade.request_publication_release(failed["build"]["build_id"], "reviewer")
            wrong = deepcopy(input_)
            wrong["source_docx_digest"] = "sha256:" + "0" * 64
            with self.assertRaises(LocalApplicationError):
                facade.finalize_publication_pdf(build["build_id"], wrong)
            # Separate public persistence/approval tests from the real renderer:
            # the deliberately blank PDF above already failed actual inspection.
            fake_machine = {
                "page_count": 1,
                "fonts": [],
                "problems": [],
                "page_text": ["synthetic"],
            }
            accepted = deepcopy(input_)
            accepted["review"]["reviewer_id"] = "synthetic-persistence-reviewer"
            with patch(
                "plugins.local_application.publication.publication_pdf.inspect_pdf",
                return_value=fake_machine,
            ):
                finalized = facade.finalize_publication_pdf(build["build_id"], accepted)
                self.assertEqual(
                    facade.finalize_publication_pdf(build["build_id"], accepted)["status"],
                    "VERIFIED_REUSE",
                )
            final = finalized["build"]
            request = facade.request_publication_release(final["build_id"], "reviewer")[
                "decision_request"
            ]
            decision = {
                "request_id": request["request_id"],
                "request_digest": request["request_digest"],
                "disposition": "approve_release",
                "actor_id": "reviewer",
            }
            released = facade.release_publication(final["build_id"], decision)
            self.assertEqual(released["release"]["output"]["media_type"], "application/pdf")
            self.assertEqual(released["release"]["output"]["digest"], accepted["pdf_digest"])
            self.assertEqual(
                facade.release_publication(final["build_id"], decision)["status"], "VERIFIED_REUSE"
            )
            broken = deepcopy(accepted)
            broken["review"]["checks"][0]["status"] = "not_applicable"
            with patch(
                "plugins.local_application.publication.publication_pdf.inspect_pdf",
                return_value=fake_machine,
            ):
                rejected = facade.finalize_publication_pdf(build["build_id"], broken)
            with self.assertRaises(LocalApplicationError):
                facade.request_publication_release(rejected["build"]["build_id"], "reviewer")
        finally:
            facade.close()

    def test_group_answer_advances_through_public_boundary_and_survives_restart(self):
        with LocalWorkspace.open(self.workspace) as opened:
            before = deepcopy(dict(opened.project_config))
        request = {
            "profile_manifest_files": [
                str(writer_tests.WRITER_MANIFEST),
                str(ROOT / "profiles/publication/misco/1.4.0/profile.json"),
            ],
            "publication_metadata": {"research_group_type": "M"},
            "expected_project_config_digest": before["configuration_digest"],
        }
        out = self.root / "metadata-generation"
        LocalApplicationFacade.resolve_profile_generation(self.workspace, request, out)
        advance = {
            "project_config_file": str(out / "project-config.json"),
            "effective_profile_set_file": str(out / "effective-profile-set.json"),
            "profile_manifest_files": request["profile_manifest_files"],
            "origin": "synthetic-issue456",
        }
        result = LocalApplicationFacade.advance_profile_generation(self.workspace, advance)
        self.assertFalse(result.get("research_state_mutation_performed", False))
        with LocalWorkspace.open(self.workspace) as opened:
            current = deepcopy(dict(opened.project_config))
        self.assertEqual(current["publication_metadata"], {"research_group_type": "M"})
        self.assertNotEqual(current["configuration_digest"], before["configuration_digest"])
        for key in ["scope", "research_questions", "research_attention", "project_constraints"]:
            self.assertEqual(current[key], before[key])
        with self.assertRaises(Exception):
            LocalApplicationFacade.resolve_profile_generation(
                self.workspace, request, self.root / "stale-answer"
            )
        request["expected_project_config_digest"] = current["configuration_digest"]
        same = self.root / "same-answer"
        LocalApplicationFacade.resolve_profile_generation(self.workspace, request, same)
        self.assertEqual(
            json.loads((same / "project-config.json").read_text(encoding="utf-8")), current
        )
