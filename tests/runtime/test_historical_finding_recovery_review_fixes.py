from __future__ import annotations

from copy import deepcopy
from unittest.mock import patch

from core.runtime import canonical_digest
from plugins.local_application import LocalApplicationError
from research_package_acceptance_support import ResearchPackageAcceptanceSupport
from test_historical_finding_lineage_recovery import HistoricalFindingLineageRecoveryTests


class HistoricalFindingRecoveryReviewFixTests(ResearchPackageAcceptanceSupport):
    def test_missing_proposal_identity_is_bounded_without_full_state_load(self):
        facade, case = self._prepare_case()
        try:
            legacy = HistoricalFindingLineageRecoveryTests._legacyize(
                self, facade, case["proposal"]
            )
            store = facade._application.conversation_store
            broken = deepcopy(legacy)
            broken.pop("proposal_id")
            broken.pop("proposal_digest", None)
            broken["proposal_digest"] = canonical_digest(broken)
            store._db.execute(
                "UPDATE state_delta_proposals SET payload_json=? WHERE proposal_id=?",
                (store._json(broken), legacy["proposal_id"]),
            )
            with patch.object(
                facade._application.state_repository,
                "load_state_view",
                side_effect=AssertionError("run show diagnosis must stay metadata-only"),
            ):
                diagnosis = facade.show_run(case["run_id"])["finding_recovery"]
            self.assertEqual(diagnosis["stage"], "candidate_integrity")
            self.assertEqual(
                diagnosis["failure_class"], "candidate_integrity_failure"
            )
        finally:
            facade.close()

    def test_candidate_lookup_failure_is_not_reclassified_as_exact_match(self):
        facade, case = self._prepare_case()
        try:
            with patch(
                "plugins.local_application.finding_recovery_lineage.find_state_delta_proposals_by_provenance_run_id",
                side_effect=RuntimeError("simulated candidate-store read failure"),
            ):
                with self.assertRaises(LocalApplicationError) as caught:
                    facade.recover_legacy_desktop_research_finding_candidate(
                        case["run_id"]
                    )
            self.assertEqual(
                caught.exception.code, "APPLICATION-FINDING-RECOVERY-CANDIDATE-001"
            )
        finally:
            facade.close()
