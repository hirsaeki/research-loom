from __future__ import annotations

from copy import deepcopy
from unittest.mock import patch

from plugins.local_application import LocalApplicationFacade
from plugins.local_application.material_reacquisition_facade import RetrievedMaterial
from plugins.desktop_research.submission import with_context_extension_digest
from research_package_acceptance_support import ResearchPackageAcceptanceSupport
import test_external_desktop_research_intake as intake


class Issue127MultiMaterialContinuationTests(ResearchPackageAcceptanceSupport):
    @staticmethod
    def _snapshot(facade):
        repo = facade._application.state_repository
        return deepcopy(
            repo.load_state_view(
                facade.project_id, repo.load_active_lineage_ref(facade.project_id)
            ).current_snapshot
        )

    @staticmethod
    def _remove_producer_candidate(facade, proposal_id: str) -> None:
        facade._application.conversation_store._db.execute(
            "DELETE FROM state_delta_proposals WHERE proposal_id=?", (proposal_id,)
        )

    def _prepare_three_capture_case(self):
        facade = LocalApplicationFacade.open_workspace(self.workspace)
        rq_id = intake.adopt_rq(facade)
        run_id = facade.submit_action(
            {
                "action_type": "desktop_research.investigate",
                "payload": {"question_id": rq_id, "purpose": "paired continuation acceptance"},
            }
        )["run_id"]

        captures: dict[str, dict] = {}
        for index, capture_id in enumerate(("CAP-1", "CAP-2", "CAP-3"), start=1):
            attempt_id = f"ATT-{index}"
            facade.start_external_retrieval_attempt(
                run_id,
                {
                    "attempt_id": attempt_id,
                    "strategy": f"source {index} search",
                    "coverage_dimension_ids": ["COV-SUPPORT"],
                    "target_locator": f"https://example.test/source-{index}",
                },
            )
            raw = self.workspace / f"captures/raw/source-{index}.html"
            text = self.workspace / f"captures/text/source-{index}.txt"
            raw.parent.mkdir(parents=True, exist_ok=True)
            text.parent.mkdir(parents=True, exist_ok=True)
            if index == 1:
                text_body = "Source A contains the exact supporting excerpt used here."
            else:
                text_body = f"Source {index} retained material."
            raw.write_bytes(f"<html><body>{text_body}</body></html>".encode())
            text.write_text(text_body, encoding="utf-8")
            captures[capture_id] = facade.capture_external_source(
                run_id,
                {
                    "capture_id": capture_id,
                    "source_category": "other",
                    "exact_locator": f"https://example.test/source-{index}#section",
                    "acquired_at": f"2026-09-07T00:00:0{index}Z",
                    "original_file": f"captures/raw/source-{index}.html",
                    "original_media_type": "text/html",
                    "text_rendition_file": f"captures/text/source-{index}.txt",
                },
            )["capture"]
            facade.complete_external_retrieval_attempt(
                run_id,
                {
                    "attempt_id": attempt_id,
                    "outcome": "source_captured",
                    "resulting_capture_id": capture_id,
                },
            )

        facade.start_external_retrieval_attempt(
            run_id,
            {
                "attempt_id": "ATT-4",
                "strategy": "counter search",
                "coverage_dimension_ids": ["COV-COUNTER"],
            },
        )
        facade.complete_external_retrieval_attempt(
            run_id,
            {"attempt_id": "ATT-4", "outcome": "no_relevant_source"},
        )

        handoff, extension = intake.golden_submission(
            facade._application, run_id, captures["CAP-1"]
        )
        for index, capture_id in enumerate(("CAP-2", "CAP-3"), start=2):
            capture = captures[capture_id]
            handoff["outputs"]["source_captures"].append(
                {
                    "capture_id": capture_id,
                    "origin": {
                        "origin_type": "acquired_source",
                        "acquisition_locator": f"https://example.test/source-{index}",
                    },
                    "locator": f"https://example.test/source-{index}#section",
                    "content_digest": capture["original_capture"]["content_digest"],
                }
            )
            extension["source_capture_details"].append(deepcopy(capture))
        intake.refresh(handoff, "handoff_digest")
        extension["handoff_binding"]["handoff_digest"] = handoff["handoff_digest"]
        extension["search_trace"] = {
            "entries": [
                {
                    "trace_entry_id": f"ATT-{index}",
                    "strategy": f"source {index} search",
                    "coverage_dimension_ids": ["COV-SUPPORT"],
                    "outcome": "source_captured",
                    "related_handoff_output_ids": ["EVC-1"] if index == 1 else [],
                    "source_capture_ids": [f"CAP-{index}"],
                }
                for index in (1, 2, 3)
            ]
            + [
                {
                    "trace_entry_id": "ATT-4",
                    "strategy": "counter search",
                    "coverage_dimension_ids": ["COV-COUNTER"],
                    "outcome": "no_relevant_source",
                    "related_handoff_output_ids": ["OBS-NULL", "GAP-1"],
                    "source_capture_ids": [],
                }
            ],
            "unsuccessful_entry_ids": ["ATT-4"],
        }
        for dimension in extension["coverage_assessment"]["dimensions"]:
            if dimension["dimension_id"] == "COV-SUPPORT":
                dimension["trace_entry_ids"] = ["ATT-1", "ATT-2", "ATT-3"]
            elif dimension["dimension_id"] == "COV-COUNTER":
                dimension["trace_entry_ids"] = ["ATT-4"]
        extension = with_context_extension_digest(extension)
        collected = facade.collect_external(
            run_id, {"handoff": handoff, "extension": extension}
        )
        self.assertEqual(collected["execution_result"]["run"]["status"], "COMPLETED")
        return facade, {
            "run_id": run_id,
            "proposal_id": collected["execution_result"]["state_delta_proposal"]["proposal_id"],
        }

    @staticmethod
    def _remove_pair_bytes(facade, run_id: str, capture_id: str):
        store = facade._application.execution_store
        pair = {
            item.role: item
            for item in store.artifacts_for(run_id)
            if item.provenance.get("capture_id") == capture_id
        }
        original = pair["desktop_research.original_capture"]
        rendition = pair["desktop_research.text_rendition"]
        store._locator_path(original.storage_locator, original.digest).unlink()
        store._locator_path(rendition.storage_locator, rendition.digest).unlink()
        return original, rendition

    def _reacquire_original(self, facade, run_id: str, capture_id: str, index: int):
        changed = (
            f"<html><body><p>{'Source A contains the exact supporting excerpt used here.' if index == 1 else f'Source {index} retained material.'}</p>"
            f"<p>new version {index}</p></body></html>"
        ).encode()
        with patch(
            "plugins.local_application.material_reacquisition_facade._retrieve_exact_locator",
            return_value=RetrievedMaterial(
                changed,
                "text/html",
                f"https://example.test/source-{index}#section",
                "fixture-http",
                200,
            ),
        ):
            data = facade.submit_action(
                {
                    "action_type": "desktop_research.material.reacquire",
                    "payload": {
                        "historical_run_id": run_id,
                        "capture_id": capture_id,
                        "kind": "original",
                    },
                }
            )["data"]
        self.assertEqual(data["status"], "NEW_MATERIAL_VERSION")
        self.assertEqual(data["new_material_kind"], "original")
        return data

    def test_explicit_group_can_expand_after_failed_partial_group(self):
        facade, case = self._prepare_three_capture_case()
        try:
            historical_before = facade._application.execution_store.load_run(case["run_id"])
            state_before = self._snapshot(facade)
            self._remove_producer_candidate(facade, case["proposal_id"])
            old_pairs = {
                capture_id: self._remove_pair_bytes(facade, case["run_id"], capture_id)
                for capture_id in ("CAP-1", "CAP-2", "CAP-3")
            }
            reacquired = {
                capture_id: self._reacquire_original(facade, case["run_id"], capture_id, index)
                for index, capture_id in enumerate(("CAP-1", "CAP-2", "CAP-3"), start=1)
            }

            first = reacquired["CAP-1"]["reacquisition_run_id"]
            second = reacquired["CAP-2"]["reacquisition_run_id"]
            third = reacquired["CAP-3"]["reacquisition_run_id"]

            # Control/ablation: single-target continuation remains fail-closed
            # because it cannot fabricate the other missing historical captures.
            single = facade.submit_action(
                {
                    "action_type": "desktop_research.material.continue_new_version",
                    "payload": {"reacquisition_run_id": first},
                }
            )
            self.assertEqual(single["status"], "FAILED")
            self.assertIn("required paired capture material is unavailable", single["issues"][0]["message"])

            # A too-small explicit group also fails, but must not permanently
            # poison the same material Runs: the operator can add the missing
            # verified replacement and retry as a new group.
            partial = facade.submit_action(
                {
                    "action_type": "desktop_research.material.continue_new_version",
                    "payload": {
                        "reacquisition_run_id": first,
                        "paired_reacquisition_run_ids": [second],
                    },
                }
            )
            self.assertEqual(partial["status"], "FAILED")
            self.assertIn("required paired capture material is unavailable: CAP-3", partial["issues"][0]["message"])

            grouped = facade.submit_action(
                {
                    "action_type": "desktop_research.material.continue_new_version",
                    "payload": {
                        "reacquisition_run_id": first,
                        "paired_reacquisition_run_ids": [second, third],
                    },
                }
            )
            self.assertEqual(grouped["status"], "SUCCEEDED")
            data = grouped["data"]
            self.assertEqual(data["status"], "COMPLETED")
            self.assertTrue(data["candidate_only"])
            self.assertFalse(data["research_state_mutation_performed"])
            self.assertEqual(set(data["reacquisition_run_ids"]), {first, second, third})

            store = facade._application.execution_store
            self.assertEqual(store.load_run(case["run_id"]), historical_before)
            self.assertEqual(self._snapshot(facade), state_before)
            for original, rendition in old_pairs.values():
                self.assertEqual(store.diagnose_artifact_content(original.artifact_id)["status"], "content_missing")
                self.assertEqual(store.diagnose_artifact_content(rendition.artifact_id)["status"], "content_missing")

            new_run = store.load_run(data["new_run_id"])
            self.assertEqual(new_run.status.value, "COMPLETED")
            artifacts = store.artifacts_for(new_run.run_id)
            replacement_originals = {
                item.provenance.get("historical_capture_id"): item
                for item in artifacts
                if item.role == "desktop_research.original_capture"
            }
            self.assertEqual(set(replacement_originals), {"CAP-1", "CAP-2", "CAP-3"})
            for capture_id in ("CAP-1", "CAP-2", "CAP-3"):
                item = replacement_originals[capture_id]
                expected = reacquired[capture_id]
                self.assertEqual(item.digest, expected["actual_digest"])
                self.assertEqual(item.size, expected["actual_size"])
                self.assertEqual(item.provenance["reacquisition_run_id"], expected["reacquisition_run_id"])
                self.assertEqual(item.provenance["relation"], "new_material_version_group_continuation")

            shown = facade.show_run(data["new_run_id"])["new_material_continuation"]
            self.assertEqual(shown["status"], "completed")
            self.assertEqual(shown["mode"], "paired")
            self.assertEqual(set(shown["reacquisition_run_ids"]), {first, second, third})
            self.assertEqual(
                {item["historical_capture_id"] for item in shown["replacements"]},
                {"CAP-1", "CAP-2", "CAP-3"},
            )

            repeated = facade.submit_action(
                {
                    "action_type": "desktop_research.material.continue_new_version",
                    "payload": {
                        "reacquisition_run_id": first,
                        "paired_reacquisition_run_ids": [second, third],
                    },
                }
            )["data"]
            self.assertTrue(repeated["idempotent_reuse"])
            self.assertEqual(repeated["new_run_id"], data["new_run_id"])
        finally:
            facade.close()

    def test_paired_payload_rejects_primary_duplication(self):
        from plugins.local_application.new_material_continuation_public_facade import _payload

        with self.assertRaises(ValueError):
            _payload(
                {
                    "reacquisition_run_id": "RUN-MRA-1",
                    "paired_reacquisition_run_ids": ["RUN-MRA-1"],
                }
            )
