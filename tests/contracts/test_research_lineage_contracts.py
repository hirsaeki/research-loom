from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator, FormatChecker, ValidationError
import yaml

from research_lineage_oracle import (
    ERROR_IDS,
    canonical_digest,
    comparison_error,
    conversation_error,
    digest_error,
    downstream_error,
    fork_plan_error,
    lineage_error,
    replay_error,
    revision_collision_error,
    selection_error,
    virtual_real_error,
)

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "core/packages/research-lineage"
FIX = ROOT / "core/fixtures/research-lineage/valid/generic-research-lineage-fixtures.json"
BINDING_FIX = (
    ROOT
    / "core/fixtures/research-lineage/valid/generic-research-package-lineage-binding.json"
)
CONV = ROOT / "core/fixtures/conversation/valid/research-lineage-routing.json"
WORK = ROOT / "core/packages/work-conversation.schema.json"


def load(path: Path) -> dict:
    """Load a UTF-8 JSON fixture or schema."""
    return json.loads(path.read_text(encoding="utf-8"))


def refresh(doc: dict, field: str) -> None:
    """Refresh one canonical content digest after a deliberate mutation."""
    doc[field] = canonical_digest(doc, field)


class ResearchLineageContractsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        """Load canonical schemas, fixtures, semantics, and validators."""
        cls.schema = load(PKG / "research-lineage.schema.json")
        cls.binding_schema = load(PKG / "research-package-lineage-binding.schema.json")
        cls.f = load(FIX)
        cls.binding = load(BINDING_FIX)
        cls.route = load(CONV)
        cls.work_schema = load(WORK)
        cls.sem = yaml.safe_load(
            (PKG / "research-lineage-semantics.yaml").read_text(encoding="utf-8")
        )
        cls.validator = Draft202012Validator(
            cls.schema, format_checker=FormatChecker()
        )

    def validate(self, doc: dict) -> None:
        """Validate one canonical lineage object."""
        self.validator.validate(doc)

    def test_schema_and_valid_fixtures(self) -> None:
        """Validate representative primary, fork, recovery, replay, and compare objects."""
        Draft202012Validator.check_schema(self.schema)
        for key in (
            "primary_lineage",
            "exploratory_lineage",
            "recovery_lineage",
            "fork_proposal",
            "fork_plan",
            "impact_assessment",
            "recovery_request",
            "replay_plan",
            "interrupted_replay_plan",
            "active_lineage_selection",
            "lineage_comparison",
        ):
            self.validate(self.f[key])

        Draft202012Validator(self.binding_schema).validate(self.binding)
        Draft202012Validator(
            self.work_schema, format_checker=FormatChecker()
        ).validate(self.route["action_proposal"])

    def test_error_catalog_exact(self) -> None:
        """Keep semantic error catalog and executable oracle exact."""
        self.assertEqual({item["id"] for item in self.sem["errors"]}, ERROR_IDS)

    def test_all_digest_bearing_fixtures_and_tamper_detection(self) -> None:
        """Validate every canonical fixture digest and reject stale content digests."""
        keys = (
            "primary_lineage",
            "exploratory_lineage",
            "recovery_lineage",
            "fork_proposal",
            "fork_plan",
            "impact_assessment",
            "recovery_request",
            "replay_plan",
            "interrupted_replay_plan",
            "active_lineage_selection",
            "lineage_comparison",
        )
        for key in keys:
            with self.subTest(key=key):
                document = self.f[key]
                self.assertIsNone(digest_error(document))
                tampered = deepcopy(document)
                if "rationale" in tampered:
                    tampered["rationale"] += " tampered"
                elif "reason" in tampered:
                    tampered["reason"] += " tampered"
                elif "replay_actions" in tampered:
                    tampered["replay_actions"].append("tampered")
                elif "items" in tampered:
                    tampered["items"][0]["object_ref"] = "TAMPERED"
                elif "uncertainty" in tampered:
                    tampered["uncertainty"] += " tampered"
                elif "replay_start_boundary" in tampered:
                    tampered["replay_start_boundary"] = "TAMPERED"
                elif "impact_summary_ref" in tampered:
                    tampered["impact_summary_ref"] = "TAMPERED"
                else:
                    tampered["changes"][0]["object_ref"] = "TAMPERED"
                self.assertEqual(digest_error(tampered), "RL-DIGEST-001")

    def test_parent_and_child_continue_independently(self) -> None:
        """A historical fork must not move the parent lineage head."""
        parent = self.f["primary_lineage"]
        child = self.f["exploratory_lineage"]
        self.assertIsNone(lineage_error(parent))
        self.assertIsNone(lineage_error(child, parent))
        self.assertNotEqual(parent["current_snapshot"], child["current_snapshot"])

    def test_lineage_parent_execution_mode_is_part_of_firewall(self) -> None:
        """Reject a REAL child when its known parent lineage is VIRTUAL."""
        parent = deepcopy(self.f["primary_lineage"])
        parent["execution_mode"] = "virtual"
        parent["baseline_snapshot"]["execution_mode"] = "virtual"
        parent["current_snapshot"]["execution_mode"] = "virtual"
        refresh(parent, "lineage_digest")
        self.assertEqual(
            lineage_error(self.f["exploratory_lineage"], parent),
            "RL-VIRTUAL-REAL-001",
        )

    def test_treatments_and_invalidated_leak(self) -> None:
        """Require explicit treatments and prevent invalidated state from leaking."""
        fixture = self.f
        self.assertIsNone(
            fork_plan_error(
                fixture["fork_plan"],
                fixture["fork_proposal"],
                fixture["primary_lineage"],
                {"RQ-1", "METHOD-2"},
            )
        )

        missing_decision = deepcopy(fixture["fork_plan"])
        missing_decision["treatments"][1].pop("human_decision_ref")
        refresh(missing_decision, "plan_digest")
        self.assertEqual(
            fork_plan_error(
                missing_decision,
                fixture["fork_proposal"],
                fixture["primary_lineage"],
                set(),
            ),
            "RL-HUMAN-DECISION-001",
        )

        unused_decision = deepcopy(fixture["fork_plan"])
        unused_decision["required_human_decision_refs"].append("HD-UNUSED")
        refresh(unused_decision, "plan_digest")
        self.assertEqual(
            fork_plan_error(
                unused_decision,
                fixture["fork_proposal"],
                fixture["primary_lineage"],
                set(),
            ),
            "RL-HUMAN-DECISION-001",
        )

        incomplete = deepcopy(fixture["fork_plan"])
        incomplete["treatments"].pop()
        refresh(incomplete, "plan_digest")
        self.assertEqual(
            fork_plan_error(
                incomplete,
                fixture["fork_proposal"],
                fixture["primary_lineage"],
                set(),
            ),
            "RL-TREATMENT-001",
        )

        wrong_parent = deepcopy(fixture["fork_plan"])
        wrong_parent["parent_lineage_ref"] = "LIN-OTHER"
        refresh(wrong_parent, "plan_digest")
        self.assertEqual(
            fork_plan_error(
                wrong_parent,
                fixture["fork_proposal"],
                fixture["primary_lineage"],
                set(),
            ),
            "RL-PARENT-001",
        )

        stale_pin = deepcopy(fixture["fork_plan"])
        stale_pin["exact_input_pins"][0]["content_digest"] = "sha256:" + "9" * 64
        refresh(stale_pin, "plan_digest")
        self.assertEqual(
            fork_plan_error(
                stale_pin,
                fixture["fork_proposal"],
                fixture["primary_lineage"],
                set(),
            ),
            "RL-CONFIG-PROFILE-PIN-001",
        )

        self.assertEqual(
            fork_plan_error(
                fixture["fork_plan"],
                fixture["fork_proposal"],
                fixture["primary_lineage"],
                {"FND-OLD"},
            ),
            "RL-INVALIDATED-LEAK-001",
        )

    def test_stale_baseline_digest(self) -> None:
        """Fail closed when the approved historical baseline pin changes."""
        proposal = deepcopy(self.f["fork_proposal"])
        proposal["baseline_snapshot"]["content_digest"] = "sha256:" + "f" * 64
        refresh(proposal, "proposal_digest")
        self.assertEqual(
            fork_plan_error(
                self.f["fork_plan"],
                proposal,
                self.f["primary_lineage"],
                set(),
            ),
            "RL-BASELINE-STALE-001",
        )

    def test_object_identity_revision_collision(self) -> None:
        """Reject conflicting content for one kind/id/revision identity."""
        records = [
            {
                "kind": "finding",
                "id": "FND-1",
                "revision": 2,
                "content_digest": "sha256:" + "1" * 64,
            },
            {
                "kind": "finding",
                "id": "FND-1",
                "revision": 2,
                "content_digest": "sha256:" + "2" * 64,
            },
        ]
        self.assertEqual(
            revision_collision_error(records), "RL-OBJECT-IDENTITY-001"
        )

    def test_replay_uses_new_runs_contexts_and_handoffs(self) -> None:
        """Replay must stay in-project and allocate new Runs, Context Packs, and Handoffs."""
        fixture = self.f
        source = fixture["primary_lineage"]
        target = fixture["recovery_lineage"]
        self.assertIsNone(
            replay_error(fixture["replay_plan"], fixture["replay_execution"], source, target)
        )

        execution = deepcopy(fixture["replay_execution"])
        execution["target_new_run_ids"] = ["RUN-014"]
        self.assertEqual(
            replay_error(fixture["replay_plan"], execution, source, target),
            "RL-REPLAY-RUN-ID-001",
        )

        execution = deepcopy(fixture["replay_execution"])
        execution["target_handoff_refs"] = ["HANDOFF-014"]
        self.assertEqual(
            replay_error(fixture["replay_plan"], execution, source, target),
            "RL-REPLAY-HANDOFF-001",
        )

        execution = deepcopy(fixture["replay_execution"])
        execution["context_pack_policy"] = "reuse_old"
        self.assertEqual(
            replay_error(fixture["replay_plan"], execution, source, target),
            "RL-REPLAY-CONTEXT-001",
        )

        cross_project = deepcopy(fixture["replay_plan"])
        cross_project["project_ref"] = "PROJ-OTHER"
        refresh(cross_project, "plan_digest")
        self.assertEqual(
            replay_error(cross_project, fixture["replay_execution"], source, target),
            "RL-PROJECT-MISMATCH-001",
        )

    def test_active_selection_and_read_only_comparison(self) -> None:
        """Separate fork creation from active selection and keep compare read-only."""
        self.assertIsNone(selection_error(self.f["active_lineage_selection"]))
        selection = deepcopy(self.f["active_lineage_selection"])
        selection["authority_confirmed"] = False
        refresh(selection, "selection_digest")
        self.assertEqual(selection_error(selection), "RL-ACTIVE-SELECTION-001")

        self.assertIsNone(comparison_error(self.f["lineage_comparison"]))
        comparison = deepcopy(self.f["lineage_comparison"])
        comparison["automatic_adoption_performed"] = True
        refresh(comparison, "comparison_digest")
        self.assertEqual(comparison_error(comparison), "RL-AUTO-MERGE-001")

        comparison = deepcopy(self.f["lineage_comparison"])
        comparison["read_only"] = False
        refresh(comparison, "comparison_digest")
        self.assertEqual(
            comparison_error(comparison), "RL-COMPARISON-READONLY-001"
        )

    def test_writer_publication_downstream_staleness(self) -> None:
        """Keep old packages historical while marking them stale against a new active line."""
        fixture = self.f
        self.assertIsNone(
            downstream_error(
                self.binding,
                fixture["exploratory_lineage"],
                fixture["exploratory_lineage"]["current_snapshot"],
            )
        )
        self.assertEqual(
            downstream_error(
                self.binding,
                fixture["primary_lineage"],
                fixture["primary_lineage"]["current_snapshot"],
            ),
            "RL-DOWNSTREAM-STALE-001",
        )

    def test_virtual_to_real_fork_promotion_forbidden(self) -> None:
        """Preserve PR17 by refusing VIRTUAL-to-REAL through lineage fork semantics."""
        parent = deepcopy(self.f["primary_lineage"])
        parent["execution_mode"] = "virtual"
        parent["baseline_snapshot"]["execution_mode"] = "virtual"
        parent["current_snapshot"]["execution_mode"] = "virtual"
        refresh(parent, "lineage_digest")
        self.assertEqual(
            virtual_real_error(parent, self.f["exploratory_lineage"]),
            "RL-VIRTUAL-REAL-001",
        )
        self.assertEqual(
            lineage_error(self.f["exploratory_lineage"], parent),
            "RL-VIRTUAL-REAL-001",
        )

    def test_conversation_routes_to_proposal_not_decision(self) -> None:
        """PR10 prose may propose Fork/Recovery but cannot be the Human Decision."""
        self.assertIsNone(conversation_error(self.route))
        self.assertEqual(
            self.route["action_proposal"]["route"]["service_id"],
            "research-lineage.propose",
        )

    def test_fail_closed_replay_schema(self) -> None:
        """Reject Replay Plans that omit project identity or permit old Handoff reuse."""
        replay = deepcopy(self.f["replay_plan"])
        replay.pop("project_ref")
        with self.assertRaises(ValidationError):
            self.validate(replay)

        replay = deepcopy(self.f["replay_plan"])
        replay["handoff_copy_allowed"] = True
        with self.assertRaises(ValidationError):
            self.validate(replay)


if __name__ == "__main__":
    unittest.main()
