from __future__ import annotations

from copy import deepcopy
from unittest.mock import patch

from core.runtime import canonical_digest
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
