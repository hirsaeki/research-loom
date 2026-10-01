from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
import shutil
import tempfile
import unittest

from plugins.local_application import LocalApplicationError, LocalApplicationFacade
from tests.runtime.test_external_desktop_research_intake import golden_submission
from tests.runtime.test_issue91_external_material_content import _prepare
from tests.runtime.test_research_question_review import _adopt_question, _workspace


def _research_result(handoff: dict, extension: dict) -> dict:
    outputs = deepcopy(handoff["outputs"])
    capture_ids = [item["capture_id"] for item in outputs.pop("source_captures")]
    citations = [
        {
            key: item[key]
            for key in (
                "citation_id",
                "handoff_output_kind",
                "handoff_output_id",
                "capture_id",
                "excerpt",
                "excerpt_locator",
            )
        }
        for item in extension["citation_details"]
    ]
    links = []
    for item in extension["search_trace"]["entries"]:
        link = {
            "attempt_id": item["trace_entry_id"],
            "related_handoff_output_ids": deepcopy(item["related_handoff_output_ids"]),
        }
        if "notes" in item:
            link["notes"] = item["notes"]
        links.append(link)
    return {
        "validation": deepcopy(handoff["validation"]),
        "outputs": outputs,
        "capture_ids": capture_ids,
        "citation_details": citations,
        "search_trace": {"entries": links},
        "null_results": deepcopy(extension["null_results"]),
        "evidence_gap_assessments": deepcopy(extension["evidence_gap_assessments"]),
        "coverage_assessment": deepcopy(extension["coverage_assessment"]),
        "candidate_next_method_ids": deepcopy(extension["candidate_next_method_ids"]),
    }


class Issue368HostAttachmentIntakeTests(unittest.TestCase):
    def test_project_input_attachment_uses_workspace_relative_staging_and_survives_cleanup(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = _workspace(root)
            staged = workspace / "intake" / "chat" / "ATT-brief" / "project-brief.md"
            staged.parent.mkdir(parents=True)
            content = b"# Supplied project brief\nUse this as framing, not evidence.\n"
            staged.write_bytes(content)

            with LocalApplicationFacade.open_workspace(workspace) as facade:
                snapshot_before = facade.resume_context()["research_state"]["snapshot"]
                registered = facade.register_project_input({
                    "file": str(staged.relative_to(workspace)),
                    "role": "project_brief",
                    "expected_snapshot_id": snapshot_before["snapshot_id"],
                    "expected_snapshot_digest": snapshot_before["content_digest"],
                    "provenance": {
                        "source": "host_attachment",
                        "host_attachment_id": "ATT-brief",
                    },
                })["project_input"]
                self.assertEqual(
                    registered["content_digest"],
                    "sha256:" + hashlib.sha256(content).hexdigest(),
                )
                self.assertEqual(
                    registered["source_path"],
                    str(staged.relative_to(workspace)),
                )
                self.assertEqual(
                    facade.resume_context()["research_state"]["snapshot"],
                    snapshot_before,
                )

            shutil.rmtree(staged.parent)
            with LocalApplicationFacade.open_workspace(workspace) as facade:
                shown = facade.show_project_input(registered["input_id"], format="text")
                self.assertEqual(shown["content"]["value"].encode("utf-8"), content)
                self.assertEqual(shown["project_input"]["role"], "project_brief")
                self.assertEqual(
                    shown["project_input"]["provenance"]["host_attachment_id"],
                    "ATT-brief",
                )

    def test_research_source_attachment_uses_existing_run_capture_and_survives_cleanup(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = _workspace(root)
            stage = workspace / "intake" / "chat" / "ATT-source"
            original = stage / "report.pdf"
            rendition = stage / "report.txt"
            stage.mkdir(parents=True)
            original_bytes = b"%PDF-1.4\nfixture research source\n%%EOF\n"
            text_bytes = b"Source A contains the exact supporting excerpt used here.\n"
            original.write_bytes(original_bytes)
            rendition.write_bytes(text_bytes)

            with LocalApplicationFacade.open_workspace(workspace) as facade:
                question_id = _adopt_question(facade, "Issue 368 source intake")
                snapshot_before = facade.resume_context()["research_state"]["snapshot"]
                run_id = _prepare(facade, question_id)
                facade.start_external_retrieval_attempt(run_id, {
                    "attempt_id": "ATT-1",
                    "strategy": "explicit host attachment intake",
                    "coverage_dimension_ids": ["COV-SUPPORT"],
                    "query_or_target": "attachment:ATT-source",
                    "provider_or_tool": "host_attachment",
                })
                captured = facade.capture_external_source(run_id, {
                    "capture_id": "CAP-1",
                    "source_category": "other",
                    "exact_locator": "https://example.test/source-a#section-1",
                    "acquired_at": "2026-10-01T00:00:00Z",
                    "original_file": str(original.relative_to(workspace)),
                    "original_media_type": "application/pdf",
                    "text_rendition_file": str(rendition.relative_to(workspace)),
                    "provenance": {
                        "source": "host_attachment",
                        "host_attachment_id": "ATT-source",
                    },
                })["capture"]
                facade.complete_external_retrieval_attempt(run_id, {
                    "attempt_id": "ATT-1",
                    "outcome": "source_captured",
                    "resulting_capture_id": "CAP-1",
                })
                run_view = facade.show_run(run_id)
                self.assertEqual(run_view["run"]["status"], "RUNNING")
                self.assertEqual(
                    run_view["desktop_research"]["retrieval_attempt_summary"]["source_captured"],
                    1,
                )
                facade.start_external_retrieval_attempt(run_id, {
                    "attempt_id": "ATT-2",
                    "strategy": "bounded counter-source check",
                    "coverage_dimension_ids": ["COV-COUNTER"],
                    "query_or_target": "counter-source fixture",
                    "provider_or_tool": "host_attachment_acceptance",
                })
                facade.complete_external_retrieval_attempt(run_id, {
                    "attempt_id": "ATT-2",
                    "outcome": "no_relevant_source",
                })
                handoff, extension = golden_submission(facade._application, run_id, captured)
                result_input = _research_result(handoff, extension)
                preflight = facade.preflight_external(run_id, {"research_result": result_input})
                self.assertEqual(preflight["status"], "PREFLIGHT_OK")
                collected = facade.collect_external(run_id, {"research_result": result_input})
                self.assertEqual(collected["execution_result"]["run"]["status"], "COMPLETED")
                self.assertTrue(
                    collected["execution_result"]["state_delta_proposal"]["candidate_only"]
                )
                self.assertEqual(
                    facade.resume_context()["research_state"]["snapshot"],
                    snapshot_before,
                )
                original_digest = captured["original_capture"]["content_digest"]
                text_digest = captured["text_rendition"]["content_digest"]

            shutil.rmtree(stage)
            with LocalApplicationFacade.open_workspace(workspace) as facade:
                shown = facade.show_external_material(run_id, "CAP-1")
                self.assertEqual(
                    shown["capture"]["original"]["digest"],
                    original_digest,
                )
                self.assertEqual(
                    shown["capture"]["renditions"][0]["digest"],
                    text_digest,
                )
                self.assertEqual(shown["text_rendition_view"]["content"].encode("utf-8"), text_bytes)
                self.assertEqual(
                    shown["capture"]["provenance"]["host_attachment_id"],
                    "ATT-source",
                )
                self.assertEqual(
                    shown["capture"]["source_locator"],
                    "https://example.test/source-a#section-1",
                )

    def test_missing_rendition_is_recorded_as_failed_attempt_without_capture_or_state_mutation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = _workspace(root)
            stage = workspace / "intake" / "chat" / "ATT-unreadable"
            original = stage / "scan.pdf"
            stage.mkdir(parents=True)
            original.write_bytes(b"%PDF unreadable fixture")

            with LocalApplicationFacade.open_workspace(workspace) as facade:
                question_id = _adopt_question(facade, "Issue 368 unavailable rendition")
                snapshot_before = facade.resume_context()["research_state"]["snapshot"]
                run_id = _prepare(facade, question_id)
                facade.start_external_retrieval_attempt(run_id, {
                    "attempt_id": "ATT-NO-TEXT",
                    "strategy": "explicit host attachment intake",
                    "coverage_dimension_ids": ["COV-SUPPORT"],
                    "query_or_target": "attachment:ATT-unreadable",
                    "provider_or_tool": "host_attachment",
                })
                with self.assertRaises(LocalApplicationError) as missing:
                    facade.capture_external_source(run_id, {
                        "capture_id": "CAP-NO-TEXT",
                        "source_category": "other",
                        "exact_locator": "attachment:ATT-unreadable/scan.pdf",
                        "acquired_at": "2026-10-01T00:00:00Z",
                        "original_file": str(original.relative_to(workspace)),
                        "original_media_type": "application/pdf",
                        "text_rendition_file": "intake/chat/ATT-unreadable/scan.txt",
                    })
                self.assertEqual(missing.exception.code, "APPLICATION-EXTERNAL-FILE-002")
                facade.complete_external_retrieval_attempt(run_id, {
                    "attempt_id": "ATT-NO-TEXT",
                    "outcome": "failed",
                    "failure_or_blocking_reason": "host could not produce a UTF-8 text rendition",
                })
                shown = facade.show_run(run_id)
                self.assertEqual(shown["desktop_research"]["retrieval_attempt_summary"]["failed"], 1)
                self.assertEqual(shown["artifacts"], [])
                self.assertEqual(
                    facade.resume_context()["research_state"]["snapshot"],
                    snapshot_before,
                )

    def test_same_attachment_bytes_can_be_explicitly_routed_without_auto_classification(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = _workspace(root)
            stage = workspace / "intake" / "chat" / "ATT-ambiguous"
            original = stage / "ambiguous.pdf"
            rendition = stage / "ambiguous.txt"
            stage.mkdir(parents=True)
            body = b"same attachment bytes"
            original.write_bytes(body)
            rendition.write_bytes(body)

            with LocalApplicationFacade.open_workspace(workspace) as facade:
                question_id = _adopt_question(facade, "Issue 368 explicit routing")
                snapshot = facade.resume_context()["research_state"]["snapshot"]
                project_input = facade.register_project_input({
                    "file": str(original.relative_to(workspace)),
                    "role": "project_brief",
                    "media_type": "application/pdf",
                    "expected_snapshot_id": snapshot["snapshot_id"],
                    "expected_snapshot_digest": snapshot["content_digest"],
                    "provenance": {"route": "project_input"},
                })["project_input"]

                run_id = _prepare(facade, question_id)
                captured = facade.capture_external_source(run_id, {
                    "capture_id": "CAP-AMBIGUOUS",
                    "source_category": "other",
                    "exact_locator": "attachment:ATT-ambiguous/ambiguous.pdf",
                    "acquired_at": "2026-10-01T00:00:00Z",
                    "original_file": str(original.relative_to(workspace)),
                    "original_media_type": "application/pdf",
                    "text_rendition_file": str(rendition.relative_to(workspace)),
                    "provenance": {"route": "research_source"},
                })["capture"]
                self.assertEqual(
                    project_input["content_digest"],
                    captured["original_capture"]["content_digest"],
                )
                self.assertEqual(project_input["provenance"]["route"], "project_input")
                shown = facade.show_external_material(run_id, "CAP-AMBIGUOUS")
                self.assertEqual(shown["capture"]["provenance"]["route"], "research_source")

                outside = root / "outside.txt"
                outside.write_text("outside", encoding="utf-8")
                with self.assertRaises(LocalApplicationError) as traversal:
                    facade.register_project_input({
                        "file": "../outside.txt",
                        "role": "other",
                        "expected_snapshot_id": snapshot["snapshot_id"],
                        "expected_snapshot_digest": snapshot["content_digest"],
                    })
                self.assertEqual(traversal.exception.code, "APPLICATION-PROJECT-INPUT-FILE-001")


if __name__ == "__main__":
    unittest.main()
