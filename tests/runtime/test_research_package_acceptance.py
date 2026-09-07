from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import rfc8785
from unittest.mock import patch

from core.execution import CapabilityRunRecord, RunStatus
from core.runtime import canonical_digest
from plugins.local_application import LocalApplicationError, LocalApplicationFacade, LocalResearchApplication, LocalWorkspace
from plugins.local_application.research_package_service import verify_export_root
import test_external_desktop_research_intake as intake
import test_research_exhibits as exhibits
import survey_virtual_runner_test_support as vr
from runtime_fixtures import decision, project, rq, seed_state
from test_survey_production import NullResolver


class ResearchPackageAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        cfg, eps = self._write_structured_workspace_inputs()
        opened = LocalWorkspace.init(self.root / "workspace", cfg, eps)
        opened.close(); self.workspace = self.root / "workspace"

    def _write_structured_workspace_inputs(self):
        config = intake.bootstrap_config()
        effective = json.loads(intake.PROFILE_FIXTURE.read_text(encoding="utf-8"))
        narrative_path = intake.ROOT / "profiles/fixtures/narrative/valid/generic-narrative.profile.json"
        narrative = json.loads(narrative_path.read_text(encoding="utf-8"))
        manifest_sha = hashlib.sha256(narrative_path.read_bytes()).hexdigest()
        pin = {
            "profile_id": narrative["profile_id"],
            "profile_type": "narrative",
            "profile_version": narrative["profile_version"],
            "manifest_sha256": manifest_sha,
        }
        config["profile_requests"]["narrative"] = [{
            "profile_id": pin["profile_id"], "profile_type": "narrative", "version": pin["profile_version"]
        }]
        config.pop("configuration_digest", None)
        config["configuration_digest"] = "sha256:" + hashlib.sha256(rfc8785.dumps(config)).hexdigest()
        effective["candidate_universe"] = [pin if x["profile_type"] == "narrative" else x for x in effective["candidate_universe"]]
        effective["requested_profiles"] = [
            {"profile_id": pin["profile_id"], "profile_type": "narrative", "version": pin["profile_version"]}
            if x["profile_type"] == "narrative" else x for x in effective["requested_profiles"]
        ]
        effective["effective_profiles"] = [
            {**pin, "selection_provenance": [{"relation": "requested", "required_version": pin["profile_version"]}]}
            if x["profile_type"] == "narrative" else x for x in effective["effective_profiles"]
        ]
        effective["effective_constraints"] = [
            x for x in effective["effective_constraints"] if not str(x["path"]).startswith("narrative.")
        ]
        for constraint in narrative["constraints"]:
            effective["effective_constraints"].append({
                "path": constraint["path"],
                "merge_strategy": constraint["merge_strategy"],
                "value": deepcopy(constraint["value"]),
                "resolution": "single",
                "provenance": [{**pin, "constraint_id": constraint["id"]}],
            })
        effective["effective_constraints"].sort(key=lambda item: item["path"])
        cfg = self.root / "project-config-input.json"
        eps = self.root / "profiles-input.json"
        cfg.write_text(json.dumps(config), encoding="utf-8")
        eps.write_text(json.dumps(effective), encoding="utf-8")
        return cfg, eps

    def tearDown(self): self.temp.cleanup()

    def _prepare_case(self):
        facade = LocalApplicationFacade.open_workspace(self.workspace)
        rq_id = intake.adopt_rq(facade)
        state = facade._application.state_repository.load_state_view(facade.project_id, facade._application.state_repository.load_active_lineage_ref(facade.project_id))
        before = (state.current_snapshot["id"], state.current_snapshot["content_digest"])
        run_id = facade.submit_action({"action_type":"desktop_research.investigate","payload":{"question_id":rq_id,"purpose":"RP1 fixed-source acceptance."}})["run_id"]
        facade.start_external_retrieval_attempt(run_id,{"attempt_id":"ATT-1","strategy":"support search","coverage_dimension_ids":["COV-SUPPORT"],"target_locator":"https://example.test/source-a"})
        raw=self.workspace/"captures/raw/source-a.html"; text=self.workspace/"captures/text/source-a.txt"; raw.parent.mkdir(parents=True); text.parent.mkdir(parents=True)
        raw.write_bytes(b"<html>fixed source body</html>"); exact="Source A contains the exact supporting excerpt used here."; text.write_text(exact,encoding="utf-8")
        capture=facade.capture_external_source(run_id,{"capture_id":"CAP-1","source_category":"other","exact_locator":"https://example.test/source-a#section-1","acquired_at":"2026-09-07T00:00:00Z","original_file":"captures/raw/source-a.html","original_media_type":"text/html","text_rendition_file":"captures/text/source-a.txt"})["capture"]
        facade.complete_external_retrieval_attempt(run_id,{"attempt_id":"ATT-1","outcome":"source_captured","resulting_capture_id":"CAP-1"})
        facade.start_external_retrieval_attempt(run_id,{"attempt_id":"ATT-2","strategy":"counter search","coverage_dimension_ids":["COV-COUNTER"]})
        facade.complete_external_retrieval_attempt(run_id,{"attempt_id":"ATT-2","outcome":"no_relevant_source"})
        handoff, extension = intake.golden_submission(facade._application, run_id, capture)
        collected=facade.collect_external(run_id,{"handoff":handoff,"extension":extension})
        self.assertEqual(collected["execution_result"]["run"]["status"],"COMPLETED")
        proposal=deepcopy(collected["execution_result"]["state_delta_proposal"])
        exhibit=facade.capture_exhibit(exhibits.exhibit_payload(rq_id=rq_id,source_run_ids=[run_id],source_artifact_refs=[f"{run_id}.CAP-1.text"],source_object_ids=[]))["exhibit"]
        state2=facade._application.state_repository.load_state_view(facade.project_id, facade._application.state_repository.load_active_lineage_ref(facade.project_id))
        build_input={"snapshot_id":state2.current_snapshot["id"],"rq_id":rq_id,"run_ids":[run_id],"exhibit_ids":[exhibit["exhibit_id"]],"materials":[{"run_id":run_id,"capture_id":"CAP-1"}],"gap_ids":["GAP-1"]}
        return facade,{"rq_id":rq_id,"run_id":run_id,"capture":capture,"exhibit_id":exhibit["exhibit_id"],"source_text":exact,"before":before,"proposal":proposal,"build_input":build_input}

    def _build(self):
        facade,case=self._prepare_case(); result=facade.build_research_package(case["build_input"]); case["package_id"]=result["package"]["package_id"]; case["digest"]=result["package"]["package_digest"]; return facade,case

    def _virtual_facade(self):
        config = json.loads((self.root / "project-config-input.json").read_text(encoding="utf-8"))
        effective = json.loads((self.root / "profiles-input.json").read_text(encoding="utf-8"))
        config_digest = canonical_digest(config)
        effective_digest = canonical_digest(effective)
        method_decision = decision("DEC-METHOD-1", "research_adoption", "approve", "method", vr.METHOD_ID)
        protocol_decision = decision("DEC-PROTOCOL-MAT-1", "research_revision", "revise", "protocol", vr.PROTOCOL_ID)
        seed = seed_state(
            objects=[project(), rq(state="approved"), vr.method_object()],
            decisions=[method_decision, protocol_decision],
            snapshot_id="SNP-RP5-VIRTUAL-BASE",
            project_config=config,
        )
        lineage = replace(
            seed.lineages[0],
            project_config_digest=config_digest,
            effective_profile_set_digest=effective_digest,
        )
        seed = replace(
            seed,
            project_config_digest=config_digest,
            effective_profile_set_digest=effective_digest,
            lineages=(lineage,),
        )
        root = self.root / "virtual-workspace"
        root.mkdir()
        (root / "effective-profile-set.json").write_text(json.dumps(effective), encoding="utf-8")
        def virtual_profile_provider(_project, expected):
            if expected != effective_digest:
                return None
            projected = deepcopy(effective)
            projected["content_digest"] = expected
            return projected

        app = LocalResearchApplication(
            root,
            resolver=NullResolver(),
            effective_profile_set_provider=virtual_profile_provider,
            seed_state=seed,
        )
        return LocalApplicationFacade(app, "PRJ-1", workspace_root=root, owns_application=True)

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
        narrative=(out/package["resolved_profiles"]["narrative_semantics"]["contract_path"]).read_text(encoding="utf-8")
        self.assertIn("narrative.semantic_stages",narrative); self.assertIn("produces",narrative)

    def test_rp2_in_progress_real_and_candidate_authority_are_preserved(self):
        facade,case=self._prepare_case()
        try:
            first=facade.build_research_package(case["build_input"]); p=facade.show_research_package(first["package"]["package_id"])["package"]
            self.assertEqual(p["source_epistemic_status"],"EMPIRICAL_RESEARCH_STATE"); self.assertTrue(p["preview_only"]); self.assertFalse(p["authoritative_research_freeze"]); self.assertFalse(p["release_eligible"])
            self.assertEqual(p["content"]["finding_refs"],[])
            run=p["resolved_content"]["working_material"]["run_candidates"][0]
            self.assertTrue(run["candidate_only"]); self.assertTrue(run["handoff"]["outputs"]["candidate_findings"])

            proposal=case["proposal"]
            pending=facade.submit_action({
                "action_type":"state.apply_candidate",
                "payload":{"state_delta_proposal_id":proposal["proposal_id"]},
                "actor_id":"HUMAN-RP2",
            })
            decision_request=facade.submit_confirmation({
                "confirmation_request_id":pending["confirmation_request"]["confirmation_request_id"],
                "actor_id":"HUMAN-RP2",
            })["decision_request"]
            resolved=facade.resolve_human_decision({
                "request_id":decision_request["request_id"],
                "request_digest":decision_request["request_digest"],
                "disposition":"approve_exact",
                "actor_id":"HUMAN-RP2",
            })
            self.assertEqual(resolved["status"],"RESOLVED")

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
            })
            package=facade.show_research_package(second["package"]["package_id"])["package"]
            resolved_objects={obj["id"]:obj for obj in package["resolved_content"]["research_objects"]}
            for object_id in candidate_objects:
                self.assertEqual(resolved_objects[object_id],expected[object_id])
                self.assertEqual(resolved_objects[object_id].get("adoption_state"),"candidate")
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
            out=self.root/"tamper"; facade.export_research_package(case["package_id"],out); path=next((out/"attachments/materials").iterdir()); data=bytearray(path.read_bytes()); data[0]^=1; path.write_bytes(bytes(data))
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
            virtual = CapabilityRunRecord(
                run_id="RUN-RP5-VIRTUAL-MIX", invocation_id="INV-RP5", invocation_digest="sha256:"+"4"*64,
                capability_id="survey", capability_version="0.1.0", descriptor_digest="sha256:"+"5"*64,
                implementation_id="fixture.virtual", implementation_version="0.1.0", function_id="virtual", execution_mode="virtual",
                context_pack_id="CTX-RP5", context_pack_digest="sha256:"+"6"*64, project_ref=real_facade.project_id,
                lineage_ref=state.active_lineage_ref, snapshot_ref=state.current_snapshot["id"], snapshot_digest=state.current_snapshot["content_digest"],
                attempt=1, parent_run_id=None, status=RunStatus.COMPLETED, prepared_at="2026-09-07T00:00:00Z",
                started_at="2026-09-07T00:00:01Z", completed_at="2026-09-07T00:00:02Z",
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
