from __future__ import annotations

import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from plugins.local_application import LocalApplicationError, LocalApplicationFacade
from tests.runtime.test_research_question_review import _workspace as make_workspace, _adopt_question


class ProjectInputRegistrationTests(unittest.TestCase):
    def test_register_duplicate_read_and_question_review_linkage(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_workspace(Path(tmp))
            facade = LocalApplicationFacade.open_workspace(workspace)
            try:
                question_id = _adopt_question(facade)
                source = workspace / "theme.md"
                content = b"Theme input\n"
                source.write_bytes(content)
                before = facade.resume_context()
                snap = before["research_state"]["snapshot"]
                payload = {
                    "file": str(source),
                    "role": "theme",
                    "expected_snapshot_id": snap["snapshot_id"],
                    "expected_snapshot_digest": snap["content_digest"],
                    "provenance": {"supplied_by": "test"},
                }

                first = facade.register_project_input(payload)["project_input"]
                second = facade.register_project_input(payload)["project_input"]
                self.assertEqual(first["input_id"], second["input_id"])
                self.assertEqual(first["content_digest"], "sha256:" + hashlib.sha256(content).hexdigest())
                self.assertEqual(len(facade.list_project_inputs()["project_inputs"]), 1)
                self.assertEqual(facade.show_project_input(first["input_id"])["project_input"]["role"], "theme")
                after = facade.resume_context()
                self.assertEqual(before["research_state"]["snapshot"], after["research_state"]["snapshot"])
                self.assertEqual(before["research_questions"]["authoritative"], after["research_questions"]["authoritative"])

                review = facade.submit_action({
                    "action_type": "research_question.review",
                    "payload": {
                        "operation": "KEEP",
                        "question_ids": [question_id],
                        "rationale": "review supplied theme",
                        "review_inputs": {"project_input_ids": [first["input_id"]]},
                    },
                })
                self.assertFalse(review["data"]["question_review"]["material_change"])
                self.assertEqual(review["data"]["question_review"]["review_inputs"]["project_input_ids"], [first["input_id"]])

                refine = facade.submit_action({
                    "action_type": "research_question.review",
                    "payload": {
                        "operation": "REFINE",
                        "question_ids": [question_id],
                        "rationale": "narrow from supplied theme",
                        "text": "Refined question",
                        "review_inputs": {"project_input_ids": [first["input_id"]]},
                    },
                })
                self.assertEqual(refine["data"]["question_delta"]["operation"], "REFINE")
                self.assertEqual(
                    refine["data"]["state_delta_proposal"]["provenance"]["review_inputs"]["project_input_ids"],
                    [first["input_id"]],
                )
                with self.assertRaises(LocalApplicationError) as unknown:
                    facade.submit_action({
                        "action_type": "research_question.review",
                        "payload": {
                            "operation": "KEEP",
                            "question_ids": [question_id],
                            "rationale": "bad provenance",
                            "review_inputs": {"project_input_ids": ["PIN-missing"]},
                        },
                    })
                self.assertEqual(unknown.exception.code, "APPLICATION-PROJECT-INPUT-404")

                _adopt_question(facade, "Second question")
                current = facade.resume_context()["research_state"]["snapshot"]
                self.assertNotEqual(current["snapshot_id"], first["snapshot_id"])
                reused = facade.submit_action({
                    "action_type": "research_question.review",
                    "payload": {
                        "operation": "KEEP",
                        "question_ids": [question_id],
                        "rationale": "reuse immutable project input",
                        "review_inputs": {"project_input_ids": [first["input_id"]]},
                    },
                })
                self.assertFalse(reused["data"]["question_review"]["material_change"])
                self.assertEqual(
                    reused["data"]["question_review"]["bound_snapshot"]["snapshot_id"],
                    current["snapshot_id"],
                )
                self.assertEqual(len(facade.list_project_inputs()["project_inputs"]), 1)
                self.assertEqual(
                    facade.show_project_input(first["input_id"])["project_input"]["snapshot_id"],
                    first["snapshot_id"],
                )

                with self.assertRaises(LocalApplicationError) as too_many:
                    facade.submit_action({
                        "action_type": "research_question.review",
                        "payload": {
                            "operation": "KEEP",
                            "question_ids": [question_id],
                            "rationale": "bounded project inputs",
                            "review_inputs": {"project_input_ids": [f"PIN-{i}" for i in range(65)]},
                        },
                    })
                self.assertEqual(too_many.exception.code, "APPLICATION-PROJECT-INPUT-001")
            finally:
                facade.close()

    def test_legacy_registry_schema_migrates_without_losing_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_workspace(Path(tmp))
            facade = LocalApplicationFacade.open_workspace(workspace)
            try:
                project_id = facade.project_id
                current = facade.resume_context()["research_state"]["snapshot"]
            finally:
                facade.close()

            root = workspace / ".research-loom" / "project-inputs"
            root.mkdir(parents=True, exist_ok=True)
            database = root / "project-inputs.sqlite3"
            content = b"legacy theme"
            digest = "sha256:" + hashlib.sha256(content).hexdigest()
            db = sqlite3.connect(database)
            db.execute(
                """CREATE TABLE project_inputs(
                    input_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, role TEXT NOT NULL,
                    media_type TEXT NOT NULL, byte_length INTEGER NOT NULL, content_digest TEXT NOT NULL,
                    source_path TEXT NOT NULL, provenance_json TEXT NOT NULL, registered_at TEXT NOT NULL,
                    lineage_ref TEXT NOT NULL, snapshot_id TEXT NOT NULL, snapshot_digest TEXT NOT NULL,
                    UNIQUE(project_id, role, content_digest)
                )"""
            )
            db.execute(
                "INSERT INTO project_inputs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    "PIN-legacy", project_id, "theme", "text/markdown", len(content), digest,
                    "theme.md", "{}", "2026-01-01T00:00:00Z", "LIN-legacy",
                    "SNP-legacy", "sha256:legacy-snapshot",
                ),
            )
            db.commit(); db.close()

            source = workspace / "theme.md"
            source.write_bytes(content)
            facade = LocalApplicationFacade.open_workspace(workspace)
            try:
                items = facade.list_project_inputs()["project_inputs"]
                self.assertEqual([item["input_id"] for item in items], ["PIN-legacy"])
                migrated = sqlite3.connect(database)
                try:
                    self.assertEqual(migrated.execute("PRAGMA user_version").fetchone()[0], 2)
                    unique_columns = []
                    for index in migrated.execute("PRAGMA index_list(project_inputs)").fetchall():
                        if index[2]:
                            columns = [
                                row[2] for row in migrated.execute(
                                    f"PRAGMA index_info('{index[1]}')"
                                ).fetchall()
                            ]
                            unique_columns.append(columns)
                    self.assertIn(
                        ["project_id", "role", "content_digest", "lineage_ref", "snapshot_id", "snapshot_digest"],
                        unique_columns,
                    )
                finally:
                    migrated.close()

                registered = facade.register_project_input({
                    "file": str(source),
                    "role": "theme",
                    "expected_snapshot_id": current["snapshot_id"],
                    "expected_snapshot_digest": current["content_digest"],
                })["project_input"]
                self.assertNotEqual(registered["input_id"], "PIN-legacy")
                self.assertEqual(registered["content_digest"], digest)
                self.assertEqual(len(facade.list_project_inputs()["project_inputs"]), 2)
            finally:
                facade.close()

    def test_existing_content_addressed_blob_is_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_workspace(Path(tmp))
            facade = LocalApplicationFacade.open_workspace(workspace)
            try:
                source = workspace / "theme.md"
                source.write_text("theme", encoding="utf-8")
                snap = facade.resume_context()["research_state"]["snapshot"]
                payload = {
                    "file": str(source),
                    "role": "theme",
                    "expected_snapshot_id": snap["snapshot_id"],
                    "expected_snapshot_digest": snap["content_digest"],
                }
                registered = facade.register_project_input(payload)["project_input"]
                with patch.object(Path, "read_bytes", side_effect=AssertionError("unbounded blob read")):
                    same = facade.register_project_input(payload)["project_input"]
                self.assertEqual(same["input_id"], registered["input_id"])
                digest_hex = registered["content_digest"].split(":", 1)[1]
                blob = workspace / ".research-loom" / "project-inputs" / "blobs" / digest_hex[:2] / digest_hex
                blob.write_bytes(b"corrupt")
                with self.assertRaises(LocalApplicationError) as corrupted:
                    facade.register_project_input(payload)
                self.assertEqual(corrupted.exception.code, "APPLICATION-PROJECT-INPUT-INTEGRITY-001")
            finally:
                facade.close()

    def test_stale_outside_and_non_regular_workspace_input_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_workspace(Path(tmp))
            facade = LocalApplicationFacade.open_workspace(workspace)
            try:
                source = workspace / "expectations.md"
                source.write_text("x", encoding="utf-8")
                snap = facade.resume_context()["research_state"]["snapshot"]
                with self.assertRaises(LocalApplicationError) as stale:
                    facade.register_project_input({
                        "file": str(source),
                        "role": "expectations",
                        "expected_snapshot_id": "SNP-stale",
                        "expected_snapshot_digest": snap["content_digest"],
                    })
                self.assertEqual(stale.exception.code, "APPLICATION-PROJECT-INPUT-STALE-001")

                non_regular = workspace / "input-dir"
                non_regular.mkdir()
                with self.assertRaises(LocalApplicationError) as directory:
                    facade.register_project_input({
                        "file": str(non_regular),
                        "role": "other",
                        "expected_snapshot_id": snap["snapshot_id"],
                        "expected_snapshot_digest": snap["content_digest"],
                    })
                self.assertEqual(directory.exception.code, "APPLICATION-PROJECT-INPUT-FILE-001")

                oversized = workspace / "oversized.bin"
                with oversized.open("wb") as stream:
                    stream.seek(8 * 1024 * 1024)
                    stream.write(b"x")
                with self.assertRaises(LocalApplicationError) as size_error:
                    facade.register_project_input({
                        "file": str(oversized),
                        "role": "other",
                        "expected_snapshot_id": snap["snapshot_id"],
                        "expected_snapshot_digest": snap["content_digest"],
                    })
                self.assertEqual(size_error.exception.code, "APPLICATION-PROJECT-INPUT-FILE-001")

                outside = Path(tmp).parent / "outside-project-input.txt"
                outside.write_text("x", encoding="utf-8")
                try:
                    with self.assertRaises(LocalApplicationError) as outside_error:
                        facade.register_project_input({
                            "file": str(outside),
                            "role": "other",
                            "expected_snapshot_id": snap["snapshot_id"],
                            "expected_snapshot_digest": snap["content_digest"],
                        })
                    self.assertEqual(outside_error.exception.code, "APPLICATION-PROJECT-INPUT-FILE-001")
                finally:
                    outside.unlink(missing_ok=True)
            finally:
                facade.close()
