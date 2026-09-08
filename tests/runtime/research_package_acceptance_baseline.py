from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
import unittest
from unittest.mock import patch

from core.execution import CapabilityRunRecord, RunStatus
from plugins.local_application import LocalApplicationError
from plugins.local_application.research_package_service import verify_export_root
import test_external_desktop_research_intake as intake
import test_research_exhibits as exhibits
import survey_virtual_runner_test_support as vr
from research_package_acceptance_support import ResearchPackageAcceptanceSupport


class ResearchPackageAcceptanceTests(ResearchPackageAcceptanceSupport):
    def test_rp1_detached_show_export_and_verify_reads_exact_materials(self):
        facade,case=self._build()
        try:
            shown=facade.show_research_package(case["package_id"])["package"]
            self.assertEqual(shown["resolved_content"]["materials"][0]["capture"]["capture_id"],"CAP-1")
            self.assertEqual(shown["resolved_content"]["unresolved_gaps"][0]["gap_id"],"GAP-1")
            self.assertEqual(shown["resolved_content"]["working_material"]["research_exhibits"][0]["content"]["value"], exhibits.exhibit_payload()["content"]["value"])
            (self.workspace/"captures").rename(self.workspace/"captures-unavailable")
            out=self.root/"detached-package"; exported=facade.export_research_package(case["package_id"],out)
            self.assertEqual(exported["status"],"EXPORTED")
        finally: facade.close()
        verified=verify_export_root(out); self.assertEqual(verified["status"],"VERIFIED")
        package=json.loads((out/"research-package.json").read_text(encoding="utf-8"))
        self.assertEqual((out/package["resolved_content"]["materials"][0]["text_rendition"]["attachment_path"]).read_text(encoding="utf-8"),case["source_text"])
        narrative=(out/"attachments/profile/narrative-semantics.yaml").read_text(encoding="utf-8")
        self.assertIn("narrative.stages.definitions", narrative); self.assertIn("produces", narrative)
        self.assertIn("GAP-1",(out/"research-package.md").read_text(encoding="utf-8"))
        print(json.dumps({"RP_ACCEPTANCE":{"package_id":package["package_id"],"package_digest":package["package_digest"],"snapshot_id":package["source_research_snapshot"]["snapshot_id"],"snapshot_digest":package["source_research_snapshot"]["content_digest"],"material_digest":package["resolved_content"]["materials"][0]["text_rendition"]["content_digest"]}},sort_keys=True))

    def test_rp2_in_progress_real_and_candidate_authority_are_preserved(self):
        facade,case=self._build()
        try:
            p=facade.show_research_package(case["package_id"])["package"]
            self.assertEqual(p["source_epistemic_status"],"EMPIRICAL_RESEARCH_STATE")
            self.assertTrue(p["preview_only"]); self.assertFalse(p["authoritative_research_freeze"]); self.assertFalse(p["release_eligible"])
            self.assertEqual(p["content"]["finding_refs"],[])
            run=p["resolved_content"]["working_material"]["run_candidates"][0]
            self.assertTrue(run["candidate_only"]); self.assertTrue(run["handoff"]["outputs"]["candidate_findings"])

            proposal=case["proposal"]
            pending=facade.submit_action({
                "action_type":"state.apply_candidate",
                "payload":{"state_delta_proposal_id":proposal["proposal_id"]},
                "actor_id":"HUMAN-RP2",
            })
            confirmed=facade.submit_confirmation({
                "confirmation_request_id":pending["confirmation_request"]["confirmation_request_id"],
                "actor_id":"HUMAN-RP2",
            })
            if confirmed["status"] == "HUMAN_DECISION_REQUIRED":
                decision_request=confirmed["decision_request"]
                facade.resolve_human_decision({
                    "request_id":decision_request["request_id"],
                    "request_digest":decision_request["request_digest"],
                    "disposition":"approve_exact",
                    "actor_id":"HUMAN-RP2",
                })

            state=facade._application.state_repository.load_state_view(
                facade.project_id,
                facade._application.state_repository.load_active_lineage_ref(facade.project_id),
            )
            candidate_objects=[]
            expected={}
            for action in proposal["proposed_actions"]:
                obj=action.get("payload",{}).get("object")
                if isinstance(obj,dict) and obj.get("kind") in {"source","evidence","finding"}:
                    candidate_objects.append(obj["id"])
                    expected[obj["id"]]=deepcopy(obj)
            self.assertTrue(candidate_objects)
            second=facade.build_research_package({
                "snapshot_id":state.current_snapshot["id"],
                "rq_id":case["rq_id"],
                "object_ids":candidate_objects,
                "run_ids":[case["run_id"]],
                "materials":[{"run_id":case["run_id"],"capture_id":"CAP-1"}],
            })
            package=facade.show_research_package(second["package"]["package_id"])["package"]
            resolved_objects={obj["id"]:obj for obj in package["resolved_content"]["research_objects"]}
            for object_id in candidate_objects:
                self.assertEqual(resolved_objects[object_id],expected[object_id])
                if "adoption_state" in expected[object_id]:
                    self.assertEqual(
                        resolved_objects[object_id].get("adoption_state"),
                        expected[object_id]["adoption_state"],
                    )
            finding=next(obj for obj in resolved_objects.values() if obj.get("kind")=="finding")
            expected_finding=next(obj for obj in expected.values() if obj.get("kind")=="finding")
            self.assertEqual(finding.get("evidence_ids"),expected_finding.get("evidence_ids"))
            self.assertEqual(finding.get("counter_evidence_ids"),expected_finding.get("counter_evidence_ids"))
            self.assertEqual(finding.get("boundary_conditions"),expected_finding.get("boundary_conditions"))
            self.assertEqual(finding.get("limitations"),expected_finding.get("limitations"))
            self.assertTrue(package["resolved_content"]["working_material"]["run_candidates"][0]["candidate_only"])
        finally: facade.close()

    def test_rp3_saved_package_survives_head_advance_and_source_loss(self):
        facade,case=self._build()
        try:
            before=deepcopy(facade.show_research_package(case["package_id"])["package"]); run_before=facade._application.execution_store.load_run(case["run_id"])
            intake.adopt_rq(facade); (self.workspace/"captures").rename(self.workspace/"captures-unavailable")
            after=facade.show_research_package(case["package_id"])["package"]
            self.assertEqual(before,after); self.assertEqual(facade._application.execution_store.load_run(case["run_id"]),run_before)
            out=self.root/"reexport"; facade.export_research_package(case["package_id"],out); self.assertEqual(verify_export_root(out)["package_digest"],case["digest"])
        finally: facade.close()

    def test_rp4_gap_is_valid_but_bad_ids_bindings_and_tamper_fail(self):
        facade,case=self._build()
        try:
            state=facade._application.state_repository.load_state_view(facade.project_id,facade._application.state_repository.load_active_lineage_ref(facade.project_id))
            with self.assertRaises(LocalApplicationError): facade.build_research_package({**case["build_input"],"object_ids":["OBJ-MISSING"]})
            with self.assertRaises(LocalApplicationError): facade.build_research_package({**case["build_input"],"snapshot_digest":"sha256:"+"0"*64})
            foreign=CapabilityRunRecord(run_id="RUN-RP4-FOREIGN",invocation_id="INV-RP4",invocation_digest="sha256:"+"1"*64,capability_id="survey",capability_version="0.1.0",descriptor_digest="sha256:"+"2"*64,implementation_id="fixture.foreign",implementation_version="0.1.0",function_id="inspect",execution_mode="real",context_pack_id="CTX-RP4",context_pack_digest="sha256:"+"3"*64,project_ref="PRJ-FOREIGN",lineage_ref="LIN-FOREIGN",snapshot_ref=state.current_snapshot["id"],snapshot_digest=state.current_snapshot["content_digest"],attempt=1,parent_run_id=None,status=RunStatus.COMPLETED,prepared_at="2026-09-07T00:00:00Z",started_at="2026-09-07T00:00:01Z",completed_at="2026-09-07T00:00:02Z")
            facade._application.execution_store.create_run(foreign)
            with self.assertRaises(LocalApplicationError) as e: facade.build_research_package({**case["build_input"],"run_ids":[foreign.run_id]})
            self.assertEqual(e.exception.code,"APPLICATION-RESEARCH-PACKAGE-BINDING-001")
            out=self.root/"tamper"; facade.export_research_package(case["package_id"],out); path=next((out/"attachments/materials").rglob("*.txt")); data=bytearray(path.read_bytes()); data[0]^=1; path.write_bytes(bytes(data))
            with self.assertRaises(LocalApplicationError): verify_export_root(out)
        finally: facade.close()

    def test_rp5_virtual_origin_and_real_virtual_mixing_fail_closed(self):
        virtual_facade = self._virtual_facade()
        try:
            virtual_facade.capture_survey_design(vr.design_payload())
            captured = virtual_facade.capture_survey_instrument(vr.instrument_payload())
            questionnaire = virtual_facade.show_survey_instrument(
                captured["instrument_id"], captured["version"]
            )["instrument"]["questionnaire"]
            virtual_result = virtual_facade.submit_action({
                "action_type": "virtual_runner.survey.execute",
                "payload": vr.execution_payload(
                    scenario="STANDARD",
                    instrument_version=questionnaire["version"],
                    instrument_digest=questionnaire["content_digest"],
                ),
                "actor_id": "HUMAN-RP5",
            })
            self.assertEqual(virtual_result["status"], "SUCCEEDED")
            self.assertEqual(virtual_result["execution_mode"], "virtual")
            (self.root / "virtual-workspace" / "effective-profile-set.json").write_text(
                (self.root / "profiles-input.json").read_text(encoding="utf-8"), encoding="utf-8"
            )
            state = virtual_facade._application.state_repository.load_state_view(
                virtual_facade.project_id,
                virtual_facade._application.state_repository.load_active_lineage_ref(virtual_facade.project_id),
            )
            built = virtual_facade.build_research_package({
                "snapshot_id": state.current_snapshot["id"],
                "rq_id": "RQ-1",
                "run_ids": [virtual_result["run_id"]],
            })
            package = virtual_facade.show_research_package(built["package"]["package_id"])["package"]
            self.assertEqual(package["source_epistemic_status"], "SYNTHETIC_TEST_ONLY")
            self.assertEqual(package["package_mode"], "preview")
            self.assertTrue(package["preview_only"])
            self.assertFalse(package["authoritative_research_freeze"])
            self.assertFalse(package["release_eligible"])
            self.assertEqual(package["source_research_snapshot"]["execution_mode"], "real")
            self.assertEqual(package["resolved_content"]["working_material"]["run_candidates"][0]["execution_mode"], "virtual")
        finally:
            virtual_facade.close()

        real_facade, case = self._build()
        try:
            state = real_facade._application.state_repository.load_state_view(
                real_facade.project_id,
                real_facade._application.state_repository.load_active_lineage_ref(real_facade.project_id),
            )
            real_run = real_facade._application.execution_store.load_run(case["run_id"])
            self.assertIsNotNone(real_run)
            self.assertIsNotNone(real_run.handoff_ref)
            virtual = replace(
                real_run,
                run_id="RUN-RP5-VIRTUAL-MIX",
                invocation_id="INV-RP5-VIRTUAL-MIX",
                execution_mode="virtual",
            )
            real_facade._application.execution_store.create_run(virtual)
            with self.assertRaises(LocalApplicationError) as error:
                real_facade.build_research_package({**case["build_input"], "run_ids": [case["run_id"], virtual.run_id]})
            self.assertEqual(error.exception.code, "APPLICATION-RESEARCH-PACKAGE-EPISTEMIC-001")
        finally:
            real_facade.close()

    def test_rp6_bounds_existing_target_and_write_failure_are_atomic(self):
        facade,case=self._build()
        try:
            with self.assertRaises(LocalApplicationError): facade.build_research_package({**case["build_input"],"object_ids":[f"X-{i}" for i in range(65)]})
            existing=self.root/"existing"; existing.mkdir(); (existing/"keep.txt").write_text("keep")
            with self.assertRaises(LocalApplicationError): facade.export_research_package(case["package_id"],existing)
            self.assertEqual((existing/"keep.txt").read_text(),"keep")
            failed=self.root/"failed"
            with patch("plugins.local_application.research_package_service.os.replace",side_effect=OSError("fixture write failure")):
                with self.assertRaises(LocalApplicationError) as error: facade.export_research_package(case["package_id"],failed)
            self.assertEqual(error.exception.code,"APPLICATION-RESEARCH-PACKAGE-WRITE-001")
            self.assertFalse(failed.exists())
        finally: facade.close()

    def test_ablation_body_resolution_is_required_for_detached_use(self):
        facade,case=self._build()
        try: p=facade.show_research_package(case["package_id"])["package"]
        finally: facade.close()
        legacy={k:deepcopy(v) for k,v in p.items() if k not in {"resolved_profiles","resolved_content","attachments","projections"}}
        legacy["schema_version"]="0.1.0"; legacy["package_digest"]="sha256:"+"0"*64
        # Reference-only shape can still satisfy the legacy contract, but cannot provide exact detached bodies.
        from plugins.local_application.research_package_format import validate_schema
        validate_schema(legacy)
        self.assertNotIn("resolved_content",legacy); self.assertNotIn("attachments",legacy)

    def test_ablation_package_digest_rejects_inline_tamper(self):
        facade,case=self._build()
        try:
            out=self.root/"digest-ablation"; facade.export_research_package(case["package_id"],out)
        finally: facade.close()
        p=json.loads((out/"research-package.json").read_text(encoding="utf-8")); p["resolved_content"]["research_objects"][0]["text"]="same-shape tamper"; (out/"research-package.json").write_text(json.dumps(p,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
        with self.assertRaises(LocalApplicationError): verify_export_root(out)
        # Test-only ablation: schema/attachment/projection checks remain, package document digest is omitted.
        self.assertEqual(verify_export_root(out,verify_package_digest=False)["status"],"VERIFIED")


if __name__ == "__main__": unittest.main()
