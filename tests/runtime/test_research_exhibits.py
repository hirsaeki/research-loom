from __future__ import annotations

from contextlib import redirect_stdout
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import rfc8785

from core.execution import CapabilityRunRecord, RunStatus
from plugins.local_application import LocalApplicationError, LocalApplicationFacade, LocalResearchApplication
from plugins.local_application.cli import main as cli_main
from plugins.local_research_exhibit_store import (
    EXHIBIT_CONTENT_MAX_BYTES,
    LocalResearchExhibitStore,
    LocalResearchExhibitStoreError,
)
from runtime_fixtures import project, rq, seed_state


class NullResolver:
    def resolve(self, *_args, **_kwargs):
        return None


def profile_provider(_project_ref, expected_digest):
    return {
        "schema_version": "0.1.0",
        "core_contracts": {
            "research_contract": "0.1.0",
            "invariant_contract": "0.1.0",
        },
        "profile_pins": [{
            "profile_id": "fixture.research",
            "profile_type": "research",
            "profile_version": "1.0.0",
            "manifest_sha256": "1" * 64,
        }],
        "content_digest": expected_digest,
    }


def rq_two() -> dict:
    value = deepcopy(rq(state="approved"))
    value["id"] = "RQ-2"
    value["text"] = "What differs?"
    return value


def make_app(root: str | Path) -> LocalResearchApplication:
    seed = seed_state(
        objects=[project(), rq(state="approved"), rq_two()],
        snapshot_id="SNP-EXHIBIT-0",
        project_config={
            "project": {
                "project_id": "PRJ-1",
                "title": "Research Exhibit fixture",
                "objective": "Exercise Exhibit persistence boundaries.",
            },
            "scope": {"in_scope": [], "out_of_scope": []},
        },
    )
    return LocalResearchApplication(
        root,
        resolver=NullResolver(),
        effective_profile_set_provider=profile_provider,
        seed_state=seed,
    )


def exhibit_payload(
    *,
    rq_id: str = "RQ-1",
    title: str = "Common AI terms to operational variables",
    kind: str = "table",
    representation: str = "markdown",
    value=None,
    **extra,
) -> dict:
    if value is None:
        value = (
            "| Term | Ordinary meaning | Gap | Observable variables | "
            "Operational autonomy | Enterprise implication |\n"
            "|---|---|---|---|---|---|\n"
            "| agent | acting AI | authority is ambiguous | task completion | bounded | workflow redesign |\n"
        )
    payload = {
        "kind": kind,
        "title": title,
        "purpose": "Bridge ambiguous terminology to reusable operational analysis",
        "rq_ids": [rq_id],
        "source_run_ids": [],
        "source_artifact_refs": [],
        "source_object_ids": ["CF-G1-ONTOLOGY"],
        "derived_from_exhibit_ids": [],
        "content": {"representation": representation, "value": value},
        "capture_origin": "operator_conversation",
    }
    payload.update(extra)
    return payload


def state_signature(app: LocalResearchApplication) -> tuple:
    repo = app.state_repository
    lineage = repo.load_active_lineage_ref("PRJ-1")
    state = repo.load_state_view("PRJ-1", lineage)
    return (
        state.active_lineage_ref,
        str(state.current_snapshot["id"]),
        str(state.current_snapshot["content_digest"]),
        tuple(
            (str(item["kind"]), str(item["id"]), int(item.get("revision", 0)))
            for item in state.effective_objects()
        ),
        tuple(
            str(item["request_id"])
            for item in app.human_decisions.pending("PRJ-1")
        ),
    )


def run_record(
    app: LocalResearchApplication,
    run_id: str,
    *,
    project_id: str = "PRJ-1",
    status: RunStatus = RunStatus.COMPLETED,
) -> CapabilityRunRecord:
    state = app.state_repository.load_state_view(
        "PRJ-1",
        app.state_repository.load_active_lineage_ref("PRJ-1"),
    )
    return CapabilityRunRecord(
        run_id=run_id,
        invocation_id=f"INV-{run_id}",
        invocation_digest="sha256:" + "1" * 64,
        capability_id="desktop-research",
        capability_version="0.1.0",
        descriptor_digest="sha256:" + "2" * 64,
        implementation_id="desktop-research@0.1.0",
        implementation_version="0.1.0",
        function_id="investigate",
        execution_mode="real",
        context_pack_id=f"CTX-{run_id}",
        context_pack_digest="sha256:" + "3" * 64,
        project_ref=project_id,
        lineage_ref=str(state.active_lineage_ref),
        snapshot_ref=str(state.current_snapshot["id"]),
        snapshot_digest=str(state.current_snapshot["content_digest"]),
        attempt=1,
        parent_run_id=None,
        status=status,
        prepared_at="2026-08-31T00:00:00Z",
        started_at="2026-08-31T00:00:01Z",
        completed_at=(
            "2026-08-31T00:00:02Z"
            if status in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.ABORTED}
            else None
        ),
    )


def run_cli(argv, stdin_text=""):
    stream = io.StringIO()
    with patch("sys.stdin", io.StringIO(stdin_text)), redirect_stdout(stream):
        code = cli_main(argv)
    raw = stream.getvalue()
    return code, json.loads(raw)


class ResearchExhibitTests(unittest.TestCase):
    def test_markdown_capture_exact_show_restart_and_research_state_invariant(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_app(temp)
            facade = LocalApplicationFacade(app, "PRJ-1")
            before = state_signature(app)
            original = exhibit_payload()["content"]["value"]

            captured = facade.capture_exhibit(exhibit_payload())
            exhibit_id = captured["exhibit"]["exhibit_id"]
            expected_digest = "sha256:" + hashlib.sha256(original.encode("utf-8")).hexdigest()
            self.assertEqual(captured["status"], "CAPTURED")
            self.assertEqual(captured["exhibit"]["content_digest"], expected_digest)
            self.assertNotIn("content", captured["exhibit"])
            self.assertEqual(state_signature(app), before)
            self.assertFalse(any(
                item["kind"] in {"evidence", "finding"}
                for item in app.state_repository.load_state_view("PRJ-1", "LIN-1").effective_objects()
            ))
            app.close()

            reopened = LocalResearchApplication(
                temp,
                resolver=NullResolver(),
                effective_profile_set_provider=profile_provider,
            )
            try:
                shown = LocalApplicationFacade(reopened, "PRJ-1").show_exhibit(exhibit_id)
                self.assertEqual(shown["exhibit"]["content"]["representation"], "markdown")
                self.assertEqual(shown["exhibit"]["content"]["value"], original)
                self.assertEqual(shown["exhibit"]["content_digest"], expected_digest)
                self.assertEqual(state_signature(reopened), before)
            finally:
                reopened.close()

    def test_json_content_uses_stable_canonical_digest(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_app(temp)
            try:
                facade = LocalApplicationFacade(app, "PRJ-1")
                value_a = {"z": [3, 2, 1], "a": {"right": 2, "left": 1}}
                value_b = {"a": {"left": 1, "right": 2}, "z": [3, 2, 1]}
                first = facade.capture_exhibit(exhibit_payload(
                    kind="matrix", representation="json", value=value_a, title="Matrix A"
                ))
                second = facade.capture_exhibit(exhibit_payload(
                    kind="matrix", representation="json", value=value_b, title="Matrix B"
                ))
                expected = "sha256:" + hashlib.sha256(rfc8785.dumps(value_a)).hexdigest()
                self.assertEqual(first["exhibit"]["content_digest"], expected)
                self.assertEqual(second["exhibit"]["content_digest"], expected)
                self.assertEqual(
                    facade.show_exhibit(first["exhibit"]["exhibit_id"])["exhibit"]["content"]["value"],
                    value_a,
                )
            finally:
                app.close()

    def test_list_is_metadata_only_and_filters_by_authoritative_rq(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_app(temp)
            try:
                facade = LocalApplicationFacade(app, "PRJ-1")
                a = facade.capture_exhibit(exhibit_payload(rq_id="RQ-1", title="G1 table"))
                facade.capture_exhibit(exhibit_payload(
                    rq_id="RQ-2", title="G2 note", kind="note", representation="text", value="note"
                ))
                listed = facade.list_exhibits(rq_id="RQ-1")
                self.assertEqual(
                    [item["exhibit_id"] for item in listed["exhibits"]],
                    [a["exhibit"]["exhibit_id"]],
                )
                self.assertFalse(listed["truncated"])
                self.assertNotIn("content", listed["exhibits"][0])
                with self.assertRaises(LocalApplicationError) as unknown:
                    facade.list_exhibits(rq_id="RQ-UNKNOWN")
                self.assertEqual(unknown.exception.code, "APPLICATION-EXHIBIT-RQ-001")
            finally:
                app.close()

    def test_source_run_artifact_provenance_does_not_mutate_completed_run(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_app(temp)
            try:
                facade = LocalApplicationFacade(app, "PRJ-1")
                run = run_record(app, "RUN-SOURCE")
                app.execution_store.create_run(run)
                artifact = app.execution_store.put_bytes(
                    run,
                    role="source_text",
                    media_type="text/plain",
                    content=b"source rendition",
                )
                before_run = app.execution_store.load_run(run.run_id)
                before_artifacts = app.execution_store.artifacts_for(run.run_id)

                payload = exhibit_payload(
                    source_run_ids=[run.run_id],
                    source_artifact_refs=[artifact.artifact_id],
                )
                result = facade.capture_exhibit(payload)
                shown = facade.show_exhibit(result["exhibit"]["exhibit_id"])["exhibit"]
                self.assertEqual(shown["source_run_ids"], [run.run_id])
                self.assertEqual(shown["source_artifact_refs"], [artifact.artifact_id])
                self.assertEqual(app.execution_store.load_run(run.run_id), before_run)
                self.assertEqual(app.execution_store.artifacts_for(run.run_id), before_artifacts)

                other = run_record(app, "RUN-OTHER", project_id="PRJ-OTHER")
                app.execution_store.create_run(other)
                with self.assertRaises(LocalApplicationError) as cross_project:
                    facade.capture_exhibit(exhibit_payload(source_run_ids=[other.run_id]))
                self.assertEqual(
                    cross_project.exception.code, "APPLICATION-EXHIBIT-RUN-BINDING-001"
                )
            finally:
                app.close()

    def test_derived_from_is_immutable_and_unknown_reference_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_app(temp)
            try:
                facade = LocalApplicationFacade(app, "PRJ-1")
                first = facade.capture_exhibit(exhibit_payload(title="v0"))
                first_id = first["exhibit"]["exhibit_id"]
                first_before = facade.show_exhibit(first_id)["exhibit"]
                second = facade.capture_exhibit(exhibit_payload(
                    title="v1",
                    derived_from_exhibit_ids=[first_id],
                ))
                self.assertEqual(
                    facade.show_exhibit(second["exhibit"]["exhibit_id"])["exhibit"][
                        "derived_from_exhibit_ids"
                    ],
                    [first_id],
                )
                self.assertEqual(facade.show_exhibit(first_id)["exhibit"], first_before)

                with self.assertRaises(LocalApplicationError) as unknown:
                    facade.capture_exhibit(exhibit_payload(
                        title="bad", derived_from_exhibit_ids=["EXH-UNKNOWN"]
                    ))
                self.assertEqual(unknown.exception.code, "APPLICATION-EXHIBIT-DERIVED-001")

                store = LocalResearchExhibitStore(Path(temp) / "research-exhibits.sqlite3")
                with self.assertRaises(LocalResearchExhibitStoreError) as collision:
                    store.capture(first_before)
                self.assertEqual(collision.exception.code, "EXHIBIT-IMMUTABLE-001")
            finally:
                app.close()

    def test_harness_owned_fields_and_unsupported_content_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_app(temp)
            try:
                facade = LocalApplicationFacade(app, "PRJ-1")
                for field, value in (
                    ("exhibit_id", "EXH-CALLER"),
                    ("project_id", "PRJ-CALLER"),
                    ("content_digest", "sha256:" + "0" * 64),
                    ("captured_at", "2026-08-31T00:00:00Z"),
                    ("captured_against", {}),
                ):
                    payload = exhibit_payload()
                    payload[field] = value
                    with self.assertRaises(LocalApplicationError) as owned:
                        facade.capture_exhibit(payload)
                    self.assertEqual(
                        owned.exception.code, "APPLICATION-EXHIBIT-AUTHORITY-001"
                    )

                bad_values = [
                    exhibit_payload(kind="figure"),
                    exhibit_payload(representation="binary", value="x"),
                    exhibit_payload(representation="json", value="scalar"),
                    exhibit_payload(representation="text", value=b"bytes"),
                    exhibit_payload(representation="text", value="\ud800"),
                    exhibit_payload(
                        representation="text",
                        value="x" * (EXHIBIT_CONTENT_MAX_BYTES + 1),
                    ),
                ]
                for payload in bad_values:
                    with self.assertRaises(LocalApplicationError):
                        facade.capture_exhibit(payload)

                payload = exhibit_payload()
                payload["content"]["media_type"] = "text/markdown"
                with self.assertRaises(LocalApplicationError):
                    facade.capture_exhibit(payload)

                with self.assertRaises(LocalApplicationError) as unknown_rq:
                    facade.capture_exhibit(exhibit_payload(rq_id="RQ-MISSING"))
                self.assertEqual(unknown_rq.exception.code, "APPLICATION-EXHIBIT-RQ-001")
            finally:
                app.close()

    def test_optional_store_is_lazy_for_status_resume_run_show_and_list(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_app(temp)
            try:
                facade = LocalApplicationFacade(app, "PRJ-1")
                run = run_record(app, "RUN-READ", status=RunStatus.RUNNING)
                app.execution_store.create_run(run)
                store_path = Path(temp) / "research-exhibits.sqlite3"
                self.assertFalse(store_path.exists())

                facade.status()
                facade.resume_context()
                facade.show_run(run.run_id)
                listed = facade.list_exhibits()

                self.assertEqual(listed["exhibits"], [])
                self.assertFalse(listed["truncated"])
                self.assertFalse(store_path.exists())

                facade.capture_exhibit(exhibit_payload())
                self.assertTrue(store_path.is_file())
            finally:
                app.close()

    def test_bounded_list_returns_one_hundred_and_marks_truncated(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_app(temp)
            try:
                facade = LocalApplicationFacade(app, "PRJ-1")
                for index in range(101):
                    facade.capture_exhibit(exhibit_payload(
                        title=f"Fixture table {index:03d}",
                        representation="text",
                        value=f"fixture-{index}",
                    ))
                listed = facade.list_exhibits()
                self.assertEqual(len(listed["exhibits"]), 100)
                self.assertTrue(listed["truncated"])
                self.assertTrue(all("content" not in item for item in listed["exhibits"]))
            finally:
                app.close()

    def test_cli_capture_list_show_use_public_facade(self):
        with tempfile.TemporaryDirectory() as temp:
            app = make_app(temp)
            try:
                facade = LocalApplicationFacade(app, "PRJ-1")
                with patch(
                    "plugins.local_application.cli.LocalApplicationFacade.open_workspace",
                    return_value=facade,
                ):
                    code, captured = run_cli(
                        ["exhibit", "capture", "--workspace", str(temp), "--json", "-"],
                        json.dumps(exhibit_payload()),
                    )
                    self.assertEqual(code, 0)
                    exhibit_id = captured["exhibit"]["exhibit_id"]

                    code, listed = run_cli([
                        "exhibit", "list", "--workspace", str(temp),
                        "--rq-id", "RQ-1", "--json",
                    ])
                    self.assertEqual(code, 0)
                    self.assertEqual(
                        [item["exhibit_id"] for item in listed["exhibits"]],
                        [exhibit_id],
                    )

                    code, shown = run_cli([
                        "exhibit", "show", "--workspace", str(temp),
                        "--exhibit-id", exhibit_id, "--json",
                    ])
                    self.assertEqual(code, 0)
                    self.assertEqual(shown["exhibit"]["exhibit_id"], exhibit_id)
                    self.assertIn("content", shown["exhibit"])
            finally:
                app.close()


if __name__ == "__main__":
    unittest.main()
