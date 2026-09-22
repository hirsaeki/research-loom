from __future__ import annotations

import tempfile
from pathlib import Path

from plugins.local_application import LocalApplicationFacade
from test_issue134_argument_proposal import Issue134ArgumentProposalTests
from test_issue135_recommendation_proposal import Issue135RecommendationProposalTests
from test_research_question_adoption import _init_workspace, _proposal_input
from test_research_question_batch_adoption import (
    _apply_to_decision,
    _batch_input,
    _five_questions,
    _resolve,
)


def test_rq_projection_separates_candidate_target_from_current_state():
    with tempfile.TemporaryDirectory() as temp:
        workspace = _init_workspace(Path(temp))
        with LocalApplicationFacade.open_workspace(workspace) as facade:
            result = facade.submit_action(_proposal_input())
            candidate = result["data"]["research_question_candidate"]
            projection = result["data"]["candidate_projection"]
            assert projection["bound_to_current_snapshot"] is True
            assert projection["subjects"][0]["current_value"] is None
            assert projection["subjects"][0]["candidate_value"] == candidate
            assert candidate["adoption_state"] == "approved"

            resumed = facade.resume_context()["research_questions"]["candidates"]
            row = next(
                item
                for item in resumed
                if item["state_delta_proposal_id"] == result["data"]["state_delta_proposal_id"]
            )
            assert row["candidate_projection"]["subjects"][0]["current_value"] is None


def test_recommendation_projection_does_not_treat_target_approved_as_current():
    helper = Issue135RecommendationProposalTests()
    with tempfile.TemporaryDirectory() as temp:
        facade = helper.make_facade(temp)
        try:
            result = facade.submit_action(helper.proposal_input())
            recommendation = result["data"]["recommendation_candidate"]
            projection = result["data"]["candidate_projection"]
            assert recommendation["adoption_state"] == "approved"
            assert projection["subjects"][0]["current_value"] is None
            assert projection["subjects"][0]["candidate_value"] == recommendation
        finally:
            facade.close()


def test_argument_projection_preserves_schema_without_synthesizing_adoption_state():
    helper = Issue134ArgumentProposalTests()
    with tempfile.TemporaryDirectory() as temp:
        facade = helper.make_facade(temp)
        try:
            result = facade.submit_action(helper.proposal_input())
            argument = result["data"]["argument_candidate"]
            projection = result["data"]["candidate_projection"]
            assert projection["subjects"][0]["current_value"] is None
            assert projection["subjects"][0]["candidate_value"] == argument
            assert "adoption_state" not in projection["subjects"][0]["candidate_value"]
        finally:
            facade.close()


def test_historical_batch_projection_reports_current_values_without_false_reproposal():
    with tempfile.TemporaryDirectory() as temp:
        workspace = _init_workspace(Path(temp))
        with LocalApplicationFacade.open_workspace(workspace) as facade:
            proposed = facade.submit_action(_batch_input(*_five_questions()))
            candidate_id = proposed["data"]["state_delta_proposal_id"]
            generated_ids = [
                item["id"] for item in proposed["data"]["research_questions"]
            ]
            _, confirmed = _apply_to_decision(facade, candidate_id)
            resolved = _resolve(facade, confirmed["decision_request"], "approve_exact")
            assert resolved["status"] == "RESOLVED"

            row = next(
                item
                for item in facade.resume_context()["research_questions"]["candidates"]
                if item["state_delta_proposal_id"] == candidate_id
            )
            projection = row["candidate_projection"]
            assert projection["bound_to_current_snapshot"] is False
            assert [item["subject"]["id"] for item in projection["subjects"]] == generated_ids
            assert all(item["current_value"] is not None for item in projection["subjects"])
