from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import rfc8785

from core.runtime import canonical_digest
from plugins.local_application import LocalApplicationFacade, LocalResearchApplication, LocalWorkspace
import test_external_desktop_research_intake as intake
import test_research_exhibits as exhibits
import survey_virtual_runner_test_support as vr
from runtime_fixtures import decision, project, rq, seed_state
from test_survey_production import NullResolver


class ResearchPackageAcceptanceSupport(unittest.TestCase):
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
