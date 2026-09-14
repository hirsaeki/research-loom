from __future__ import annotations

from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from unittest.mock import patch

from core.runtime import canonical_digest
from plugins.local_application import LocalApplicationError, LocalApplicationFacade
from plugins.local_application.cli import main as cli_main
from research_package_acceptance_support import ResearchPackageAcceptanceSupport
import test_issue134_writer_composition as issue134_writer


class FindingCandidateRecoveryTests(ResearchPackageAcceptanceSupport):
    def _legacyize(self, facade, proposal):
        legacy = deepcopy(proposal)
        finding_count = 0
        for action in legacy["proposed_actions"]:
            obj = action.get("payload", {}).get("object", {})
            if obj.get("kind") == "finding":
                finding_count += 1
                obj["adoption_state"] = "candidate"
        self.assertGreater(finding_count, 0)
        legacy.pop("proposal_digest", None)
        legacy["proposal_digest"] = canonical_digest(legacy)
        serialized = facade._application.conversation_store._json(legacy)
        db = facade._application.conversation_store._db
        db.execute(
            "UPDATE state_delta_proposals SET payload_json=? WHERE proposal_id=?",
            (serialized, legacy["proposal_id"]),
        )
        return legacy

    def _advance_head(self, facade):
        proposed = facade.submit_action({
            "action_type": "research_question.propose",
            "payload": {
                "text": "Which later condition advances the recovery-test head?",
                "acceptance_criteria": ["The condition can be inspected."],
                "scope_limits": ["Recovery-test only."],
            },
            "actor_id": "HUMAN-FCR",
        })
        pending = facade.submit_action({
            "action_type": "state.apply_candidate",
            "payload": {"state_delta_proposal_id": proposed["data"]["state_delta_proposal_id"]},
            "actor_id": "HUMAN-FCR",
        })
        confirmed = facade.submit_confirmation({
            "confirmation_request_id": pending["confirmation_request"]["confirmation_request_id"],
            "actor_id": "HUMAN-FCR",
        })
        request = confirmed["decision_request"]
        facade.resolve_human_decision({
            "request_id": request["request_id"],
            "request_digest": request["request_digest"],
            "disposition": "approve_exact",
            "actor_id": "HUMAN-FCR",
        })

    def test_public_cli_recovers_by_run_id_only(self):
        facade, case = self._prepare_case()
        try:
            self._legacyize(facade, case["proposal"])
        finally:
            facade.close()
        input_path = self.root / "recover-input.json"
        input_path.write_text(json.dumps({
            "action_type": "desktop_research.finding.recover",
            "payload": {"run_id": case["run_id"]},
            "actor_id": "HUMAN-FCR-CLI",
        }), encoding="utf-8")
        stream = io.StringIO()
        with redirect_stdout(stream):
            code = cli_main([
                "action", "submit",
                "--workspace", str(self.workspace),
                "--json", str(input_path),
            ])
        self.assertEqual(code, 0)
        payload = json.loads(stream.getvalue())
        self.assertEqual(payload["status"], "SUCCEEDED")
        self.assertEqual(payload["data"]["status"], "RECOVERED")
        self.assertEqual(payload["data"]["run_id"], case["run_id"])
        self.assertFalse(payload["action_receipt"]["research_state_mutation_performed"])

    def test_fcr1_fcr2_public_run_recovery_is_candidate_only_immutable_and_idempotent(self):
        facade, case = self._prepare_case()
        try:
            historical = self._legacyize(facade, case["proposal"])
            state = facade._application.state_repository.load_state_view(
                facade.project_id,
                facade._application.state_repository.load_active_lineage_ref(facade.project_id),
            )
            before = (state.current_snapshot["id"], state.current_snapshot["content_digest"])

            first = facade.recover_legacy_desktop_research_finding_candidate(case["run_id"])
            second = facade.recover_legacy_desktop_research_finding_candidate(case["run_id"])
            self.assertFalse(first["research_state_mutation_performed"])
            self.assertFalse(first["idempotent_reuse"])
            self.assertTrue(second["idempotent_reuse"])
            self.assertEqual(first["state_delta_proposal_id"], second["state_delta_proposal_id"])
            self.assertEqual(
                facade._application.conversation_store.load_state_delta_proposal(historical["proposal_id"]),
                historical,
            )
            recovered = facade._application.conversation_store.load_state_delta_proposal(
                first["state_delta_proposal_id"]
            )
            old_actions = deepcopy(historical["proposed_actions"])
            new_actions = deepcopy(recovered["proposed_actions"])
            for old, new in zip(old_actions, new_actions, strict=True):
                old_obj = old["payload"]["object"]
                new_obj = new["payload"]["object"]
                if old_obj["kind"] == "finding":
                    self.assertEqual(old_obj.pop("adoption_state"), "candidate")
                    self.assertEqual(new_obj.pop("adoption_state"), "approved")
                self.assertEqual(old, new)
            after_state = facade._application.state_repository.load_state_view(
                facade.project_id,
                facade._application.state_repository.load_active_lineage_ref(facade.project_id),
            )
            self.assertEqual(before, (after_state.current_snapshot["id"], after_state.current_snapshot["content_digest"]))
        finally:
            facade.close()

    def test_fcr3_recovered_candidate_uses_existing_confirmation_and_human_decision_flow(self):
        facade, case = self._prepare_case()
        try:
            self._legacyize(facade, case["proposal"])
            recovered = facade.recover_legacy_desktop_research_finding_candidate(case["run_id"])
            pending = facade.submit_action({
                "action_type": "state.apply_candidate",
                "payload": {"state_delta_proposal_id": recovered["state_delta_proposal_id"]},
                "actor_id": "HUMAN-FCR3",
            })
            confirmed = facade.submit_confirmation({
                "confirmation_request_id": pending["confirmation_request"]["confirmation_request_id"],
                "actor_id": "HUMAN-FCR3",
            })
            self.assertEqual(confirmed["status"], "HUMAN_DECISION_REQUIRED")
            request = confirmed["decision_request"]
            facade.resolve_human_decision({
                "request_id": request["request_id"],
                "request_digest": request["request_digest"],
                "disposition": "approve_exact",
                "actor_id": "HUMAN-FCR3",
            })
            facade.close()
            facade = LocalApplicationFacade.open_workspace(self.workspace)
            state = facade._application.state_repository.load_state_view(
                facade.project_id,
                facade._application.state_repository.load_active_lineage_ref(facade.project_id),
            )
            finding = next(obj for obj in state.effective_objects() if obj.get("kind") == "finding")²È="24€€‘ÕÁ±¥…Ñ•l‰ÁÉ½Á½Í…±}‘¥•ÍĞ‰t€ô…¹½¹¥…±}‘¥•ÍĞ¡‘ÕÁ±¥…Ñ”¤(€€€€€€€€€€€ÍÑ½É”€ô™……‘”¹}…ÁÁ±¥…Ñ¥½¸¹½¹Ù•ÉÍ…Ñ¥½¹}ÍÑ½É”(€€€€€€€€€€€ÍÑ½É”¹ÍÑ½É•}ÍÑ…Ñ•}‘•±Ñ…}ÁÉ½Á½Í…°¡‘ÕÁ±¥…Ñ•l‰ÁÉ½Á½Í…±}¥‰t°‘ÕÁ±¥…Ñ”¤((€€€€€€€€€€€É•½Ù•É•€ô™……‘”¹É•½Ù•É}±•…å}‘•Í­Ñ½Á}É•Í•…É¡}™¥¹‘¥¹}…¹‘¥‘…Ñ” (€€€€€€€€€€€€€€€…Í•l‰ÉÕ¹}¥‰t(€€€€€€€€€€€€¤(€€€€€€€€€€€Í•±˜¹…ÍÍ•ÉÑÅÕ…°¡É•½Ù•É•‘l‰É½ÕÑ”‰t°€‰…¹½¹¥…±}É•ÍÕ±Ñ}É•µ…Ñ•É¥…±¥é…Ñ¥½¸ˆ¤(€€€€€€€€€€€ÁÉ½Á½Í…°€ôÍÑ½É”¹±½…‘}ÍÑ…Ñ•}‘•±Ñ…}ÁÉ½Á½Í…° (€€€€€€€€€€€€€€€É•½Ù•É•‘l‰ÍÑ…Ñ•}‘•±Ñ…}ÁÉ½Á½Í…±}¥‰t(€€€€€€€€€€€€¤(€€€€€€€€€€€ÁÉ½Ù•¹…¹”€ôÁÉ½Á½Í…±l‰ÁÉ½Ù•¹…¹”‰ul‰¡¥ÍÑ½É¥…±}É•½Ù•Éä‰t(€€€€€€€€€€€Í•±˜¹…ÍÍ•ÉÑÅÕ…°¡ÁÉ½Ù•¹…¹•l‰É•½Ù•Éå}Í½ÕÉ”‰t°€‰…¹½¹¥…±}É•ÍÕ±Ğˆ¤(€€€€€€€€€€€Í•±˜¹…ÍÍ•ÉÑÅÕ…° (€€€€€€€€€€€€€€€ÁÉ½Ù•¹…¹•l‰¡¥ÍÑ½É¥…±}…¹‘¥‘…Ñ•}±¥¹•…•}ÍÑ…ÑÕÌ‰t°€‰…µ‰¥Õ½ÕÌˆ(€€€€€€€€€€€€¤(€€€€€€€€€€€Í•±˜¹…ÍÍ•ÉÑÅÕ…°¡ÁÉ½Ù•¹…¹•l‰¡¥ÍÑ½É¥…±}…¹‘¥‘…Ñ•}½Õ¹Ğ‰t°€‰µÕ±Ñ¥Á±”ˆ¤(€€€€€€€€€€€Í•±˜¹…ÍÍ•ÉÑÅÕ…° (€€€€€€€€€€€€€€€ÍÑ½É”¹±½…‘}ÍÑ…Ñ•}‘•±Ñ…}ÁÉ½Á½Í…°¡±•…ål‰ÁÉ½Á½Í…±}¥‰t¤°±•…ä(€€€€€€€€€€€€¤(€€€€€€€€€€€Í•±˜¹…ÍÍ•ÉÑÅÕ…° (€€€€€€€€€€€€€€€ÍÑ½É”¹±½…‘}ÍÑ…Ñ•}‘•±Ñ…}ÁÉ½Á½Í…°¡‘ÕÁ±¥…Ñ•l‰ÁÉ½Á½Í…±}¥‰t¤°‘ÕÁ±¥…Ñ”(€€€€€€€€€€€€¤(€€€€€€€™¥¹…±±äè(€€€€€€€€€€€™……‘”¹±½Í” ¤((€€€‘•˜Ñ•ÍÑ}™ÈÑ}½ÉÉÕÁÑ}Õ¹É•½¹¥é•‘}…¹‘}µ¥ÍÍ¥¹}…¹‘¥‘…Ñ•Í}™…¥±}±½Í•¡Í•±˜¤è(€€€€€€€™……‘”°…Í”€ôÍ•±˜¹}ÁÉ•Á…É•}…Í” ¤(€€€€€€€ÑÉäè(€€€€€€€€€€€±•…ä€ôÍ•±˜¹}±•…å¥é”¡™……‘”°…Í•l‰ÁÉ½Á½Í…°‰t¤(€€€€€€€€€€€‘ˆ€ô™……‘”¹}…ÁÁ±¥…Ñ¥½¸¹½¹Ù•ÉÍ…Ñ¥½¹}ÍÑ½É”¹}‘ˆ(€€€€€€€€€€€‰É½­•¸€ô‘••Á½Áä¡±•…ä¤(€€€€€€€€€€€‰É½­•¹l‰É…Ñ¥½¹…±”‰t€ô€‰Ñ…µÁ•É•ˆ(€€€€€€€€€€€‘ˆ¹•á•ÕÑ” (€€€€€€€€€€€€€€€€‰UAQÍÑ…Ñ•}‘•±Ñ…}ÁÉ½Á½Í…±ÌMPÁ…å±½…‘}©Í½¸ôü]!IÁÉ½Á½Í…±}¥ôüˆ°(€€€€€€€€€€€€€€€€¡™……‘”¹}…ÁÁ±¥…Ñ¥½¸¹½¹Ù•ÉÍ…Ñ¥½¹}ÍÑ½É”¹}©Í½¸¡‰É½­•¸¤°‰É½­•¹l‰ÁÉ½Á½Í…±}¥‰t¤°(€€€€€€€€€€€€¤(€€€€€€€€€€€İ¥Ñ Í•±˜¹…ÍÍ•ÉÑI…¥Í•Ì¡1½…±ÁÁ±¥…Ñ¥½¹ÉÉ½È¤…Ì…Õ¡Ğè(€€€€€€€€€€€€€€€™……‘”¹É•½Ù•É}±•…å}‘•Í­Ñ½Á}É•Í•…É¡}™¥¹‘¥¹}…¹‘¥‘…Ñ”¡…Í•l‰ÉÕ¹}¥‰t¤(€€€€€€€€€€€Í•±˜¹…ÍÍ•ÉÑÅÕ…°¡…Õ¡Ğ¹•á•ÁÑ¥½¸¹½‘”°€‰AA1%Q%=8µ%9%9µI=YIdµ%9QI%Qd´ÀÀÄˆ¤((€€€€€€€€€€€‘ˆ¹•á•ÕÑ” ‰1QI=4ÍÑ…Ñ•}‘•±Ñ…}ÁÉ½Á½Í…±Ì]!IÁÉ½Á½Í…±}¥ôüˆ°€¡±•…ål‰ÁÉ½Á½Í…±}¥‰t°¤¤(€€€€€€€€€€€É•µ…Ñ•É¥…±¥é•€ô™……‘”¹É•½Ù•É}±•…å}‘•Í­Ñ½Á}É•Í•…É¡}™¥¹‘¥¹}…¹‘¥‘…Ñ” (€€€€€€€€€€€€€€€…Í•l‰ÉÕ¹}¥‰t(€€€€€€€€€€€€¤(€€€€€€€€€€€Í•±˜¹…ÍÍ•ÉÑÅÕ…° (€€€€€€€€€€€€€€€É•µ…Ñ•É¥…±¥é•‘l‰É½ÕÑ”‰t°€‰…¹½¹¥…±}É•ÍÕ±Ñ}É•µ…Ñ•É¥…±¥é…Ñ¥½¸ˆ(€€€€€€€€€€€€¤(€€€€€€€™¥¹…±±äè(€€€€€€€€€€€™……‘”¹±½Í” ¤((€€€‘•˜Ñ•ÍÑ}™ÈÕ}É•½Ù•É•‘}™¥¹‘¥¹}½¹Ñ¥¹Õ•Í}Ñ¡É½Õ¡}…ÉÕµ•¹Ñ}Á…­…•}…¹‘}Í•}œÅ|ÀÔ¡Í•±˜¤è(€€€€€€€™……‘”°…Í”€ôÍ•±˜¹}ÁÉ•Á…É•}…Í” ¤(€€€€€€€ÑÉäè(€€€€€€€€€€€Í•±˜¹}±•…å¥é”¡™……‘”°…Í•l‰ÁÉ½Á½Í…°‰t¤(€€€€€€€€€€€É•½Ù•É•€ô™……‘”¹É•½Ù•É}±•…å}‘•Í­Ñ½Á}É•Í•…É¡}™¥¹‘¥¹}…¹‘¥‘…Ñ”¡…Í•l‰ÉÕ¹}¥‰t¤(€€€€€€€€€€€Á•¹‘¥¹œ€ô™……‘”¹ÍÕ‰µ¥Ñ}…Ñ¥½¸¡ì(€€€€€€€€€€€€€€€€‰…Ñ¥½¹}ÑåÁ”ˆè€‰ÍÑ…Ñ”¹…ÁÁ±å}…¹‘¥‘…Ñ”ˆ°(€€€€€€€€€€€€€€€€‰Á…å±½…ˆèì‰ÍÑ…Ñ•}‘•±Ñ…}ÁÉ½Á½Í…±}¥ˆèÉ•½Ù•É•‘l‰ÍÑ…Ñ•}‘•±Ñ…}ÁÉ½Á½Í…±}¥‰uô°(€€€€€€€€€€€€€€€€‰…Ñ½É}¥ˆè€‰!U58µHÔˆ°(€€€€€€€€€€€ô¤(€€€€€€€€€€€½¹™¥Éµ•€ô™……‘”¹ÍÕ‰µ¥Ñ}½¹™¥Éµ…Ñ¥½¸¡ì(€€€€€€€€€€€€€€€€‰½¹™¥Éµ…Ñ¥½¹}É•ÅÕ•ÍÑ}¥ˆèÁ•¹‘¥¹l‰½¹™¥Éµ…Ñ¥½¹}É•ÅÕ•ÍĞ‰ul‰½¹™¥Éµ…Ñ¥½¹}É•ÅÕ•ÍÑ}¥‰t°(€€€€€€€€€€€€€€€€‰…Ñ½É}¥ˆè€‰!U58µHÔˆ°(€€€€€€€€€€€ô¤(€€€€€€€€€€€É•ÅÕ•ÍĞ€ô½¹™¥Éµ•‘l‰‘•¥Í¥½¹}É•ÅÕ•ÍĞ‰t(€€€€€€€€€€€™……‘”¹É•Í½±Ù•}¡Õµ…¹}‘•¥Í¥½¸¡ì(€€€€€€€€€€€€€€€€‰É•ÅÕ•ÍÑ}¥ˆèÉ•ÅÕ•ÍÑl‰É•ÅÕ•ÍÑ}¥‰t°(€€€€€€€€€€€€€€€€‰É•ÅÕ•ÍÑ}‘¥•ÍĞˆèÉ•ÅÕ•ÍÑl‰É•ÅÕ•ÍÑ}‘¥•ÍĞ‰t°(€€€€€€€€€€€€€€€€‰‘¥ÍÁ½Í¥Ñ¥½¸ˆè€‰…ÁÁÉ½Ù•}•á…Ğˆ°(€€€€€€€€€€€€€€€€‰…Ñ½É}¥ˆè€‰!U58µHÔˆ°(€€€€€€€€€€€ô¤(€€€€€€€€€€€ÍÑ…Ñ”€ô™……‘”¹}…ÁÁ±¥…Ñ¥½¸¹ÍÑ…Ñ•}É•Á½Í¥Ñ½Éä¹±½…‘}ÍÑ…Ñ•}Ù¥•Ü (€€€€€€€€€€€€€€€™……‘”¹ÁÉ½©•Ñ}¥°(€€€€€€€€€€€€€€€™……‘”¹}…ÁÁ±¥…Ñ¥½¸¹ÍÑ…Ñ•}É•Á½Í¥Ñ½Éä¹±½…‘}…Ñ¥Ù•}±¥¹•…•}É•˜¡™……‘”¹ÁÉ½©•Ñ}¥¤°(€€€€€€€€€€€€¤(€€€€€€€€€€€™¥¹‘¥¹œ€ô¹•áĞ¡½‰¨™½È½‰¨¥¸ÍÑ…Ñ”¹•™™•Ñ¥Ù•}½‰©•ÑÌ ¤¥˜½‰¨¹•Ğ ‰­¥¹ˆ¤€ôô€‰™¥¹‘¥¹œˆ¤(€€€€€€€€€€€•Ù¥‘•¹”€ô¹•áĞ¡½‰¨™½È½‰¨¥¸ÍÑ…Ñ”¹•™™•Ñ¥Ù•}½‰©•ÑÌ ¤¥˜½‰¨¹•Ğ ‰­¥¹ˆ¤€ôô€‰•Ù¥‘•¹”ˆ¤(€€€€€€€€€€€Í½ÕÉ”€ô¹•áĞ¡½‰¨™½È½‰¨¥¸ÍÑ…Ñ”¹•™™•Ñ¥Ù•}½‰©•ÑÌ ¤¥˜½‰¨¹•Ğ ‰­¥¹ˆ¤€ôô€‰Í½ÕÉ”ˆ¤(€€€€€€€€€€€ÁÉ½Á½Í•€ô™……‘”¹ÍÕ‰µ¥Ñ}…Ñ¥½¸¡ì(€€€€€€€€€€€€€€€€‰…Ñ¥½¹}ÑåÁ”ˆè€‰É•Í•…É ¹…ÉÕµ•¹Ğ¹ÁÉ½Á½Í”ˆ°(€€€€€€€€€€€€€€€€‰Á…å±½…ˆèì(€€€€€€€€€€€€€€€€€€€€‰½¹±ÕÍ¥½¸ˆè€‰Q¡”É•½Ù•É•¥¹‘¥¹œÍÕÁÁ½ÉÑÌÑ¡”‰½Õ¹‘•Ù…±¥‘…Ñ¥½¸½¹±ÕÍ¥½¸¸ˆ°(€€€€€€€€€€€€€€€€€€€€‰İ…ÉÉ…¹Ğˆè€‰Q¡”…ÁÁÉ½Ù•¥¹‘¥¹œ…¹Ù¥‘•¹”É•Í½±Ù”¥¸Ñ¡”•á…ĞÕÉÉ•¹ĞM¹…ÁÍ¡½Ğ¸ˆ°(€€€€€€€€€€€€€€€€€€€€‰ÅÕ•ÍÑ¥½¹}¥‘Ìˆèm…Í•l‰ÉÅ}¥‰ut°(€€€€€€€€€€€€€€€€€€€€‰™¥¹‘¥¹}¥‘Ìˆèm™¥¹‘¥¹l‰¥‰ut°(€€€€€€€€€€€€€€€€€€€€‰•Ù¥‘•¹•}¥‘Ìˆèm•Ù¥‘•¹•l‰¥‰ut°(€€€€€€€€€€€€€€€€€€€€‰ÅÕ…±¥™¥•Èˆè€‰]¥Ñ¡¥¸Ñ¡”…ÁÑÕÉ•Í½ÕÉ”Í½Á”¸ˆ°(€€€€€€€€€€€€€€€ô°(€€€€€€€€€€€€€€€€‰…Ñ½É}¥ˆè€‰!U58µHÔˆ°(€€€€€€€€€€€ô¤(€€€€€€€€€€€…É}Á•¹‘¥¹œ€ô™……‘”¹ÍÕ‰µ¥Ñ}…Ñ¥½¸¡ì(€€€€€€€€€€€€€€€€‰…Ñ¥½¹}ÑåÁ”ˆè€‰ÍÑ…Ñ”¹…ÁÁ±å}…¹‘¥‘…Ñ”ˆ°(€€€€€€€€€€€€€€€€‰Á…å±½…ˆèì‰ÍÑ…Ñ•}‘•±Ñ…}ÁÉ½Á½Í…±}¥ˆèÁÉ½Á½Í•‘l‰‘…Ñ„‰ul‰ÍÑ…Ñ•}‘•±Ñ…}ÁÉ½Á½Í…±}¥‰uô°(€€€€€€€€€€€€€€€€‰…Ñ½É}¥ˆè€‰!U58µHÔˆ°(€€€€€€€€€€€ô¤(€€€€€€€€€€€½µµ¥ÑÑ•€ô™……‘”¹ÍÕ‰µ¥Ñ}½¹™¥Éµ…Ñ¥½¸¡ì(€€€€€€€€€€€€€€€€‰½¹™¥Éµ…Ñ¥½¹}É•ÅÕ•ÍÑ}¥ˆè…É}Á•¹‘¥¹l‰½¹™¥Éµ…Ñ¥½¹}É•ÅÕ•ÍĞ‰ul‰½¹™¥Éµ…Ñ¥½¹}É•ÅÕ•ÍÑ}¥‰t°(€€€€€€€€€€€€€€€€‰…Ñ½É}¥ˆè€‰!U58µHÔˆ°(€€€€€€€€€€€ô¤(€€€€€€€€€€€Í•±˜¹…ÍÍ•ÉÑÅÕ…°¡½µµ¥ÑÑ•‘l‰ÍÑ…ÑÕÌ‰t°€‰MUˆ¤(€€€€€€€€€€€…ÉÕµ•¹Ñ}¥€ôÁÉ½Á½Í•‘l‰‘…Ñ„‰ul‰…ÉÕµ•¹Ñ}…¹‘¥‘…Ñ”‰ul‰¥‰t(€€€€€€€€€€€ÕÉÉ•¹Ğ€ô™……‘”¹}…ÁÁ±¥…Ñ¥½¸¹ÍÑ…Ñ•}É•Á½Í¥Ñ½Éä¹±½…‘}ÍÑ…Ñ•}Ù¥•Ü (€€€€€€€€€€€€€€€™……‘”¹ÁÉ½©•Ñ}¥°(€€€€€€€€€€€€€€€™……‘”¹}…ÁÁ±¥…Ñ¥½¸¹ÍÑ…Ñ•}É•Á½Í¥Ñ½Éä¹±½…‘}…Ñ¥Ù•}±¥¹•…•}É•˜¡™……‘”¹ÁÉ½©•Ñ}¥¤°(€€€€€€€€€€€€¤(€€€€€€€€€€€‰Õ¥±Ğ€ô™……‘”¹‰Õ¥±‘}É•Í•…É¡}Á…­…”¡ì(€€€€€€€€€€€€€€€€¨©…Í•l‰‰Õ¥±‘}¥¹ÁÕĞ‰t°(€€€€€€€€€€€€€€€€‰Í¹…ÁÍ¡½Ñ}¥ˆèÕÉÉ•¹Ğ¹ÕÉÉ•¹Ñ}Í¹…ÁÍ¡½Ñl‰¥‰t°(€€€€€€€€€€€€€€€€‰Í¹…ÁÍ¡½Ñ}‘¥•ÍĞˆèÕÉÉ•¹Ğ¹ÕÉÉ•¹Ñ}Í¹…ÁÍ¡½Ñl‰½¹Ñ•¹Ñ}‘¥•ÍĞ‰t°(€€€€€€€€€€€€€€€€‰±¥¹•…•}É•˜ˆèÕÉÉ•¹Ğ¹…Ñ¥Ù•}±¥¹•…•}É•˜°(€€€€€€€€€€€€€€€€‰½‰©•Ñ}¥‘ÌˆèmÍ½ÕÉ•l‰¥‰t°•Ù¥‘•¹•l‰¥‰t°™¥¹‘¥¹l‰¥‰t°…ÉÕµ•¹Ñ}¥‘t°(€€€€€€€€€€€ô¥l‰Á…­…”‰t(€€€€€€€€€€€½µÁ½Í¥Ñ¥½¸€ô™……‘”¹…ÁÑÕÉ•}İÉ¥Ñ•É}½µÁ½Í¥Ñ¥½¸ (€€€€€€€€€€€€€€€‰Õ¥±Ñl‰Á…­…•}¥‰t°(€€€€€€€€€€€€€€€¥ÍÍÕ”ÄÌÑ}İÉ¥Ñ•È¹%ÍÍÕ”ÄÌÑ]É¥Ñ•É½µÁ½Í¥Ñ¥½¹I•½Ù•ÉåQ•ÍÑÌ¹}ÁÉ½Á½Í…° (€€€€€€€€€€€€€€€€€€€…Í”°…ÉÕµ•¹Ñ}¥°™¥¹‘¥¹l‰¥‰t°•Ù¥‘•¹•l‰¥‰t(€€€€€€€€€€€€€€€€¤°(€€€€€€€€€€€€¥l‰½µÁ½Í¥Ñ¥½¸‰t(€€€€€€€€€€€Í•±˜¹…ÍÍ•ÉÑ…±Í”¡…¹ä (€€€€€€€€€€€€€€€¥Ñ•´¹•Ğ ‰Í•Ñ¥½¹}¥ˆ¤€ôô€‰MµÄ´ÀÔˆ(€€€€€€€€€€€€€€€…¹¥Ñ•´¹•Ğ ‰½‘”ˆ¤€ôô€‰]I%QHµ=5A=M%Q%=8µ9IIQ%YµU95Pˆ(€€€€€€€€€€€€€€€™½È¥Ñ•´¥¸½µÁ½Í¥Ñ¥½¹l‰Ù…±¥‘…Ñ¥½¸‰ul‰‘¥…¹½ÍÑ¥Ì‰t(€€€€€€€€€€€€¤¤(€€€€€€€€€€€™……‘”¹Í•±•Ñ}İÉ¥Ñ•É}½µÁ½Í¥Ñ¥½¸ (€€€€€€€€€€€€€€€½µÁ½Í¥Ñ¥½¹l‰½µÁ½Í¥Ñ¥½¹}¥‰t°€Ä°½µÁ½Í¥Ñ¥½¹l‰½µÁ½Í¥Ñ¥½¹}‘¥•ÍĞ‰t(€€€€€€€€€€€€¤(€€€€€€€€€€€½ÕÑÁÕĞ€ôÍ•±˜¹É½½Ğ€¼€‰™ÈÔµÍ•ŒµœÄ´ÀÔˆ(€€€€€€€€€€€™……‘”¹•áÁ½ÉÑ}İÉ¥Ñ•É}Í•Ñ¥½¹}¥¹ÁÕĞ (€€€€€€€€€€€€€€€½µÁ½Í¥Ñ¥½¹l‰½µÁ½Í¥Ñ¥½¹}¥‰t°€‰MµÄ´ÀÔˆ°½ÕÑÁÕĞ(€€€€€€€€€€€€¤(€€€€€€€€€€€‘•Ñ…¡•€ô©Í½¸¹±½…‘Ì ¡½ÕÑÁÕĞ€¼€‰Í•Ñ¥½¸µİÉ¥Ñ•Èµ¥¹ÁÕĞ¹©Í½¸ˆ¤¹É•…‘}Ñ•áĞ¡•¹½‘¥¹œô‰ÕÑ˜´àˆ¤¤(€€€€€€€€€€€Í•±˜¹…ÍÍ•ÉÑ%¸¡…ÉÕµ•¹Ñ}¥°‘•Ñ…¡•‘l‰É•Í½±Ù•‘}½‰©•Ñ}¥‘Ì‰t¤(€€€€€€€€€€€Í•±˜¹…ÍÍ•ÉÑ%¸¡™¥¹‘¥¹l‰¥‰t°‘•Ñ…¡•‘l‰É•Í½±Ù•‘}½‰©•Ñ}¥‘Ì‰t¤(€€€€€€€™¥¹…±±äè(€€€€€€€€€€€™……‘”¹±½Í” ¤((€€€‘•˜Ñ•ÍÑ}™ÈÙ}ÕÉÉ•¹Ñ}…ÁÁÉ½Ù•‘}Í¡…Á•}¥Í}¹½Ñ}É•İÉ¥ÑÑ•¸¡Í•±˜¤è(€€€€€€€™……‘”°…Í”€ôÍ•±˜¹}ÁÉ•Á…É•}…Í” ¤(€€€€€€€ÑÉäè(€€€€€€€€€€€İ¥Ñ Í•±˜¹…ÍÍ•ÉÑI…¥Í•Ì¡1½…±ÁÁ±¥…Ñ¥½¹ÉÉ½È¤…Ì…Õ¡Ğè(€€€€€€€€€€€€€€€™……‘”¹É•½Ù•É}±•…å}‘•Í­Ñ½Á}É•Í•…É¡}™¥¹‘¥¹}…¹‘¥‘…Ñ”¡…Í•l‰ÉÕ¹}¥‰t¤(€€€€€€€€€€€Í•±˜¹…ÍÍ•ÉÑÅÕ…°¡…Õ¡Ğ¹•á•ÁÑ¥½¸¹½‘”°€‰AA1%Q%=8µ%9%9µI=YIdµM!A´ÀÀÄˆ¤(€€€€€€€™¥¹…±±äè(€€€€€€€€€€€™……‘”¹±½Í” ¤(