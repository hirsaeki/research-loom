from __future__ import annotations

from dataclasses import asdict
import sqlite3
from typing import Any, TYPE_CHECKING

from core.runtime.ports import RepositoryError

from ._support import (
    debug_active_lineage,
    decode_payload_row,
    lineage_from_row,
    receipt_from_json,
    verify_embedded_content_digest,
)

if TYPE_CHECKING:
    from .adapter import SQLiteResearchStateRepository


class DiagnosticsMixin:
    def integrity_issues(
        self: "SQLiteResearchStateRepository",
    ) -> tuple[str, ...]:
        """Return deterministic diagnostics; never repair persisted state."""

        issues: list[str] = []
        try:
            for row in self._connection.execute("PRAGMA integrity_check"):
                if str(row[0]).lower() != "ok":
                    issues.append(f"sqlite-integrity:{row[0]}")
            for row in self._connection.execute("PRAGMA foreign_key_check"):
                issues.append(
                    "foreign-key:"
                    + ":".join(
                        str(row[key])
                        for key in row.keys()
                        if row[key] is not None
                    )
                )

            for row in self._connection.execute(
                """
                SELECT kind, object_id, revision,
                       payload_json, payload_digest, content_digest
                FROM object_revisions
                ORDER BY kind, object_id, revision
                """
            ):
                label = (
                    f"{row['kind']}:{row['object_id']}@{row['revision']}"
                )
                try:
                    payload = decode_payload_row(row)
                    if str(row["kind"]) == "snapshot":
                        verify_embedded_content_digest(payload)
                except RepositoryError as exc:
                    issues.append(f"payload:{label}:{exc}")

            for row in self._connection.execute(
                """
                SELECT s.snapshot_ref, s.content_digest,
                       o.payload_json, o.payload_digest,
                       o.content_digest AS object_content_digest
                FROM snapshots s
                LEFT JOIN object_revisions o
                  ON o.kind = 'snapshot'
                 AND o.object_id = s.snapshot_ref
                 AND o.revision = s.revision
                ORDER BY s.snapshot_ref
                """
            ):
                snapshot_ref = str(row["snapshot_ref"])
                if row["payload_json"] is None:
                    issues.append(
                        f"snapshot-object-missing:{snapshot_ref}"
                    )
                    continue
                try:
                    payload = decode_payload_row(
                        {
                            "payload_json": row["payload_json"],
                            "payload_digest": row["payload_digest"],
                            "content_digest": row["object_content_digest"],
                        }
                    )
                except RepositoryError as exc:
                    issues.append(
                        f"snapshot-payload:{snapshot_ref}:{exc}"
                    )
                    continue
                if (
                    str(payload.get("content_digest"))
                    != str(row["content_digest"])
                ):
                    issues.append(
                        f"snapshot-content-digest-mismatch:{snapshot_ref}"
                    )

                indexed = [
                    {
                        "kind": str(item["member_kind"]),
                        "id": str(item["member_id"]),
                        "revision": int(item["member_revision"]),
                        "digest": str(item["member_content_digest"]),
                    }
                    for item in self._connection.execute(
                        """
                        SELECT member_kind, member_id,
                               member_revision, member_content_digest
                        FROM snapshot_members
                        WHERE snapshot_ref = ?
                        ORDER BY ordinal
                        """,
                        (snapshot_ref,),
                    )
                ]
                if indexed != list(payload.get("members", ())):
                    issues.append(
                        f"snapshot-member-index-mismatch:{snapshot_ref}"
                    )
                for member in indexed:
                    target = self._connection.execute(
                        """
                        SELECT payload_digest FROM object_revisions
                        WHERE kind = ? AND object_id = ? AND revision = ?
                        """,
                        (
                            member["kind"],
                            member["id"],
                            member["revision"],
                        ),
                    ).fetchone()
                    if target is None:
                        issues.append(
                            "snapshot-member-object-missing:"
                            f"{snapshot_ref}:{member['kind']}:"
                            f"{member['id']}@{member['revision']}"
                        )
                    elif (
                        str(target["payload_digest"])
                        != member["digest"]
                    ):
                        issues.append(
                            "snapshot-member-digest-mismatch:"
                            f"{snapshot_ref}:{member['kind']}:"
                            f"{member['id']}@{member['revision']}"
                        )

            for table, ref_name, kind in (
                ("decisions", "decision_ref", "decision"),
                ("audit_events", "audit_ref", "audit_event"),
            ):
                for row in self._connection.execute(
                    f"""
                    SELECT x.{ref_name} AS ref, x.revision
                    FROM {table} x
                    LEFT JOIN object_revisions o
                      ON o.kind = ?
                     AND o.object_id = x.{ref_name}
                     AND o.revision = x.revision
                    WHERE o.object_id IS NULL
                    ORDER BY x.{ref_name}
                    """,
                    (kind,),
                ):
                    issues.append(
                        f"{kind}-object-missing:{row['ref']}"
                    )

            for row in self._connection.execute(
                """
                SELECT lineage_id, head_snapshot_ref,
                       head_snapshot_digest, head_snapshot_revision
                FROM lineages ORDER BY lineage_id
                """
            ):
                head = self._connection.execute(
                    """
                    SELECT content_digest, revision FROM snapshots
                    WHERE snapshot_ref = ?
                    """,
                    (row["head_snapshot_ref"],),
                ).fetchone()
                if head is None:
                    issues.append(
                        f"lineage-head-missing:{row['lineage_id']}"
                    )
                elif (
                    str(head["content_digest"])
                    != str(row["head_snapshot_digest"])
                    or int(head["revision"])
                    != int(row["head_snapshot_revision"])
                ):
                    issues.append(
                        f"lineage-head-metadata-mismatch:"
                        f"{row['lineage_id']}"
                    )

            for row in self._connection.execute(
                """
                SELECT p.project_ref, p.active_lineage_ref
                FROM project_active_lineage p
                LEFT JOIN lineages l
                  ON l.lineage_id = p.active_lineage_ref
                 AND l.project_ref = p.project_ref
                WHERE l.lineage_id IS NULL
                ORDER BY p.project_ref
                """
            ):
                issues.append(
                    f"active-lineage-missing:{row['project_ref']}"
                )

            for row in self._connection.execute(
                """
                SELECT commit_id, transition_id, bundle_digest,
                       idempotency_key, receipt_json,
                       prior_snapshot_ref, prior_snapshot_digest,
                       new_snapshot_ref, new_snapshot_digest
                FROM commits ORDER BY commit_id
                """
            ):
                try:
                    receipt = receipt_from_json(
                        str(row["receipt_json"])
                    )
                except RepositoryError as exc:
                    issues.append(
                        f"commit-receipt:{row['commit_id']}:{exc}"
                    )
                    continue
                checks = {
                    "id": receipt.commit_id == str(row["commit_id"]),
                    "transition": receipt.transition_id
                    == str(row["transition_id"]),
                    "bundle": receipt.bundle_digest
                    == str(row["bundle_digest"]),
                    "idempotency": receipt.idempotency_key
                    == str(row["idempotency_key"]),
                    "prior-ref": receipt.prior_snapshot_ref
                    == str(row["prior_snapshot_ref"]),
                    "prior-digest": receipt.prior_snapshot_digest
                    == str(row["prior_snapshot_digest"]),
                    "new-ref": receipt.new_snapshot_ref
                    == (
                        str(row["new_snapshot_ref"])
                        if row["new_snapshot_ref"] is not None
                        else None
                    ),
                    "new-digest": receipt.new_snapshot_digest
                    == (
                        str(row["new_snapshot_digest"])
                        if row["new_snapshot_digest"] is not None
                        else None
                    ),
                }
                for label, okay in checks.items():
                    if not okay:
                        issues.append(
                            f"commit-receipt-{label}-mismatch:"
                            f"{row['commit_id']}"
                        )
        except sqlite3.Error as exc:
            raise RepositoryError(
                "SQLite integrity diagnostics failed"
            ) from exc
        return tuple(sorted(set(issues)))

    def debug_state(
        self: "SQLiteResearchStateRepository",
    ) -> dict[str, Any]:
        """Stable test diagnostic, not an authoritative mutation API."""

        return {
            "objects": [
                (
                    (
                        str(row["kind"]),
                        str(row["object_id"]),
                        int(row["revision"]),
                    ),
                    str(row["payload_digest"]),
                )
                for row in self._connection.execute(
                    """
                    SELECT kind, object_id, revision, payload_digest
                    FROM object_revisions
                    ORDER BY kind, object_id, revision
                    """
                )
            ],
            "snapshots": [
                (
                    str(row["snapshot_ref"]),
                    str(row["payload_digest"]),
                )
                for row in self._connection.execute(
                    """
                    SELECT snapshot_ref, payload_digest
                    FROM snapshots ORDER BY snapshot_ref
                    """
                )
            ],
            "decisions": [
                (
                    str(row["decision_ref"]),
                    str(row["payload_digest"]),
                )
                for row in self._connection.execute(
                    """
                    SELECT decision_ref, payload_digest
                    FROM decisions ORDER BY decision_ref
                    """
                )
            ],
            "lineages": [
                (
                    str(row["lineage_id"]),
                    asdict(lineage_from_row(row)),
                )
                for row in self._connection.execute(
                    "SELECT * FROM lineages ORDER BY lineage_id"
                )
            ],
            "active": debug_active_lineage(self._connection),
            "used_decisions": [
                str(row["decision_ref"])
                for row in self._connection.execute(
                    """
                    SELECT decision_ref FROM used_decisions
                    ORDER BY decision_ref
                    """
                )
            ],
            "adoptions": [
                str(row["adoption_ref"])
                for row in self._connection.execute(
                    """
                    SELECT adoption_ref FROM adoption_refs
                    ORDER BY adoption_ref
                    """
                )
            ],
            "audits": [
                (
                    str(row["audit_ref"]),
                    str(row["payload_digest"]),
                )
                for row in self._connection.execute(
                    """
                    SELECT audit_ref, payload_digest
                    FROM audit_events ORDER BY audit_ref
                    """
                )
            ],
            "commits": [
                (
                    str(row["idempotency_key"]),
                    str(row["request_digest"]),
                )
                for row in self._connection.execute(
                    """
                    SELECT idempotency_key, request_digest
                    FROM commits ORDER BY idempotency_key
                    """
                )
            ],
        }
