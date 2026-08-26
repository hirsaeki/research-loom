from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import rfc8785

from core.execution import (
    BoundedResourceAccess,
    CapabilityExecutionError,
    CapabilityExecutionOutput,
    CapabilityExecutionService,
    CapabilityRegistry,
    ExecutionFailureCode,
    ExecutionStyle,
    RunLifecycleEvent,
    RunStatus,
)
from core.execution.testing import (
    AllowListedAuthorizationProvider,
    InMemoryExecutionTraceStore,
    StaticClock,
)
from core.runtime import (
    CapabilityNormalizationBoundary,
    LineageView,
    StateDeltaProposal,
    StateView,
)
from plugins.local_execution_store import (
    LocalExecutionStore,
    LocalExecutionStoreConfig,
    LocalExecutionStoreError,
    LocalExecutionStoreIntegrityError,
)
from plugins.sqlite_state_store import SQLiteResearchStateRepository
from runtime_fixtures import project, rq, snapshot


ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "core/fixtures/capabilities/valid"


def load(name: str) -> dict:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def refresh(document: dict, field: str) -> dict:
    body = deepcopy(document)
    body.pop(field, None)
    document[field] = "sha256:" + hashlib.sha256(
        rfc8785.dumps(body)
    ).hexdigest()
    return document


DESCRIPTOR = load("generic-capability-descriptor.json")
CONTEXT = load("generic-capability-context-pack.json")
INVOCATION = load("generic-capability-invocation.json")
HANDOFF = load("generic-capability-handoff.json")


def trace_run(
    run_id: str = "RUN-T",
    *,
    mode: str = "virtual",
    status: RunStatus = RunStatus.PREPARED,
):
    from core.execution import CapabilityRunRecord

    return CapabilityRunRecord(
        run_id,
        f"INV-{run_id}",
        "sha256:" + "1" * 64,
        "fixture.research-support",
        "1.0.0",
        DESCRIPTOR["descriptor_digest"],
        "plugin.fixture.research-support",
        "1.0.0",
        "investigate",
        mode,
        f"CTX-{run_id}",
        "sha256:" + "2" * 64,
        "PRJ-1",
        "LIN-1",
        "SNP-1",
        "sha256:" + "3" * 64,
        1,
        None,
        status,
        "2026-08-26T00:00:00Z",
        "2026-08-26T00:00:01Z" if status is not RunStatus.PREPARED else None,
        None,
        None,
        None,
        None,
        {"trace_id": f"TRACE-{run_id}"},
    )


def seed_state_for_context(context: dict) -> StateView:
    objects = [project(), rq()]
    pin = context["pins"]["research_snapshot"]
    snap = snapshot(
        str(pin["snapshot_id"]),
        objects,
        mode="virtual",
    )
    pin["revision"] = snap["revision"]
    pin["content_digest"] = snap["content_digest"]
    cfg_digest = context["pins"]["project_config"]["configuration_digest"]
    profile_digest = context["pins"]["effective_profile_set"]["content_digest"]
    lineage = LineageView(
        "LIN-1",
        "primary",
        snap["id"],
        snap["content_digest"],
        snap["revision"],
        "virtual",
        project_config_ref="CFG-1",
        project_config_digest=cfg_digest,
        effective_profile_set_ref="EPS-1",
        effective_profile_set_digest=profile_digest,
    )
    return StateView(
        "PRJ-1",
        "LIN-1",
        snap,
        tuple([*objects, snap]),
        (),
        (),
        (lineage,),
        "LIN-1",
        "CFG-1",
        cfg_digest,
        "EPS-1",
        profile_digest,
    )


def bound_documents(store: LocalExecutionStore):
    context = deepcopy(CONTEXT)
    state = seed_state_for_context(context)
    for item in context["resources"]:
        ref = str(item["reference_id"])
        record = store.register_input_bytes(
            ref,
            f"payload:{ref}".encode(),
            media_type="application/octet-stream",
        )
        item["locator"] = record.storage_locator
        item["digest"] = record.digest
    refresh(context, "context_pack_digest")

    invocation = deepcopy(INVOCATION)
    invocation["context_pack"]["context_pack_digest"] = context[
        "context_pack_digest"
    ]
    invocation["pins"]["research_snapshot"] = deepcopy(
        context["pins"]["research_snapshot"]
    )
    refresh(invocation, "invocation_digest")

    handoff = deepcopy(HANDOFF)
    handoff["input_pins"]["invocation_digest"] = invocation[
        "invocation_digest"
    ]
    handoff["input_pins"]["context_pack_digest"] = context[
        "context_pack_digest"
    ]
    handoff["input_pins"]["research_snapshot"] = deepcopy(
        context["pins"]["research_snapshot"]
    )
    handoff["provenance"]["input_content_digests"] = [
        DESCRIPTOR["descriptor_digest"],
        context["context_pack_digest"],
        invocation["invocation_digest"],
    ]
    refresh(handoff, "handoff_digest")
    return context, invocation, handoff, state


class GenericNormalizer:
    def supports(
        self,
        capability_contract_id: str,
        function_id: str,
        contract_version: str,
    ) -> bool:
        return (
            capability_contract_id,
            function_id,
            contract_version,
        ) == ("fixture.research-support", "investigate", "1.0.0")

    def validate_extension(self, handoff, extension, context):
        return ()

    def normalize(self, handoff, extension, context):
        proposal = StateDeltaProposal(
            "SDP-LOCAL-EXEC",
            context["project_ref"],
            context["lineage_ref"],
            (handoff["handoff_id"],),
            (),
            (),
            "local execution integration fixture",
            (),
            context["current_snapshot_ref"],
            context["current_snapshot_digest"],
            {"run_id": context["run_id"]},
        )
        return proposal.with_calculated_digest()


class ArtifactProducingAdapter:
    implementation_id = "plugin.fixture.research-support"
    implementation_version = "1.0.0"
    capability_id = "fixture.research-support"
    capability_version = "1.0.0"
    supported_functions = ("investigate",)
    supported_execution_modes = ("virtual",)
    execution_style = ExecutionStyle.MANAGED

    def __init__(self, handoff) -> None:
        self.handoff = deepcopy(handoff)
        self.cancelled = []

    def execute(self, request):
        payload = request.resources.read("REF-INPUT-001")
        artifacts = (
            request.artifacts.put_bytes(
                role="generated_code",
                media_type="text/x-python",
                content=b"print('future poc')\n",
            ),
            request.artifacts.put_bytes(
                role="log",
                media_type="text/plain",
                content=b"ok\n",
            ),
            request.artifacts.put_bytes(
                role="measurement",
                media_type="application/json",
                content=b'{"value":1}',
                provenance={"input_digest": payload.digest},
            ),
        )
        return CapabilityExecutionOutput(
            deepcopy(self.handoff),
            artifacts=artifacts,
        )

    def cancel(self, run_id: str) -> None:
        self.cancelled.append(run_id)


class ExternalAdapter(ArtifactProducingAdapter):
    execution_style = ExecutionStyle.EXTERNAL

    def execute(self, request):
        raise AssertionError("external adapter must not execute")


def make_service(
    store: LocalExecutionStore,
    state_repository: SQLiteResearchStateRepository,
    adapter,
    invocation: dict,
):
    registry = CapabilityRegistry()
    registry.register(adapter, DESCRIPTOR)
    auth = AllowListedAuthorizationProvider(
        (
            invocation["runtime_authorization_evidence"][
                "authorization_digest"
            ],
        )
    )
    return CapabilityExecutionService(
        registry,
        store,
        state_repository,
        auth,
        store,
        CapabilityNormalizationBoundary((GenericNormalizer(),)),
        StaticClock(),
        artifact_store=store,
    )


class TraceStoreConformanceMixin:
    def make_trace_store(self):
        raise NotImplementedError

    def test_trace_store_cas_and_immutable_identity_conformance(self):
        store = self.make_trace_store()
        run = trace_run()
        store.create_run(run)
        store.append_run_event(
            RunLifecycleEvent(
                run.run_id,
                1,
                None,
                RunStatus.PREPARED,
                "2026-08-26T00:00:00Z",
                "prepared",
            )
        )
        running = replace(
            run,
            status=RunStatus.RUNNING,
            started_at="2026-08-26T00:00:01Z",
        )
        event = RunLifecycleEvent(
            run.run_id,
            2,
            RunStatus.PREPARED,
            RunStatus.RUNNING,
            "2026-08-26T00:00:01Z",
            "started",
        )
        with self.assertRaises((ValueError, LocalExecutionStoreIntegrityError)):
            store.transition_run(
                RunStatus.PREPARED,
                replace(running, capability_id="fixture.mutated"),
                event,
            )
        self.assertEqual(store.load_run(run.run_id), run)
        self.assertTrue(store.transition_run(RunStatus.PREPARED, running, event))
        self.assertFalse(
            store.transition_run(RunStatus.PREPARED, running, event)
        )

        invocation = {
            "invocation_id": "INV-IMM",
            "value": 1,
        }
        store.store_invocation(invocation)
        store.store_invocation(deepcopy(invocation))
        with self.assertRaises(ValueError):
            store.store_invocation(
                {"invocation_id": "INV-IMM", "value": 2}
            )


class InMemoryTraceStoreConformanceTests(
    TraceStoreConformanceMixin,
    unittest.TestCase,
):
    def make_trace_store(self):
        return InMemoryExecutionTraceStore()


class LocalTraceStoreConformanceTests(
    TraceStoreConformanceMixin,
    unittest.TestCase,
):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.store = LocalExecutionStore(
            Path(self.tempdir.name) / "execution-store"
        )

    def tearDown(self):
        self.store.close()
        self.tempdir.cleanup()

    def make_trace_store(self):
        return self.store


class LocalExecutionStoreTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.intake = self.root / "intake"
        self.intake.mkdir()
        self.store = LocalExecutionStore(
            self.root / "execution-store",
            allowed_import_roots=(self.intake,),
        )
        self.runs = []
        for run_id, mode in (
            ("RUN-A", "virtual"),
            ("RUN-B", "virtual"),
            ("RUN-R", "real"),
        ):
            run = trace_run(run_id, mode=mode)
            self.store.create_run(run)
            self.store.append_run_event(
                RunLifecycleEvent(
                    run.run_id,
                    1,
                    None,
                    RunStatus.PREPARED,
                    "2026-08-26T00:00:00Z",
                    "prepared",
                )
            )
            self.runs.append(run)

    def tearDown(self):
        if self.store is not None:
            self.store.close()
        self.tempdir.cleanup()

    def test_fresh_migration_reopen_and_run_history(self):
        self.assertEqual(self.store.schema_version, 1)
        running = replace(
            self.runs[0],
            status=RunStatus.RUNNING,
            started_at="2026-08-26T00:00:01Z",
        )
        self.assertTrue(
            self.store.transition_run(
                RunStatus.PREPARED,
                running,
                RunLifecycleEvent(
                    "RUN-A",
                    2,
                    RunStatus.PREPARED,
                    RunStatus.RUNNING,
                    "2026-08-26T00:00:01Z",
                    "started",
                ),
            )
        )
        self.store.close()
        reopened = LocalExecutionStore(
            self.root / "execution-store",
            allowed_import_roots=(self.intake,),
        )
        self.store = reopened
        self.assertEqual(reopened.load_run("RUN-A"), running)
        self.assertEqual(
            [item.to_status for item in reopened.events_for("RUN-A")],
            [RunStatus.PREPARED, RunStatus.RUNNING],
        )
        self.assertEqual(reopened.describe_run("RUN-A")["status"], "RUNNING")

    def test_unknown_newer_schema_fails_closed(self):
        self.store.close()
        with sqlite3.connect(
            self.root / "execution-store" / "execution.db"
        ) as connection:
            connection.execute(
                """
                INSERT INTO schema_migrations(version, name)
                VALUES (9999, '9999_future')
                """
            )
        with self.assertRaises(LocalExecutionStoreError):
            LocalExecutionStore(self.root / "execution-store")
        self.store = None

    def test_artifact_round_trip_unicode_binary_dedup_and_identity(self):
        text = "研究ログ 🐇".encode("utf-8")
        first = self.store.put_bytes(
            self.runs[0],
            role="log",
            media_type="text/plain",
            content=text,
            artifact_id="ART-1",
        )
        second = self.store.put_bytes(
            self.runs[1],
            role="measurement",
            media_type="text/plain",
            content=text,
            artifact_id="ART-2",
        )
        binary = self.store.put_bytes(
            self.runs[0],
            role="binary",
            media_type="application/octet-stream",
            content=bytes(range(256)),
            artifact_id="ART-3",
        )
        self.assertEqual(first.digest, second.digest)
        self.assertNotEqual(first.run_id, second.run_id)
        self.assertEqual(
            self.store.load_artifact("ART-1").content,
            text,
        )
        self.assertEqual(
            self.store.load_artifact(binary.artifact_id).content,
            bytes(range(256)),
        )
        with self.assertRaises(ValueError):
            self.store.put_bytes(
                self.runs[0],
                role="log",
                media_type="text/plain",
                content=b"different",
                artifact_id="ART-1",
            )
        self.assertEqual(first.execution_mode, "virtual")

        real = self.store.put_bytes(
            self.runs[2],
            role="measurement",
            media_type="text/plain",
            content=text,
            artifact_id="ART-REAL",
        )
        self.assertEqual(real.digest, first.digest)
        self.assertEqual(real.execution_mode, "real")
        self.assertNotEqual(real.run_id, first.run_id)

    def test_artifact_quota_and_staging_failure_cleanup(self):
        limited_root = self.root / "limited"
        limited = LocalExecutionStore(
            limited_root,
            config=LocalExecutionStoreConfig(
                max_artifact_bytes=4,
                max_run_output_bytes=6,
                max_resource_bytes=16,
            ),
        )
        try:
            run = trace_run("RUN-LIMIT")
            limited.create_run(run)
            limited.append_run_event(
                RunLifecycleEvent(
                    run.run_id,
                    1,
                    None,
                    RunStatus.PREPARED,
                    "2026-08-26T00:00:00Z",
                    "prepared",
                )
            )
            limited.put_bytes(
                run,
                role="log",
                media_type="text/plain",
                content=b"1234",
            )
            with self.assertRaises(LocalExecutionStoreError):
                limited.put_bytes(
                    run,
                    role="log",
                    media_type="text/plain",
                    content=b"567",
                )
        finally:
            limited.close()

        failing_root = self.root / "failing"
        failing = LocalExecutionStore(failing_root)
        try:
            run = trace_run("RUN-FAIL")
            failing.create_run(run)
            failing.append_run_event(
                RunLifecycleEvent(
                    run.run_id,
                    1,
                    None,
                    RunStatus.PREPARED,
                    "2026-08-26T00:00:00Z",
                    "prepared",
                )
            )
            with patch(
                "plugins.local_execution_store.store.os.link",
                side_effect=OSError("simulated atomic link failure"),
            ):
                with self.assertRaises(OSError):
                    failing.put_bytes(
                        run,
                        role="log",
                        media_type="text/plain",
                        content=b"partial",
                    )
            self.assertEqual(list(failing.staging_root.iterdir()), [])
        finally:
            failing.close()

    def test_controlled_file_intake_rejects_symlink_traversal_and_special_file(self):
        regular = self.intake / "data.bin"
        regular.write_bytes(b"external")
        imported = self.store.import_output_file(
            self.runs[0],
            regular,
            role="measurement",
            media_type="application/octet-stream",
            artifact_id="ART-EXT",
        )
        self.assertEqual(
            self.store.load_artifact(imported.artifact_id).content,
            b"external",
        )
        resource = self.store.register_input_file(
            "REF-FILE",
            regular,
            media_type="application/octet-stream",
        )
        self.assertEqual(resource.size, 8)

        link = self.intake / "link.bin"
        try:
            link.symlink_to(regular)
        except (OSError, NotImplementedError):
            link = None
        if link is not None:
            with self.assertRaises(PermissionError):
                self.store.register_input_file("REF-LINK", link)

        with self.assertRaises(PermissionError):
            self.store.register_input_file(
                "REF-TRAVERSAL",
                self.intake / ".." / "intake" / "data.bin",
            )

        if hasattr(os, "mkfifo"):
            fifo = self.intake / "fifo"
            os.mkfifo(fifo)
            with self.assertRaises(PermissionError):
                self.store.register_input_file("REF-FIFO", fifo)

    def test_resource_provider_verifies_registration_digest_and_authorization(self):
        record = self.store.register_input_bytes(
            "REF-1",
            b"bounded",
            media_type="text/plain",
        )
        context = {
            "resources": [
                {
                    "reference_id": "REF-1",
                    "locator": record.storage_locator,
                    "digest": record.digest,
                },
                {
                    "reference_id": "REF-2",
                    "locator": "resource://sha256/" + "0" * 64,
                    "digest": "sha256:" + "0" * 64,
                },
            ]
        }
        access = BoundedResourceAccess(
            context,
            ("REF-1",),
            self.store,
            artifact_store=self.store,
        )
        self.assertEqual(access.artifact_store, self.store)
        self.assertEqual(access.read("REF-1").content, b"bounded")
        with self.assertRaises(CapabilityExecutionError) as denied:
            access.read("REF-2")
        self.assertEqual(
            denied.exception.issue.code,
            ExecutionFailureCode.RESOURCE_DENIED.value,
        )

        bad = deepcopy(context["resources"][0])
        bad["digest"] = "sha256:" + "f" * 64
        with self.assertRaises(LocalExecutionStoreIntegrityError):
            self.store.load(bad)

    def test_blob_corruption_and_missing_blob_are_detected(self):
        artifact = self.store.put_bytes(
            self.runs[0],
            role="measurement",
            media_type="application/octet-stream",
            content=b"original",
            artifact_id="ART-CORRUPT",
        )
        digest_hex = artifact.digest.removeprefix("sha256:")
        path = self.store.blob_root / digest_hex[:2] / digest_hex
        path.write_bytes(b"corrupt")
        with self.assertRaises(LocalExecutionStoreIntegrityError):
            self.store.load_artifact("ART-CORRUPT")
        self.assertIn(
            "ARTIFACT_BLOB_DIGEST_MISMATCH",
            {item.code for item in self.store.diagnose_integrity()},
        )

        missing = self.store.put_bytes(
            self.runs[1],
            role="log",
            media_type="text/plain",
            content=b"missing",
            artifact_id="ART-MISSING",
        )
        missing_hex = missing.digest.removeprefix("sha256:")
        (
            self.store.blob_root / missing_hex[:2] / missing_hex
        ).unlink()
        self.assertIn(
            "ARTIFACT_BLOB_MISSING",
            {item.code for item in self.store.diagnose_integrity()},
        )

    def test_run_scoped_doctor_ignores_unrelated_document_corruption(self):
        with sqlite3.connect(
            self.root / "execution-store" / "execution.db"
        ) as connection:
            connection.execute(
                """
                INSERT INTO execution_documents(
                    document_type, identity, payload_sha256, payload_json, run_id
                ) VALUES ('extension', 'UNRELATED', 'sha256:bad', '{', 'RUN-B')
                """
            )
        scoped = {item.code for item in self.store.diagnose_integrity("RUN-A")}
        global_codes = {item.code for item in self.store.diagnose_integrity()}
        self.assertNotIn("DOCUMENT_INVALID_JSON", scoped)
        self.assertIn("DOCUMENT_INVALID_JSON", global_codes)

    def test_doctor_detects_dangling_document_and_diagnostic_run_refs(self):
        payload = {"kind": "fixture"}
        payload_json = rfc8785.dumps(payload).decode("utf-8")
        payload_sha = "sha256:" + hashlib.sha256(
            rfc8785.dumps(payload)
        ).hexdigest()
        with sqlite3.connect(
            self.root / "execution-store" / "execution.db"
        ) as connection:
            connection.execute(
                "PRAGMA foreign_keys = OFF"
            )
            connection.execute(
                """
                INSERT INTO execution_documents(
                    document_type, identity, payload_sha256, payload_json, run_id
                ) VALUES ('extension', 'DANGLING', ?, ?, 'RUN-MISSING')
                """,
                (payload_sha, payload_json),
            )
            connection.execute(
                """
                INSERT INTO diagnostics(run_id, kind, payload_json)
                VALUES ('RUN-MISSING', 'fixture', '{}')
                """
            )
        codes = {item.code for item in self.store.diagnose_integrity()}
        self.assertIn("DANGLING_DOCUMENT_RUN_REF", codes)
        self.assertIn("DANGLING_DIAGNOSTIC_RUN_REF", codes)

    def test_lifecycle_projection_corruption_is_diagnostic_only(self):
        with sqlite3.connect(
            self.root / "execution-store" / "execution.db"
        ) as connection:
            connection.execute(
                "UPDATE runs SET status='COMPLETED' WHERE run_id='RUN-A'"
            )
        codes = {
            item.code
            for item in self.store.diagnose_integrity("RUN-A")
        }
        self.assertIn("RUN_EVENT_PROJECTION_MISMATCH", codes)
        self.assertEqual(
            self.store.diagnose_integrity("NO-SUCH-RUN")[0].code,
            "MISSING_RUN",
        )


class LocalExecutionIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.exec_root = self.root / "execution-store"
        self.state_db = self.root / "research-state.sqlite3"
        self.store = LocalExecutionStore(
            self.exec_root,
            allowed_import_roots=(self.root,),
        )
        (
            self.context,
            self.invocation,
            self.handoff,
            self.state,
        ) = bound_documents(self.store)
        self.state_repo = SQLiteResearchStateRepository(self.state_db)
        self.state_repo.initialize_from_validated_state_view(self.state)

    def tearDown(self):
        try:
            self.store.close()
        except sqlite3.Error:
            pass
        try:
            self.state_repo.close()
        except sqlite3.Error:
            pass
        self.tempdir.cleanup()

    def test_managed_resource_artifact_handoff_to_candidate_proposal_only(self):
        before = self.state_repo.load_state_view("PRJ-1", "LIN-1")
        service = make_service(
            self.store,
            self.state_repo,
            ArtifactProducingAdapter(self.handoff),
            self.invocation,
        )
        result = service.execute_managed(
            DESCRIPTOR,
            self.invocation,
            self.context,
            lineage_ref="LIN-1",
        )
        self.assertEqual(result.run.status, RunStatus.COMPLETED)
        self.assertIsNotNone(result.state_delta_proposal)
        artifacts = self.store.artifacts_for("RUN-001")
        self.assertEqual(
            {item.role for item in artifacts},
            {"generated_code", "log", "measurement"},
        )
        self.assertTrue(
            all(item.execution_mode == "virtual" for item in artifacts)
        )
        after = self.state_repo.load_state_view("PRJ-1", "LIN-1")
        self.assertEqual(before, after)
        self.assertEqual(
            before.current_snapshot["content_digest"],
            after.current_snapshot["content_digest"],
        )
        self.assertEqual(before.active_lineage_ref, after.active_lineage_ref)
        self.assertEqual(
            self.store.diagnose_integrity("RUN-001"),
            (),
        )

    def test_external_prepare_reopen_intake_collect(self):
        service = make_service(
            self.store,
            self.state_repo,
            ExternalAdapter(self.handoff),
            self.invocation,
        )
        prepared = service.prepare_external(
            DESCRIPTOR,
            self.invocation,
            self.context,
            lineage_ref="LIN-1",
        )
        self.assertEqual(prepared.run.status, RunStatus.RUNNING)

        self.store.close()
        self.state_repo.close()
        self.store = LocalExecutionStore(
            self.exec_root,
            allowed_import_roots=(self.root,),
        )
        self.state_repo = SQLiteResearchStateRepository(self.state_db)

        self.assertEqual(
            self.store.load(self.context["resources"][0]).content,
            b"payload:REF-INPUT-001",
        )

        output = self.root / "external-output.bin"
        output.write_bytes(b"external measurement")
        artifact = self.store.import_output_file(
            self.store.load_run("RUN-001"),
            output,
            role="measurement",
            media_type="application/octet-stream",
            artifact_id="ART-EXTERNAL",
        )
        reopened = make_service(
            self.store,
            self.state_repo,
            ExternalAdapter(self.handoff),
            self.invocation,
        )
        result = reopened.collect_external(
            "RUN-001",
            self.handoff,
            artifacts=(artifact,),
        )
        self.assertEqual(result.run.status, RunStatus.COMPLETED)
        self.assertIsNotNone(result.state_delta_proposal)
        self.assertEqual(
            self.store.load_artifact("ART-EXTERNAL").content,
            b"external measurement",
        )


if __name__ == "__main__":
    unittest.main()
