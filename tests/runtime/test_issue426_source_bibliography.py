from copy import deepcopy
import base64
import hashlib
import inspect
import json
from pathlib import Path
import tempfile
import unittest

import rfc8785

from core.conversation import ConversationRuntimeError
from core.runtime import canonical_digest
from plugins.local_application import LocalApplicationError, LocalApplicationFacade, LocalResearchApplication
from plugins.local_application.publication_exhibits import prepare_exhibits
from runtime_fixtures import project, rq, source, seed_state
from test_research_exhibits import NullResolver, profile_provider
import test_issue405_research_charts as charts


class SourceBibliographyIngressTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.original = source()
        self.original.update({
            "content_digest": "sha256:" + "1" * 64,
            "media_type": "application/pdf",
        })
        seed = seed_state(objects=[project(), rq(state="approved"), self.original])
        self.app = LocalResearchApplication(
            Path(temp.name), resolver=NullResolver(), effective_profile_set_provider=profile_provider,
            seed_state=seed,
        )
        self.addCleanup(self.app.close)
        self.facade = LocalApplicationFacade(self.app, "PRJ-1")

    def current(self):
        state = self.app.state_repository.load_state_view("PRJ-1", "LIN-1")
        return state.latest_object("source", "SRC-1")

    def propose(self, **metadata):
        current = self.current()
        payload = {
            "source_id": "SRC-1",
            "expected_revision": current["revision"],
            "expected_digest": canonical_digest(current),
            "rationale": "Bibliographic fields transcribed from the retained official source.",
            **metadata,
        }
        return self.facade.submit_action({
            "action_type": "research.source.bibliography", "payload": payload, "actor_id": "H",
        })

    def apply_through_confirmation(self, proposal_id):
        apply = self.facade.submit_action({
            "action_type": "state.apply_candidate",
            "payload": {"state_delta_proposal_id": proposal_id}, "actor_id": "H",
        })
        confirmed = self.facade.submit_confirmation({
            "confirmation_request_id": apply["confirmation_request"]["confirmation_request_id"],
            "actor_id": "H",
        })
        self.assertNotIn("decision_request", confirmed)
        return confirmed

    def test_candidate_only_then_existing_confirmation_commits_bibliographic_revision(self):
        before = deepcopy(self.current())
        proposed = self.propose(
            title="Digitalisation in Europe – 2025 edition",
            publisher_or_author="Eurostat",
            publication_or_update_date="2025",
            version_or_revision="2025 edition",
        )
        self.assertEqual(proposed["data"]["bibliography_status"], "CANDIDATE_CREATED")
        self.assertEqual(self.current(), before)
        candidate = proposed["data"]["state_delta_proposal"]
        self.assertEqual(candidate["required_human_decision_kinds"], [])
        revised = candidate["proposed_actions"][0]["payload"]["object"]
        self.assertEqual(revised["revision"], 1)
        for field in ("id", "project_id", "source_type", "canonical_locator", "content_digest", "media_type"):
            self.assertEqual(revised[field], before[field])
        self.assertEqual(self.apply_through_confirmation(proposed["data"]["state_delta_proposal_id"])["status"], "SUCCEEDED")
        current = self.current()
        self.assertEqual(current["revision"], 1)
        self.assertEqual(current["title"], "Digitalisation in Europe – 2025 edition")
        self.assertEqual(current["publisher_or_author"], "Eurostat")
        self.assertEqual(current["publication_or_update_date"], "2025")
        self.assertEqual(
            self.app.state_repository.load_object_revision("source", "SRC-1", 0), before
        )

    def test_stale_empty_unknown_and_binding_smuggling_fail_closed(self):
        base = {
            "source_id": "SRC-1",
            "expected_revision": 0,
            "expected_digest": canonical_digest(self.current()),
            "rationale": "reviewed",
            "title": "Source title",
        }
        for payload in (
            {**base, "expected_revision": 1},
            {**base, "expected_digest": "sha256:" + "0" * 64},
            {**base, "title": ""},
            {**base, "canonical_locator": "https://changed.invalid/"},
            {**base, "content_digest": "sha256:" + "2" * 64},
        ):
            with self.subTest(payload=payload):
                with self.assertRaises((LocalApplicationError, ConversationRuntimeError)):
                    self.facade.submit_action({
                        "action_type": "research.source.bibliography", "payload": payload, "actor_id": "H",
                    })
        self.assertEqual(self.current(), self.original)

    def test_exact_retry_is_noop_and_action_preserves_view_contract(self):
        proposed = self.propose(title="Source title")
        self.apply_through_confirmation(proposed["data"]["state_delta_proposal_id"])
        current = deepcopy(self.current())
        retry = self.propose(title="Source title")
        self.assertEqual(retry["data"]["bibliography_status"], "ALREADY_CURRENT")
        self.assertEqual(self.current(), current)
        row = next(
            x for x in self.facade.list_actions()["actions"]
            if x["action_type"] == "research.source.bibliography"
        )
        self.assertEqual(
            (row["effect"], row["route_category"], row["confirmation_required"]),
            ("read_only", "harness_service", False),
        )
        self.assertIn("view", inspect.signature(type(self.facade).submit_action).parameters)
        current = self.current()
        conversation = self.facade.submit_action({
            "action_type": "research.source.bibliography",
            "payload": {
                "source_id": "SRC-1",
                "expected_revision": current["revision"],
                "expected_digest": canonical_digest(current),
                "rationale": "Public conversation-view bibliography proposal.",
                "publisher_or_author": "Example publisher",
            },
            "actor_id": "H",
        }, view="conversation")
        self.assertEqual(conversation["operation"]["action_type"], "research.source.bibliography")
        self.assertEqual(conversation["candidate"]["content"][0]["content"]["kind"], "source")


class SourceBibliographyPublicationAblationTests(unittest.TestCase):
    setUp = charts.ChartCaptureTests.setUp
    capture = charts.ChartCaptureTests.capture

    def test_misco_visual_blocker_disappears_only_with_complete_source_bibliography(self):
        chart = self.capture()
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp)
            package_root = workspace / ".research-loom/research-packages/RP-CONSUMER"
            package_root.mkdir(parents=True)
            png = base64.b64decode(chart["content"]["value"]["output"]["bytes_base64"])
            origin = rfc8785.dumps(self.package)

            def pin(path, data, media):
                (package_root / path).write_bytes(data)
                return {
                    "path": path, "media_type": media, "byte_length": len(data),
                    "content_digest": "sha256:" + hashlib.sha256(data).hexdigest(),
                }

            image_pin = pin("chart.png", png, "image/png")
            origin_pin = pin("origin.json", origin, "application/json")
            chart["generated_visual"] = {
                "visual_class": "data_visualization",
                "attachment_path": "chart.png",
                "media_type": "image/png",
                "byte_length": len(png),
                "digest": image_pin["content_digest"],
                "generation_context": {
                    "attachment_path": "origin.json",
                    "byte_length": len(origin),
                    "content_digest": origin_pin["content_digest"],
                },
            }
            objects = deepcopy(self.package["resolved_content"]["research_objects"])
            package = {
                "package_id": "RP-CONSUMER",
                "attachments": [image_pin, origin_pin],
                "resolved_content": {
                    "research_objects": objects,
                    "working_material": {"research_exhibits": [chart]},
                },
            }
            inspection = {
                "source_package_document": package,
                "revision": {"sections": [{"exhibit_refs": [chart["exhibit_id"]]}]},
                "publication_profile": {"profile_id": "misco.publication"},
            }
            self.assertEqual(
                prepare_exhibits(inspection, workspace)[chart["exhibit_id"]]["code"],
                "VISUAL_SOURCE_METADATA_REQUIRED",
            )
            src = next(o for o in objects if o["kind"] == "source")
            src.update({
                "title": "Digitalisation in Europe – 2025 edition",
                "publisher_or_author": "Eurostat",
                "publication_or_update_date": "2025",
            })
            self.assertEqual(prepare_exhibits(inspection, workspace)[chart["exhibit_id"]]["kind"], "image")


if __name__ == "__main__":
    unittest.main()
