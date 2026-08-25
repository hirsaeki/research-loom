from __future__ import annotations

from typing import Any, Mapping, Sequence, TYPE_CHECKING

from core.runtime.ports import RepositoryError
from core.runtime.transition_models import CommitReceipt, StateView

from ._support import (
    decode_json,
    decode_payload_row,
    lineage_from_row,
    receipt_from_json,
    repository_read,
    verify_embedded_content_digest,
)

if TYPE_CHECKING:
    from .adapter import SQLiteResearchStateRepository


class ReadMixin:
    @repository_read
    def load_state_view(
        self: "SQLiteResearchStateRepository",
        project_ref: str,
        lineage_ref: str,
    ) -> StateView:
        project = self._connection.execute(
            "SELECT * FROM project_state WHERE project_ref = ?",
            (project_ref,),
        ).fetchone()
        if project is None:
            raise RepositoryError(f"project {project_ref!r} does not resolve")

        lineage_row = self._connection.execute(
            """
            SELECT * FROM lineages
            WHERE lineage_id = ? AND project_ref = ?
            """,
            (lineage_ref, project_ref),
        ).fetchone()
        if lineage_row is None:
            raise RepositoryError(f"lineage {lineage_ref!r} does not resolve")
        snapshot = self.load_snapshot(str(lineage_row["head_snapshot_ref"]))
        if snapshot is None:
            raise RepositoryError(
                f"lineage head snapshot {lineage_row['head_snapshot_ref']!r} "
                "does not resolve"
            )
        if str(snapshot["content_digest"]) != str(
            lineage_row["head_snapshot_digest"]
        ):
            raise RepositoryError(
                "lineage HEAD digest does not match stored Snapshot"
            )

        objects = tuple(
            decode_payload_row(row)
            for row in self._connection.execute(
                """
                SELECT payload_json, payload_digest, content_digest
                FROM object_revisions
                WHERE project_ref = ?
                ORDER BY kind, object_id, revision
                """,
                (project_ref,),
            )
        )
        decisions = tuple(
            decode_payload_row(row)
            for row in self._connection.execute(
                """
                SELECT o.payload_json, o.payload_digest, o.content_digest
                FROM decisions d
                JOIN object_revisions o
                  ON o.kind = 'decision'
                 AND o.object_id = d.decision_ref
                 AND o.revision = d.revision
                WHERE d.project_ref = ?
                ORDER BY d.decision_ref
                """,
                (project_ref,),
            )
        )
        lineages = tuple(
            lineage_from_row(row)
            for row in self._connection.execute(
                """
                SELECT * FROM lineages
                WHERE project_ref = ?
                ORDER BY lineage_id
                """,
                (project_ref,),
            )
        )

        active = self._connection.execute(
            """
            SELECT active_lineage_ref
            FROM project_active_lineage
            WHERE project_ref = ?
            """,
            (project_ref,),
        ).fetchone()
        if active is None:
            raise RepositoryError(
                f"project {project_ref!r} has no active lineage pointer"
            )
        if not any(
            lineage.lineage_id == str(active["active_lineage_ref"])
            for lineage in lineages
        ):
            raise RepositoryError("project active lineage pointer is dangling")

        used = tuple(
            str(row["decision_ref"])
            for row in self._connection.execute(
                """
                SELECT u.decision_ref
                FROM used_decisions u
                JOIN decisions d ON d.decision_ref = u.decision_ref
                WHERE d.project_ref = ?
                ORDER BY u.decision_ref
                """,
                (project_ref,),
            )
        )
        adoptions = tuple(
            str(row["adoption_ref"])
            for row in self._connection.execute(
                """
                SELECT adoption_ref FROM adoption_refs
                WHERE project_ref = ? ORDER BY adoption_ref
                """,
                (project_ref,),
            )
        )
        non_reusable = tuple(
            str(row["ref"])
            for row in self._connection.execute(
                """
                SELECT ref FROM non_reusable_refs
                WHERE project_ref = ? ORDER BY ref
                """,
                (project_ref,),
            )
        )
        source_modes = {
            str(row["source_ref"]): str(row["source_mode"])
            for row in self._connection.execute(
                """
                SELECT source_ref, source_mode FROM source_modes
                WHERE project_ref = ? ORDER BY source_ref
                """,
                (project_ref,),
            )
        }

        return StateView(
            project_ref=project_ref,
            lineage_ref=lineage_ref,
            current_snapshot=snapshot,
            objects=objects,
            decisions=decisions,
            used_decision_ids=used,
            lineages=lineages,
            active_lineage_ref=str(active["active_lineage_ref"]),
            project_config_ref=str(project["project_config_ref"]),
            project_config_digest=str(project["project_config_digest"]),
            effective_profile_set_ref=str(project["effective_profile_set_ref"]),
            effective_profile_set_digest=str(
                project["effective_profile_set_digest"]
            ),
            project_config=decode_json(str(project["project_config_json"])),
            effective_constraints=decode_json(
                str(project["effective_constraints_json"])
            ),
            adoption_refs=adoptions,
            non_reusable_refs=non_reusable,
            source_modes=source_modes,
        )

    @repository_read
    def load_snapshot(
        self: "SQLiteResearchStateRepository",
        snapshot_ref: str,
    ) -> Mapping[str, Any] | None:
        row = self._connection.execute(
            """
            SELECT o.payload_json, o.payload_digest, o.content_digest
            FROM snapshots s
            JOIN object_revisions o
              ON o.kind = 'snapshot'
             AND o.object_id = s.snapshot_ref
             AND o.revision = s.revision
            WHERE s.snapshot_ref = ?
            """,
            (snapshot_ref,),
        ).fetchone()
        if row is None:
            return None
        payload = decode_payload_row(row)
        verify_embedded_content_digest(payload)
        return payload

    @repository_read
    def load_object_revision(
        self: "SQLiteResearchStateRepository",
        kind: str,
        object_id: str,
        revision: int,
    ) -> Mapping[str, Any] | None:
        row = self._connection.execute(
            """
            SELECT payload_json, payload_digest, content_digest
            FROM object_revisions
            WHERE kind = ? AND object_id = ? AND revision = ?
            """,
            (kind, object_id, revision),
        ).fetchone()
        return decode_payload_row(row) if row is not None else None

    @repository_read
    def resolve_refs(
        self: "SQLiteResearchStateRepository",
        refs: Sequence[tuple[str, str]],
    ) -> Mapping[tuple[str, str], bool]:
        known = {
            (str(row["kind"]), str(row["object_id"]))
            for row in self._connection.execute(
                "SELECT DISTINCT kind, object_id FROM object_revisions"
            )
        }
        known.update(
            ("snapshot", str(row["snapshot_ref"]))
            for row in self._connection.execute(
                "SELECT snapshot_ref FROM snapshots"
            )
        )
        known.update(
            ("research_lineage", str(row["lineage_id"]))
            for row in self._connection.execute(
                "SELECT lineage_id FROM lineages"
            )
        )
        return {tuple(ref): tuple(ref) in known for ref in refs}

    @repository_read
    def find_commit_by_idempotency_key(
        self: "SQLiteResearchStateRepository",
        idempotency_key: str,
    ) -> tuple[str, CommitReceipt] | None:
        row = self._connection.execute(
            """
            SELECT request_digest, receipt_json
            FROM commits WHERE idempotency_key = ?
            """,
            (idempotency_key,),
        ).fetchone()
        if row is None:
            return None
        return (
            str(row["request_digest"]),
            receipt_from_json(str(row["receipt_json"])),
        )
