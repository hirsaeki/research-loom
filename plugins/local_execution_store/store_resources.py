"""Registering and loading artifact and input resources of the execution store (#494)."""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from core.execution.models import (
    CapabilityRunRecord,
    ExecutionArtifactMetadata,
    ResourcePayload,
)
from plugins._infra.clock import utc_now as _now

from .store_model import (
    LocalExecutionStoreError,
    LocalExecutionStoreIntegrityError,
    RegisteredResource,
    _canonical_json,
)


class StoreResourceMixin:
    def put_bytes(
        self,
        run: CapabilityRunRecord,
        *,
        role: str,
        media_type: str,
        content: bytes,
        artifact_id: str | None = None,
        provenance: Mapping[str, Any] | None = None,
        parent_artifact_refs: tuple[str, ...] = (),
    ) -> ExecutionArtifactMetadata:
        if not isinstance(content, bytes):
            raise TypeError("artifact content must be bytes")
        if len(content) > self.config.max_artifact_bytes:
            raise LocalExecutionStoreError("artifact exceeds configured max_artifact_bytes")
        persisted = self.load_run(run.run_id)
        if persisted is None:
            raise LocalExecutionStoreError("artifact Run must already exist in the execution trace")
        if (
            persisted.execution_mode != run.execution_mode
            or persisted.capability_id != run.capability_id
        ):
            raise LocalExecutionStoreIntegrityError(
                "artifact Run binding does not match persisted Run"
            )

        trusted_provenance = dict(provenance or {})
        trusted_provenance.update(
            {
                "source_run_id": run.run_id,
                "execution_mode": run.execution_mode,
                "stored_by": "plugins.local_execution_store",
                "stored_at": _now(),
                "parent_artifact_refs": list(parent_artifact_refs),
            }
        )
        artifact_identity = artifact_id or f"ART-{uuid.uuid4().hex}"
        with self._write_transaction():
            row = self._connection.execute(
                """
                SELECT COALESCE(SUM(size), 0) AS total
                FROM execution_artifacts WHERE run_id = ?
                """,
                (run.run_id,),
            ).fetchone()
            current_total = int(row["total"])
            if current_total + len(content) > self.config.max_run_output_bytes:
                raise LocalExecutionStoreError("Run output exceeds configured max_run_output_bytes")

            digest, locator = self._store_blob(content, scheme="artifact")
            metadata = ExecutionArtifactMetadata(
                artifact_identity,
                run.run_id,
                str(role),
                str(media_type),
                len(content),
                digest,
                locator,
                run.execution_mode,
                trusted_provenance,
            )
            self._register_output_artifact_in_transaction(metadata)
        return metadata

    def import_output_file(
        self,
        run: CapabilityRunRecord,
        source_path: str | Path,
        *,
        role: str,
        media_type: str,
        artifact_id: str | None = None,
        provenance: Mapping[str, Any] | None = None,
        parent_artifact_refs: tuple[str, ...] = (),
    ) -> ExecutionArtifactMetadata:
        content = self._read_controlled_file(
            source_path,
            max_bytes=self.config.max_artifact_bytes,
        )
        return self.put_bytes(
            run,
            role=role,
            media_type=media_type,
            content=content,
            artifact_id=artifact_id,
            provenance=provenance,
            parent_artifact_refs=parent_artifact_refs,
        )

    def load_artifact(self, artifact_id: str) -> ResourcePayload:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT artifact_id, media_type, size, digest, storage_locator
                FROM execution_artifacts WHERE artifact_id = ?
                """,
                (artifact_id,),
            ).fetchone()
        if row is None:
            raise KeyError(artifact_id)
        content = self._load_verified_blob(
            str(row["storage_locator"]),
            str(row["digest"]),
            int(row["size"]),
        )
        return ResourcePayload(
            str(row["artifact_id"]),
            content,
            str(row["digest"]),
            str(row["media_type"]),
        )

    def artifacts_for(
        self,
        run_id: str,
    ) -> tuple[ExecutionArtifactMetadata, ...]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT artifact_id, run_id, role, media_type, size, digest,
                       storage_locator, execution_mode, provenance_json
                FROM execution_artifacts
                WHERE run_id = ?
                ORDER BY artifact_id
                """,
                (run_id,),
            ).fetchall()
        return tuple(
            ExecutionArtifactMetadata(
                str(row["artifact_id"]),
                str(row["run_id"]),
                str(row["role"]),
                str(row["media_type"]),
                int(row["size"]),
                str(row["digest"]),
                str(row["storage_locator"]),
                str(row["execution_mode"]),
                json.loads(str(row["provenance_json"])),
            )
            for row in rows
        )

    # ---- ResourceProvider ----------------------------------------------------

    def register_input_bytes(
        self,
        reference_id: str,
        content: bytes,
        *,
        media_type: str | None = None,
        provenance: Mapping[str, Any] | None = None,
    ) -> RegisteredResource:
        if not isinstance(content, bytes):
            raise TypeError("resource content must be bytes")
        if len(content) > self.config.max_resource_bytes:
            raise LocalExecutionStoreError("resource exceeds configured max_resource_bytes")
        digest, locator = self._store_blob(content, scheme="resource")
        trusted_provenance = dict(provenance or {})
        trusted_provenance.update(
            {
                "registered_by": "plugins.local_execution_store",
                "registered_at": _now(),
            }
        )
        record = RegisteredResource(
            str(reference_id),
            str(media_type) if media_type is not None else None,
            len(content),
            digest,
            locator,
            trusted_provenance,
        )
        payload = (
            record.reference_id,
            record.media_type,
            record.size,
            record.digest,
            record.storage_locator,
            _canonical_json(dict(record.provenance)),
        )
        with self._write_transaction():
            prior = self._connection.execute(
                """
                SELECT reference_id, media_type, size, digest, storage_locator,
                       provenance_json
                FROM input_resources WHERE reference_id = ?
                """,
                (record.reference_id,),
            ).fetchone()
            if prior is not None:
                prior_tuple = tuple(prior[key] for key in prior.keys())
                if prior_tuple != payload:
                    raise ValueError("immutable resource identity collision")
                return record
            self._connection.execute(
                """
                INSERT INTO input_resources(
                    reference_id, media_type, size, digest, storage_locator,
                    provenance_json
                ) VALUES (?,?,?,?,?,?)
                """,
                payload,
            )
        return record

    def register_input_file(
        self,
        reference_id: str,
        source_path: str | Path,
        *,
        media_type: str | None = None,
        provenance: Mapping[str, Any] | None = None,
    ) -> RegisteredResource:
        content = self._read_controlled_file(
            source_path,
            max_bytes=self.config.max_resource_bytes,
        )
        return self.register_input_bytes(
            reference_id,
            content,
            media_type=media_type,
            provenance=provenance,
        )

    def load(self, resource: Mapping[str, Any]) -> ResourcePayload:
        reference_id = str(resource["reference_id"])
        with self._lock:
            row = self._connection.execute(
                """
                SELECT reference_id, media_type, size, digest, storage_locator
                FROM input_resources WHERE reference_id = ?
                """,
                (reference_id,),
            ).fetchone()
        if row is None:
            raise KeyError(reference_id)
        locator = resource.get("locator")
        if locator is not None and str(locator) != str(row["storage_locator"]):
            raise LocalExecutionStoreIntegrityError(
                "Context Pack resource locator does not match registered locator"
            )
        expected_digest = resource.get("digest")
        if expected_digest is not None and str(expected_digest) != str(row["digest"]):
            raise LocalExecutionStoreIntegrityError(
                "Context Pack resource digest does not match registered digest"
            )
        content = self._load_verified_blob(
            str(row["storage_locator"]),
            str(row["digest"]),
            int(row["size"]),
        )
        return ResourcePayload(
            reference_id,
            content,
            str(row["digest"]),
            str(row["media_type"]) if row["media_type"] is not None else None,
        )

    # ---- Diagnostics ---------------------------------------------------------
