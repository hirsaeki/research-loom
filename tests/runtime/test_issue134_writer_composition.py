from __future__ import annotations

import json

from plugins.local_application import LocalApplicationFacade
from research_package_acceptance_support import ResearchPackageAcceptanceSupport


class Issue134WriterCompositionRecoveryTests(ResearchPackageAcceptanceSupport):
    @staticmethod
    def _proposal(case, argument_id, finding_id, evidence_id):
        return {
            "purpose": "Plan the selected G1 validation section from authoritative research content.",
            "audience": ["reviewer"],
            "sections": [
                {
                    "section_id": "SEC-FRAME",
                    "order": 1,
                    "heading": "Framing",
                    "reader_question": "What is being investigated?",
                    "purpose": "Frame the research question and available material.",
                    "narrative_stage_refs": ["framing"],
                    "semantic_purpose_refs": ["frame_problem"],
                    "messages": ["State the question and bounded evidence context."],
                    "material_refs": [f"{case['run_id']}:CAP-1"],
                    "exhibit_refs": [case["exhibit_id"]],
                    "gap_refs": ["GAP-1"],
                    "opening_intent": "State the question.",
                    "closing_intent": "Hand off to validation.",
                    "next_section_id": "SEC-G1-05",
                    "prohibited_claims": ["Do not treat candidate material as authoritative."],
                },
                {
                    "section_id": "SEC-G1-05",
                    "order": 2,
                    "heading": "5. 能力と自律性を二軸で統合する",
                    "reader_question": "How are capability and autonomy integrated?",
                    "purpose": "Integrate the authoritative Finding and Argument without invention.",
                    "narrative_stage_refs": ["validation"],
                    "semantic_purpose_refs": ["test_and_qualify"],
                    "messages": ["Use only the supplied authoritative research objects."],
                    "argument_refs": [argument_id],
                    "finding_refs": [finding_id],
                    "evidence_refs": [evidence_id],
                    "previous_section_id": "SEC-FRAME",
                    "detailed": False,
                },
            ],
            "created_by": {
                "type": "human_or_external_llm",
                "instruction": "Use supplied package only.",
            },
        }

    def test_arg4_recovers_sec_g1_05_through_public_research_path(self):
        facade, case = self._prepare_case()
        try:
            pending = facade.submit_action({
                "action_type": "state.apply_candidate",
                "payload": {"state_delta_proposal_id": case["proposal"]["proposal_id"]},
                "actor_id": "HUMAN-I134",
            })
            confirmed = facade.submit_confirmation({
                "confirmation_request_id": pending["confirmation_request"]["confirmation_request_id"],
                "actor_id": "HUMAN-I134",
            })
            self.assertEqual(confirmed["status"], "HUMAN_DECISION_REQUIRED")
            request = confirmed["decision_request"]
            self.assertEqual(
                facade.resolve_human_decision({
                    "request_id": request["request_id"],
                    "request_digest": request["request_digest"],
                    "disposition": "approve_exact",
                    "actor_id": "HUMAN-I134",
                })["status"],
                "RESOLVED",
            )

            state = facade._application.state_repository.load_state_view(
                facade.project_id,
                facade._application.state_repository.load_active_lineage_ref(facade.project_id),
            )
            finding = next(obj for obj in state.effective_objects() if obj.get("kind") == "finding")
            evidence = next(obj for obj in state.effective_objects() if obj.get("kind") == "evidence")
            source = next(obj for obj in state.effective_objects() if obj.get("kind") == "source")
            self.assertEqual(finding["adoption_state"], "approved")

            proposed = facade.submit_action({
                "action_type": "research.argument.propose",
                "payload": {
                    "conclusion": "The adopted Finding supports the bounded validation conclusion.",
                    "warrant": "The Finding and Evidence resolve in the exact current Research Snapshot.",
                    "question_ids": [case["rq_id"]],
                    "finding_ids": [finding["id"]],
                    "evidence_ids": [evidence["id"]],
                    "qualifier": "Within the captured source scope.",
                },
                "actor_id": "HUMAN-I134",
            })
            arg_pending = facade.submit_action({
                "action_type": "state.apply_candidate",
                "payload": {"state_delta_proposal_id": proposed["data"]["state_delta_proposal_id"]},
                "actor_id": "HUMAN-I134",
            })
            committed = facade.submit_confirmation({
                "confirmation_request_id": arg_pending["confirmation_request"]["confirmation_request_id"],
                "actor_id": "HUMAN-I134",
            })
            self.assertEqual(committed["status"], "SUCCEEDED")
            argument_id = proposed["data"]["argument_candidate"]["id"]

            facade.close()
            facade = LocalApplicationFacade.open_workspace(self.workspace)
            reopened = facade._application.state_repository.load_state_view(
                facade.project_id,
                facade._application.state_repository.load_active_lineage_ref(facade.project_id),
            )
            self.assertEqual(
                next(obj for obj in reopened.effective_objects() if obj.get("id") == argument_id)["kind"],
                "argument",
            )

            build_input = {
                **case["build_input"],
                "snapshot_id": reopened.current_snapshot["id"],
                "snapshot_digest": reopened.current_snapshot["content_digest"],
                "lineage_ref": reopened.active_lineage_ref,
                "object_ids": [source["id"], evidence["id"], finding["id"], argument_id],
            }
            built = facade.build_research_package(build_input)["package"]
            package = facade.show_research_package(built["package_id"])["package"]
            self.assertEqual(package["content"]["finding_refs"], [finding["id"]])
            self.assertEqual(package["content"]["argument_refs"], [argument_id])

            composition = facade.capture_writer_composition(
                package["package_id"],
                self._proposal(case, argument_id, finding["id"], evidence["id"]),
            )["composition"]
            self.assertFalse(any(
                item.get("section_id") == "SEC-G1-05"
                and item.get("code") == "WRITER-COMPOSITION-NARRATIVE-UNMET"
                for item in composition["validation"]["diagnostics"]
            ))
            facade.select_writer_composition(
                composition["composition_id"], 1, composition["composition_digest"]
            )
            output = self.root / "issue134-sec-g1-05"
            facade.export_writer_section_input(composition["composition_id"], "SEC-G1-05", output)
            detached = json.loads((output / "section-writer-input.json").read_text(encoding="utf-8"))
            self.assertIn(argument_id, detached["resolved_object_ids"])
            self.assertIn(finding["id"], detached["resolved_object_ids"])
        finally:
            facade.close()
