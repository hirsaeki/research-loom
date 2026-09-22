from __future__ import annotations

from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
import tempfile
from unittest.mock import patch

import pytest

from core.conversation import ConversationRuntimeError
from core.runtime import canonical_digest
from plugins.local_application import LocalApplicationFacade, LocalResearchApplication
from plugins.local_application.cli import main as cli_main
from runtime_fixtures import finding, project, rq, seed_state
from test_issue135_recommendation_proposal import profile_provider
from test_survey_production import NullResolver


def _make_facade(root: str) -> LocalApplicationFacade:
    seed = seed_state(
        objects=[project(), rq(state="approved"), finding(state="approved")],
        snapshot_id="SNP-SYNTH-0",
        project_config={
            "project": {
                "project_id": "PRJ-1",
                "title": "Synthesis candidate fixture",
                "objective": "Exercise persisted synthesis candidate discovery.",
            },
            "scope": {"in_scope": [], "out_of_scope": []},
            "research_questions": {"seeds": []},
            "research_attention": [],
        },
    )
    app = LocalResearchApplication(
        root,
        resolver=NullResolver(),
        effective_profile_set_provider=profile_provider,
        seed_state=seed,
    )
    return LocalApplicationFacade(app, "PRJ-1", owns_application=True)


def _reopen_facade(root: str) -> LocalApplicationFacade:
    app = LocalResearchApplication(
        root,
        resolver=NullResolver(),
        effective_profile_set_provider=profile_provider,
    )
    return LocalApplicationFacade(app, "PRJ-1", owns_application=True)


def _recommendation_input(statement: str = "Adopt the bounded operating control supported by the Finding.") -> dict:
    return {
        "action_type": "research.recommendation.propose",
        "payload": {
            "statement": statement,
            "finding_ids": ["FND-1"],
            "conditions": ["Within the validated fixture scope."],
            "scope": ["Operational planning"],
        },
        "actor_id": "HUMAN-REC",
    }


def _argument_input() -> dict:
    return {
        "action_type": "research.argument.propose",
        "payload": {
            "conclusion": "The approved Finding supports a bounded synthesis conclusion.",
            "warrant": "The current approved Finding is sufficient for this fixture Argument.",
            "question_ids": ["RQ-1"],
            "finding_ids": ["FND-1"],
            "evidence_ids": [],
            "qualifier": "Within the fixture scope.",
            "implications": ["Use this conclusion only within the stated scope."],
        },
        "actor_id": "HUMAN-ARG",
    }


def test_saved_recommendation_and_argument_are_discoverable_after_reopen():
    with tempfile.TemporaryDirectory() as temp:
        facade = _make_facade(temp)
        recommendation = facade.submit_action(_recommendation_input())
        argument = facade.submit_action(_argument_input())
        recommendation_id = recommendation["data"]["state_delta_proposal_id"]
        argument_id = argument["data"]["state_delta_proposal_id"]
        facade.close()

        reopened = _reopen_facade(temp)
        try:
            resumed = reopened.resume_context()
            saved = resumed["saved_synthesis_candidates"]
            ids = {item["candidate_id"] for item in saved["items"]}
            assert {recommendation_id, argument_id} <= ids
            assert all("candidate_projection" not in item for item in saved["items"])
            assert all("candidate_position" in item for item in saved["items"])
            assert resumed["workflow"]["pending_runs"] == []

            rec_show = reopened.show_synthesis_candidate(recommendation_id)
            assert rec_show["kind"] == "recommendation"
            assert rec_show["content"]["statement"] == _recommendation_input()["payload"]["statement"]
            assert rec_show["content"]["conditions"] == _recommendation_input()["payload"]["conditions"]
            assert rec_show["content"]["scope"] == _recommendation_input()["payload"]["scope"]
            assert rec_show["content"]["finding_ids"] == ["FND-1"]

            arg_show = reopened.show_synthesis_candidate(argument_id)
            assert arg_show["kind"] == "argument"
            assert arg_show["content"]["warrant"] == _argument_input()["payload"]["warrant"]
            assert arg_show["content"]["qualifier"] == "Within the fixture scope."
            assert arg_show["content"]["finding_ids"] == ["FND-1"]
        finally:
            reopened.close()


def test_list_is_bounded_cursor_stable_and_filter_bound():
    with tempfile.TemporaryDirectory() as temp:
        facade = _make_facade(temp)
        try:
            created = []
            for index in range(25):
                result = facade.submit_action(
                    _recommendation_input(statement=f"Recommendation {index:02d}")
                )
                created.append(result["data"]["state_delta_proposal_id"])

            first = facade.list_synthesis_candidates(kind="recommendation", limit=20)
            assert len(first["items"]) == 20
            assert first["truncated"] is True
            assert first["next_cursor"] == first["items"][-1]["candidate_id"]

            newer = facade.submit_action(_recommendation_input(statement="Newer after page one"))
            newer_id = newer["data"]["state_delta_proposal_id"]
            second = facade.list_synthesis_candidates(
                kind="recommendation", limit=20, cursor=first["next_cursor"]
            )
            second_ids = [item["candidate_id"] for item in second["items"]]
            assert len(second_ids) == 5
            assert newer_id not in second_ids
            assert set(second_ids).isdisjoint(
                {item["candidate_id"] for item in first["items"]}
            )
            assert set(second_ids) | {item["candidate_id"] for item in first["items"]} == set(created)
            assert second["truncated"] is False
            assert second["next_cursor"] is None

            facade.submit_action(_argument_input())
            with pytest.raises(ConversationRuntimeError) as error:
                facade.list_synthesis_candidates(
                    kind="argument", limit=20, cursor=first["next_cursor"]
                )
            assert error.value.code == "SYNTHESIS-CANDIDATE-CURSOR-001"

            with pytest.raises(ValueError):
                facade.list_synthesis_candidates(limit=101)
        finally:
            facade.close()


def test_more_than_one_hundred_candidates_are_reachable_by_cursor_without_preloading_history():
    with tempfile.TemporaryDirectory() as temp:
        facade = _make_facade(temp)
        try:
            created = [
                facade.submit_action(_recommendation_input(statement=f"Long history {index:03d}"))["data"][
                    "state_delta_proposal_id"
                ]
                for index in range(105)
            ]
            first = facade.list_synthesis_candidates(kind="recommendation", limit=100)
            assert len(first["items"]) == 100
            assert first["truncated"] is True
            second = facade.list_synthesis_candidates(
                kind="recommendation", limit=100, cursor=first["next_cursor"]
            )
            assert len(second["items"]) == 5
            assert second["truncated"] is False
            assert {item["candidate_id"] for item in first["items"] + second["items"]} == set(created)
        finally:
            facade.close()



def test_corrupt_items_are_isolated_and_unattributable_json_marks_collection_incomplete():
    with tempfile.TemporaryDirectory() as temp:
        facade = _make_facade(temp)
        try:
            healthy = facade.submit_action(_recommendation_input(statement="Healthy recommendation"))
            corrupt = facade.submit_action(_recommendation_input(statement="Corrupt recommendation"))
            healthy_id = healthy["data"]["state_delta_proposal_id"]
            corrupt_id = corrupt["data"]["state_delta_proposal_id"]
            store = facade._application.conversation_store
            raw = store.load_state_delta_proposal(corrupt_id)
            raw["rationale"] = "tampered without refreshing digest"
            store._db.execute(
                "UPDATE state_delta_proposals SET payload_json=? WHERE proposal_id=?",
                (json.dumps(raw, ensure_ascii=False), corrupt_id),
            )
            store._db.execute(
                "INSERT INTO state_delta_proposals(proposal_id,payload_json) VALUES(?,?)",
                ("SDP-UNATTRIBUTABLE", "not-json"),
            )

            listing = facade.list_synthesis_candidates(kind="recommendation")
            by_id = {item["candidate_id"]: item for item in listing["items"]}
            assert listing["status"] == "DEGRADED"
            assert by_id[healthy_id]["availability"] == "AVAILABLE"
            assert by_id[corrupt_id]["availability"] == "UNAVAILABLE"
            assert listing["issues"] == [{
                "code": "SYNTHESIS-CANDIDATE-COLLECTION-001",
                "message": "candidate collection may be incomplete because an unattributable stored proposal is malformed",
            }]

            shown = facade.show_synthesis_candidate(healthy_id)
            assert shown["status"] == "OK"
            with pytest.raises(ConversationRuntimeError):
                facade.show_synthesis_candidate(corrupt_id)
            with pytest.raises(ConversationRuntimeError):
                facade.show_synthesis_candidate("SDP-UNATTRIBUTABLE")

            malformed = facade.submit_action(_recommendation_input(statement="Malformed fields"))
            malformed_id = malformed["data"]["state_delta_proposal_id"]
            malformed_wire = store.load_state_delta_proposal(malformed_id)
            malformed_wire["proposed_actions"][0]["payload"]["object"]["conditions"] = 42
            malformed_wire.pop("proposal_digest", None)
            malformed_wire["proposal_digest"] = canonical_digest(malformed_wire)
            store._db.execute(
                "UPDATE state_delta_proposals SET payload_json=? WHERE proposal_id=?",
                (json.dumps(malformed_wire, ensure_ascii=False), malformed_id),
            )
            malformed_listing = facade.list_synthesis_candidates(kind="recommendation")
            malformed_item = next(
                item for item in malformed_listing["items"] if item["candidate_id"] == malformed_id
            )
            assert malformed_item["availability"] == "UNAVAILABLE"
            assert malformed_listing["status"] == "DEGRADED"
        finally:
            facade.close()


def test_cross_project_candidate_and_cursor_do_not_leak_content_and_reads_do_not_write():
    with tempfile.TemporaryDirectory() as temp:
        facade = _make_facade(temp)
        try:
            result = facade.submit_action(_recommendation_input(statement="Local recommendation"))
            local_id = result["data"]["state_delta_proposal_id"]
            store = facade._application.conversation_store
            local = store.load_state_delta_proposal(local_id)
            foreign = deepcopy(local)
            foreign["proposal_id"] = "SDP-FOREIGN"
            foreign["project_ref"] = "PRJ-OTHER"
            foreign.pop("proposal_digest", None)
            foreign["proposal_digest"] = canonical_digest(foreign)
            store.store_state_delta_proposal("SDP-FOREIGN", foreign)

            state_before = deepcopy(facade._current_state_view().current_snapshot)
            count_before = store._db.execute("SELECT COUNT(*) FROM state_delta_proposals").fetchone()[0]
            local_show = facade.show_synthesis_candidate(local_id)
            facade.list_synthesis_candidates()
            count_after = store._db.execute("SELECT COUNT(*) FROM state_delta_proposals").fetchone()[0]
            state_after = facade._current_state_view().current_snapshot
            assert local_show["candidate_id"] == local_id
            assert count_after == count_before
            assert state_after == state_before

            with pytest.raises(ConversationRuntimeError):
                facade.show_synthesis_candidate("SDP-FOREIGN")
            with pytest.raises(ConversationRuntimeError) as error:
                facade.list_synthesis_candidates(cursor="SDP-FOREIGN")
            assert error.value.code == "SYNTHESIS-CANDIDATE-CURSOR-001"
        finally:
            facade.close()


class _CliFacade:
    def __init__(self):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def list_synthesis_candidates(self, *, kind=None, limit=20, cursor=None):
        self.calls.append(("list", kind, limit, cursor))
        return {"status": "OK", "project_id": "PRJ-1", "items": [], "truncated": False, "next_cursor": None, "issues": []}

    def show_synthesis_candidate(self, candidate_id):
        self.calls.append(("show", candidate_id))
        return {"status": "OK", "project_id": "PRJ-1", "candidate_id": candidate_id}


def test_cli_list_and_show_route_to_public_facade():
    fake = _CliFacade()
    output = io.StringIO()
    with patch(
        "plugins.local_application.cli.LocalApplicationFacade.open_workspace",
        return_value=fake,
    ), redirect_stdout(output):
        code = cli_main([
            "synthesis-candidate", "list", "--workspace", "unused", "--kind", "argument",
            "--limit", "7", "--cursor", "SDP-CURSOR", "--json",
        ])
    assert code == 0
    assert fake.calls == [("list", "argument", 7, "SDP-CURSOR")]

    fake.calls.clear()
    output = io.StringIO()
    with patch(
        "plugins.local_application.cli.LocalApplicationFacade.open_workspace",
        return_value=fake,
    ), redirect_stdout(output):
        code = cli_main([
            "synthesis-candidate", "show", "--workspace", "unused",
            "--candidate-id", "SDP-ONE", "--json",
        ])
    assert code == 0
    assert fake.calls == [("show", "SDP-ONE")]
