from __future__ import annotations

from copy import deepcopy
import json
from unittest.mock import patch

from core.runtime import canonical_digest
from plugins.local_application import LocalApplicationError
from plugins.local_application import historical_result_recovery_facade as historical_result_recovery
from research_package_acceptance_support import ResearchPackageAcceptanceSupport
from test_finding_candidate_recovery import FindingCandidateRecoveryTests


class Issue151AmbiguousCanonicalRecoveryTests(ResearchPackageAcceptanceSupport):
    _legacyize = FindingCandidateRecoveryTests._legacyize

    def _ambiguous_case(self):
        facade, case = self._prepare_case()
        legacy = self._legacyize(facade, case["proposal"])
        duplicate = deepcopy(legacy)
        duplicate["proposal_id"] = "SDP-ISSUE151-DUPLICATE"
        duplicate.pop("proposal_digest", None)
        duplicate["proposal_digest"] = canonical_digest(duplicate)
        facade._application.conversation_store.store_state_delta_proposal(
            duplicate["proposal_id"], duplicate
        )
        return facade, case, legacy, duplicate

    def test_ambiguous_legacy_candidates_use_verified_canonical_result(self):
        facade, case, legacy, duplicate = self._ambiguous_case()
        try:
            diagnosis = facade.show_run(case["run_id"])["finding_recovery"]
            self.assertEqual(diagnosis["recovery_class"], "proposal_rematerializable")
            self.assertEqual(
                diagnosis["recovery_route"], "canonical_result_rematerialization"
            )
            self.assertEqual(
                diagnosis["historical_candidate_lineage_status"], "ambiguous"
            )
            self.assertEqual(diagnosis["historical_candidate_count"], "multiple")

            action = facade.submit_action({
                "action_type": "desktop_research.finding.recover",
                "payload": {"run_id": case["run_id"]},
                "actor_id": "HUMAN-ISSUE151",
            })
            self.assertEqual(action["status"], "SUCCEEDED")
            recovered = action["data"]
            self.assertEqual(recovered["route"], "canonical_result_rematerialization")
            proposal = facade._application.conversation_store.load_state_delta_proposal(
                recovered["state_delta_proposal_id"]
            )
            recovery = proposal["provenance"]["historical_recovery"]
            self.assertEqual(recovery["recovery_source"], "canonical_result")
            self.assertEqual(
                recovery["historical_candidate_lineage_status"], "ambiguous"
            )
            self.assertEqual(recovery["historical_candidate_count"], "multiple")
            self.assertNotIn("historical_proposal_id", recovery)
            self.assertEqual(
                facade._application.conversation_store.load_state_delta_proposal(
                    legacy["proposal_id"]
                ),
                legacy,
            )
            self.assertEqual(
                facade._application.conversation_store.load_state_delta_proposal(
                    duplicate["proposal_id"]
                ),
                duplicate,
            )
        finally:
            facade.close()

    def test_corrupt_canonical_result_still_blocks_and_ablation_proves_guard(self):
        facade, case, _legacy, _duplicate = self._ambiguous_case()
        try:
            verified_canonical = historical_result_recovery._canonical_result(
                facade._application, facade.project_id, case["run_id"]
            )
            db = facade._application.execution_store._connection
            row = db.execute(
                "SELECT payload_json FROM execution_documents "
                "WHERE document_type='extension' AND run_id=?",
                (case["run_id"],),
            ).fetchone()
            extension = json.loads(str(row["payload_json"]))
            extension["source_capture_details"][0]["original_capture"][
                "content_reference"
            ] = "ART-MISSING"
            db.execute(
                "UPDATE execution_documents SET payload_json=? "
                "WHERE document_type='extension' AND run_id=?",
                (
                    json.dumps(extension, sort_keys=True, separators=(",", ":")),
                    case["run_id"],
                ),
            )

            diagnosis = facade.show_run(case["run_id"])["finding_recovery"]
            self.assertNotEqual(diagnosis["recovery_class"], "proposal_rematerializable")
            with self.assertRaises(LocalApplicationError) as caught:
                facade.recover_legacy_desktop_research_finding_candidate(case["run_id"])
            self.assertIn(
                caught.exception.code,
                {
                    "APPLICATION-HISTORICAL-RECOVERY-MATERIAL-001",
                    "APPLICATION-HISTORICAL-RECOVERY-RESULT-001",
                },
            )

            # Ablation: with independent canonical verification disabled, the
            # same invalid result can enter rematerialization through ambiguity.
            with patch(
                "plugins.local_application.historical_result_recovery_facade._canonical_result",
                return_value=verified_canonical,
            ):
                ablated = facade.recover_legacy_desktop_research_finding_candidate(
                    case["run_id"]
                )
            self.assertEqual(ablated["route"], "canonical_result_rematerialization")
        finally:
            facade.close()

    def test_exact_valid_persisted_candidate_route_is_unchanged(self):
        facade, case = self._prepare_case()
        try:
            self._legacyize(facade, case["proposal"])
            diagnosis = facade.show_run(case["run_id"])["finding_recovery"]
            self.assertEqual(diagnosis["recovery_route"], "persisted_candidate_recovery")
            recovered = facade.recover_legacy_desktop_research_finding_candidate(
                case["run_id"]
            )
            self.assertEqual(recovered["producer_relation"], "exact_run")
        finally:
            facade.close()
