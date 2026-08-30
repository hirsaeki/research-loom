from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import rfc8785

from plugins.local_application import LocalApplicationFacade


ROOT = Path(__file__).resolve().parents[2]
PROJECT_FIXTURE = ROOT / "projects/fixtures/valid/generic-project-config.json"
PROFILE_FIXTURE = ROOT / "profiles/fixtures/valid/effective-profile-set.json"


def _configuration_digest(config: dict) -> str:
    value = deepcopy(config)
    value.pop("configuration_digest", None)
    return "sha256:" + hashlib.sha256(rfc8785.dumps(value)).hexdigest()


def _write_inputs(root: Path) -> tuple[Path, Path]:
    config = json.loads(PROJECT_FIXTURE.read_text(encoding="utf-8"))
    config["research_questions"]["references"] = []
    for attention in config["research_attention"]:
        attention.pop("related_question_ids", None)
    config["configuration_digest"] = _configuration_digest(config)

    config_path = root / "project-config.json"
    profiles_path = root / "effective-profile-set.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    profiles_path.write_text(PROFILE_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    return config_path, profiles_path


def _adopt_research_question(facade: LocalApplicationFacade) -> str:
    proposed = facade.submit_action({
        "action_type": "research_question.propose",
        "payload": {
            "text": "Which current conditions materially shape the research target?",
            "acceptance_criteria": ["Relevant current conditions can be compared."],
            "scope_limits": ["Do not infer beyond the gathered evidence."],
            "derived_from_seed_ids": ["RQ-SEED-001"],
        },
        "actor_id": "HUMAN-PR34",
    })
    rq_id = proposed["data"]["research_question_candidate"]["id"]
    pending = facade.submit_action({
        "action_type": "state.apply_candidate",
        "payload": {"state_delta_proposal_id": proposed["data"]["state_delta_proposal_id"]},
        "actor_id": "HUMAN-PR34",
    })
    decision = facade.submit_confirmation({
        "confirmation_request_id": pending["confirmation_request"]["confirmation_request_id"],
        "actor_id": "HUMAN-PR34",
    })["decision_request"]
    resolved = facade.resolve_human_decision({
        "request_id": decision["request_id"],
        "request_digest": decision["request_digest"],
        "disposition": "approve_exact",
        "actor_id": "HUMAN-PR34",
    })
    assert resolved["status"] == "RESOLVED"
    return rq_id


def _activate_attention(facade: LocalApplicationFacade, rq_id: str) -> dict:
    candidate = facade.submit_action({
        "action_type": "research_attention.propose",
        "payload": {
            "additions": [{
                "statement": "Keep counterevidence and boundary conditions visible during Desktop Research.",
                "related_question_ids": [rq_id],
            }],
        },
    })["data"]["attention_map"]
    pending = facade.submit_action({
        "action_type": "research_attention.activate_candidate",
        "payload": {"attention_map_id": candidate["map_id"]},
        "actor_id": "HUMAN-PR34",
    })
    committed = facade.submit_confirmation({
        "confirmation_request_id": pending["confirmation_request"]["confirmation_request_id"],
        "actor_id": "HUMAN-PR34",
    })
    assert committed["status"] == "SUCCEEDED"
    return candidate


class CurrentDesktopResearchContextRegressionTests(unittest.TestCase):
    def test_canonical_profile_set_rq_and_active_attention_prepare_desktop_run(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config_path, profiles_path = _write_inputs(root)
            workspace = root / "workspace"
            initialized = LocalApplicationFacade.initialize_workspace(workspace, config_path, profiles_path)
            self.assertEqual(initialized["status"], "INITIALIZED")

            with LocalApplicationFacade.open_workspace(workspace) as facade:
                rq_id = _adopt_research_question(facade)
                attention = _activate_attention(facade, rq_id)
                app = facade._application
                lineage = app.state_repository.load_active_lineage_ref(facade.project_id)
                before = app.state_repository.load_state_view(facade.project_id, lineage)
                snapshot_before = deepcopy(before.current_snapshot)
                rq_before = deepcopy(before.latest_object("research_question", rq_id))
                decisions_before = deepcopy(list(before.decisions))
                activation_count_before = len(app.attention_store.activation_events(facade.project_id))

                result = facade.submit_action({
                    "action_type": "desktop_research.investigate",
                    "payload": {"question_id": rq_id, "purpose": "Investigate the adopted Research Question."},
                })

                self.assertEqual(result["status"], "CAPABILITY_EXECUTION_PREPARED")
                materialization = app.conversation_store.load_materialization(result["proposal"]["proposal_id"])
                context = materialization["context_pack"]
                self.assertEqual(context["question_ids"], [rq_id])
                self.assertEqual(context["research_object_references"], [{
                    "kind": "research_question",
                    "id": rq_id,
                    "revision": rq_before["revision"],
                }])
                self.assertEqual(context["research_attention"], attention["items"])

                canonical_profiles = json.loads(PROFILE_FIXTURE.read_text(encoding="utf-8"))
                projected = context["pins"]["effective_profile_set"]
                self.assertEqual(
                    set(projected),
                    {"schema_version", "core_contracts", "profile_pins", "content_digest"},
                )
                self.assertEqual(projected["schema_version"], canonical_profiles["schema_version"])
                self.assertEqual(projected["core_contracts"], canonical_profiles["core_contracts"])
                self.assertEqual(projected["profile_pins"], [
                    {
                        key: profile[key]
                        for key in ("profile_id", "profile_type", "profile_version", "manifest_sha256")
                    }
                    for profile in canonical_profiles["effective_profiles"]
                ])
                self.assertEqual(projected["content_digest"], before.effective_profile_set_digest)

                after = app.state_repository.load_state_view(facade.project_id, lineage)
                self.assertEqual(after.current_snapshot, snapshot_before)
                self.assertEqual(after.latest_object("research_question", rq_id), rq_before)
                self.assertEqual(list(after.decisions), decisions_before)
                self.assertEqual(
                    len(app.attention_store.activation_events(facade.project_id)),
                    activation_count_before,
                )
                active = facade.submit_action({"action_type": "research_attention.status", "payload": {}})
                self.assertEqual(active["data"]["active_map"]["map_id"], attention["map_id"])


if __name__ == "__main__":
    unittest.main()
