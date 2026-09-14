from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from unittest.mock import patch

from core.runtime import canonical_digest
from plugins.local_application import LocalApplicationError
from plugins.local_conversation_store import (
    LocalConversationStore,
    find_state_delta_proposals_by_provenance_run_id,
    persist_state_delta_proposal_idempotently,
)
from research_package_acceptance_support import ResearchPackageAcceptanceSupport


class FindingCandidateRecoveryReviewFixTests(ResearchPackageAcceptanceSupport):
    def _legacyize(self, facade, proposal):
        legacy = deepcopy(proposal)
        for action in legacy["proposed_actions"]:
            obj = action.get("payload", {}).get("object", {})
            if obj.get("kind") == "finding":
                obj["adoption_state"] = "candidate"
        legacy.pop("proposal_digest", None)
        legacy["proposal_digest"] = canonical_digest(legacy)
        facade._application.conversation_store._db.execute(
            "UPDATE state_delta_proposals SET payload_json=? WHERE proposal_id=?",
            (
                facade._application.conversation_store._json(legacy),
                legacy["proposal_id"],
            ),
        )
        return legacy

    def test_invalid_context_pins_fail_closed_as_integrity_error(self):
        facade, case = self._prepare_case()
        try:
            self._legacyize(facade, case["proposal"])
            run = facade._application.execution_store.load_run(case["run_id"])
            context = facade._application.execution_store.load_context_pack(
                run.context_pack_id
            )
            malformed = deepcopy(context)
            malformed["pins"] = None
            with patch.object(
                facade._application.execution_store,
                "load_context_pack",
                return_value=malformed,
            ):
                with self.assertRaises(LocalApplicationError) as caught:
                    facade.recover_legacy_desktop_research_finding_candidate(
                        case["run_id"]
                    )
            self.assertEqual(
                caught.exception.code, "APPLICATION-FINDING-RECOVERY-INTEGRITY-001"
            )
        finally:
            facade.close()

    def test_idempotent_persistence_is_atomic_across_connections(self):
        path = self.root / "recovery-idempotency.sqlite3"
        first = LocalConversationStore(path)
        second = LocalConversationStore(path)
        payload = {
            "proposal_id": "SDP-RECOVERY-ATOMIC",
            "project_ref": "PRJ-ATOMIC",
            "provenance": {"run_id": "RUN-ATOMIC"},
        }
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(
                    pool.map(
                        lambda store: persist_state_delta_proposal_idempotently(
                            store, payload["proposal_id"], payload
                        ),
                        (first, second),
                    )
                )
            self.assertCountEqual(results, [False, True])
        finally:
            first.close()
            second.close()

    def test_recovery_identity_collision_is_reported_as_integrity_error(self):
        facade, case = self._prepare_case()
        try:
            self._legacyize(facade, case["proposal"])
            recovered = facade.recover_legacy_desktop_research_finding_candidate(
                case["run_id"]
            )
            store = facade._application.conversation_store
            store._db.execute(
                "UPDATE state_delta_proposals SET payload_json=? WHERE proposal_id=?",
                (
                    store._json(
                        {
                            "proposal_id": recovered["state_delta_proposal_id"],
                            "tampered": True,
                        }
                    ),
                    recovered["state_delta_proposal_id"],
                ),
            )
            with self.assertRaises(LocalApplicationError) as caught:
                facade.recover_legacy_desktop_research_finding_candidate(case["run_id"])
            self.assertEqual(
                caught.exception.code, "APPLICATION-FINDING-RECOVERY-INTEGRITY-001"
            )
        finally:
            facade.close()

    def test_run_lookup_uses_provenance_index_and_remains_bounded(self):
        path = self.root / "recovery-index.sqlite3"
        store = LocalConversationStore(path)
        try:
            index = store._db.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
                ("state_delta_proposals_provenance_run_id",),
            ).fetchone()
            self.assertIsNotNone(index)
            for idx in range(5):
                payload = {
                    "proposal_id": f"SDP-{idx}",
                    "provenance": {"run_id": "RUN-TARGET" if idx < 2 else f"RUN-{idx}"},
                }
                store.store_state_delta_proposal(payload["proposal_id"], payload)
            statements = []
            store._db.set_trace_callback(statements.append)
            try:
                matches = find_state_delta_proposals_by_provenance_run_id(
                    store, "RUN-TARGET", limit=3
                )
            finally:
                store._db.set_trace_callback(None)
            self.assertEqual(len(matches), 2)
            self.assertFalse(
                any(statement.lstrip().upper().startswith("CREATE INDEX") for statement in statements)
            )
            plan = store._db.execute(
                "EXPLAIN QUERY PLAN SELECT payload_json FROM state_delta_proposals "
                "WHERE json_valid(payload_json) "
                "AND json_extract(payload_json, '$.provenance.run_id')=? "
                "ORDER BY proposal_id LIMIT ?",
                ("RUN-TARGET", 3),
            ).fetchall()
            self.assertTrue(
                any(
                    "state_delta_proposals_provenance_run_id" in str(row["detail"])
                    for row in plan
                )
            )
        finally:
            store.close()
