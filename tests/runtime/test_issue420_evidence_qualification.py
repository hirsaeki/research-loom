from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from core.runtime import canonical_digest
from plugins.local_application import LocalApplicationFacade, LocalResearchApplication
from plugins.local_application.research_chart import quantitative_input
from plugins.local_application.facade import LocalApplicationError
from core.conversation import ConversationRuntimeError
from runtime_fixtures import project, rq, source, evidence, seed_state
from test_research_exhibits import NullResolver, profile_provider


class EvidenceQualificationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.original = evidence(verification="unverified", evidence_kind="supporting")
        self.original["capture_digest"] = "sha256:" + "1" * 64
        seed = seed_state(objects=[project(), rq(state="approved"), source(), self.original])
        self.app = LocalResearchApplication(
            Path(temp.name), resolver=NullResolver(), effective_profile_set_provider=profile_provider,
            seed_state=seed,
        )
        self.addCleanup(self.app.close)
        self.facade = LocalApplicationFacade(self.app, "PRJ-1")
        self.excerpt = json.dumps({
            "columns": ["city", "cases"],
            "rows": [["東京", 30], ["大阪", 20], ["名古屋", 50]],
            "units": {"city": None, "cases": "件"},
            "denominator": None,
            "period": "2026",
        }, ensure_ascii=False, separators=(",", ":"))

    def current(self):
        state = self.app.state_repository.load_state_view("PRJ-1", "LIN-1")
        return state.latest_object("evidence", "EVD-1")

    def propose(self, **extra):
        payload = {
            "evidence_id": "EVD-1",
            "expected_revision": self.current()["revision"],
            "expected_digest": canonical_digest(self.current()),
            "rationale": "Exact quantitative excerpt checked against the captured source.",
            **extra,
        }
        return self.facade.submit_action({
            "action_type": "research.evidence.qualify", "payload": payload, "actor_id": "H",
        })

    def apply_through_decision(self, proposal_id):
        apply = self.facade.submit_action({
            "action_type": "state.apply_candidate",
            "payload": {"state_delta_proposal_id": proposal_id}, "actor_id": "H",
        })
        confirmed = self.facade.submit_confirmation({
            "confirmation_request_id": apply["confirmation_request"]["confirmation_request_id"],
            "actor_id": "H",
        })
        request = confirmed["decision_request"]
        self.assertEqual(
            {(u["required_decision_kind"], u["required_choice"]) for u in request["decision_units"]},
            {("evidence_qualification", "verify")},
        )
        self.assertEqual(self.current()["verification_status"], "unverified")
        return self.facade.resolve_human_decision({
            "request_id": request["request_id"], "request_digest": request["request_digest"],
            "disposition": "approve_exact", "actor_id": "H",
        })

    def test_candidate_only_then_existing_human_decision_commits_verified_revision(self):
        before = deepcopy(self.current())
        proposed = self.propose(excerpt=self.excerpt)
        self.assertEqual(proposed["data"]["qualification_status"], "CANDIDATE_CREATED")
        self.assertEqual(self.current(), before)
        revised = proposed["data"]["state_delta_proposal"]["proposed_actions"][0]["payload"]["object"]
        self.assertEqual(revised["revision"], 1)
        self.assertEqual(revised["verification_status"], "verified")
        self.assertEqual(revised["excerpt"], self.excerpt)
        for field in ("id", "project_id", "source_id", "locator", "statement", "capture_digest", "evidence_kind", "evidence_mode", "limitations"):
            self.assertEqual(revised[field], before[field])
        self.assertEqual(self.apply_through_decision(proposed["data"]["state_delta_proposal_id"])["status"], "RESOLVED")
        current = self.current()
        self.assertEqual((current["revision"], current["verification_status"]), (1, "verified"))
        self.assertEqual(quantitative_input(current)["rows"][0], ["東京", 30])
        self.assertNotIn("excerpt", self.app.state_repository.load_object_revision("evidence", "EVD-1", 0))

    def test_stale_or_field_smuggling_fails_closed(self):
        base = {
            "evidence_id": "EVD-1", "expected_revision": 0,
            "expected_digest": canonical_digest(self.current()), "rationale": "reviewed",
        }
        for payload in (
            {**base, "expected_revision": 1},
            {**base, "expected_digest": "sha256:" + "0" * 64},
            {**base, "statement": "silently changed"},
            {**base, "evidence_kind": "counterevidence"},
            {**base, "excerpt": ""},
        ):
            with self.subTest(payload=payload):
                with self.assertRaises((LocalApplicationError, ConversationRuntimeError)):
                    self.facade.submit_action({"action_type": "research.evidence.qualify", "payload": payload, "actor_id": "H"})
        self.assertEqual(self.current(), self.original)

    def test_verified_exact_retry_is_noop_but_content_rewrite_is_rejected(self):
        proposed = self.propose(excerpt=self.excerpt)
        self.apply_through_decision(proposed["data"]["state_delta_proposal_id"])
        current = deepcopy(self.current())
        retry = self.propose()
        self.assertEqual(retry["data"]["qualification_status"], "ALREADY_VERIFIED")
        self.assertEqual(self.current(), current)
        with self.assertRaises(ConversationRuntimeError):
            self.propose(excerpt="different")

    def test_action_registry_exposes_candidate_only_public_ingress(self):
        row = next(x for x in self.facade.list_actions()["actions"] if x["action_type"] == "research.evidence.qualify")
        self.assertEqual((row["effect"], row["route_category"], row["confirmation_required"]), ("read_only", "harness_service", False))


if __name__ == "__main__":
    unittest.main()
