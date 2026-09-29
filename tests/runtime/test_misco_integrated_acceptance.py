from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from plugins.local_application import LocalApplicationError, LocalApplicationFacade
from research_package_acceptance_support import ResearchPackageAcceptanceSupport
import test_misco_writer_profile_application as writer_profile
import test_external_desktop_research_intake as intake

ROOT = Path(__file__).resolve().parents[2]
PROJECT_CONFIG = ROOT / "projects/misco-ai-2026/project-config.json"
PROJECT_EPS = ROOT / "projects/misco-ai-2026/effective-profile-set.json"


class MiscoIntegratedAcceptanceTests(ResearchPackageAcceptanceSupport):
    """Issue #337 deterministic integration over the production MISCO config/Profile path."""

    def _write_structured_workspace_inputs(self):
        cfg = self.root / "project-config-input.json"
        eps = self.root / "profiles-input.json"
        cfg.write_bytes(PROJECT_CONFIG.read_bytes())
        eps.write_bytes(PROJECT_EPS.read_bytes())
        return cfg, eps

    @staticmethod
    def _adopt_current_rq(facade: LocalApplicationFacade) -> str:
        proposed = facade.submit_action({
            "action_type": "research_question.propose",
            "payload": {
                "text": "Which current evidence should this MISCO research checkpoint test first?",
                "acceptance_criteria": ["Current evidence can be compared without importing legacy research state."],
                "scope_limits": ["Use only material captured in this current Workspace."],
            },
            "actor_id": "HUMAN-337",
        })
        rq_id = proposed["data"]["research_question_candidate"]["id"]
        pending = facade.submit_action({
            "action_type": "state.apply_candidate",
            "payload": {"state_delta_proposal_id": proposed["data"]["state_delta_proposal_id"]},
            "actor_id": "HUMAN-337",
        })
        decision = facade.submit_confirmation({
            "confirmation_request_id": pending["confirmation_request"]["confirmation_request_id"],
            "actor_id": "HUMAN-337",
        })["decision_request"]
        resolved = facade.resolve_human_decision({
            "request_id": decision["request_id"],
            "request_digest": decision["request_digest"],
            "disposition": "approve_exact",
            "actor_id": "HUMAN-337",
        })
        assert resolved["status"] == "RESOLVED"
        return rq_id

    def _prepare_case(self, **kwargs):
        # ResearchPackageAcceptanceSupport calls the shared helper directly.
        # Patch only the test helper so the production path receives current
        # operator input instead of the fixture's historical seed id.
        with patch.object(intake, "adopt_rq", self._adopt_current_rq):
            return super()._prepare_case(**kwargs)

    def _build_round_trip(self):
        return writer_profile.MiscoWriterProfileApplicationTests._build_round_trip(self)

    @staticmethod
    def _response(input_doc, **kwargs):
        return writer_profile.MiscoWriterProfileApplicationTests._response(input_doc, **kwargs)

    def test_g1_mid_research_checkpoint_can_round_trip_writer_preview_and_return_to_research(self):
        facade, case, composition, input_doc, _output = self._build_round_trip()
        try:
            self.assertEqual(facade.project_id, "misco-m3-2026")
            package = facade.show_research_package(case["package_id"])["package"]
            pins = {
                (row["profile_type"], row["profile_id"], row["profile_version"])
                for row in package["effective_profile_set"]["profile_pins"]
            }
            self.assertIn(("narrative", "misco.writer", "1.1.0"), pins)
            self.assertIn(("publication", "misco.publication", "1.2.0"), pins)

            state = facade._application.state_repository.load_state_view(
                facade.project_id,
                facade._application.state_repository.load_active_lineage_ref(facade.project_id),
            )
            research_snapshot_before = state.current_snapshot["content_digest"]

            response = self._response(input_doc, response_id="WR-G337-1")
            scope = input_doc["sections"][0]["citation_scope"][0]
            response["sections"][0]["citations"] = [{
                "source_ref": scope["source_ref"],
                "locator_ref": scope["locators"][0],
            }]
            response["sections"][0]["content"] += f" [[citation:{scope['source_ref']}]]"
            first = facade.import_writer_response(response)

            revision = self._response(
                input_doc,
                response_id="WR-G337-2",
                base={"revision_id": first["revision_id"], "revision_digest": first["revision_digest"]},
                partial=True,
            )
            revision["sections"][0]["content"] = (
                "Revised framing remains bounded by the current Workspace material. "
                f"[[citation:{scope['source_ref']}]]"
            )
            revision["sections"][0]["citations"] = [{
                "source_ref": scope["source_ref"],
                "locator_ref": scope["locators"][0],
            }]
            second = facade.import_writer_response(revision)
            self.assertEqual(second["revision_number"], 2)
            self.assertEqual(second["reused_section_ids"], ["SEC-VALIDATE"])

            after_writer = facade._application.state_repository.load_state_view(
                facade.project_id,
                facade._application.state_repository.load_active_lineage_ref(facade.project_id),
            )
            self.assertEqual(after_writer.current_snapshot["content_digest"], research_snapshot_before)

            preview = facade.build_publication_preview(composition["composition_id"], second["revision_id"])["build"]
            self.assertEqual(preview["publication_profile"]["profile_id"], "misco.publication")
            self.assertEqual(preview["verification"]["formal_specification"], "passed")
            self.assertEqual(preview["verification"]["editorial_qa"], "warning")
            shown_preview = facade.show_publication_preview(preview["build_id"])
            self.assertIn("https://example.test/source-a", shown_preview["preview_markdown"])
            with self.assertRaises(LocalApplicationError) as raised:
                facade.request_publication_release(preview["build_id"], "human-337")
            self.assertEqual(raised.exception.code, "APPLICATION-PUBLICATION-RELEASE-CHECK-001")

            after_preview = facade._application.state_repository.load_state_view(
                facade.project_id,
                facade._application.state_repository.load_active_lineage_ref(facade.project_id),
            )
            self.assertEqual(after_preview.current_snapshot["content_digest"], research_snapshot_before)

            # Returning to Research after Writer/Publication preview remains a normal operation.
            attention = facade.submit_action({
                "action_type": "research_attention.propose",
                "payload": {"additions": [{"statement": "Investigate the unresolved gap exposed by the checkpoint draft."}]},
                "actor_id": "HUMAN-337",
            })["data"]["attention_map"]
            self.assertTrue(attention["map_id"])
        finally:
            facade.close()

        with LocalApplicationFacade.open_workspace(self.workspace) as reopened:
            shown = reopened.inspect_writer_round_trip(composition["composition_id"], second["revision_id"])
            self.assertEqual(shown["revision"]["revision_id"], second["revision_id"])
            self.assertEqual(reopened.show_publication_preview(preview["build_id"])["build"]["build_id"], preview["build_id"])
            self.assertEqual(reopened.status()["project_id"], "misco-m3-2026")


if __name__ == "__main__":
    import unittest
    unittest.main()
