from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from copy import deepcopy
from pathlib import Path
from threading import Barrier, Event
import tempfile
import unittest
from unittest.mock import patch

from plugins.desktop_research import with_context_extension_digest
from plugins.local_application import LocalApplicationError, LocalApplicationFacade, LocalResearchApplication
from plugins.local_execution_store import LocalExecutionStoreError
from runtime_fixtures import project, rq, seed_state
from test_external_desktop_research_intake import NullResolver, profile_provider


class ExternalDesktopResearchAtomicityTests(unittest.TestCase):
    def make_facade(self, root: Path):
        seed = seed_state(
            objects=[project(), rq(state="approved")],
            mode="real",
            snapshot_id="SNP-PR35-ATOMIC-0",
        )
        app = LocalResearchApplication(
            root / ".research-loom",
            resolver=NullResolver(),
            effective_profile_set_provider=profile_provider,
            seed_state=seed,
        )
        return app, LocalApplicationFacade(app, "PRJ-1", workspace_root=root)

    @staticmethod
    def prepare(facade: LocalApplicationFacade, policy: dict | None = None) -> str:
        payload = {
            "question_id": "RQ-1",
            "purpose": "PR35 atomic external intake regression.",
        }
        if policy is not None:
            payload["desktop_policy"] = policy
        result = facade.submit_action(
            {"action_type": "desktop_research.investigate", "payload": payload}
        )
        return result["run_id"]

    @staticmethod
    def write_pair(root: Path, name: str, original: bytes, text: bytes) -> tuple[str, str]:
        raw_path = root / f"captures/raw/{name}.bin"
        text_path = root / f"captures/text/{name}.txt"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        text_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(original)
        text_path.write_bytes(text)
        return (
            str(raw_path.relative_to(root)),
            str(text_path.relative_to(root)),
        )

    @staticmethod
    def capture_input(capture_id: str, raw: str, text: str) -> dict:
        return {
            "capture_id": capture_id,
            "source_category": "other",
            "exact_locator": f"https://example.test/{capture_id.lower()}#source",
            "acquired_at": "2026-08-31T00:00:00Z",
            "original_file": raw,
            "original_media_type": "application/octet-stream",
            "text_rendition_file": text,
            "provenance": {},
        }

    def test_cumulative_role_budgets_reject_second_pair_without_partial_artifacts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app, facade = self.make_facade(root)
            try:
                run_id = self.prepare(
                    facade,
                    {
                        "max_acquired_source_captures": 3,
                        "max_capture_artifacts": 6,
                        "max_original_capture_bytes": 8,
                        "max_text_rendition_bytes": 8,
                    },
                )
                raw1, text1 = self.write_pair(root, "one", b"1234", b"abcd")
                facade.capture_external_source(
                    run_id,
                    self.capture_input("CAP-ONE", raw1, text1),
                )
                raw2, text2 = self.write_pair(root, "two", b"12345", b"abcde")
                with self.assertRaises(LocalApplicationError) as raised:
                    facade.capture_external_source(
                        run_id,
                        self.capture_input("CAP-TWO", raw2, text2),
                    )
                self.assertEqual(raised.exception.code, "APPLICATION-EXTERNAL-CAPTURE-001")
                artifacts = app.execution_store.artifacts_for(run_id)
                self.assertEqual(len(artifacts), 2)
                self.assertEqual(
                    {item.provenance["capture_id"] for item in artifacts},
                    {"CAP-ONE"},
                )
            finally:
                facade.close()

    def test_atomic_pair_rolls_back_metadata_when_second_artifact_write_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app, facade = self.make_facade(root)
            try:
                run_id = self.prepare(facade)
                raw, text = self.write_pair(root, "fault", b"original", b"valid utf8")
                real_store_blob = app.execution_store._store_blob
                calls = 0

                def fail_second(content: bytes, *, scheme: str):
                    nonlocal calls
                    calls += 1
                    if calls == 2:
                        raise LocalExecutionStoreError("injected second artifact failure")
                    return real_store_blob(content, scheme=scheme)

                with patch.object(app.execution_store, "_store_blob", side_effect=fail_second):
                    with self.assertRaises(LocalApplicationError) as raised:
                        facade.capture_external_source(
                            run_id,
                            self.capture_input("CAP-FAULT", raw, text),
                        )
                self.assertEqual(raised.exception.code, "APPLICATION-EXTERNAL-CAPTURE-001")
                self.assertEqual(app.execution_store.artifacts_for(run_id), ())
            finally:
                facade.close()

    def test_concurrent_capture_reservation_allows_only_one_budgeted_pair(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app1, facade1 = self.make_facade(root)
            app2 = None
            facade2 = None
            try:
                run_id = self.prepare(
                    facade1,
                    {
                        "max_acquired_source_captures": 1,
                        "max_capture_artifacts": 2,
                        "max_original_capture_bytes": 1024,
                        "max_text_rendition_bytes": 1024,
                    },
                )
                app2 = LocalResearchApplication(
                    root / ".research-loom",
                    resolver=NullResolver(),
                    effective_profile_set_provider=profile_provider,
                )
                facade2 = LocalApplicationFacade(app2, "PRJ-1", workspace_root=root)
                raw1, text1 = self.write_pair(root, "race-a", b"a", b"a")
                raw2, text2 = self.write_pair(root, "race-b", b"b", b"b")
                barrier = Barrier(2)

                def capture(facade, capture_id, raw, text):
                    barrier.wait()
                    try:
                        return facade.capture_external_source(
                            run_id,
                            self.capture_input(capture_id, raw, text),
                        )["status"]
                    except LocalApplicationError as exc:
                        return exc.code

                with ThreadPoolExecutor(max_workers=2) as pool:
                    results = [
                        pool.submit(capture, facade1, "CAP-RACE-A", raw1, text1),
                        pool.submit(capture, facade2, "CAP-RACE-B", raw2, text2),
                    ]
                    values = [future.result(timeout=5) for future in results]
                self.assertEqual(values.count("EXTERNAL_SOURCE_CAPTURED"), 1)
                self.assertEqual(values.count("APPLICATION-EXTERNAL-CAPTURE-001"), 1)
                self.assertEqual(len(app1.execution_store.artifacts_for(run_id)), 2)
            finally:
                if facade2 is not None:
                    facade2.close()
                facade1.close()

    def test_schema_valid_legacy_optional_limits_and_zero_text_budget_are_supported(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app, facade = self.make_facade(root)
            try:
                run_id = self.prepare(facade)
                run = app.execution_store.load_run(run_id)
                self.assertIsNotNone(run)
                extension = app.context_extension_store.load(
                    run.capability_id,
                    run.capability_version,
                    run.function_id,
                    run.context_pack_id,
                )
                legacy = deepcopy(dict(extension))
                legacy["budget"].pop("max_original_capture_bytes", None)
                legacy["budget"].pop("max_capture_artifacts", None)
                legacy["budget"]["max_text_rendition_bytes"] = 0
                legacy = with_context_extension_digest(legacy)
                raw, text = self.write_pair(root, "legacy", b"original", b"")
                with patch.object(app.context_extension_store, "load", return_value=legacy):
                    result = facade.capture_external_source(
                        run_id,
                        self.capture_input("CAP-LEGACY", raw, text),
                    )
                self.assertEqual(result["status"], "EXTERNAL_SOURCE_CAPTURED")
                artifacts = app.execution_store.artifacts_for(run_id)
                self.assertEqual(len(artifacts), 2)
                rendition = next(
                    item for item in artifacts
                    if item.role == "desktop_research.text_rendition"
                )
                self.assertEqual(rendition.size, 0)
            finally:
                facade.close()

    def test_attempt_append_holds_running_condition_against_terminal_transition(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app1, facade1 = self.make_facade(root)
            app2 = None
            try:
                run_id = self.prepare(facade1)
                app2 = LocalResearchApplication(
                    root / ".research-loom",
                    resolver=NullResolver(),
                    effective_profile_set_provider=profile_provider,
                )
                entered_append = Event()
                release_append = Event()
                real_append = app1.operational_store.append

                def delayed_append(*args, **kwargs):
                    entered_append.set()
                    self.assertTrue(release_append.wait(timeout=5))
                    return real_append(*args, **kwargs)

                with patch.object(app1.operational_store, "append", side_effect=delayed_append):
                    with ThreadPoolExecutor(max_workers=2) as pool:
                        attempt_future = pool.submit(
                            facade1.start_external_retrieval_attempt,
                            run_id,
                            {
                                "attempt_id": "ATT-RACE",
                                "strategy": "race fixture",
                                "coverage_dimension_ids": ["COV-SUPPORT"],
                            },
                        )
                        self.assertTrue(entered_append.wait(timeout=5))
                        abort_future = pool.submit(
                            app2.capability_execution_service.abort,
                            run_id,
                            reason="concurrent terminal transition fixture",
                        )
                        with self.assertRaises(FutureTimeout):
                            abort_future.result(timeout=0.1)
                        release_append.set()
                        attempt = attempt_future.result(timeout=5)
                        aborted = abort_future.result(timeout=5)

                self.assertEqual(attempt["status"], "EXTERNAL_ATTEMPT_STARTED")
                self.assertEqual(aborted.status.value, "ABORTED")
                self.assertEqual(len(app1.operational_store.events_for(run_id)), 1)
                with self.assertRaises(LocalApplicationError):
                    facade1.start_external_retrieval_attempt(
                        run_id,
                        {
                            "attempt_id": "ATT-LATE",
                            "strategy": "late fixture",
                            "coverage_dimension_ids": ["COV-SUPPORT"],
                        },
                    )
                self.assertEqual(len(app1.operational_store.events_for(run_id)), 1)
            finally:
                if app2 is not None:
                    app2.close()
                facade1.close()


if __name__ == "__main__":
    unittest.main()
