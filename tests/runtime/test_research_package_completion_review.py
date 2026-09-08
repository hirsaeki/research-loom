from __future__ import annotations

from copy import deepcopy
import json
from types import SimpleNamespace

from plugins.local_application import LocalApplicationError
from plugins.local_application.research_package_builder import _collect_exhibit_modes
from plugins.local_application.research_package_format import MAX_RUNS, digest_json, safe_component, verify_export_root, without_digest
import survey_virtual_runner_test_support as vr
import test_research_exhibits as exhibits
from research_package_acceptance_support import ResearchPackageAcceptanceSupport


class ResearchPackageCompletionReviewTests(ResearchPackageAcceptanceSupport):
    def test_selected_finding_requires_complete_support_chain(self):
        facade, case = self._prepare_case()
        try:
            proposal = case["proposal"]
            pending = facade.submit_action({
                "action_type": "state.apply_candidate",
                "payload": {"state_delta_proposal_id": proposal["proposal_id"]},
                "actor_id": "HUMAN-RP2-CLOSURE",
            })
            confirmed = facade.submit_confirmation({
                "confirmation_request_id": pending["confirmation_request"]["confirmation_request_id"],
                "actor_id": "HUMAN-RP2-CLOSURE",
            })
            if confirmed["status"] == "HUMAN_DECISION_REQUIRED":
                request = confirmed["decision_request"]
                facade.resolve_human_decision({
                    "request_id": request["request_id"],
                    "request_digest": request["request_digest"],
                    "disposition": "approve_exact",
                    "actor_id": "HUMAN-RP2-CLOSURE",
                })
            state = facade._application.state_repository.load_state_view(
                facade.project_id,
                facade._application.state_repository.load_active_lineage_ref(facade.project_id),
            )
            objects = []
            expected = {}
            for action in proposal["proposed_actions"]:
                obj = action.get("payload", {}).get("object")
                if isinstance(obj, dict) and isinstance(obj.get("id"), str):
                    objects.append(obj["id"])
                    expected[obj["id"]] = deepcopy(obj)
            finding_id = next(oid for oid in objects if expected[oid].get("kind") == "finding")
            with self.assertRaises(LocalApplicationError) as incomplete:
                facade.build_research_package({
                    "snapshot_id": state.current_snapshot["id"],
                    "rq_id": case["rq_id"],
                    "object_ids": [finding_id],
                })
            self.assertEqual(incomplete.exception.code, "APPLICATION-RESEARCH-PACKAGE-REFERENCE-001")

            built = facade.build_research_package({
                "snapshot_id": state.current_snapshot["id"],
                "rq_id": case["rq_id"],
                "object_ids": objects,
                "run_ids": [case["run_id"]],
                "materials": [{"run_id": case["run_id"], "capture_id": "CAP-1"}],
            })
            package = facade.show_research_package(built["package"]["package_id"])["package"]
            resolved = {obj["id"]: obj for obj in package["resolved_content"]["research_objects"]}
            for object_id in objects:
                self.assertEqual(resolved[object_id], expected[object_id])
            sources = {oid for oid in objects if expected[oid].get("kind") == "source"}
            self.assertEqual({ref["source_id"] for ref in package["content"]["source_refs"]}, sources)
            self.assertEqual(
                package["resolved_content"]["materials"][0]["capture"]["capture_id"],
                "CAP-1",
            )
        finally:
            facade.close()


    def test_selected_sources_require_bundled_material_without_run_selector(self):
        facade, case = self._prepare_case()
        try:
            proposal = case["proposal"]
            pending = facade.submit_action({
                "action_type": "state.apply_candidate",
                "payload": {"state_delta_proposal_id": proposal["proposal_id"]},
                "actor_id": "HUMAN-RP2-SOURCE-BODY",
            })
            confirmed = facade.submit_confirmation({
                "confirmation_request_id": pending["confirmation_request"]["confirmation_request_id"],
                "actor_id": "HUMAN-RP2-SOURCE-BODY",
            })
            if confirmed["status"] == "HUMAN_DECISION_REQUIRED":
                request = confirmed["decision_request"]
                facade.resolve_human_decision({
                    "request_id": request["request_id"],
                    "request_digest": request["request_digest"],
                    "disposition": "approve_exact",
                    "actor_id": "HUMAN-RP2-SOURCE-BODY",
                })
            state = facade._application.state_repository.load_state_view(
                facade.project_id,
                facade._application.state_repository.load_active_lineage_ref(facade.project_id),
            )
            objects = [
                action["payload"]["object"]["id"]
                for action in proposal["proposed_actions"]
                if isinstance(action.get("payload", {}).get("object"), dict)
                and action["payload"]["object"].get("kind") in {"source", "evidence", "finding"}
            ]
            with self.assertRaises(LocalApplicationError) as missing_body:
                facade.build_research_package({
                    "snapshot_id": state.current_snapshot["id"],
                    "rq_id": case["rq_id"],
                    "object_ids": objects,
                })
            self.assertEqual(missing_body.exception.code, "APPLICATION-RESEARCH-PACKAGE-REFERENCE-001")

            built = facade.build_research_package({
                "snapshot_id": state.current_snapshot["id"],
                "rq_id": case["rq_id"],
                "object_ids": objects,
                "materials": [{"run_id": case["run_id"], "capture_id": "CAP-1"}],
            })
            package = facade.show_research_package(built["package"]["package_id"])["package"]
            source_ids = {
                obj["id"] for obj in package["resolved_content"]["research_objects"]
                if obj.get("kind") == "source"
            }
            self.assertEqual(
                {row["source_id"] for row in package["resolved_content"]["materials"]},
                source_ids,
            )
            self.assertEqual(
                {ref["source_id"] for ref in package["content"]["source_refs"]},
                source_ids,
            )
        finally:
            facade.close()

    def test_detached_verify_resolves_all_body_attachment_references(self):
        facade, case = self._build()
        try:
            mutations = (
                ("material-missing", lambda package: package["resolved_content"]["materials"][0]["text_rendition"].__setitem__("attachment_path", "attachments/materials/missing.txt")),
                ("material-misbinding", lambda package: package["resolved_content"]["materials"][0]["text_rendition"].__setitem__("attachment_path", "attachments/profile/narrative-semantics.yaml")),
                ("project-input", lambda package: package["resolved_content"]["working_material"]["project_inputs"][0]["content"].__setitem__("attachment_path", "attachments/inputs/missing.txt")),
                ("narrative", lambda package: next(
                    item for item in package["attachments"]
                    if item["path"] == package["resolved_profiles"]["narrative_semantics"]["contract_path"]
                ).__setitem__("content_digest", "sha256:" + "0" * 64)),
            )
            for label, mutate in mutations:
                with self.subTest(label=label):
                    output = self.root / f"bad-body-ref-{label}"
                    facade.export_research_package(case["package_id"], output)
                    package_path = output / "research-package.json"
                    package = json.loads(package_path.read_text(encoding="utf-8"))
                    mutate(package)
                    package["package_digest"] = digest_json(without_digest(package))
                    package_path.write_text(
                        json.dumps(package, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                        encoding="utf-8",
                    )
                    with self.assertRaises(LocalApplicationError) as error:
                        verify_export_root(output)
                    self.assertEqual(error.exception.code, "APPLICATION-RESEARCH-PACKAGE-REFERENCE-001")
        finally:
            facade.close()

    def test_build_rejects_corrupted_saved_material_before_packaging(self):
        facade, case = self._prepare_case()
        try:
            artifact_id = case["capture"]["text_rendition"]["content_reference"]
            artifact = next(
                item
                for item in facade._application.execution_store.artifacts_for(case["run_id"])
                if item.artifact_id == artifact_id
            )
            value = str(artifact.digest).removeprefix("sha256:")
            self.assertEqual(len(value), 64)
            blob = facade._application.execution_store.blob_root / value[:2] / value
            original = blob.read_bytes()
            tampered = bytearray(original)
            tampered[0] ^= 1
            blob.write_bytes(bytes(tampered))
            with self.assertRaises(LocalApplicationError):
                facade.build_research_package(case["build_input"])
        finally:
            facade.close()

    def test_build_rejects_missing_saved_material_before_packaging(self):
        facade, case = self._prepare_case()
        try:
            artifact_id = case["capture"]["text_rendition"]["content_reference"]
            artifact = next(
                item
                for item in facade._application.execution_store.artifacts_for(case["run_id"])
                if item.artifact_id == artifact_id
            )
            value = str(artifact.digest).removeprefix("sha256:")
            blob = facade._application.execution_store.blob_root / value[:2] / value
            blob.unlink()
            with self.assertRaises(LocalApplicationError):
                facade.build_research_package(case["build_input"])
        finally:
            facade.close()

    def test_detached_verify_rejects_unresolved_content_refs(self):
        facade, case = self._build()
        try:
            output = self.root / "dangling-content-ref"
            facade.export_research_package(case["package_id"], output)
        finally:
            facade.close()
        package_path = output / "research-package.json"
        package = json.loads(package_path.read_text(encoding="utf-8"))
        package["content"]["finding_refs"] = ["FND-MISSING"]
        package["package_digest"] = digest_json(without_digest(package))
        package_path.write_text(json.dumps(package, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        with self.assertRaises(LocalApplicationError) as error:
            verify_export_root(output)
        self.assertEqual(error.exception.code, "APPLICATION-RESEARCH-PACKAGE-REFERENCE-001")

    def test_windows_drive_and_ads_components_fail_closed(self):
        for value in ("D:outside", "foo:bar"):
            with self.subTest(value=value):
                with self.assertRaises(LocalApplicationError) as error:
                    safe_component(value, "package_id")
                self.assertEqual(error.exception.code, "APPLICATION-RESEARCH-PACKAGE-INPUT-001")

    def test_exhibit_source_run_provenance_is_bounded_before_load(self):
        class Store:
            def load_run(self, _run_id):
                raise AssertionError("source Run must not be loaded after bound failure")
        service = SimpleNamespace(
            project_id="PROJECT-1",
            app=SimpleNamespace(execution_store=Store()),
            facade=SimpleNamespace(),
        )
        state = SimpleNamespace(active_lineage_ref="LINEAGE-1")
        exhibit = {
            "exhibit_id": "EX-BIG",
            "project_id": "PROJECT-1",
            "captured_against": {"lineage_ref": "LINEAGE-1"},
            "source_run_ids": [f"RUN-{index}" for index in range(MAX_RUNS + 1)],
            "derived_from_exhibit_ids": [],
        }
        with self.assertRaises(LocalApplicationError) as error:
            _collect_exhibit_modes(service, exhibit, state, set())
        self.assertEqual(error.exception.code, "APPLICATION-RESEARCH-PACKAGE-BOUND-001")

    def test_detached_verify_rejects_missing_or_malformed_body_rows(self):
        facade, case = self._build()
        try:
            mutations = (
                ("missing-text", lambda package: package["resolved_content"]["materials"][0].__setitem__("text_rendition", None)),
                ("bad-capture", lambda package: package["resolved_content"]["materials"][0].__setitem__("capture", "bad")),
                ("bad-byte-length", lambda package: package["resolved_content"]["materials"][0]["text_rendition"].__setitem__("byte_length", "not-an-int")),
                ("missing-input-content", lambda package: package["resolved_content"]["working_material"]["project_inputs"][0].__setitem__("content", None)),
            )
            for label, mutate in mutations:
                with self.subTest(label=label):
                    output = self.root / f"bad-body-row-{label}"
                    facade.export_research_package(case["package_id"], output)
                    package_path = output / "research-package.json"
                    package = json.loads(package_path.read_text(encoding="utf-8"))
                    mutate(package)
                    package["package_digest"] = digest_json(without_digest(package))
                    package_path.write_text(
                        json.dumps(package, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                        encoding="utf-8",
                    )
                    with self.assertRaises(LocalApplicationError) as error:
                        verify_export_root(output)
                    self.assertIn(error.exception.code, {
                        "APPLICATION-RESEARCH-PACKAGE-REFERENCE-001",
                        "APPLICATION-RESEARCH-PACKAGE-SCHEMA-001",
                    })
        finally:
            facade.close()

    def test_virtual_exhibit_only_package_preserves_synthetic_origin(self):
        facade = self._virtual_facade()
        try:
            facade.capture_survey_design(vr.design_payload())
            captured = facade.capture_survey_instrument(vr.instrument_payload())
            questionnaire = facade.show_survey_instrument(
                captured["instrument_id"], captured["version"]
            )["instrument"]["questionnaire"]
            result = facade.submit_action({
                "action_type": "virtual_runner.survey.execute",
                "payload": vr.execution_payload(
                    scenario="STANDARD",
                    instrument_version=questionnaire["version"],
                    instrument_digest=questionnaire["content_digest"],
                ),
                "actor_id": "HUMAN-RP5-EXHIBIT",
            })
            self.assertEqual(result["status"], "SUCCEEDED")
            (self.root / "virtual-workspace" / "effective-profile-set.json").write_text(
                (self.root / "profiles-input.json").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            exhibit = facade.capture_exhibit(exhibits.exhibit_payload(
                rq_id="RQ-1",
                source_run_ids=[result["run_id"]],
                source_object_ids=[],
                source_artifact_refs=[],
            ))["exhibit"]
            state = facade._application.state_repository.load_state_view(
                facade.project_id,
                facade._application.state_repository.load_active_lineage_ref(facade.project_id),
            )
            built = facade.build_research_package({
                "snapshot_id": state.current_snapshot["id"],
                "rq_id": "RQ-1",
                "exhibit_ids": [exhibit["exhibit_id"]],
            })
            package = facade.show_research_package(built["package"]["package_id"])["package"]
            self.assertEqual(package["source_epistemic_status"], "SYNTHETIC_TEST_ONLY")
            self.assertEqual(package["package_mode"], "preview")

            derived = facade.capture_exhibit(exhibits.exhibit_payload(
                rq_id="RQ-1",
                title="Derived virtual exhibit",
                source_run_ids=[],
                source_object_ids=[],
                source_artifact_refs=[],
                derived_from_exhibit_ids=[exhibit["exhibit_id"]],
            ))["exhibit"]
            derived_built = facade.build_research_package({
                "snapshot_id": state.current_snapshot["id"],
                "rq_id": "RQ-1",
                "exhibit_ids": [derived["exhibit_id"]],
            })
            derived_package = facade.show_research_package(
                derived_built["package"]["package_id"]
            )["package"]
            self.assertEqual(derived_package["source_epistemic_status"], "SYNTHETIC_TEST_ONLY")
            self.assertEqual(derived_package["package_mode"], "preview")
        finally:
            facade.close()


if __name__ == "__main__":
    import unittest
    unittest.main()
