from __future__ import annotations

import json
import sqlite3
import unittest

from core.conversation import ConversationRuntimeError
from plugins.local_application import LocalApplicationFacade
from plugins.local_application.resume import (
    _project_projection,
    _question_projection,
    _rq_candidate,
    _validated_limits,
)
from plugins.local_attention_resume import _activation_ids_for_map, validate_active_attention_binding
from plugins.local_attention_store import LocalAttentionStoreError, attention_event_digest


_MAP_DIGEST = "sha256:" + "a" * 64


def _candidate_fixture() -> dict:
    return {
        "candidate_only": True,
        "current_snapshot_ref": "SNAP-1",
        "current_snapshot_digest": "sha256:" + "b" * 64,
        "provenance": {"producer": "research_question.propose@0.1.0"},
        "proposed_actions": [{
            "kind": "CREATE_OBJECT",
            "payload": {"object": {"kind": "research_question", "id": "RQ-1"}},
        }],
        "affected_refs": [{"kind": "research_question", "id": "RQ-1"}],
    }


def _activation_event(activation_id: str, *, map_id: str = "MAP-1") -> dict:
    event = {
        "schema_version": "0.1.0",
        "activation_id": activation_id,
        "project_id": "PRJ-1",
        "map_id": map_id,
        "map_digest": _MAP_DIGEST,
        "activated_at": "2026-08-30T00:00:00Z",
    }
    event["event_digest"] = attention_event_digest(event)
    return event


def _activation_connection(events: list[dict]) -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        "CREATE TABLE attention_activation_events ("
        "activation_id TEXT, project_id TEXT, map_id TEXT, map_digest TEXT, "
        "event_digest TEXT, document_json TEXT)"
    )
    for event in events:
        connection.execute(
            "INSERT INTO attention_activation_events VALUES (?,?,?,?,?,?)",
            (
                event["activation_id"],
                event["project_id"],
                event["map_id"],
                event["map_digest"],
                event["event_digest"],
                json.dumps(event),
            ),
        )
    connection.commit()
    return connection


class _ReadStore:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def _connect_read(self):
        return self._connection


class PR31ReviewRegressionTests(unittest.TestCase):
    def test_public_resume_limits_reject_nonpositive_and_above_production_bounds_before_reads(self):
        facade = LocalApplicationFacade(object(), "PRJ-1")
        for limits in (
            {"attention_maps": 0},
            {"attention_maps": 51},
            {"recent_runs": 21},
            {"research_question_candidates": 101},
            {"pending_confirmations": 0},
            {"pending_confirmations": 101},
            {"pending_runs": 0},
            {"pending_runs": 101},
        ):
            with self.subTest(limits=limits), self.assertRaises(ValueError):
                facade.resume_context(limits=limits)

    def test_pending_boundary_limits_are_valid_public_resume_limits(self):
        effective = _validated_limits({"pending_confirmations": 1, "pending_runs": 1})
        self.assertEqual(effective["pending_confirmations"], 1)
        self.assertEqual(effective["pending_runs"], 1)

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

    def test_project_projection_fails_closed_on_non_list_scope_members(self):
        project = {"project_id": "PRJ-1", "title": "Fixture"}
        for scope in (
            {"in_scope": "not-a-list", "out_of_scope": []},
            {"in_scope": [], "out_of_scope": "not-a-list"},
            {"in_scope": None, "out_of_scope": []},
            {"in_scope": [], "out_of_scope": None},
        ):
            project_config = {"project": project, "scope": scope}
            with self.subTest(scope=scope), self.assertRaises(ConversationRuntimeError) as raised:
                _project_projection(project_config, "PRJ-1")
            self.assertEqual(raised.exception.code, "RESUME-PROJECT-001")

    def test_project_projection_preserves_valid_scope_lists(self):
        project_config = {
            "project": {"project_id": "PRJ-1", "title": "Fixture"},
            "scope": {"in_scope": ["A"], "out_of_scope": ["B"]},
        }
        projected = _project_projection(project_config, "PRJ-1")
        self.assertEqual(projected["scope"], {"in_scope": ["A"], "out_of_scope": ["B"]})

    def test_question_projection_converts_missing_identity_or_text_to_structured_error(self):
        for question in ({}, {"id": "RQ-1"}, {"text": "Question?"}):
            with self.subTest(question=question), self.assertRaises(ConversationRuntimeError) as raised:
                _question_projection(question, error_code="RESUME-CANDIDATE-001")
            self.assertEqual(raised.exception.code, "RESUME-CANDIDATE-001")

    def test_question_projection_converts_malformed_revision_to_requested_structured_error(self):
        for error_code in ("RESUME-CANDIDATE-001", "RESUME-STATE-001"):
            questions = (
                {"id": "RQ-1", "text": "Question?"},
                {"id": "RQ-1", "text": "Question?", "revision": None},
                {"id": "RQ-1", "text": "Question?", "revision": "not-an-integer"},
                {"id": "RQ-1", "text": "Question?", "revision": "1"},
                {"id": "RQ-1", "text": "Question?", "revision": 1.5},
                {"id": "RQ-1", "text": "Question?", "revision": True},
                {"id": "RQ-1", "text": "Question?", "revision": -1},
                {"id": "RQ-1", "text": "Question?", "revision": []},
                {"id": "RQ-1", "text": "Question?", "revision": {}},
            )
            for question in questions:
                with self.subTest(error_code=error_code, question=question), self.assertRaises(
                    ConversationRuntimeError
                ) as raised:
                    _question_projection(question, error_code=error_code)
                self.assertEqual(raised.exception.code, error_code)
        self.assertEqual(
            _question_projection(
                {"id": "RQ-1", "text": "Question?", "revision": 0},
                error_code="RESUME-STATE-001",
            )["revision"],
            0,
        )

    def test_rq_candidate_fails_closed_on_missing_snapshot_binding(self):
        for key in ("current_snapshot_ref", "current_snapshot_digest"):
            candidate = _candidate_fixture()
            candidate.pop(key)
            with self.subTest(key=key), self.assertRaises(ConversationRuntimeError) as raised:
                _rq_candidate(candidate)
            self.assertEqual(raised.exception.code, "RESUME-CANDIDATE-001")

    def test_attention_activation_history_is_bounded_with_truncation(self):
        connection = _activation_connection([
            _activation_event("ACT-1"),
            _activation_event("ACT-2"),
            _activation_event("ACT-3"),
        ])
        try:
            activation_ids, truncated = _activation_ids_for_map(
                connection,
                project_id="PRJ-1",
                map_id="MAP-1",
                map_digest=_MAP_DIGEST,
                limit=2,
            )
            self.assertEqual(activation_ids, ("ACT-2", "ACT-3"))
            self.assertTrue(truncated)
        finally:
            connection.close()

    def test_active_attention_pointer_must_bind_matching_activation_event(self):
        connection = _activation_connection([_activation_event("ACT-1")])
        store = _ReadStore(connection)
        with self.assertRaises(LocalAttentionStoreError) as raised:
            validate_active_attention_binding(
                store,
                "PRJ-1",
                {
                    "activation_id": "ACT-1",
                    "map_id": "MAP-OTHER",
                    "map_digest": _MAP_DIGEST,
                },
            )
        self.assertEqual(raised.exception.code, "ATTENTION-STORE-INTEGRITY-001")


if __name__ == "__main__":
    unittest.main()
