from __future__ import annotations

from typing import Any, Mapping, TYPE_CHECKING
import sqlite3

from core.runtime.ports import (
    AtomicCommitError,
    IdempotencyConflictError,
    RepositoryError,
    StaleHeadError,
)
from core.runtime.transition_models import (
    CommitBundle,
    CommitReceipt,
    LineageView,
    canonical_digest,
    canonical_json,
)

from ._support import encode_json, object_key, receipt_from_json, verify_embedded_content_digest

if TYPE_CHECKING:
    from .adapter import SQLiteResearchStateRepository


class WriteMixin:
    def commit(
        self: "SQLiteResearchStateRepository",
        bundle: CommitBundle,
        *,
        expected_head_snapshot_digest: str,
    ) -> CommitReceipt:
        if bundle.receipt is None:
            raise AtomicCommitError(
                "CommitBundle must contain its immutable receipt"
            )
        try:
            with self._write_transaction():
                prior = self._connection.execute(
                    """
                    SELECT request_digest, receipt_json
                    FROM commits WHERE idempotency_key = ?
                    """,
                    (bundle.idempotency_key,),
                ).fetchone()
                if prior is not None:
                    if str(prior["request_digest"]) == bundle.request_digest:
                        return receipt_from_json(str(prior["receipt_json"]))
                    raise IdempotencyConflictError(
                        "idempotency key collides with a different committed request"
                    )

                source = self._connection.execute(
                    """
                    SELECT project_ref, head_snapshot_ref, head_snapshot_digest
                    FROM lineages WHERE lineage_id = ?
                    """,
                    (bundle.lineage_ref,),
                ).fetchone()
                if source is None:
                    raise AtomicCommitError(
                        f"source lineage {bundle.lineage_ref!r} does not resolve"
                    )
                if str(source["project_ref"]) != bundle.project_ref:
                    raise AtomicCommitError(
                        "source lineage belongs to a different project"
                    )
                if (
                    str(source["head_snapshot_digest"])
                    != expected_head_snapshot_digest
                ):
                    raise StaleHeadError(
                        "Research Lineage HEAD changed before atomic commit"
                    )
                if (
                    str(source["head_snapshot_ref"])
                    != bundle.previous_snapshot_ref
                    or str(source["head_snapshot_digest"])
                    != bundle.previous_snapshot_digest
                ):
                    raise StaleHeadError(
                        "CommitBundle previous Snapshot no longer matches "
                        "Research Lineage HEAD"
                    )

                for obj in bundle.object_revisions:
                    self._insert_immutable_object(
                        obj,
                        created_commit_id=bundle.commit_id,
                    )
                for decision in bundle.decision_records:
                    key = object_key(decision)
                    try:
                        stored_decision = self._load_object_revision_unchecked(*key)
                    except RepositoryError as exc:
                        raise AtomicCommitError(
                            "failed to validate Decision canonical object revision"
                        ) from exc
                    if stored_decision is None:
                        raise AtomicCommitError(
                            f"Decision {decision['id']!r} is missing its "
                            "canonical object revision"
                        )
                    self._insert_decision_index(
                        decision,
                        created_commit_id=bundle.commit_id,
                    )

                if bundle.new_snapshot is not None:
                    snapshot_id = str(bundle.new_snapshot["id"])
                    if self._connection.execute(
                        "SELECT 1 FROM snapshots WHERE snapshot_ref = ?",
                        (snapshot_id,),
                    ).fetchone() is not None:
                        raise AtomicCommitError(
                            f"immutable Snapshot identity already exists: "
                            f"{snapshot_id}"
                        )
                    self._insert_immutable_object(
                        bundle.new_snapshot,
                        created_commit_id=bundle.commit_id,
                    )
                    self._insert_snapshot_index(
                        bundle.new_snapshot,
                        created_commit_id=bundle.commit_id,
                    )

                for lineage in bundle.lineage_updates:
                    self._update_lineage(
                        bundle.project_ref,
                        lineage,
                        updated_commit_id=bundle.commit_id,
                    )
                for lineage in bundle.new_lineages:
                    if (
                        bundle.new_snapshot is None
                        or lineage.head_snapshot_ref
                        != str(bundle.new_snapshot["id"])
                    ):
                        raise AtomicCommitError(
                            "new lineage HEAD snapshot must be in the same "
                            "atomic bundle"
                        )
                    self._insert_new_lineage(
                        bundle.project_ref,
                        lineage,
                        created_commit_id=bundle.commit_id,
                        updated_commit_id=bundle.commit_id,
                    )

                if bundle.active_lineage_update is not None:
                    target = self._connection.execute(
                        """
                        SELECT 1 FROM lineages
                        WHERE lineage_id = ? AND project_ref = ?
                        """,
                        (
                            bundle.active_lineage_update,
                            bundle.project_ref,
                        ),
                    ).fetchone()
                    if target is None:
                        raise AtomicCommitError(
                            "active lineage target does not resolve"
                        )
                    updated = self._connection.execute(
                        """
                        UPDATE project_active_lineage
                        SET active_lineage_ref = ?, updated_commit_id = ?
                        WHERE project_ref = ?
                        """,
                        (
                            bundle.active_lineage_update,
                            bundle.commit_id,
                            bundle.project_ref,
                        ),
                    )
                    if updated.rowcount != 1:
                        raise AtomicCommitError(
                            "project active lineage pointer is missing: "
                            f"{bundle.project_ref}"
                        )

                for decision_ref in bundle.used_decision_refs:
                    try:
                        self._connection.execute(
                            """
                            INSERT INTO used_decisions(
                                decision_ref, consuming_transition_id,
                                consuming_commit_id
                            ) VALUES (?, ?, ?)
                            """,
                            (
                                decision_ref,
                                bundle.transition_id,
                                bundle.commit_id,
                            ),
                        )
                    except sqlite3.IntegrityError as exc:
                        raise AtomicCommitError(
                            "Decision reference cannot be consumed twice: "
                            f"{decision_ref}"
                        ) from exc

                for adoption_ref in bundle.adoption_refs:
                    self._connection.execute(
                        """
                        INSERT OR IGNORE INTO adoption_refs(
                            adoption_ref, project_ref, lineage_ref,
                            created_commit_id
                        ) VALUES (?, ?, ?, ?)
                        """,
                        (
                            adoption_ref,
                            bundle.project_ref,
                            bundle.lineage_ref,
                            bundle.commit_id,
                        ),
                    )

                for audit in bundle.audit_events:
                    audit_id = str(audit["id"])
                    if self._connection.execute(
                        "SELECT 1 FROM audit_events WHERE audit_ref = ?",
                        (audit_id,),
                    ).fetchone() is not None:
                        raise AtomicCommitError(
                            f"AuditEvent identity already exists: {audit_id}"
                        )
                    self._insert_immutable_object(
                        audit,
                        created_commit_id=bundle.commit_id,
                    )
                    self._connection.execute(
                        """
                        INSERT INTO audit_events(
                            audit_ref, revision, project_ref,
                            payload_digest, commit_ref
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            audit_id,
                            int(audit.get("revision", 0)),
                            bundle.project_ref,
                            canonical_digest(audit),
                            bundle.commit_id,
                        ),
                    )

                receipt = bundle.receipt
                self._connection.execute(
                    """
                    INSERT INTO commits(
                        commit_id, transition_id, project_ref, lineage_ref,
                        idempotency_key, request_digest, bundle_digest,
                        receipt_json, prior_snapshot_ref,
                        prior_snapshot_digest, new_snapshot_ref,
                        new_snapshot_digest, committed_at, actor_id, actor_type
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        bundle.commit_id,
                        bundle.transition_id,
                        bundle.project_ref,
                        bundle.lineage_ref,
                        bundle.idempotency_key,
                        bundle.request_digest,
                        bundle.bundle_digest,
                        canonical_json(receipt),
                        bundle.previous_snapshot_ref,
                        bundle.previous_snapshot_digest,
                        receipt.new_snapshot_ref,
                        receipt.new_snapshot_digest,
                        receipt.timestamp,
                        receipt.actor.actor_id,
                        receipt.actor.actor_type,
                    ),
                )
                return receipt
        except (
            StaleHeadError,
            IdempotencyConflictError,
            AtomicCommitError,
        ):
            raise
        except sqlite3.IntegrityError as exc:
            raise AtomicCommitError(
                "SQLite integrity constraint rejected atomic commit"
            ) from exc
        except sqlite3.Error as exc:
            raise AtomicCommitError(
                "SQLite persistence operation failed"
            ) from exc

    def _insert_immutable_object(
        self: "SQLiteResearchStateRepository",
        obj: Mapping[str, Any],
        *,
        created_commit_id: str | None,
    ) -> None:
        kind, object_id, revision = object_key(obj)
        project_ref = str(obj.get("project_id", ""))
        if not project_ref:
            if kind == "project":
                project_ref = object_id
            else:
                raise AtomicCommitError(
                    f"{kind}:{object_id} has no project_id"
                )
        payload_json = encode_json(obj)
        payload_digest = canonical_digest(obj)
        content_digest = str(
            obj.get("content_digest") or payload_digest
        )
        existing = self._connection.execute(
            """
            SELECT payload_digest FROM object_revisions
            WHERE kind = ? AND object_id = ? AND revision = ?
            """,
            (kind, object_id, revision),
        ).fetchone()
        if existing is not None:
            if str(existing["payload_digest"]) == payload_digest:
                return
            raise AtomicCommitError(
                f"immutable object revision collision at "
                f"{(kind, object_id, revision)}"
            )
        self._connection.execute(
            """
            INSERT INTO object_revisions(
                kind, object_id, revision, project_ref, content_digest,
                payload_digest, payload_json, created_commit_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                kind,
                object_id,
                revision,
                project_ref,
                content_digest,
                payload_digest,
                payload_json,
                created_commit_id,
            ),
        )

    def _insert_snapshot_index(
        self: "SQLiteResearchStateRepository",
        snapshot: Mapping[str, Any],
        *,
        created_commit_id: str | None,
    ) -> None:
        verify_embedded_content_digest(snapshot)
        snapshot_ref = str(snapshot["id"])
        revision = int(snapshot.get("revision", 0))
        self._connection.execute(
            """
            INSERT INTO snapshots(
                snapshot_ref, revision, project_ref, mode,
                content_digest, payload_digest, created_commit_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot_ref,
                revision,
                str(snapshot["project_id"]),
                str(snapshot.get("mode", "real")),
                str(snapshot["content_digest"]),
                canonical_digest(snapshot),
                created_commit_id,
            ),
        )
        members = snapshot.get("members", ())
        if isinstance(members, (str, bytes)) or not isinstance(
            members, (list, tuple)
        ):
            raise AtomicCommitError(
                "Snapshot members must be an ordered sequence"
            )
        for ordinal, member in enumerate(members):
            if not isinstance(member, Mapping):
                raise AtomicCommitError(
                    "Snapshot member must be an object"
                )
            kind = str(member["kind"])
            object_id = str(member["id"])
            revision = int(member["revision"])
            digest = str(member["digest"])
            target = self._connection.execute(
                """
                SELECT payload_digest FROM object_revisions
                WHERE kind = ? AND object_id = ? AND revision = ?
                """,
                (kind, object_id, revision),
            ).fetchone()
            if target is None:
                raise AtomicCommitError(
                    "Snapshot member does not resolve: "
                    f"{kind}:{object_id}@{revision}"
                )
            if str(target["payload_digest"]) != digest:
                raise AtomicCommitError(
                    "Snapshot member digest mismatch: "
                    f"{kind}:{object_id}@{revision}"
                )
            self._connection.execute(
                """
                INSERT INTO snapshot_members(
                    snapshot_ref, ordinal, member_kind, member_id,
                    member_revision, member_content_digest
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_ref,
                    ordinal,
                    kind,
                    object_id,
                    revision,
                    digest,
                ),
            )

    def _insert_decision_index(
        self: "SQLiteResearchStateRepository",
        decision: Mapping[str, Any],
        *,
        created_commit_id: str | None,
    ) -> None:
        decision_ref = str(decision["id"])
        revision = int(decision.get("revision", 0))
        digest = canonical_digest(decision)
        existing = self._connection.execute(
            """
            SELECT revision, payload_digest
            FROM decisions WHERE decision_ref = ?
            """,
            (decision_ref,),
        ).fetchone()
        if existing is not None:
            if (
                int(existing["revision"]) == revision
                and str(existing["payload_digest"]) == digest
            ):
                return
            raise AtomicCommitError(
                f"immutable Decision collision at {decision_ref}"
            )
        self._connection.execute(
            """
            INSERT INTO decisions(
                decision_ref, revision, project_ref,
                payload_digest, created_commit_id
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                decision_ref,
                revision,
                str(decision["project_id"]),
                digest,
                created_commit_id,
            ),
        )

    def _insert_new_lineage(
        self: "SQLiteResearchStateRepository",
        project_ref: str,
        lineage: LineageView,
        *,
        created_commit_id: str | None,
        updated_commit_id: str | None,
    ) -> None:
        if self._connection.execute(
            "SELECT 1 FROM lineages WHERE lineage_id = ?",
            (lineage.lineage_id,),
        ).fetchone() is not None:
            raise AtomicCommitError(
                f"lineage identity already exists: {lineage.lineage_id}"
            )
        self._assert_lineage_head(lineage)
        self._connection.execute(
            """
            INSERT INTO lineages(
                lineage_id, project_ref, lineage_kind,
                parent_lineage_ref, baseline_snapshot_ref,
                head_snapshot_ref, head_snapshot_digest,
                head_snapshot_revision, execution_mode, status,
                project_config_ref, project_config_digest,
                effective_profile_set_ref,
                effective_profile_set_digest,
                created_commit_id, updated_commit_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                lineage.lineage_id,
                project_ref,
                lineage.lineage_kind,
                lineage.parent_lineage_ref,
                lineage.baseline_snapshot_ref,
                lineage.head_snapshot_ref,
                lineage.head_snapshot_digest,
                lineage.head_snapshot_revision,
                lineage.execution_mode,
                lineage.status,
                lineage.project_config_ref,
                lineage.project_config_digest,
                lineage.effective_profile_set_ref,
                lineage.effective_profile_set_digest,
                created_commit_id,
                updated_commit_id,
            ),
        )

    def _update_lineage(
        self: "SQLiteResearchStateRepository",
        project_ref: str,
        lineage: LineageView,
        *,
        updated_commit_id: str,
    ) -> None:
        if self._connection.execute(
            """
            SELECT 1 FROM lineages
            WHERE lineage_id = ? AND project_ref = ?
            """,
            (lineage.lineage_id, project_ref),
        ).fetchone() is None:
            raise AtomicCommitError(
                f"cannot update unknown lineage {lineage.lineage_id}"
            )
        self._assert_lineage_head(lineage)
        self._connection.execute(
            """
            UPDATE lineages SET
                lineage_kind = ?, parent_lineage_ref = ?,
                baseline_snapshot_ref = ?, head_snapshot_ref = ?,
                head_snapshot_digest = ?, head_snapshot_revision = ?,
                execution_mode = ?, status = ?, project_config_ref = ?,
                project_config_digest = ?, effective_profile_set_ref = ?,
                effective_profile_set_digest = ?, updated_commit_id = ?
            WHERE lineage_id = ? AND project_ref = ?
            """,
            (
                lineage.lineage_kind,
                lineage.parent_lineage_ref,
                lineage.baseline_snapshot_ref,
                lineage.head_snapshot_ref,
                lineage.head_snapshot_digest,
                lineage.head_snapshot_revision,
                lineage.execution_mode,
                lineage.status,
                lineage.project_config_ref,
                lineage.project_config_digest,
                lineage.effective_profile_set_ref,
                lineage.effective_profile_set_digest,
                updated_commit_id,
                lineage.lineage_id,
                project_ref,
            ),
        )

    def _assert_lineage_head(
        self: "SQLiteResearchStateRepository",
        lineage: LineageView,
    ) -> None:
        row = self._connection.execute(
            """
            SELECT revision, content_digest FROM snapshots
            WHERE snapshot_ref = ?
            """,
            (lineage.head_snapshot_ref,),
        ).fetchone()
        if row is None:
            raise AtomicCommitError(
                f"lineage HEAD snapshot does not resolve: "
                f"{lineage.head_snapshot_ref}"
            )
        if (
            int(row["revision"]) != lineage.head_snapshot_revision
            or str(row["content_digest"])
            != lineage.head_snapshot_digest
        ):
            raise AtomicCommitError(
                "lineage HEAD metadata does not match Snapshot"
            )
