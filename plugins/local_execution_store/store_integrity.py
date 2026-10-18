"""Read-only integrity diagnosis of the execution store (#494)."""

from __future__ import annotations

import json
from typing import Any

from core.execution.models import (
    RunStatus,
)

from .store_model import (
    _ALLOWED_TRANSITIONS,
    LocalExecutionStoreIntegrityError,
    StoreIntegrityDiagnostic,
    _payload_sha256,
)


class StoreIntegrityMixin:
    def diagnose_integrity(
        self,
        run_id: str | None = None,
    ) -> tuple[StoreIntegrityDiagnostic, ...]:
        diagnostics: list[StoreIntegrityDiagnostic] = []
        with self._lock:
            if run_id is not None:
                exists = self._connection.execute(
                    "SELECT 1 FROM runs WHERE run_id = ?",
                    (run_id,),
                ).fetchone()
                if exists is None:
                    return (
                        StoreIntegrityDiagnostic(
                            "MISSING_RUN",
                            f"Run {run_id} is missing",
                            run_id=run_id,
                        ),
                    )
            run_rows = self._connection.execute(
                "SELECT * FROM runs" + (" WHERE run_id = ?" if run_id is not None else ""),
                (run_id,) if run_id is not None else (),
            ).fetchall()
            if run_id is None:
                document_rows = self._connection.execute(
                    "SELECT * FROM execution_documents"
                ).fetchall()
                diagnostic_rows = self._connection.execute(
                    "SELECT run_id FROM diagnostics"
                ).fetchall()
            else:
                run_row = run_rows[0]
                clauses = ["run_id = ?"]
                args: list[Any] = [run_id]
                for doc_type, identity in (
                    ("descriptor", str(run_row["descriptor_digest"])),
                    ("invocation", str(run_row["invocation_id"])),
                    ("context_pack", str(run_row["context_pack_id"])),
                ):
                    clauses.append("(document_type = ? AND identity = ?)")
                    args.extend((doc_type, identity))
                if run_row["handoff_ref"] is not None:
                    clauses.append("(document_type = ? AND identity = ?)")
                    args.extend(("handoff", str(run_row["handoff_ref"])))
                document_rows = self._connection.execute(
                    "SELECT * FROM execution_documents WHERE " + " OR ".join(clauses),
                    tuple(args),
                ).fetchall()
                diagnostic_rows = self._connection.execute(
                    "SELECT run_id FROM diagnostics WHERE run_id = ?",
                    (run_id,),
                ).fetchall()
            artifact_rows = self._connection.execute(
                "SELECT * FROM execution_artifacts"
                + (" WHERE run_id = ?" if run_id is not None else ""),
                (run_id,) if run_id is not None else (),
            ).fetchall()

        docs = {(str(row["document_type"]), str(row["identity"])): row for row in document_rows}
        for row in document_rows:
            document_run_id = str(row["run_id"]) if row["run_id"] else None
            if document_run_id is not None:
                with self._lock:
                    run_exists = self._connection.execute(
                        "SELECT 1 FROM runs WHERE run_id = ?",
                        (document_run_id,),
                    ).fetchone()
                if run_exists is None:
                    diagnostics.append(
                        StoreIntegrityDiagnostic(
                            "DANGLING_DOCUMENT_RUN_REF",
                            "execution document references a missing Run",
                            run_id=document_run_id,
                        )
                    )
            try:
                payload = json.loads(str(row["payload_json"]))
                if _payload_sha256(payload) != str(row["payload_sha256"]):
                    diagnostics.append(
                        StoreIntegrityDiagnostic(
                            "DOCUMENT_PAYLOAD_DIGEST_MISMATCH",
                            "immutable execution document payload hash mismatch",
                            run_id=document_run_id,
                        )
                    )
            except (TypeError, ValueError, json.JSONDecodeError):
                diagnostics.append(
                    StoreIntegrityDiagnostic(
                        "DOCUMENT_INVALID_JSON",
                        "immutable execution document is not valid canonical JSON",
                        run_id=document_run_id,
                    )
                )

        for row in diagnostic_rows:
            diagnostic_run_id = str(row["run_id"])
            with self._lock:
                run_exists = self._connection.execute(
                    "SELECT 1 FROM runs WHERE run_id = ?",
                    (diagnostic_run_id,),
                ).fetchone()
            if run_exists is None:
                diagnostics.append(
                    StoreIntegrityDiagnostic(
                        "DANGLING_DIAGNOSTIC_RUN_REF",
                        "diagnostic record references a missing Run",
                        run_id=diagnostic_run_id,
                    )
                )

        for run_row in run_rows:
            rid = str(run_row["run_id"])
            required = (
                ("descriptor", str(run_row["descriptor_digest"])),
                ("invocation", str(run_row["invocation_id"])),
                ("context_pack", str(run_row["context_pack_id"])),
            )
            for doc_type, identity in required:
                if (doc_type, identity) not in docs:
                    diagnostics.append(
                        StoreIntegrityDiagnostic(
                            f"MISSING_{doc_type.upper()}",
                            f"Run references missing {doc_type} {identity}",
                            run_id=rid,
                        )
                    )
            if (
                run_row["handoff_ref"] is not None
                and (
                    "handoff",
                    str(run_row["handoff_ref"]),
                )
                not in docs
            ):
                diagnostics.append(
                    StoreIntegrityDiagnostic(
                        "MISSING_HANDOFF",
                        "Run projection references a missing Handoff",
                        run_id=rid,
                    )
                )

            events = self.events_for(rid)
            if not events:
                diagnostics.append(
                    StoreIntegrityDiagnostic(
                        "INVALID_LIFECYCLE_SEQUENCE",
                        "Run has no lifecycle events",
                        run_id=rid,
                    )
                )
                continue
            prior: RunStatus | None = None
            for index, event in enumerate(events, start=1):
                if event.sequence != index:
                    diagnostics.append(
                        StoreIntegrityDiagnostic(
                            "INVALID_LIFECYCLE_SEQUENCE",
                            "Run lifecycle sequence is not contiguous",
                            run_id=rid,
                        )
                    )
                    break
                if index == 1:
                    if event.from_status is not None or event.to_status is not RunStatus.PREPARED:
                        diagnostics.append(
                            StoreIntegrityDiagnostic(
                                "ILLEGAL_LIFECYCLE_TRANSITION",
                                "first lifecycle event must be None -> PREPARED",
                                run_id=rid,
                            )
                        )
                    prior = event.to_status
                    continue
                if (
                    event.from_status is not prior
                    or event.to_status not in _ALLOWED_TRANSITIONS[prior]
                ):
                    diagnostics.append(
                        StoreIntegrityDiagnostic(
                            "ILLEGAL_LIFECYCLE_TRANSITION",
                            "lifecycle event does not follow canonical transition graph",
                            run_id=rid,
                        )
                    )
                    break
                prior = event.to_status
            if prior is not None and prior.value != str(run_row["status"]):
                diagnostics.append(
                    StoreIntegrityDiagnostic(
                        "RUN_EVENT_PROJECTION_MISMATCH",
                        "current Run status disagrees with append-only lifecycle history",
                        run_id=rid,
                    )
                )

        for row in artifact_rows:
            aid = str(row["artifact_id"])
            rid = str(row["run_id"])
            with self._lock:
                run_exists = self._connection.execute(
                    "SELECT 1 FROM runs WHERE run_id = ?",
                    (rid,),
                ).fetchone()
            if run_exists is None:
                diagnostics.append(
                    StoreIntegrityDiagnostic(
                        "DANGLING_ARTIFACT_RUN_REF",
                        "artifact metadata references a missing Run",
                        run_id=rid,
                        artifact_id=aid,
                    )
                )
            try:
                self._load_verified_blob(
                    str(row["storage_locator"]),
                    str(row["digest"]),
                    int(row["size"]),
                )
            except FileNotFoundError:
                diagnostics.append(
                    StoreIntegrityDiagnostic(
                        "ARTIFACT_BLOB_MISSING",
                        "artifact metadata has no backing blob",
                        run_id=rid,
                        artifact_id=aid,
                    )
                )
            except LocalExecutionStoreIntegrityError:
                diagnostics.append(
                    StoreIntegrityDiagnostic(
                        "ARTIFACT_BLOB_DIGEST_MISMATCH",
                        "artifact blob digest/size does not match metadata",
                        run_id=rid,
                        artifact_id=aid,
                    )
                )
        return tuple(diagnostics)
