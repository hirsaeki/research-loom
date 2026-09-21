from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
from threading import Barrier
import tempfile
import unittest
from unittest.mock import patch

from plugins.local_application import LocalApplicationError, LocalApplicationFacade, LocalResearchApplication
from plugins.local_delphi_store import LocalDelphiStore, LocalDelphiStoreError
from tests.runtime.test_delphi_two_round_production import make_app, design, instrument, response, with_digest, approve_instrument
from tests.runtime.test_survey_production import NullResolver, profile_provider, state_signature
from tests.runtime.test_local_workspace_application_cli import run_cli
from tests.runtime.test_research_question_adoption import _init_workspace, _proposal_input


def proposal(inst, *, panel="PANEL-1", derived=None):
    value = {"delphi_design_id": "DLD-1", "delphi_design_version": "1.0.0", "panel_id": panel, "instrument": inst}
    if derived is not None:
        value["derived_from"] = derived
    return value


def round_input(inst, responses, *, panel="PANEL-1", expected=None):
    return {"panel_id": panel, "instrument_id": inst["instrument_id"], "instrument_version": inst["version"],
            "instrument_digest": inst["content_digest"], "expected_participant_ids": expected or ["P1", "P2", "P3"], "responses": responses}


def approval_response(request, *, choice="approve_exact"):
    return {"request_id": request["request_id"], "request_digest": request["request_digest"],
            "actor": {"actor_id": "operator", "actor_type": "human"}, "choice": choice}


def derived_from(inst, result, feedback):
    return {"prior_instrument_id": inst["instrument_id"], "prior_instrument_version": inst["version"],
            "prior_instrument_digest": inst["content_digest"], "prior_round_result_id": result["round_result_id"],
            "prior_round_result_version": result["round_result_version"], "prior_round_result_digest": result["content_digest"],
            "feedback_id": feedback["feedback_id"], "feedback_digest": feedback["content_digest"]}


class Issue252DelphiLifecycleTests(unittest.TestCase):
    def fixture(self, root):
        app = make_app(root)
        facade = LocalApplicationFacade(app, "PRJ-1")
        facade.capture_delphi_design({"rq_ids": ["RQ-1"], "panel_id": "PANEL-1", "design": design()})
        return app, facade

    def test_fresh_workspace_public_approval_and_late_results_through_cli(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = _init_workspace(Path(temp))
            with LocalApplicationFacade.open_workspace(workspace) as facade:
                proposed = facade.submit_action(_proposal_input())
                rq_id = proposed["data"]["research_question_candidate"]["id"]
                applied = facade.submit_action({"action_type": "state.apply_candidate", "payload": {"state_delta_proposal_id": proposed["data"]["state_delta_proposal_id"]}, "actor_id": "HUMAN-RQ"})
                decision = facade.submit_confirmation({"confirmation_request_id": applied["confirmation_request"]["confirmation_request_id"], "actor_id": "HUMAN-RQ"})["decision_request"]
                self.assertEqual(facade.resolve_human_decision({"request_id": decision["request_id"], "request_digest": decision["request_digest"], "disposition": "approve_exact", "actor_id": "HUMAN-RQ"})["status"], "RESOLVED")
                before = facade.status()["snapshot"]

            def cli(words, value=None):
                arguments = ["delphi", *words, "--workspace", str(workspace), "--json"]
                if value is not None:
                    arguments.append("-")
                code, raw, result = run_cli(arguments, "" if value is None else json.dumps(value))
                self.assertEqual(code, 0, raw)
                return result

            cli(["design", "capture"], {"rq_ids": [rq_id], "panel_id": "PANEL-1", "design": design()})
            inst = instrument(1)
            inst["items"][0]["traceability"]["research_question_ids"] = [rq_id]
            request = cli(["instrument", "approval-request"], {**proposal(inst), "human_actor_id": "operator"})
            self.assertEqual(cli(["instrument", "approval-show", "--request-id", request["request_id"]])["status"], "PENDING")
            cli(["instrument", "approval-resolve"], approval_response(request))
            inst = request["request"]["target_document"]["instrument"]
            r1 = cli(["round", "capture"], round_input(inst, [response("R1-P1", "P1", 1, 2, "first")]))
            later = round_input(inst, [response("R1-P1", "P1", 1, 2, "first"), response("R1-P2", "P2", 1, 4, "late")])
            r2 = cli(["round", "capture"], later)
            self.assertEqual((r1["round_result_version"], r2["round_result_version"]), ("1", "2"))
            self.assertEqual(cli(["round", "show", "--round-result-id", r1["round_result_id"], "--version", "1"])["delphi_round"]["content_digest"], r1["content_digest"])
            self.assertEqual(cli(["round", "capture"], later)["round_result_version"], "2")
            f1 = cli(["feedback", "build", "--round-result-id", r1["round_result_id"], "--version", "1"])
            f2 = cli(["feedback", "build", "--round-result-id", r1["round_result_id"], "--version", "2"])
            self.assertNotEqual(f1["feedback_id"], f2["feedback_id"])
            self.assertTrue(cli(["instrument", "approval-resolve"], approval_response(request))["idempotent_reuse"])
            with LocalApplicationFacade.open_workspace(workspace) as facade:
                self.assertEqual(facade.status()["snapshot"], before)

    def test_exact_request_reuse_and_version_content_panel_project_separation(self):
        with tempfile.TemporaryDirectory() as temp:
            app, facade = self.fixture(temp)
            try:
                original = instrument(1)
                request = facade.request_delphi_instrument_approval({**proposal(original), "human_actor_id": "operator"})
                self.assertEqual(facade.request_delphi_instrument_approval({**proposal(original), "human_actor_id": "operator"})["request"], request["request"])
                approved = facade.resolve_delphi_instrument_approval(approval_response(request))
                self.assertEqual(approved["status"], "APPROVED")
                inst = request["request"]["target_document"]["instrument"]
                self.assertEqual(facade.capture_delphi_instrument(proposal(inst))["status"], "ALREADY_CAPTURED")
                for field in ("version", "text", "decision"):
                    bad = deepcopy(inst)
                    if field == "version":
                        bad["version"] = "2.0.0"
                    elif field == "text":
                        bad["items"][0]["text"] = "different question"
                    else:
                        bad["approval_decision_id"] = "DLDEC-unknown"
                    bad = with_digest(bad)
                    with self.subTest(field=field), self.assertRaises(LocalApplicationError) as caught:
                        facade.capture_delphi_instrument(proposal(bad))
                    self.assertEqual(caught.exception.code, "APPLICATION-DELPHI-AUTHORITY-001")
                other_design = design(); other_design["delphi_design_id"] = "DLD-OTHER"
                facade.capture_delphi_design({"rq_ids": ["RQ-1"], "panel_id": "OTHER", "design": with_digest(other_design)})
                with self.assertRaises(LocalApplicationError):
                    facade.capture_delphi_instrument({**proposal(inst, panel="OTHER"), "delphi_design_id": "DLD-OTHER"})
                foreign = LocalApplicationFacade(app, "PRJ-OTHER")
                with self.assertRaises(LocalApplicationError):
                    foreign.resolve_delphi_instrument_approval(approval_response(request))
                self.assertEqual(facade.show_delphi_instrument(inst["instrument_id"], inst["version"])["delphi_instrument"], request["request"]["target_document"])
            finally:
                app.close()

    def test_actor_digest_decline_and_conflicting_response(self):
        with tempfile.TemporaryDirectory() as temp:
            app, facade = self.fixture(temp)
            try:
                request = facade.request_delphi_instrument_approval({**proposal(instrument(1)), "human_actor_id": "operator"})
                for change in ({"actor": {"actor_id": "operator", "actor_type": "agent"}}, {"actor": {"actor_id": "other", "actor_type": "human"}}, {"request_digest": "sha256:" + "0" * 64}):
                    with self.assertRaises(LocalApplicationError) as caught:
                        facade.resolve_delphi_instrument_approval({**approval_response(request), **change})
                    self.assertEqual(caught.exception.code, "APPLICATION-DELPHI-AUTHORITY-001")
                declined = facade.resolve_delphi_instrument_approval(approval_response(request, choice="decline"))
                self.assertEqual(declined["status"], "DECLINED")
                self.assertTrue(facade.resolve_delphi_instrument_approval(approval_response(request, choice="decline"))["idempotent_reuse"])
                with self.assertRaises(LocalApplicationError):
                    facade.resolve_delphi_instrument_approval(approval_response(request))
                with self.assertRaises(LocalApplicationError):
                    facade.show_delphi_instrument("DLI-R1", "1.0.0")
            finally:
                app.close()

    def test_approval_write_interruption_rolls_back_both_effects_and_reopens(self):
        with tempfile.TemporaryDirectory() as temp:
            app, facade = self.fixture(temp)
            request = facade.request_delphi_instrument_approval({**proposal(instrument(1)), "human_actor_id": "operator"})
            original_insert = LocalDelphiStore._insert_on
            def fail_receipt(con, document):
                if document["document_kind"] == "approval_receipt":
                    raise OSError("simulated interruption after Instrument write")
                original_insert(con, document)
            try:
                with patch.object(LocalDelphiStore, "_insert_on", side_effect=fail_receipt), self.assertRaises(OSError):
                    facade.resolve_delphi_instrument_approval(approval_response(request))
                self.assertEqual(facade.show_delphi_instrument_approval(request["request_id"])["status"], "PENDING")
                with self.assertRaises(LocalApplicationError):
                    facade.show_delphi_instrument("DLI-R1", "1.0.0")
            finally:
                app.close()
            reopened = LocalResearchApplication(temp, resolver=NullResolver(), effective_profile_set_provider=profile_provider)
            try:
                facade = LocalApplicationFacade(reopened, "PRJ-1")
                self.assertEqual(facade.resolve_delphi_instrument_approval(approval_response(request))["status"], "APPROVED")
                self.assertTrue(facade.resolve_delphi_instrument_approval(approval_response(request))["idempotent_reuse"])
            finally:
                reopened.close()

    def test_response_loss_reuses_committed_approval(self):
        with tempfile.TemporaryDirectory() as temp:
            app, facade = self.fixture(temp)
            try:
                request = facade.request_delphi_instrument_approval({**proposal(instrument(1)), "human_actor_id": "operator"})
                original = LocalDelphiStore.resolve_approval
                def lose_reply(store, *args):
                    original(store, *args)
                    raise OSError("reply lost after commit")
                with patch.object(LocalDelphiStore, "resolve_approval", lose_reply), self.assertRaises(OSError):
                    facade.resolve_delphi_instrument_approval(approval_response(request))
                self.assertTrue(facade.resolve_delphi_instrument_approval(approval_response(request))["idempotent_reuse"])
                self.assertEqual(facade.show_delphi_instrument("DLI-R1", "1.0.0")["delphi_instrument"], request["request"]["target_document"])
            finally:
                app.close()

    def test_concurrent_requests_resolutions_and_round_retries_do_not_fork(self):
        with tempfile.TemporaryDirectory() as temp:
            app, first = self.fixture(temp)
            def concurrent(method, value):
                barrier = Barrier(2)
                def worker(_):
                    # Each execution context owns its SQLite connections.
                    worker_app = LocalResearchApplication(temp, resolver=NullResolver(), effective_profile_set_provider=profile_provider)
                    try:
                        facade = LocalApplicationFacade(worker_app, "PRJ-1")
                        barrier.wait(timeout=5)
                        return getattr(facade, method)(deepcopy(value))
                    finally:
                        worker_app.close()
                with ThreadPoolExecutor(max_workers=2) as pool:
                    return list(pool.map(worker, range(2)))
            try:
                payload = {**proposal(instrument(1)), "human_actor_id": "operator"}
                requests = concurrent("request_delphi_instrument_approval", payload)
                self.assertEqual(requests[0]["request"], requests[1]["request"])
                resolutions = concurrent("resolve_delphi_instrument_approval", approval_response(requests[0]))
                self.assertEqual(sum(not r["idempotent_reuse"] for r in resolutions), 1)
                inst = requests[0]["request"]["target_document"]["instrument"]
                initial = round_input(inst, [response("R1-P1", "P1", 1, 2, "first")])
                first.capture_delphi_round(initial)
                later = deepcopy(initial); later["responses"].append(response("R1-P2", "P2", 1, 4, "late"))
                rounds = concurrent("capture_delphi_round", later)
                self.assertEqual([r["round_result_version"] for r in rounds], ["2", "2"])
                self.assertEqual(sorted(r["status"] for r in rounds), ["ALREADY_CAPTURED", "CAPTURED"])
                later["responses"].reverse(); later["expected_participant_ids"].reverse()
                self.assertEqual(first.capture_delphi_round(later)["round_result_version"], "2")
                self.assertEqual(first.capture_delphi_round(initial)["round_result_version"], "1")
                self.assertEqual(len(first.inspect_delphi_panel("PANEL-1")["rounds"]), 2)
            finally:
                app.close()

    def test_late_response_revision_preserves_old_answers_and_rolls_back_interruption(self):
        with tempfile.TemporaryDirectory() as temp:
            app, facade = self.fixture(temp)
            try:
                inst = instrument(1); approve_instrument(facade, proposal(inst))
                initial = round_input(inst, [response("R1-P1", "P1", 1, 2, "first")])
                first = facade.capture_delphi_round(initial)
                old = facade.show_delphi_round(first["round_result_id"])["delphi_round"]
                later = deepcopy(initial); later["responses"].append(response("R1-P2", "P2", 1, 4, "late"))
                insert = LocalDelphiStore._insert_on
                def fail_round(con, document):
                    insert(con, document)
                    if document["document_kind"] == "round":
                        raise OSError("interrupted before commit")
                with patch.object(LocalDelphiStore, "_insert_on", side_effect=fail_round), self.assertRaises(OSError):
                    facade.capture_delphi_round(later)
                self.assertEqual(len(facade.inspect_delphi_panel("PANEL-1")["rounds"]), 1)
                second = facade.capture_delphi_round(later)
                self.assertEqual(second["round_result_version"], "2")
                changed = deepcopy(later); changed["responses"][0]["answers"][0]["rating"] = 5
                with self.assertRaises(LocalApplicationError):
                    facade.capture_delphi_round(changed)
                removed = deepcopy(later); removed["responses"].pop(0)
                with self.assertRaises(LocalApplicationError):
                    facade.capture_delphi_round(removed)
                self.assertEqual(facade.show_delphi_round(first["round_result_id"])["delphi_round"], old)
            finally:
                app.close()

    def test_feedback_and_round2_bind_exact_result_versions_not_latest(self):
        with tempfile.TemporaryDirectory() as temp:
            app, facade = self.fixture(temp)
            try:
                inst = instrument(1); approve_instrument(facade, proposal(inst))
                values = [response("R1-P1", "P1", 1, 2, "first")]
                r1 = facade.capture_delphi_round(round_input(inst, values))
                values.append(response("R1-P2", "P2", 1, 4, "late"))
                r2 = facade.capture_delphi_round(round_input(inst, values))
                feedbacks = [facade.build_delphi_feedback(r1["round_result_id"], version) for version in ("1", "2")]
                self.assertNotEqual(feedbacks[0]["feedback_id"], feedbacks[1]["feedback_id"])
                old_feedback = facade.show_delphi_feedback(feedbacks[0]["feedback_id"])
                result2 = []
                for index, (result, feedback) in enumerate(zip((r1, r2), feedbacks)):
                    revised = instrument(2, version=f"1.{index}.0", feedback_id=feedback["feedback_id"], feedback_digest=feedback["content_digest"])
                    approve_instrument(facade, proposal(revised, derived=derived_from(inst, result, feedback)))
                    captured = facade.capture_delphi_round(round_input(revised, [response(f"R2-{index}", "P1", 2, 3, "second round")]))
                    self.assertEqual(captured["analysis"]["comparison_basis"]["version"], result["round_result_version"])
                    self.assertEqual(captured["analysis"]["attrition_count"], index)
                    result2.append(captured)
                with self.assertRaises(LocalApplicationError):
                    facade.build_delphi_stopping_candidate("PANEL-1")
                for result in result2:
                    stopping = facade.build_delphi_stopping_candidate("PANEL-1", round_result_id=result["round_result_id"], version=result["round_result_version"])
                    self.assertEqual(stopping["round2_result_version"], result["round_result_version"])
                    self.assertTrue(stopping["candidate_only"])
                bad = instrument(2, version="1.2.0", feedback_id=feedbacks[0]["feedback_id"], feedback_digest=feedbacks[0]["content_digest"])
                with self.assertRaises(LocalApplicationError) as caught:
                    facade.request_delphi_instrument_approval({**proposal(bad, derived=derived_from(inst, r2, feedbacks[0])), "human_actor_id": "operator"})
                self.assertEqual(caught.exception.code, "APPLICATION-DELPHI-LINEAGE-001")
                self.assertEqual(facade.show_delphi_feedback(feedbacks[0]["feedback_id"]), old_feedback)
            finally:
                app.close()

    def test_bounded_inspection_and_invalid_result_versions(self):
        with tempfile.TemporaryDirectory() as temp:
            app, facade = self.fixture(temp)
            try:
                inst = instrument(1); approve_instrument(facade, proposal(inst))
                result = facade.capture_delphi_round(round_input(inst, [response("R1-P1", "P1", 1, 3, "first")]))
                all_rows, offset = [], 0
                while True:
                    page = facade.inspect_delphi_panel("PANEL-1", limit=1, offset=offset)
                    self.assertLessEqual(len(page["documents"]), 1)
                    all_rows.extend(page["documents"])
                    if not page["truncated"]:
                        break
                    offset = page["next_offset"]
                self.assertEqual(len({(r["document_kind"], r["identity"], r["version"]) for r in all_rows}), len(all_rows))
                self.assertEqual(len(all_rows), 5)
                for version in ("0", "-1", "01", "x", 1, True):
                    with self.subTest(version=version), self.assertRaises(LocalApplicationError):
                        facade.show_delphi_round(result["round_result_id"], version)
                for limits in ({"limit": 0}, {"limit": 101}, {"limit": True}, {"offset": -1}):
                    with self.assertRaises(LocalApplicationError):
                        facade.inspect_delphi_panel("PANEL-1", **limits)
                self.assertEqual(facade.inspect_delphi_panel("unknown")["documents"], [])
                self.assertEqual(facade.recalculate_delphi_round(result["round_result_id"])["round_result_version"], "1")
            finally:
                app.close()

    def test_stale_pending_approval_cannot_authorize_but_can_be_declined(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = _init_workspace(Path(temp))
            with LocalApplicationFacade.open_workspace(workspace) as facade:
                def adopt_question():
                    proposed = facade.submit_action(_proposal_input())
                    applied = facade.submit_action({"action_type": "state.apply_candidate", "payload": {"state_delta_proposal_id": proposed["data"]["state_delta_proposal_id"]}, "actor_id": "HUMAN-RQ"})
                    decision = facade.submit_confirmation({"confirmation_request_id": applied["confirmation_request"]["confirmation_request_id"], "actor_id": "HUMAN-RQ"})["decision_request"]
                    facade.resolve_human_decision({"request_id": decision["request_id"], "request_digest": decision["request_digest"], "disposition": "approve_exact", "actor_id": "HUMAN-RQ"})
                    return proposed["data"]["research_question_candidate"]["id"]
                rq_id = adopt_question()
                facade.capture_delphi_design({"rq_ids": [rq_id], "panel_id": "PANEL-1", "design": design()})
                inst = instrument(1); inst["items"][0]["traceability"]["research_question_ids"] = [rq_id]
                payload = {**proposal(inst), "human_actor_id": "operator"}
                pending = facade.request_delphi_instrument_approval(payload)
                adopt_question()
                with self.assertRaises(LocalApplicationError) as caught:
                    facade.resolve_delphi_instrument_approval(approval_response(pending))
                self.assertEqual(caught.exception.code, "APPLICATION-DELPHI-STALE-001")
                self.assertEqual(facade.resolve_delphi_instrument_approval(approval_response(pending, choice="decline"))["status"], "DECLINED")
                current = facade.request_delphi_instrument_approval(payload)
                self.assertNotEqual(current["request_id"], pending["request_id"])
                facade.resolve_delphi_instrument_approval(approval_response(current))
                adopt_question()
                self.assertTrue(facade.resolve_delphi_instrument_approval(approval_response(current))["idempotent_reuse"])

    def test_receipt_self_digest_cannot_replace_exact_request_binding(self):
        with tempfile.TemporaryDirectory() as temp:
            app, facade = self.fixture(temp)
            try:
                request = facade.request_delphi_instrument_approval({**proposal(instrument(1)), "human_actor_id": "operator"})
                facade.resolve_delphi_instrument_approval(approval_response(request))
                target = request["request"]["target_document"]
                original_load = LocalDelphiStore.load
                from plugins.local_delphi_store import canonical_digest, registry_digest
                for field in ("actor", "target_digest", "status"):
                    def tampered(store, project, kind, identity, version="1"):
                        document = original_load(store, project, kind, identity, version)
                        if document is not None and kind == "approval_receipt":
                            if field == "actor":
                                document["actor"]["actor_id"] = "different-human"
                            elif field == "target_digest":
                                document["target_digest"] = "sha256:" + "1" * 64
                            else:
                                document["status"] = "DECLINED"
                            document["response_digest"] = canonical_digest({key: document[key] for key in ("request_id", "request_digest", "actor", "choice")})
                            document["content_digest"] = document["response_digest"]
                            document["registry_digest"] = registry_digest(document)
                        return document
                    with self.subTest(field=field), patch.object(LocalDelphiStore, "load", tampered):
                        with self.assertRaises(LocalApplicationError):
                            facade.show_delphi_instrument_approval(request["request_id"])
                        with self.assertRaises(LocalApplicationError):
                            facade.capture_delphi_round(round_input(target["instrument"], [response("A", "P1", 1, 3, "valid answer")]))
                self.assertEqual(facade.show_delphi_instrument_approval(request["request_id"])["status"], "APPROVED")
            finally:
                app.close()

    def test_missing_approved_target_is_not_recreated_from_its_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            app, facade = self.fixture(temp)
            try:
                request = facade.request_delphi_instrument_approval({**proposal(instrument(1)), "human_actor_id": "operator"})
                facade.resolve_delphi_instrument_approval(approval_response(request))
                store = facade._delphi_store()
                import sqlite3
                with closing(sqlite3.connect(store.path)) as con:
                    with con:
                        con.execute("DELETE FROM delphi_documents WHERE kind='instrument'")
                with self.assertRaises(LocalApplicationError):
                    facade.show_delphi_instrument_approval(request["request_id"])
                with self.assertRaises(LocalApplicationError):
                    facade.resolve_delphi_instrument_approval(approval_response(request))
                self.assertIsNone(store.load("PRJ-1", "instrument", "DLI-R1", "1.0.0"))
            finally:
                app.close()

    def test_schema_publication_failure_does_not_expose_an_empty_or_repaired_database(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_app(temp)
            try:
                facade = LocalApplicationFacade(app, "PRJ-1")
                payload = {"rq_ids": ["RQ-1"], "panel_id": "PANEL-1", "design": design()}
                with patch("plugins.local_delphi_store.os.link", side_effect=PermissionError("publication denied")):
                    with self.assertRaises(LocalApplicationError) as caught:
                        facade.capture_delphi_design(payload)
                self.assertEqual(caught.exception.code, "DELPHI-STORE-DB-001")
                self.assertFalse(facade._delphi_store().path.exists())
                self.assertEqual(facade.inspect_delphi_panel("PANEL-1")["documents"], [])
                facade.capture_delphi_design(payload)
                store = facade._delphi_store()
                before = store.path.read_bytes()
                existing = store.load("PRJ-1", "design", "DLD-1", "1.0.0")
                # Existing incompatible schemas must not be silently completed.
                import sqlite3
                with closing(sqlite3.connect(store.path)) as con:
                    with con:
                        con.execute("DROP TABLE delphi_store_meta")
                damaged = store.path.read_bytes()
                with self.assertRaises(LocalDelphiStoreError):
                    store.capture(existing)
                self.assertEqual(store.path.read_bytes(), damaged)
                store.path.write_bytes(before)
                self.assertEqual(facade.show_delphi_design("DLD-1", "1.0.0")["status"], "OK")
            finally:
                app.close()
