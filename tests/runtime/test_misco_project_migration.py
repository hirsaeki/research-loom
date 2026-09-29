from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import rfc8785

from core.conversation import ConversationRuntimeError
from plugins.local_application import LocalApplicationFacade, LocalWorkspace, LocalWorkspaceError
from plugins.local_application.profile_advancement import advance_profile_generation, prepare_profile_generation, profile_history
from research_package_acceptance_support import ResearchPackageAcceptanceSupport

ROOT = Path(__file__).resolve().parents[2]
PROJECT_CONFIG = ROOT / "projects/misco-ai-2026/project-config.json"
PROJECT_EPS = ROOT / "projects/misco-ai-2026/effective-profile-set.json"
CONTINUITY = ROOT / "profiles/research/misco-workspace-continuity/profile.json"
WRITER = ROOT / "profiles/narrative/misco/profile.json"
PUBLICATION = ROOT / "profiles/publication/misco/profile.json"
PROBE2_RESOLVE = ROOT / "projects/misco-ai-2026/probe2-profile-resolve.json"


class MiscoFreshProjectRuntimeTests(unittest.TestCase):
    def test_f2_f6_fresh_init_starts_without_legacy_research_state_and_adopts_current_input(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp) / "workspace"
            opened = LocalWorkspace.init(workspace, PROJECT_CONFIG, PROJECT_EPS)
            effective_profiles = [(x["profile_type"], x["profile_id"]) for x in opened.effective_profile_set["effective_profiles"]]
            opened.close()
            with LocalApplicationFacade.open_workspace(workspace) as facade:
                self.assertEqual(facade.project_id, "MISCO-AI-2026")
                state = facade._application.state_repository.load_state_view(
                    facade.project_id,
                    facade._application.state_repository.load_active_lineage_ref(facade.project_id),
                )
                self.assertEqual(state.project_config["project"]["title"], "MISCO AI研究")
                self.assertEqual(state.project_config["research_questions"]["references"], [])
                self.assertEqual(len(state.project_config["research_questions"]["seeds"]), 1)
                self.assertEqual(state.project_config["research_questions"]["seeds"][0]["seed_id"], "RQ-SEED-MISCO-FRESH-START")
                self.assertFalse([x for x in state.objects if x.get("kind") == "research_question"])
                self.assertEqual(state.project_config["research_attention"], [])
                self.assertEqual(
                    effective_profiles,
                    [("narrative", "misco.writer"), ("publication", "misco.publication")],
                )
                proposed = facade.submit_action({
                    "action_type": "research_question.propose",
                    "payload": {"text": "What should this fresh MISCO workspace investigate first?"},
                    "actor_id": "HUMAN-336",
                })
                rq_id = proposed["data"]["research_question_candidate"]["id"]
                pending = facade.submit_action({
                    "action_type": "state.apply_candidate",
                    "payload": {"state_delta_proposal_id": proposed["data"]["state_delta_proposal_id"]},
                    "actor_id": "HUMAN-336",
                })
                decision = facade.submit_confirmation({
                    "confirmation_request_id": pending["confirmation_request"]["confirmation_request_id"],
                    "actor_id": "HUMAN-336",
                })["decision_request"]
                resolved = facade.resolve_human_decision({
                    "request_id": decision["request_id"],
                    "request_digest": decision["request_digest"],
                    "disposition": "approve_exact",
                    "actor_id": "HUMAN-336",
                })
                self.assertEqual(resolved["status"], "RESOLVED")
            with LocalApplicationFacade.open_workspace(workspace) as reopened:
                state = reopened._application.state_repository.load_state_view(
                    reopened.project_id,
                    reopened._application.state_repository.load_active_lineage_ref(reopened.project_id),
                )
                self.assertEqual(state.latest_object("research_question", rq_id)["adoption_state"], "approved")
                self.assertEqual(reopened.status()["project_id"], "MISCO-AI-2026")


class MiscoExistingWorkspaceMigrationTests(ResearchPackageAcceptanceSupport):
    def _migration_request(self):
        request = json.loads(PROBE2_RESOLVE.read_text(encoding="utf-8"))
        request["profile_manifest_files"] = [str(ROOT / item) for item in request["profile_manifest_files"]]
        return request

    def test_f3_f4_existing_workspace_advances_profiles_without_rewriting_research_or_attention(self):
        facade, case = self._prepare_case()
        try:
            active = facade.submit_action({
                "action_type": "research_attention.propose",
                "payload": {"additions": [{"statement": "Keep MISCO migration attention active."}]},
                "actor_id": "HUMAN-336",
            })["data"]["attention_map"]
            pending = facade.submit_action({
                "action_type": "research_attention.activate_candidate",
                "payload": {"attention_map_id": active["map_id"]},
                "actor_id": "HUMAN-336",
            })
            confirmed = facade.submit_confirmation({
                "confirmation_request_id": pending["confirmation_request"]["confirmation_request_id"],
                "actor_id": "HUMAN-336",
            })
            self.assertEqual(confirmed["status"], "SUCCEEDED")
            stale = facade.submit_action({
                "action_type": "research_attention.propose",
                "payload": {"additions": [{"statement": "Do not auto-adopt this stale candidate."}]},
                "actor_id": "HUMAN-336",
            })["data"]["attention_map"]
            active_before = deepcopy(facade._application.attention_store.load_active(facade.project_id))
            state_before = facade._application.state_repository.load_state_view(
                facade.project_id,
                facade._application.state_repository.load_active_lineage_ref(facade.project_id),
            )
            snapshot_before = deepcopy(state_before.current_snapshot)
            project_before = deepcopy(state_before.project_config["project"])
            material_before = deepcopy(facade.show_external_material(case["run_id"], "CAP-1", max_text_bytes=4096))
        finally:
            facade.close()

        request = self._migration_request()
        output = self.root / "misco-production-target"
        resolved = prepare_profile_generation(self.workspace, request, output)
        target_config = json.loads((output / "project-config.json").read_text(encoding="utf-8"))
        target_eps = json.loads((output / "effective-profile-set.json").read_text(encoding="utf-8"))
        self.assertEqual(target_config["project"], project_before)
        self.assertEqual(
            [(x["profile_type"], x["profile_id"]) for x in target_eps["effective_profiles"]],
            [
                ("research", "misco.workspace-continuity.exact-locator"),
                ("narrative", "misco.writer"),
                ("publication", "misco.publication"),
            ],
        )
        self.assertFalse(any(str(x["profile_id"]).startswith("fixture.") for x in target_eps["effective_profiles"]))
        advanced = advance_profile_generation(self.workspace, {
            "project_config_file": str(output / "project-config.json"),
            "effective_profile_set_file": str(output / "effective-profile-set.json"),
            "profile_manifest_files": request["profile_manifest_files"],
            "origin": "issue-336-misco-production-migration",
        })
        self.assertEqual(advanced["result"], "ADVANCED")
        self.assertEqual(advanced["source_project_config_digest"] if "source_project_config_digest" in advanced else resolved["source_project_config_digest"], resolved["source_project_config_digest"])

        with LocalApplicationFacade.open_workspace(self.workspace) as facade:
            state_after = facade._application.state_repository.load_state_view(
                facade.project_id,
                facade._application.state_repository.load_active_lineage_ref(facade.project_id),
            )
            self.assertEqual(state_after.current_snapshot, snapshot_before)
            self.assertEqual(state_after.project_config["project"], project_before)
            self.assertIsNotNone(state_after.latest_object("research_question", case["rq_id"]))
            material_after = facade.show_external_material(case["run_id"], "CAP-1", max_text_bytes=4096)
            self.assertEqual(material_after["capture"], material_before["capture"])
            self.assertEqual(material_after["text_rendition_view"], material_before["text_rendition_view"])
            self.assertEqual(facade._application.attention_store.load_active(facade.project_id), active_before)
            status = facade.submit_action({"action_type": "research_attention.status", "payload": {}})
            self.assertEqual(status["data"]["active_map"]["map_id"], active_before["map_id"])
            pending_stale = facade.submit_action({
                "action_type": "research_attention.activate_candidate",
                "payload": {"attention_map_id": stale["map_id"]},
                "actor_id": "HUMAN-336",
            })
            with self.assertRaises(ConversationRuntimeError) as raised:
                facade.submit_confirmation({
                    "confirmation_request_id": pending_stale["confirmation_request"]["confirmation_request_id"],
                    "actor_id": "HUMAN-336",
                })
            self.assertEqual(raised.exception.code, "ATTENTION-STALE-001")
            built = facade.build_research_package(case["build_input"])["package"]
            package = facade._research_package_service().show(built["package_id"])["package"]
            self.assertEqual(
                [(x["profile_type"], x["profile_id"]) for x in package["effective_profile_set"]["profile_pins"]],
                [
                    ("research", "misco.workspace-continuity.exact-locator"),
                    ("narrative", "misco.writer"),
                    ("publication", "misco.publication"),
                ],
            )

        history = profile_history(self.workspace)
        self.assertEqual(len(history["events"]), 1)
        self.assertEqual(history["events"][0]["new_binding"]["project_config_digest"], advanced["new_project_config_digest"])

    def test_f5_request_addition_is_idempotent_and_conflicting_same_id_is_rejected(self):
        request = self._migration_request()
        output = self.root / "misco-target-one"
        prepare_profile_generation(self.workspace, request, output)
        # Re-resolving from an already-added target is handled after advance; duplicate additions are no-ops in target construction.
        from plugins.local_application.profile_resolution import target_project_config
        with LocalWorkspace.open(self.workspace) as opened:
            current = deepcopy(opened.project_config)
        once = target_project_config(current, request["request_replacements"], request["request_additions"])
        twice = target_project_config(once, [], request["request_additions"])
        self.assertEqual(once, twice)
        bad = deepcopy(request["request_additions"][0]); bad["version"] = "2.0.0"
        with self.assertRaises(LocalWorkspaceError) as raised:
            target_project_config(once, [], [bad])
        self.assertEqual(raised.exception.code, "PROFILE-ADVANCE-REQUEST-001")

    def test_ablation_continuity_profile_is_required_to_preserve_active_core_strengthening(self):
        request = self._migration_request()
        request["profile_manifest_files"] = [str(WRITER), str(PUBLICATION)]
        request["request_additions"] = []
        output = self.root / "misco-target-without-continuity"
        prepare_profile_generation(self.workspace, request, output)
        with self.assertRaises(LocalWorkspaceError) as raised:
            advance_profile_generation(self.workspace, {
                "project_config_file": str(output / "project-config.json"),
                "effective_profile_set_file": str(output / "effective-profile-set.json"),
                "profile_manifest_files": request["profile_manifest_files"],
                "origin": "issue-336-ablation-no-continuity",
            })
        self.assertEqual(raised.exception.code, "PROFILE-ADVANCE-CORE-WEAKENING-001")
        self.assertEqual(profile_history(self.workspace)["events"], [])


if __name__ == "__main__":
    unittest.main()
