from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from plugins.local_application import LocalApplicationError, LocalApplicationFacade
from plugins.local_project_input_store import LocalProjectInputStore
from tests.runtime.test_research_question_review import _adopt_question, _workspace as make_workspace


class ProjectInputHardeningTests(unittest.TestCase):
    def _register(self, facade, source: Path, *, role: str = "other"):
        snap = facade.resume_context()["research_state"]["snapshot"]
        return facade.register_project_input({
            "file": str(source),
            "role": role,
            "expected_snapshot_id": snap["snapshot_id"],
            "expected_snapshot_digest": snap["content_digest"],
        })["project_input"]

    def test_registration_rejects_head_change_during_file_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_workspace(Path(tmp))
            with LocalApplicationFacade.open_workspace(workspace) as facade:
                source = workspace / "race.md"
                source.write_text("race", encoding="utf-8")
                snap = facade.resume_context()["research_state"]["snapshot"]
                payload = {
                    "file": str(source),
                    "role": "theme",
                    "expected_snapshot_id": snap["snapshot_id"],
                    "expected_snapshot_digest": snap["content_digest"],
                }

                def read_then_advance(*_args, **_kwargs):
                    content = source.read_bytes()
                    _adopt_question(facade, "Advance while input is being read")
                    return content

                with patch(
                    "plugins.local_application.project_input_facade.read_controlled_file",
                    side_effect=read_then_advance,
                ):
                    with self.assertRaises(LocalApplicationError) as stale:
                        facade.register_project_input(payload)
                self.assertEqual(stale.exception.code, "APPLICATION-PROJECT-INPUT-STALE-001")
                self.assertEqual(facade.list_project_inputs()["project_inputs"], [])

    def test_content_round_trip_survives_source_removal_and_detects_corruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_workspace(Path(tmp))
            source = workspace / "brief.md"
            content = "保存後も読み直せる本文\n"
            source.write_text(content, encoding="utf-8")
            with LocalApplicationFacade.open_workspace(workspace) as facade:
                registered = self._register(facade, source, role="project_brief")
            source.unlink()

            with LocalApplicationFacade.open_workspace(workspace) as facade:
                shown = facade.show_project_input(registered["input_id"], format="text")
                self.assertEqual(shown["content"]["value"], content)
                self.assertEqual(shown["content"]["content_digest"], registered["content_digest"])
                digest_hex = registered["content_digest"].split(":", 1)[1]
                blob = workspace / ".research-loom" / "project-inputs" / "blobs" / digest_hex[:2] / digest_hex
                blob.write_bytes(b"corrupt")
                with self.assertRaises(LocalApplicationError) as corrupted:
                    facade.show_project_input(registered["input_id"], format="text")
                self.assertEqual(corrupted.exception.code, "APPLICATION-PROJECT-INPUT-INTEGRITY-001")

    def test_list_keyset_pagination_reaches_history_beyond_100(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_workspace(Path(tmp))
            with LocalApplicationFacade.open_workspace(workspace) as facade:
                snap = facade.resume_context()["research_state"]["snapshot"]
                source = workspace / "common.txt"
                source.write_text("common", encoding="utf-8")
                common = {
                    "file": str(source), "role": "other",
                    "expected_snapshot_id": snap["snapshot_id"],
                    "expected_snapshot_digest": snap["content_digest"],
                }
                first = facade.register_project_input(common)["project_input"]
                for index in range(100):
                    item = workspace / f"input-{index:03d}.txt"
                    item.write_text(str(index), encoding="utf-8")
                    facade.register_project_input({**common, "file": str(item)})
                _adopt_question(facade, "Advance snapshot")
                current = facade.resume_context()["research_state"]["snapshot"]
                second = facade.register_project_input({
                    **common,
                    "expected_snapshot_id": current["snapshot_id"],
                    "expected_snapshot_digest": current["content_digest"],
                })["project_input"]

                ids, cursor = [], None
                while True:
                    page = facade.list_project_inputs(limit=17, cursor=cursor)
                    ids.extend(item["input_id"] for item in page["project_inputs"])
                    cursor = page["next_cursor"]
                    if cursor is None:
                        break
                self.assertEqual(len(ids), 102)
                self.assertEqual(len(set(ids)), 102)
                self.assertIn(first["input_id"], ids)
                self.assertIn(second["input_id"], ids)

    def test_ablations_demonstrate_guard_and_digest_checks_are_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_workspace(Path(tmp))
            with LocalApplicationFacade.open_workspace(workspace) as facade:
                source = workspace / "ablation.txt"
                source.write_text("original", encoding="utf-8")
                snap = facade.resume_context()["research_state"]["snapshot"]
                payload = {
                    "file": str(source), "role": "other",
                    "expected_snapshot_id": snap["snapshot_id"],
                    "expected_snapshot_digest": snap["content_digest"],
                }

                def read_then_advance(*_args, **_kwargs):
                    content = source.read_bytes()
                    _adopt_question(facade, "Ablation advance")
                    return content

                with patch(
                    "plugins.local_application.project_input_facade.read_controlled_file",
                    side_effect=read_then_advance,
                ), patch(
                    "plugins.local_application.project_input_facade.guard_research_state_head",
                    side_effect=lambda *_args, **_kwargs: nullcontext(),
                ):
                    stale = facade.register_project_input(payload)["project_input"]
                current = facade.resume_context()["research_state"]["snapshot"]
                self.assertNotEqual(stale["snapshot_id"], current["snapshot_id"])

                # Re-register against the current Snapshot, corrupt it with same-size UTF-8 bytes,
                # then remove digest verification to demonstrate that corrupted content is returned.
                registered = self._register(facade, source)
                digest_hex = registered["content_digest"].split(":", 1)[1]
                blob = workspace / ".research-loom" / "project-inputs" / "blobs" / digest_hex[:2] / digest_hex
                blob.write_bytes(b"tampered")
                with patch.object(
                    LocalProjectInputStore,
                    "_read_verified_blob",
                    side_effect=lambda path, _digest, _size: path.read_bytes(),
                ):
                    shown = facade.show_project_input(registered["input_id"], format="text")
                self.assertEqual(shown["content"]["value"], "tampered")
                self.assertEqual(shown["content"]["content_digest"], registered["content_digest"])


if __name__ == "__main__":
    unittest.main()
