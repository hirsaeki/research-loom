from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

from plugins.local_application import LocalApplicationError, verify_writer_section_input
from plugins.local_application.writer_composition_service import WriterCompositionService
from research_package_acceptance_support import ResearchPackageAcceptanceSupport
import survey_virtual_runner_test_support as vr
import test_external_desktop_research_intake as intake


class Issue80WriterCompositionTests(ResearchPackageAcceptanceSupport):
    def _proposal(self, case, *, composition_id=None, base=None):
        value = {
            "purpose": "Plan a compact evidence-linked report.",
            "audience": ["reviewer"],
            "sections": [
                {
                    "section_id": "SEC-FRAME", "order": 1, "heading": "Framing",
                    "reader_question": "What is being investigated?", "purpose": "Frame the research question and available material.",
                    "narrative_stage_refs": ["framing"], "semantic_purpose_refs": ["frame_problem"],
                    "messages": ["State the question and bounded evidence context."],
                    "material_refs": [f"{case['run_id']}:CAP-1"], "exhibit_refs": [case["exhibit_id"]], "gap_refs": ["GAP-1"],
                    "opening_intent": "State the question.", "closing_intent": "Hand off to validation.",
                    "next_section_id": "SEC-VALIDATE", "prohibited_claims": ["Do not treat candidate material as adopted Finding."],
                },
                {
                    "section_id": "SEC-VALIDATE", "order": 2, "heading": "Validation plan",
                    "reader_question": "How will the claim be tested?", "purpose": "Keep validation explicitly incomplete.",
                    "narrative_stage_refs": ["validation"], "semantic_purpose_refs": ["test_and_qualify"],
                    "messages": ["Preserve unresolved requirements instead of inventing findings."],
                    "previous_section_id": "SEC-FRAME", "detailed": False,
                },
            ],
            "created_by": {"type": "human_or_external_llm", "instruction": "Use supplied package only."},
        }
        if composition_id is not None: value["composition_id"] = composition_id
        if base is not None:
            value["base_version"] = base["version"]; value["base_digest"] = base["composition_digest"]; value["change_reason"] = "Refine framing purpose."
        return value

    def _build_complete_support_package(self):
        facade, case = self._prepare_case()
        proposal = case["proposal"]
        pending = facade.submit_action({
            "action_type": "state.apply_candidate",
            "payload": {"state_delta_proposal_id": proposal["proposal_id"]},
            "actor_id": "HUMAN-I80-SUPPORT",
        })
        confirmed = facade.submit_confirmation({
            "confirmation_request_id": pending["confirmation_request"]["confirmation_request_id"],
            "actor_id": "HUMAN-I80-SUPPORT",
        })
        if confirmed["status"] == "HUMAN_DECISION_REQUIRED":
            request = confirmed["decision_request"]
            facade.resolve_human_decision({
                "request_id": request["request_id"], "request_digest": request["request_digest"],
                "disposition": "approve_exact", "actor_id": "HUMAN-I80-SUPPORT",
            })
        state = facade._application.state_repository.load_state_view(
            facade.project_id, facade._application.state_repository.load_active_lineage_ref(facade.project_id)
        )
        objects = [
            action["payload"]["object"]["id"] for action in proposal["proposed_actions"]
            if isinstance(action.get("payload", {}).get("object"), dict)
            and action["payload"]["object"].get("kind") in {"source", "evidence", "finding"}
        ]
        built = facade.build_research_package({
            "snapshot_id": state.current_snapshot["id"], "rq_id": case["rq_id"],
            "object_ids": objects, "run_ids": [case["run_id"]],
            "materials": [{"run_id": case["run_id"], "capture_id": "CAP-1"}],
            "exhibit_ids": [case["exhibit_id"]], "gap_ids": ["GAP-1"],
        })
        case["package_id"] = built["package"]["package_id"]
        return facade, case

    def test_co1_capture_in_progress_composition_without_freeze(self):
        facade, case = self._build()
        try:
            package = facade.show_research_package(case["package_id"])["package"]
            result = facade.capture_writer_composition(case["package_id"], self._proposal(case))
            comp = result["composition"]
            self.assertEqual(comp["version"], 1)
            self.assertEqual(comp["source"]["research_package_digest"], case["digest"])
            self.assertEqual(comp["source"]["research_snapshot_id"], package["source_research_snapshot"]["snapshot_id"])
            self.assertEqual(comp["source"]["lineage_ref"], package["source_research_snapshot"]["lineage_ref"])
            self.assertEqual(comp["validation"]["status"], "VALID_WITH_GAPS")
            self.assertTrue(any(x["section_id"] == "SEC-VALIDATE" for x in comp["validation"]["diagnostics"]))
            self.assertFalse(comp["research_state_mutation_performed"])
            shown = facade.show_writer_composition(comp["composition_id"], 1)["composition"]
            self.assertEqual(shown["composition_digest"], comp["composition_digest"])
        finally: facade.close()

    def test_co2_revision_diff_selection_and_reopen_preserve_old_pins(self):
        facade, case = self._build()
        try:
            v1 = facade.capture_writer_composition(case["package_id"], self._proposal(case))["composition"]
            selected1 = facade.select_writer_composition(v1["composition_id"], 1, v1["composition_digest"])
            old_snapshot_id = v1["source"]["research_snapshot_id"]
            intake.adopt_rq(facade)
            current = facade._application.state_repository.load_state_view(facade.project_id, facade._application.state_repository.load_active_lineage_ref(facade.project_id))
            self.assertNotEqual(current.current_snapshot["id"], old_snapshot_id)
            proposal2 = self._proposal(case, composition_id=v1["composition_id"], base=v1)
            proposal2["sections"][0]["purpose"] = "Refine the framing while preserving supplied material."
            v2 = facade.capture_writer_composition(case["package_id"], proposal2)["composition"]
            shown = facade.show_writer_composition(v1["composition_id"], 2)
            self.assertEqual(shown["selection"]["selected"]["version"], 1)
            diff = facade.diff_writer_composition(v1["composition_id"], 1, 2)
            self.assertEqual(diff["section_changes"], [{"section_id": "SEC-FRAME", "change": "modified", "fields": ["purpose"]}])
            facade.select_writer_composition(v1["composition_id"], 2, v2["composition_digest"])
            old_source = deepcopy(v1["source"])
        finally: facade.close()
        with self.__class__._reopen(self.workspace) as reopened:
            self.assertEqual(reopened.show_writer_composition(v1["composition_id"], 1)["composition"]["source"], old_source)
            self.assertEqual(reopened.show_writer_composition(v1["composition_id"], 2)["selection"]["selected"]["version"], 2)

    @staticmethod
    def _reopen(workspace):
        from plugins.local_application import LocalApplicationFacade
        return LocalApplicationFacade.open_workspace(workspace)

    def test_co3_selected_section_input_is_detached_and_exact(self):
        facade, case = self._build()
        try:
            v1 = facade.capture_writer_composition(case["package_id"], self._proposal(case))["composition"]
            facade.select_writer_composition(v1["composition_id"], 1, v1["composition_digest"])
            out = self.root / "section-input"
            facade.export_writer_section_input(v1["composition_id"], "SEC-FRAME", out)
        finally: facade.close()
        moved = self.root / "workspace-hidden"; self.workspace.rename(moved)
        data = json.loads((out / "section-writer-input.json").read_text(encoding="utf-8"))
        self.assertEqual(data["section_contract"]["section_id"], "SEC-FRAME")
        self.assertEqual(data["resolved_materials"][0]["text_rendition"]["content"], case["source_text"])
        self.assertEqual(data["resolved_exhibits"][0]["exhibit_id"], case["exhibit_id"])
        self.assertEqual(data["unresolved_gaps"][0]["gap_id"], "GAP-1")
        self.assertFalse(data["authority_boundary"]["evidence_verification_performed"])
        manifest = json.loads((out / "manifest.json").read_text())
        self.assertEqual(manifest["files"][0]["byte_length"], (out / "section-writer-input.json").stat().st_size)

    def test_co4_invalid_reference_pin_and_stale_revision_fail_closed(self):
        facade, case = self._build()
        try:
            bad = self._proposal(case); bad["sections"][0]["material_refs"] = ["RUN-FOREIGN:CAP-X"]
            with self.assertRaises(LocalApplicationError) as e: facade.capture_writer_composition(case["package_id"], bad)
            self.assertEqual(e.exception.code, "APPLICATION-WRITER-COMPOSITION-REFERENCE-001")
            v1 = facade.capture_writer_composition(case["package_id"], self._proposal(case))["composition"]
            p2 = self._proposal(case, composition_id=v1["composition_id"], base=v1)
            v2 = facade.capture_writer_composition(case["package_id"], p2)["composition"]
            stale = self._proposal(case, composition_id=v1["composition_id"], base=v1)
            with self.assertRaises(LocalApplicationError) as e: facade.capture_writer_composition(case["package_id"], stale)
            self.assertEqual(e.exception.code, "APPLICATION-WRITER-COMPOSITION-STALE-001")
            with self.assertRaises(LocalApplicationError): facade.select_writer_composition(v1["composition_id"], 2, "sha256:" + "0"*64)
            self.assertEqual(facade.show_writer_composition(v1["composition_id"], 1)["composition"]["composition_digest"], v1["composition_digest"])
            self.assertEqual(facade.show_writer_composition(v1["composition_id"], 2)["composition"]["composition_digest"], v2["composition_digest"])
            facade.select_writer_composition(v1["composition_id"], 2, v2["composition_digest"])
            package = facade.show_research_package(case["package_id"])["package"]
            rel = package["resolved_content"]["materials"][0]["text_rendition"]["attachment_path"]
            material_path = facade._research_package_service().root / case["package_id"] / rel
            original = material_path.read_bytes(); tampered = bytearray(original); tampered[0] ^= 1; material_path.write_bytes(bytes(tampered))
            with self.assertRaises(LocalApplicationError):
                facade.export_writer_section_input(v1["composition_id"], "SEC-FRAME", self.root / "tampered-section")
            self.assertFalse((self.root / "tampered-section").exists())
            material_path.write_bytes(original)
            facade.export_writer_section_input(v1["composition_id"], "SEC-FRAME", self.root / "corrected-section")
            self.assertTrue((self.root / "corrected-section" / "section-writer-input.json").is_file())
        finally: facade.close()

    def test_co5_narrative_partial_order_unmet_and_virtual_origin(self):
        facade, case = self._build()
        try:
            p = self._proposal(case)
            p["sections"][0]["narrative_stage_refs"] = ["framing", "formation"]
            p["sections"][0]["semantic_purpose_refs"] = ["frame_problem", "expose_argument"]
            comp = facade.capture_writer_composition(case["package_id"], p)["composition"]
            self.assertTrue(any("argument" in d.get("unmet_requires", []) for d in comp["validation"]["diagnostics"]))
            bad = self._proposal(case); bad["sections"][0]["narrative_stage_refs"] = ["unknown-stage"]
            with self.assertRaises(LocalApplicationError): facade.capture_writer_composition(case["package_id"], bad)
        finally: facade.close()
        vf = self._virtual_facade()
        try:
            vf.capture_survey_design(vr.design_payload()); captured = vf.capture_survey_instrument(vr.instrument_payload())
            q = vf.show_survey_instrument(captured["instrument_id"], captured["version"])["instrument"]["questionnaire"]
            result = vf.submit_action({"action_type":"virtual_runner.survey.execute","payload":vr.execution_payload(scenario="STANDARD",instrument_version=q["version"],instrument_digest=q["content_digest"]),"actor_id":"HUMAN-I80"})
            (self.root / "virtual-workspace" / "effective-profile-set.json").write_text((self.root/"profiles-input.json").read_text(), encoding="utf-8")
            state = vf._application.state_repository.load_state_view(vf.project_id, vf._application.state_repository.load_active_lineage_ref(vf.project_id))
            built = vf.build_research_package({"snapshot_id":state.current_snapshot["id"],"rq_id":"RQ-1","run_ids":[result["run_id"]]})
            pkg = vf.show_research_package(built["package"]["package_id"])["package"]
            proposal = {"purpose":"Virtual composition fixture.","sections":[{"section_id":"SEC-V","order":1,"heading":"Virtual framing","reader_question":"What is synthetic?","purpose":"Keep origin explicit.","narrative_stage_refs":["framing"],"semantic_purpose_refs":["frame_problem"]}]}
            comp = vf.capture_writer_composition(pkg["package_id"], proposal)["composition"]
            self.assertEqual(comp["source"]["research_package_id"], pkg["package_id"])
            self.assertEqual(comp["source"]["source_epistemic_status"], "SYNTHETIC_TEST_ONLY")
            self.assertEqual(comp["source"]["package_mode"], "preview")
            self.assertTrue(comp["source"]["preview_only"]); self.assertFalse(comp["source"]["release_eligible"])
            vf.select_writer_composition(comp["composition_id"], 1, comp["composition_digest"])
            out = self.root / "virtual-section-input"
            vf.export_writer_section_input(comp["composition_id"], "SEC-V", out)
            detached = json.loads((out / "section-writer-input.json").read_text(encoding="utf-8"))
            self.assertEqual(detached["source"]["source_epistemic_status"], "SYNTHETIC_TEST_ONLY")
            self.assertTrue(detached["source"]["preview_only"]); self.assertFalse(detached["source"]["release_eligible"])
        finally: vf.close()

    def test_review_fixes_reject_unsafe_id_and_preserve_nested_counter_target_scope(self):
        facade, case = self._build()
        try:
            bad = self._proposal(case, composition_id="..")
            with self.assertRaises(LocalApplicationError) as error:
                facade.capture_writer_composition(case["package_id"], bad)
            self.assertEqual(error.exception.code, "APPLICATION-WRITER-COMPOSITION-INPUT-001")

            package = deepcopy(facade.show_research_package(case["package_id"])["package"])
            package["content"]["finding_refs"] = ["FND-A", "FND-B"]
            package["content"]["counter_review_refs"] = ["CR-B"]
            package["resolved_content"]["research_objects"].extend([
                {"id": "FND-A", "kind": "finding"},
                {"id": "FND-B", "kind": "finding"},
                {"id": "CR-B", "kind": "counter_review", "target": {"kind": "finding", "id": "FND-B"}},
            ])
            proposal = self._proposal(case)
            proposal["sections"][0]["finding_refs"] = ["FND-A"]
            sections, _ = facade._writer_composition_service()._validate_sections(proposal["sections"], package)
            self.assertEqual(sections[0]["finding_refs"], ["FND-A"])
            self.assertEqual(sections[0]["counter_review_refs"], [])
        finally:
            facade.close()

    def test_review_fixes_series_lock_and_list_package_cache(self):
        facade, case = self._build()
        try:
            service = facade._writer_composition_service()
            facade.capture_writer_composition(case["package_id"], self._proposal(case, composition_id="COMP-LOCK"))
            with service._series_lock("COMP-LOCK"):
                with self.assertRaises(LocalApplicationError) as error:
                    with service._series_lock("COMP-LOCK"):
                        pass
            self.assertEqual(error.exception.code, "APPLICATION-WRITER-COMPOSITION-BUSY-001")

            with (
                patch.object(service, "_versions", side_effect=[[], [1], [1]]),
                patch.object(service, "_series_lock", wraps=service._series_lock) as series_lock,
            ):
                with service._capture_lock("COMP-LOCK"):
                    pass
            self.assertEqual(series_lock.call_count, 1)

            lock_files_before = sorted(path.name for path in service.root.glob(".*.lock"))
            for index in range(8):
                with self.assertRaises(LocalApplicationError) as missing:
                    facade.select_writer_composition(f"COMP-MISSING-{index}", 1, "sha256:" + "0" * 64)
                self.assertEqual(missing.exception.code, "APPLICATION-WRITER-COMPOSITION-404")
            self.assertEqual(sorted(path.name for path in service.root.glob(".*.lock")), lock_files_before)

            facade.capture_writer_composition(case["package_id"], self._proposal(case, composition_id="COMP-A"))
            facade.capture_writer_composition(case["package_id"], self._proposal(case, composition_id="COMP-B"))
            with patch.object(service, "_package", wraps=service._package) as package_load:
                listed = service.list()
            self.assertEqual(len(listed["compositions"]), 3)
            self.assertEqual(package_load.call_count, 1)
        finally:
            facade.close()

    def test_review_fixes_package_creation_lineage_is_stable_after_active_pointer_changes(self):
        facade, case = self._build()
        try:
            package = facade.show_research_package(case["package_id"])["package"]
            lineage = package["source_research_snapshot"]["lineage_ref"]
            repository = facade._application.state_repository
            with patch.object(repository, "load_active_lineage_ref", return_value="LIN-WRONG"):
                composition = facade.capture_writer_composition(case["package_id"], self._proposal(case))["composition"]
            self.assertEqual(composition["source"]["lineage_ref"], lineage)
        finally:
            facade.close()

    def test_review_fixes_narrative_partial_order_checks_all_occurrences(self):
        facade, case = self._build()
        try:
            proposal = self._proposal(case)
            proposal["sections"][0].pop("next_section_id", None)
            proposal["sections"][1].pop("previous_section_id", None)
            proposal["sections"][1]["narrative_stage_refs"] = ["formation"]
            proposal["sections"][1]["semantic_purpose_refs"] = ["expose_argument"]
            late = deepcopy(proposal["sections"][0])
            late.update({"section_id": "SEC-FRAME-LATE", "order": 3, "heading": "Late framing"})
            proposal["sections"].append(late)
            with self.assertRaises(LocalApplicationError) as error:
                facade.capture_writer_composition(case["package_id"], proposal)
            self.assertEqual(error.exception.code, "APPLICATION-WRITER-COMPOSITION-NARRATIVE-001")

            same = self._proposal(case)
            same["sections"] = [deepcopy(same["sections"][0])]
            same["sections"][0].pop("next_section_id", None)
            same["sections"][0]["narrative_stage_refs"] = ["framing", "formation"]
            same["sections"][0]["semantic_purpose_refs"] = ["frame_problem", "expose_argument"]
            facade.capture_writer_composition(case["package_id"], same)
        finally:
            facade.close()

    def test_public_cli_round_trip_capture_select_and_detached_section_input(self):
        facade, case = self._build(); facade.close()
        proposal_path = self.root / "composition-v1.json"
        proposal_path.write_text(json.dumps(self._proposal(case)), encoding="utf-8")
        root = Path(__file__).resolve().parents[2]
        launcher = [sys.executable, str(root / "research-loom")] if os.name != "nt" else ["cmd.exe", "/d", "/s", "/c", str(root / "research-loom.cmd")]
        def run(*args):
            completed = subprocess.run([*launcher, *map(str, args)], cwd=root, text=True, capture_output=True, check=False)
            self.assertEqual(completed.returncode, 0, msg=completed.stderr or completed.stdout)
            return json.loads(completed.stdout)
        captured = run("writer-composition", "capture", "--workspace", self.workspace, "--package-id", case["package_id"], "--json", proposal_path)
        v1 = captured["composition"]
        listed = run("writer-composition", "list", "--workspace", self.workspace, "--json")
        self.assertEqual(listed["compositions"][0]["latest_version"], 1)
        shown = run("writer-composition", "show", "--workspace", self.workspace, "--composition-id", v1["composition_id"], "--version", 1, "--json")
        self.assertEqual(shown["composition"]["composition_digest"], v1["composition_digest"])
        edit_path = self.root / "composition-v2.json"
        run("writer-composition", "export", "--workspace", self.workspace, "--composition-id", v1["composition_id"], "--version", 1, "--output", edit_path, "--json")
        edit = json.loads(edit_path.read_text(encoding="utf-8"))
        edit["sections"][0]["purpose"] = "CLI-edited framing purpose."
        edit["change_reason"] = "CLI wall-discussion revision."
        edit_path.write_text(json.dumps(edit), encoding="utf-8")
        captured2 = run("writer-composition", "capture", "--workspace", self.workspace, "--package-id", case["package_id"], "--json", edit_path)
        v2 = captured2["composition"]
        diff = run("writer-composition", "diff", "--workspace", self.workspace, "--composition-id", v1["composition_id"], "--from-version", 1, "--to-version", 2, "--json")
        self.assertEqual(diff["section_changes"], [{"section_id":"SEC-FRAME","change":"modified","fields":["purpose"]}])
        run("writer-composition", "select", "--workspace", self.workspace, "--composition-id", v1["composition_id"], "--version", 2, "--digest", v2["composition_digest"], "--json")
        output = self.root / "cli-section-input"
        run("writer-composition", "section-input", "--workspace", self.workspace, "--composition-id", v1["composition_id"], "--section-id", "SEC-FRAME", "--output", output, "--json")
        self.workspace.rename(self.root / "workspace-hidden-cli")
        detached = json.loads((output / "section-writer-input.json").read_text(encoding="utf-8"))
        self.assertEqual(detached["resolved_materials"][0]["text_rendition"]["content"], case["source_text"])
        self.assertEqual(detached["section_contract"]["section_digest"], v2["sections"][0]["section_digest"])
        verified = subprocess.run(
            [sys.executable, "-c", "import json,sys; from plugins.local_application import verify_writer_section_input; print(json.dumps(verify_writer_section_input(sys.argv[1])))", str(output)],
            cwd=root, text=True, capture_output=True, check=False,
        )
        self.assertEqual(verified.returncode, 0, msg=verified.stderr)
        self.assertEqual(json.loads(verified.stdout)["status"], "VERIFIED")

    def test_review_round4_support_chain_rq_locator_and_candidate_readiness(self):
        facade, case = self._build_complete_support_package()
        try:
            package = facade.show_research_package(case["package_id"])["package"]
            by_kind = {obj["kind"]: obj for obj in package["resolved_content"]["research_objects"] if obj.get("kind") in {"research_question", "source", "evidence", "finding"}}
            proposal = self._proposal(case)
            proposal["sections"] = [deepcopy(proposal["sections"][0])]
            proposal["sections"][0].pop("next_section_id", None)
            proposal["sections"][0]["finding_refs"] = [by_kind["finding"]["id"]]
            proposal["sections"][0]["material_refs"] = []
            proposal["sections"][0]["exhibit_refs"] = []
            proposal["sections"][0]["gap_refs"] = []
            proposal["sections"][0]["citation_requirements"] = [{"source_ref": by_kind["source"]["id"], "locator_ref": by_kind["evidence"]["locator"]}]
            comp = facade.capture_writer_composition(case["package_id"], proposal)["composition"]
            facade.select_writer_composition(comp["composition_id"], 1, comp["composition_digest"])
            out = self.root / "support-chain-section"
            facade.export_writer_section_input(comp["composition_id"], "SEC-FRAME", out)
            detached = json.loads((out / "section-writer-input.json").read_text(encoding="utf-8"))
            resolved = {obj["id"]: obj for obj in detached["resolved_research_objects"]}
            self.assertEqual(resolved[case["rq_id"]]["text"], by_kind["research_question"]["text"])
            self.assertTrue({by_kind[k]["id"] for k in ("finding", "evidence", "source")} <= set(resolved))
            self.assertEqual(detached["resolved_materials"][0]["text_rendition"]["content"], case["source_text"])
            self.assertTrue(detached["resolved_materials"][0]["candidate_only"] in {True, False})
            bad = deepcopy(proposal); bad["composition_id"] = "COMP-BAD-LOC"
            bad["sections"][0]["citation_requirements"][0]["locator_ref"] = "https://example.test/not-real"
            with self.assertRaises(LocalApplicationError) as error:
                facade.capture_writer_composition(case["package_id"], bad)
            self.assertEqual(error.exception.code, "APPLICATION-WRITER-COMPOSITION-REFERENCE-001")

            candidate = deepcopy(proposal); candidate["composition_id"] = "COMP-CANDIDATE"
            candidate["sections"][0]["narrative_stage_refs"] = ["validation"]
            candidate["sections"][0]["semantic_purpose_refs"] = ["test_and_qualify"]
            candidate["sections"][0]["citation_requirements"] = []
            candidate_comp = facade.capture_writer_composition(case["package_id"], candidate)["composition"]
            diag = next(d for d in candidate_comp["validation"]["diagnostics"] if d["section_id"] == "SEC-FRAME")
            self.assertIn("finding", diag["unmet_requires"])
        finally:
            facade.close()

    def test_review_round4_detached_validator_rejects_inner_tamper_after_outer_redigest(self):
        facade, case = self._build()
        try:
            comp = facade.capture_writer_composition(case["package_id"], self._proposal(case))["composition"]
            facade.select_writer_composition(comp["composition_id"], 1, comp["composition_digest"])
            base = self.root / "detached-validator-base"
            facade.export_writer_section_input(comp["composition_id"], "SEC-FRAME", base)
        finally:
            facade.close()
        self.assertEqual(verify_writer_section_input(base)["status"], "VERIFIED")
        from core.runtime import canonical_digest
        import hashlib
        mutations = {
            "missing-content": lambda d: d["resolved_materials"][0]["text_rendition"].pop("content"),
            "same-size": lambda d: d["resolved_materials"][0]["text_rendition"].__setitem__("content", "X" * len(d["resolved_materials"][0]["text_rendition"]["content"])),
            "null-size": lambda d: d["resolved_materials"][0]["text_rendition"].__setitem__("byte_length", None),
            "null-digest": lambda d: d["resolved_materials"][0]["text_rendition"].__setitem__("content_digest", None),
            "misbinding": lambda d: d["resolved_materials"][0].__setitem__("material_ref", "RUN-OTHER:CAP-OTHER"),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                out = self.root / f"detached-bad-{label}"; out.mkdir()
                doc = json.loads((base / "section-writer-input.json").read_text(encoding="utf-8")); mutate(doc)
                basis = deepcopy(doc); basis.pop("section_input_digest", None); doc["section_input_digest"] = canonical_digest(basis)
                payload = (json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
                (out / "section-writer-input.json").write_bytes(payload)
                manifest = {"schema_version":"0.1.0","object_type":"section_writer_input_manifest","files":[{"path":"section-writer-input.json","byte_length":len(payload),"content_digest":"sha256:"+hashlib.sha256(payload).hexdigest()}]}
                manifest["manifest_digest"] = canonical_digest(manifest)
                (out / "manifest.json").write_text(json.dumps(manifest))
                with self.assertRaises(LocalApplicationError): verify_writer_section_input(out)

    def test_review_round4_whole_export_is_no_overwrite_and_atomic(self):
        facade, case = self._build()
        try:
            comp = facade.capture_writer_composition(case["package_id"], self._proposal(case))["composition"]
            normal = self.root / "whole-safe.json"
            facade.export_writer_composition(comp["composition_id"], 1, normal)
            self.assertTrue(normal.is_file())
            sentinel = self.root / "whole-sentinel.json"
            real_link = os.link
            def race_link(src, dst):
                Path(dst).write_text("sentinel", encoding="utf-8")
                raise FileExistsError(dst)
            with patch("plugins.local_application.writer_composition_service.os.link", side_effect=race_link):
                with self.assertRaises(LocalApplicationError): facade.export_writer_composition(comp["composition_id"], 1, sentinel)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "sentinel")
            failed = self.root / "whole-failed.json"
            with patch("plugins.local_application.writer_composition_service.os.fsync", side_effect=OSError("fixture")):
                with self.assertRaises(LocalApplicationError): facade.export_writer_composition(comp["composition_id"], 1, failed)
            self.assertFalse(failed.exists())
        finally:
            facade.close()

    def test_whole_proposal_export_can_be_edited_and_reimported_as_new_version(self):
        facade, case = self._build()
        try:
            v1 = facade.capture_writer_composition(case["package_id"], self._proposal(case))["composition"]
            exported = self.root / "composition-edit.json"
            facade.export_writer_composition(v1["composition_id"], 1, exported)
            proposal = json.loads(exported.read_text(encoding="utf-8"))
            original_second = deepcopy(proposal["sections"][1])
            proposal["sections"][0]["purpose"] = "Edited whole-proposal framing purpose."
            proposal["change_reason"] = "Wall-discussion revision."
            v2 = facade.capture_writer_composition(case["package_id"], proposal)["composition"]
            self.assertEqual(v2["version"], 2)
            self.assertEqual(v2["sections"][1], original_second)
            diff = facade.diff_writer_composition(v1["composition_id"], 1, 2)
            self.assertEqual(diff["section_changes"], [{"section_id":"SEC-FRAME","change":"modified","fields":["purpose"]}])
        finally: facade.close()

    def test_co6_output_safety_and_write_failure_are_atomic(self):
        facade, case = self._build()
        try:
            v1 = facade.capture_writer_composition(case["package_id"], self._proposal(case))["composition"]
            facade.select_writer_composition(v1["composition_id"], 1, v1["composition_digest"])
            existing = self.root / "existing"; existing.mkdir(); (existing/"keep").write_text("keep")
            with self.assertRaises(LocalApplicationError): facade.export_writer_section_input(v1["composition_id"], "SEC-FRAME", existing)
            self.assertEqual((existing/"keep").read_text(), "keep")
            failed = self.root / "failed"
            with patch("plugins.local_application.writer_composition_service.os.replace", side_effect=OSError("fixture")):
                with self.assertRaises(LocalApplicationError): facade.export_writer_section_input(v1["composition_id"], "SEC-FRAME", failed)
            self.assertFalse(failed.exists())
            with patch("plugins.local_application.writer_composition_service.MAX_SELECTION_EVENTS", 2):
                facade.select_writer_composition(v1["composition_id"], 1, v1["composition_digest"])
                with self.assertRaises(LocalApplicationError) as selection_bound:
                    facade.select_writer_composition(v1["composition_id"], 1, v1["composition_digest"])
                self.assertEqual(selection_bound.exception.code, "APPLICATION-WRITER-COMPOSITION-BOUND-001")
            with patch("plugins.local_application.writer_composition_service.MAX_SECTION_INPUT_BYTES", 1):
                with self.assertRaises(LocalApplicationError) as output_bound:
                    facade.export_writer_section_input(v1["composition_id"], "SEC-FRAME", self.root / "too-large")
                self.assertEqual(output_bound.exception.code, "APPLICATION-WRITER-COMPOSITION-BOUND-001")
                self.assertFalse((self.root / "too-large").exists())
        finally: facade.close()

    def test_ablation_pin_validation_is_required(self):
        facade, case = self._build()
        try:
            v1 = facade.capture_writer_composition(case["package_id"], self._proposal(case))["composition"]
            path = facade._writer_composition_service()._version_path(v1["composition_id"], 1)
            tampered = json.loads(path.read_text()); tampered["source"]["research_snapshot_digest"] = "sha256:" + "0"*64
            from core.runtime import canonical_digest
            basis = deepcopy(tampered); basis.pop("composition_digest", None); tampered["composition_digest"] = canonical_digest(basis)
            path.write_text(json.dumps(tampered, sort_keys=True))
            with self.assertRaises(LocalApplicationError): facade.show_writer_composition(v1["composition_id"], 1)
            with patch.object(WriterCompositionService, "_validate_source_pin", return_value=None):
                self.assertEqual(facade.show_writer_composition(v1["composition_id"], 1)["composition"]["source"]["research_snapshot_digest"], "sha256:" + "0"*64)
        finally: facade.close()

    def test_ablation_preservation_validation_is_required(self):
        facade, case = self._build()
        try:
            package = facade.show_research_package(case["package_id"])["package"]
            package = deepcopy(package)
            package["content"]["finding_refs"] = ["FND-X"]
            package["content"]["counter_review_refs"] = ["CR-X"]
            package["resolved_content"]["research_objects"].extend([
                {"id":"FND-X","kind":"finding"}, {"id":"CR-X","kind":"counter_review","target":{"kind":"finding","id":"FND-X"}}
            ])
            proposal = self._proposal(case); proposal["sections"][0]["finding_refs"] = ["FND-X"]
            service = facade._writer_composition_service()
            with self.assertRaises(LocalApplicationError) as e: service._validate_sections(proposal["sections"], package)
            self.assertEqual(e.exception.code, "APPLICATION-WRITER-COMPOSITION-PRESERVATION-001")
            package["resolved_profiles"]["effective_constraints"] = [x for x in package["resolved_profiles"]["effective_constraints"] if x["path"] != "narrative.preservation.required_content"]
            sections, _ = service._validate_sections(proposal["sections"], package)
            self.assertEqual(sections[0]["finding_refs"], ["FND-X"])
        finally: facade.close()


if __name__ == "__main__":
    import unittest; unittest.main()
