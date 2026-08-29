from __future__ import annotations

import unittest

from core.conversation import ConversationRuntimeError
from plugins.local_application import LocalApplicationFacade
from plugins.local_application.resume import _project_projection, _question_projection


class PR31ReviewRegressionTests(unittest.TestCase):
    def test_public_resume_limits_reject_nonpositive_and_above_production_bounds_before_reads(self):
        facade = LocalApplicationFacade(object(), "PRJ-1")
        for limits in (
            {"attention_maps": 0},
            {"attention_maps": 51},
            {"recent_runs": 21},
            {"research_question_candidates": 101},
        ):
            with self.subTest(limits=limits), self.assertRaises(ValueError):
                facade.resume_context(limits=limits)

    def test_project_projection_fails_closed_on_missing_or_mismatched_identity(self):
        cases = (
            {},
            {"project": {}},
            {"project": {"project_id": "PRJ-1"}},
            {"project": {"project_id": "PRJ-OTHER", "title": "Other"}},
        )
        for project_config in cases:
            with self.subTest(project_config=project_config), self.assertRaises(ConversationRuntimeError) as raised:
                _project_projection(project_config, "PRJ-1")
            self.assertEqual(raised.exception.code, "RESUME-PROJECT-001")

    def test_question_projection_converts_missing_identity_or_text_to_structured_error(self):
        for question in ({}, {"id": "RQ-1"}, {"text": "Question?"}):
            with self.subTest(question=question), self.assertRaises(ConversationRuntimeError) as raised:
                _question_projection(question, error_code="RESUME-CANDIDATE-001")
            self.assertEqual(raised.exception.code, "RESUME-CANDIDATE-001")


if __name__ == "__main__":
    unittest.main()
