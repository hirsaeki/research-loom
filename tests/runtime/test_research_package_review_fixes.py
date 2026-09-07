from __future__ import annotations

from dataclasses import replace
import unittest
from unittest.mock import patch

from core.execution import CapabilityRunRecord, RunStatus
from plugins.local_application import LocalApplicationError
from plugins.local_application.research_package_service import verify_export_root
import test_research_package_acceptance as acceptance


class ResearchPackageReviewFixTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = acceptance.ResearchPackageAcceptanceTests(
            methodName="test_rp1_detached_show_export_and_verify_reads_exact_materials"
        )
        self.fixture.setUp()

    def tearDown(self) -> None:
        self.fixture.tearDown()

    def test_completed_handoff_material_paths_and_list_summary_read(self) -> None:
        facade, case = self.fixture._build()
        try:
            package = facade.show_research_package(case["package_id"])["package"]
            material = package["resolved_content"]["materials"][0]
            self.assertEqual(
                material["text_rendition"]["attachment_path"],
                f"attachments/materials/{case['run_id']}/CAP-1.txt",
            )
            state = facade._application.state_repository.load_state_view(
                facade.project_id,
                facade._application.state_repository.load_active_lineage_ref(facade.project_id),
            )
            prepared = CapabilityRunRecord(
                run_id="RUN-RP-REVIEW-PREPARED",
                invocation_id="INV-RP-REVIEW-PREPARED",
                invocation_digest="sha256:" + "7" * 64,
                capability_id="desktop-research",
                capability_version="0.1.0",
                descriptor_digest="sha256:" + "8" * 64,
                implementation_id="fixture.review",
                implementation_version="0.1.0",
                function_id="investigate",
                execution_mode="real",
                context_pack_id="CTX-RP-REVIEW-PREPARED",
                context_pack_digest="sha256:" + "9" * 64,
                project_ref=facade.project_id,
                lineage_ref=state.active_lineage_ref,
                snapshot_ref=state.current_snapshot["id"],
                snapshot_digest=state.current_snapshot["content_digest"],
                attempt=1,
                parent_run_id=None,
                status=RunStatus.PREPARED,
                prepared_at="2026-09-07T00:00:00Z",
            )
            facade._application.execution_store.create_run(prepared)
            with self.assertRaises(LocalApplicationError) as error:
                facade.build_research_package(
                    {
                        "snapshot_id": state.current_snapshot["id"],
                        "rq_id": case["rq_id"],
                        "run_ids": [prepared.run_id],
                    }
                )
            self.assertEqual(error.exception.code, "APPLICATION-RESEARCH-PACKAGE-INPUT-001")

            completed = replace(
                prepared,
                run_id="RUN-RP-REVIEW-NO-HANDOFF",
                invocation_id="INV-RP-REVIEW-NO-HANDOFF",
                status=RunStatus.COMPLETED,
                started_at="2026-09-07T00:00:01Z",
                completed_at="2026-09-07T00:00:02Z",
            )
            facade._application.execution_store.create_run(completed)
            with self.assertRaises(LocalApplicationError) as error:
                facade.build_research_package(
                    {
                        "snapshot_id": state.current_snapshot["id"],
                        "rq_id": case["rq_id"],
                        "run_ids": [completed.run_id],
                    }
                )
            self.assertEqual(error.exception.code, "APPLICATION-RESEARCH-PACKAGE-INTEGRITY-001")

            service = facade._research_package_service()
            with patch.object(
                service, "_load", side_effect=AssertionError("list must not full-verify packages")
            ):
                listed = service.list()
            self.assertTrue(listed["packages"])
        finally:
            facade.close()

    def test_detached_bound_precedes_read_and_snapshot_load_is_selection_scoped(self) -> None:
        oversized = self.fixture.root / "oversized-detached"
        oversized.mkdir()
        package_path = oversized / "research-package.json"
        with package_path.open("wb") as handle:
            handle.write(b"{}")
            handle.truncate(16 * 1024 * 1024 + 1)
        with self.assertRaises(LocalApplicationError) as error:
            verify_export_root(oversized)
        self.assertEqual(error.exception.code, "APPLICATION-RESEARCH-PACKAGE-BOUND-001")

        facade, case = self.fixture._prepare_case()
        try:
            repo = facade._application.state_repository
            with patch.object(
                repo, "load_object_revision", wraps=repo.load_object_revision
            ) as load_revision:
                facade.build_research_package(
                    {
                        "snapshot_id": case["build_input"]["snapshot_id"],
                        "rq_id": case["rq_id"],
                    }
                )
            self.assertEqual(load_revision.call_count, 1)
        finally:
            facade.close()


if __name__ == "__main__":
    unittest.main()
